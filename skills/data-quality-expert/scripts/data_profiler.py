#!/usr/bin/env python3
"""Column profiles, measured quality dimensions and optional explicit business rules."""
from __future__ import annotations
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from dq_common import Parser, add_io_args, emit, identifier_like, is_null, load_csv, location, number, numeric_issues, run, select_columns

WEIGHTS = {"completeness": 30, "consistency": 25, "validity": 20, "uniqueness": 15, "timeliness": 10}

def infer_type(values):
    counts = Counter()
    for v in values:
        n, error = number(v)
        if error:
            counts["invalid_numeric"] += 1
        elif v.strip().lower() in ("true", "false"):
            counts["bool"] += 1
        elif n is not None:
            counts["int" if Decimal(v.strip()) == Decimal(v.strip()).to_integral_value() else "float"] += 1
        else:
            counts["string"] += 1
    return counts.most_common(1)[0][0] if counts else "unknown"

def safe_mean(nums):
    if not nums:
        return None
    scale = max(abs(n) for n in nums)
    return scale * (math.fsum(n / scale for n in nums) / len(nums)) if scale else 0.0

def safe_std(nums, mean):
    if len(nums) < 2:
        return None
    scale = max(abs(x - mean) for x in nums)
    return scale * math.sqrt(math.fsum(((x - mean)/scale) ** 2 for x in nums) / (len(nums) - 1)) if scale else 0.0

def profile_column(name, raw_values, table):
    total = len(raw_values)
    non_null = [v for v in raw_values if not is_null(v)]
    missing = [location(table, i, name, v) for i, v in enumerate(raw_values) if is_null(v)]
    unique = set(non_null)
    kinds = Counter(infer_type([v]) for v in non_null)
    id_like = identifier_like(name, raw_values)
    p = {"column": name, "total_rows": total, "null_count": len(missing), "null_pct": round(len(missing) / total * 100, 2), "missing_records": missing,
         "non_null_count": len(non_null), "unique_count": len(unique), "cardinality_pct": round(len(unique) / len(non_null) * 100, 2) if non_null else 0,
         "inferred_type": "identifier_like" if id_like else infer_type(non_null), "type_counts": dict(kinds), "top_values": Counter(non_null).most_common(5),
         "is_constant": len(unique) == 1, "is_high_cardinality": len(unique) / len(non_null) > .9 if len(non_null) > 10 else False,
         "notes": ["常量及高基数字段仅为描述，不自动判为质量错误。"]}
    numeric = [(i, number(v)[0]) for i, v in enumerate(raw_values) if number(v)[0] is not None]
    if numeric and not id_like:
        nums = [n for _, n in numeric]
        mean = safe_mean(nums); sd = safe_std(nums, mean)
        p.update(min=min(nums), max=max(nums), mean=mean, std=sd, numeric_count=len(nums), statistics_scope="finite numeric subset; approximate floating-point statistics; original values retained", excluded_non_numeric_count=len(non_null) - len(nums))
    elif id_like:
        p["notes"].append("字段名或值格式类似编号，保留文本；未自动计算编号的数值分布。")
    return p

def iso_datetime(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("timestamp requires explicit timezone offset")
    return d

def load_rules(path, headers, selected):
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        rules = json.load(f, parse_float=Decimal)
    if not isinstance(rules, dict):
        raise ValueError("rules must be a JSON object")
    if set(rules) - {"required", "unique_keys", "types", "ranges", "allowed_values", "timeliness"}:
        raise ValueError("unsupported rules keys")
    cols = []
    for key in ("required", "unique_keys"):
        value = rules.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value) or len(value) != len(set(value)):
            raise ValueError(key + " must be a list of distinct column names")
        cols.extend(value)
    for key in ("types", "ranges", "allowed_values"):
        if not isinstance(rules.get(key, {}), dict):
            raise ValueError(key + " must be an object")
        cols.extend(rules.get(key, {}))
    for col, kind in rules.get("types", {}).items():
        if kind not in ("number", "integer", "boolean", "string", "timestamp"):
            raise ValueError("unsupported type for " + col)
    for col, bounds in rules.get("ranges", {}).items():
        if not isinstance(bounds, dict) or not bounds or set(bounds) - {"min", "max"}:
            raise ValueError("ranges need min and/or max for " + col)
        for k, v in bounds.items():
            n, error = number(str(v))
            if n is None or error:
                raise ValueError("invalid range bound for " + col)
        if "min" in bounds and "max" in bounds and Decimal(str(bounds["min"])) > Decimal(str(bounds["max"])):
            raise ValueError("range min exceeds max for " + col)
    for col, vals in rules.get("allowed_values", {}).items():
        if not isinstance(vals, list) or not vals or not all(isinstance(x, str) for x in vals):
            raise ValueError("allowed_values must contain raw strings for " + col)
    t = rules.get("timeliness")
    if t is not None:
        if not isinstance(t, dict) or set(t) != {"column", "reference_timestamp", "max_age_days"}:
            raise ValueError("timeliness needs column, reference_timestamp, max_age_days")
        cols.append(t["column"])
        iso_datetime(t["reference_timestamp"])
        n, error = number(str(t["max_age_days"]))
        if n is None or error or n < 0:
            raise ValueError("max_age_days must be nonnegative and finite")
    if any(c not in headers for c in cols):
        raise ValueError("rules reference absent column")
    if any(c not in selected for c in cols):
        raise ValueError("rules reference column outside --columns scope; include it explicitly")
    return rules

def check_rules(table, rules):
    findings, checks = [], {k: [0, 0] for k in WEIGHTS if k != "completeness"}
    def check(dim, passed, i, col, code):
        checks[dim][0] += 1
        checks[dim][1] += int(passed)
        if not passed:
            findings.append(dict(location(table, i, col, table["rows"][i][col]), issue=code, dimension=dim))
    for i, row in enumerate(table["rows"]):
        for col in rules.get("required", []):
            if is_null(row[col]):
                findings.append(dict(location(table, i, col, row[col]), issue="required_value_missing", dimension="completeness"))
        for col, kind in rules.get("types", {}).items():
            raw = row[col]
            if is_null(raw):
                continue
            n, error = number(raw)
            good = kind == "string"
            if kind == "number": good = n is not None and not error
            if kind == "integer": good = n is not None and not error and Decimal(raw.strip()) == Decimal(raw.strip()).to_integral_value()
            if kind == "boolean": good = raw.strip().lower() in ("true", "false")
            if kind == "timestamp":
                try: iso_datetime(raw); good = True
                except ValueError: good = False
            check("consistency", good, i, col, "type_mismatch_" + kind)
        for col, bounds in rules.get("ranges", {}).items():
            if is_null(row[col]): continue
            n, error = number(row[col]); good = n is not None and not error
            if good:
                d = Decimal(row[col].strip())
                good = ("min" not in bounds or d >= Decimal(str(bounds["min"]))) and ("max" not in bounds or d <= Decimal(str(bounds["max"])))
            check("validity", good, i, col, "outside_numeric_range_or_invalid")
        for col, allowed in rules.get("allowed_values", {}).items():
            if not is_null(row[col]): check("validity", row[col] in allowed, i, col, "value_not_allowed")
        t = rules.get("timeliness")
        if t:
            col = t["column"]
            try:
                age = (iso_datetime(t["reference_timestamp"]) - iso_datetime(row[col])).total_seconds() / 86400
                good = 0 <= age <= float(t["max_age_days"])
            except ValueError:
                good = False
            check("timeliness", good, i, col, "stale_future_missing_or_invalid_timestamp")
    keys = rules.get("unique_keys", [])
    if keys:
        groups = Counter(tuple(row[k] for k in keys) for row in table["rows"])
        for i, row in enumerate(table["rows"]):
            key = tuple(row[k] for k in keys)
            good = all(not is_null(v) for v in key) and groups[key] == 1
            check("uniqueness", good, i, keys[0], "duplicate_or_missing_declared_key")
    return findings, checks

def compute_dqs(profiles, total_rows, checks):
    dims = {k: {"status": "UNKNOWN", "score": None, "checks": 0, "passed": 0} for k in WEIGHTS}
    cells = total_rows * len(profiles); missing = sum(p["null_count"] for p in profiles)
    dims["completeness"] = {"status": "MEASURED", "score": (cells-missing)/cells*100, "checks": cells, "passed": cells-missing, "basis": "selected-field nonmissing-cell rate; not a business completeness guarantee"}
    for dim, (total, passed) in checks.items():
        if total:
            dims[dim] = {"status": "MEASURED", "score": passed/total*100, "checks": total, "passed": passed}
    weight = sum(WEIGHTS[k] for k,v in dims.items() if v["score"] is not None)
    score = sum(v["score"] * WEIGHTS[k] for k,v in dims.items() if v["score"] is not None) / weight
    for v in dims.values():
        if v["score"] is not None: v["score"] = round(v["score"], 2)
    return {"score": round(score, 2), "coverage_pct": weight, "dimensions": dims, "weights": WEIGHTS, "interpretation": "按已检查维度权重归一化；必须同时阅读覆盖率、问题和未检查项。不是生产就绪认证。"}

def main():
    parser = Parser(description="数据质量专家：CSV画像与实际规则核验")
    add_io_args(parser)
    parser.add_argument("--columns", help="检查字段，多个字段以逗号分隔；未指定时检查全部字段")
    parser.add_argument("--rules", help="用户明确提供的业务规则 JSON 文件")
    parser.add_argument("--monitor", action="store_true", help="附上待业务确认的监测口径草案；不会建立定时任务")
    args = parser.parse_args()
    table = load_csv(args.file, args.delimiter); selected = select_columns(table, args.columns)
    rules = load_rules(args.rules, table["headers"], selected)
    profiles = [profile_column(c, [r[c] for r in table["rows"]], table) for c in selected]
    findings, checks = check_rules(table, rules); numeric = numeric_issues(table, selected)
    groups = defaultdict(list)
    for i,row in enumerate(table["rows"]): groups[tuple(row[c] for c in selected)].append(location(table, i))
    duplicates = [{"values": dict(zip(selected,k)), "records": v} for k,v in groups.items() if len(v)>1]
    review = bool(findings or numeric or duplicates or any(p["null_count"] for p in profiles) or any(len(p["type_counts"]) > 1 and not set(p["type_counts"]) <= {"int","float"} for p in profiles))
    result = {"tool":"数据画像与规则检查", "total_rows":len(table["rows"]), "selected_columns":selected, "columns":profiles, "numeric_issues":numeric, "rule_findings":findings, "duplicate_rows_in_selected_scope":duplicates, "duplicate_note":"相同记录是待确认信号；只有声明unique_keys时才计入唯一性规则。", "dqs":compute_dqs(profiles,len(table["rows"]),checks), "review_required":review, "status":"REVIEW_REQUIRED" if review else "NO_FINDINGS_IN_CHECKED_SCOPE"}
    if args.monitor:
        result["monitoring_draft"] = [{"column":p["column"], "observed_null_pct":p["null_pct"], "suggested_null_alert_pct":min(p["null_pct"]*1.5,100), "mean_reference_interval":[p["mean"]-2*p["std"],p["mean"]+2*p["std"]] if p.get("std") is not None else None, "status":"DRAFT_REQUIRES_BUSINESS_CONFIRMATION_NOT_SCHEDULED"} for p in profiles]
    return emit(result,args,table)

if __name__ == "__main__":
    run(main)
