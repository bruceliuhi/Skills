#!/usr/bin/env python3
"""Shared read-only CSV validation, precise record locations and safe reporting."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

NULL_STRINGS = {"", "null", "none", "n/a", "na", "nil", "undefined", "missing"}
MAX_ABS_NUMBER = Decimal("1e150")

class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for action in self._actions:
            if action.dest == "help":
                action.help = "显示帮助并退出"

    def format_help(self):
        return super().format_help().replace("usage:", "用法：").replace("optional arguments:", "可选参数：").replace("options:", "选项：").replace("positional arguments:", "位置参数：")

    def error(self, message):
        raise ValueError(message)

def is_null(value):
    return value.strip().lower() in NULL_STRINGS

def number(value):
    """Return (float or None, issue or None); non-numeric text has no issue."""
    value = value.strip()
    if is_null(value):
        return None, None
    try:
        d = Decimal(value)
    except InvalidOperation:
        return None, None
    if not d.is_finite():
        return None, "non_finite_number"
    if abs(d) > MAX_ABS_NUMBER:
        return None, "number_exceeds_supported_abs_1e150"
    n = float(d)
    if d and n == 0:
        return None, "number_underflows_float"
    if not math.isfinite(n):
        return None, "non_finite_conversion"
    return n, None

def identifier_like(name, values):
    named = bool(re.search(r"(^|[_\s])(id|code|phone|zip)($|[_\s])|编号|编码|手机|电话|邮编|身份证", name, re.I))
    raw = [v.strip() for v in values if not is_null(v)]
    formatting = any(re.fullmatch(r"0\d+", v) or re.fullmatch(r"[+-]?\d{16,}", v) for v in raw)
    return named or formatting

def load_csv(filepath, delimiter=","):
    if len(delimiter) != 1:
        raise ValueError("delimiter must be one character")
    p = Path(filepath)
    data = p.read_bytes()
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError("CSV is empty")
    if not headers or any(not h.strip() for h in headers):
        raise ValueError("CSV header names must be nonempty")
    if any(h != h.strip() for h in headers):
        raise ValueError("CSV header contains surrounding whitespace; clarify mapping before cleaning a copy")
    duplicates = [h for h, count in Counter(headers).items() if count > 1]
    if duplicates:
        raise ValueError("duplicate CSV headers: " + ", ".join(duplicates))
    rows, locations = [], []
    while True:
        line_start = reader.line_num + 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        if len(cells) != len(headers):
            raise ValueError("CSV lines %s-%s: expected %s fields, got %s" % (line_start, reader.line_num, len(headers), len(cells)))
        if any(len(v) > 1000000 for v in cells):
            raise ValueError("CSV field exceeds supported 1,000,000 characters")
        rows.append(dict(zip(headers, cells)))
        locations.append({"record": len(rows), "line_start": line_start, "line_end": reader.line_num})
    if not rows:
        raise ValueError("CSV contains no data records")
    return {"path": str(p), "headers": headers, "rows": rows, "locations": locations, "sha256": hashlib.sha256(data).hexdigest()}

def select_columns(table, value, required=False):
    if not value:
        if required:
            raise ValueError("--columns is required: explicitly select numeric measures; identifiers are not automatically scanned")
        return table["headers"][:]
    selected = [v.strip() for v in value.split(",")]
    if not all(selected) or len(selected) != len(set(selected)):
        raise ValueError("--columns must contain distinct nonempty names")
    missing = [v for v in selected if v not in table["headers"]]
    if missing:
        raise ValueError("columns not found: " + ", ".join(missing))
    return selected

def location(table, index, column=None, value=None):
    result = dict(table["locations"][index])
    if column is not None:
        result["column"] = column
        result["raw_value"] = value
    return result

def numeric_issues(table, columns):
    findings = []
    for col in columns:
        for i, row in enumerate(table["rows"]):
            _, error = number(row[col])
            if error:
                findings.append(dict(location(table, i, col, row[col]), issue=error))
    return findings

def add_io_args(parser):
    parser.add_argument("--file", required=True, help="输入 CSV 文件，只读处理")
    parser.add_argument("--delimiter", default=",", help="单字符分隔符，默认为逗号")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="text 为中文业务报告（默认）；json 为完整结构化数据")
    parser.add_argument("--output", help="新结果文件路径；拒绝覆盖已有文件或输入原件")

def render_text(report):
    """Chinese business delivery; machine JSON remains unchanged and separately available."""
    lines = ["# 数据质量专家｜" + report["tool"], "",
             "- 本次结论：" + status_label(report["status"]),
             "- 检查范围：%s 条记录；字段：%s。" % (report["total_rows"], "、".join(cell(c) for c in report["selected_columns"])),
             "- 业务可用性：尚未确认，需要结合实际业务标准判断。",
             "- 处理边界：只检查，不删除、填补或改写原始数据。", ""]
    if "dqs" in report:
        render_profile(lines, report)
    elif "total_missing_cells" in report:
        render_missing(lines, report)
    else:
        render_outliers(lines, report)
    if "numeric_issues" in report:
        render_findings(lines, "异常数字与表示范围问题", report["numeric_issues"])
    lines += ["## 如何处理与复用", "",
              "1. 按记录号和物理行号回查原值，先确认业务含义，再决定是否修正。",
              "2. 修正时另存副本；续查沿用本次字段、规则和方法，用新文件名保存结果。",
              "3. 如需继续计算或逐项处理，使用相同参数另存 JSON；中文报告不替代结构化数据。",
              "", "## 范围与追溯", "", report["scope_note"],
              "记录号从第一条数据开始计数；物理行号包含表头，带引号的跨行字段可能占多行。",
              "表格中的‘↵’表示原值换行，空字符串会明确标示；完整原始字符串保留在 JSON 中。", "",
              "- 输入文件：" + cell(report["source"]["file"]),
              "- 输入校验值（SHA-256）：" + report["source"]["sha256"],
              "- 输入编码：UTF-8（含带字节顺序标记的文件）。",
              "- 输入保护：读取结束复核校验值；本工具不写入输入文件。"]
    return "\n".join(lines) + "\n"

STATUS_LABELS = {
    "REVIEW_REQUIRED": "发现需复核事项",
    "NO_FINDINGS_IN_CHECKED_SCOPE": "所检查范围暂未发现需复核事项",
    "NO_OUTLIERS_IN_VALID_NUMERIC_SUBSET": "有效数值子集暂未发现统计异常候选",
    "NOT_ASSESSABLE_FEWER_THAN_4": "未能评估：有效数字不足 4 个",
    "NOT_ASSESSABLE_ZERO_VARIANCE": "未能评估：样本标准差为 0",
    "NOT_ASSESSABLE_ZERO_MAD": "未能评估：绝对偏差中位数为 0",
    "MEASURED": "已检查", "UNKNOWN": "未检查或证据不足",
    "NOT_APPLICABLE": "本次不适用",
    "DRAFT_REQUIRES_BUSINESS_CONFIRMATION_NOT_SCHEDULED": "待确认草案，未建立监测任务",
}
TYPE_LABELS = {"int": "整数", "integer": "整数", "float": "小数", "number": "数值",
               "bool": "布尔值", "boolean": "布尔值", "string": "文本", "timestamp": "带时区时间",
               "invalid_numeric": "异常数字", "unknown": "未知（没有可识别的非空值）", "identifier_like": "类似编号，按文本保留"}
DIMENSION_LABELS = {"completeness": "完整性", "consistency": "类型一致性", "validity": "业务取值有效性", "uniqueness": "声明键唯一性", "timeliness": "业务时效"}
METHOD_LABELS = {"iqr": "四分位距法（IQR）", "IQR": "四分位距法（IQR）",
                 "zscore": "标准分数法（Z 分数）", "Z-score": "标准分数法（Z 分数）",
                 "mzscore": "修正标准分数法（基于绝对偏差中位数）",
                 "Modified Z-score (MAD)": "修正标准分数法（基于绝对偏差中位数）"}
ISSUE_LABELS = {
    "non_finite_number": ("不是有限数值（如非数值标记或无穷大）", "回查导出或计算过程，确认真实值；不要直接改成 0。"),
    "number_exceeds_supported_abs_1e150": ("绝对值超过本工具统计上限 1e150", "确认原值与单位；需要换算时另存副本并记录换算口径。"),
    "number_underflows_float": ("数值过小，转换后会丢失为 0", "保留原值，核对计量单位，必要时另用更高精度工具。"),
    "non_finite_conversion": ("转换后不是有限数值", "核对原值和表示范围，不自动替换。"),
    "non_numeric_in_selected_measure": ("选定数值指标中存在非数值文本", "确认该列是否确为数值指标，回查原值或分类口径。"),
    "required_value_missing": ("用户声明的必填字段缺失", "回查来源补齐；确实不适用时先调整已确认规则。"),
    "outside_numeric_range_or_invalid": ("数值无效或超出用户声明范围", "核对原值、单位及范围规则，勿直接裁剪到边界。"),
    "value_not_allowed": ("原值不在用户声明的可选值中", "核对大小写、空格、业务新增选项与原始记录。"),
    "stale_future_missing_or_invalid_timestamp": ("时间缺失、无效、晚于参照时间或已超期", "按显式时区、参照时间及允许天数逐项核对，不以系统时间代替。"),
    "duplicate_or_missing_declared_key": ("用户声明的唯一键为空或发生重复", "按完整联合键回查记录，确认业务是否允许重复，勿直接删行。"),
    "missing_value": ("识别到约定空值", "确认字段适用范围和缺失是否允许；未经确认不填补或删行。"),
    "statistical_outlier": ("超出本次统计方法阈值的候选", "回查业务事件、单位和录入依据；统计异常不等于错误。"),
}

def status_label(value):
    return STATUS_LABELS.get(value, "待人工解释的状态")

def type_label(value):
    return TYPE_LABELS.get(value, "待确认类型")

def cell(value):
    if value is None:
        return "未能计算或未检查"
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value == "":
        return "（空字符串）"
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "↵").replace("\r", "↵").replace("\n", "↵")

def table(lines, headers, rows):
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    lines.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
    lines.append("")

def line_label(item):
    start, end = item["line_start"], item["line_end"]
    return str(start) if start == end else "%s—%s" % (start, end)

def issue_text(code):
    if code.startswith("type_mismatch_"):
        return ("不符合用户声明的%s类型" % type_label(code[len("type_mismatch_"):]), "核对字段含义、原值格式和类型规则；不要静默强制转换。")
    return ISSUE_LABELS.get(code, ("存在需人工解释的问题", "查看结构化记录并回查来源。"))

def render_findings(lines, title, items, default_issue=None):
    lines += ["### " + title, ""]
    if not items:
        lines += ["本次未记录此类问题。", ""]
        return
    rows = []
    for item in items:
        reason, advice = issue_text(item.get("issue", default_issue or ""))
        if item.get("dimension"):
            reason = DIMENSION_LABELS[item["dimension"]] + "：" + reason
        rows.append([item["record"], line_label(item), item.get("column", "所选字段"), item.get("raw_value", "见对应字段原值"), reason, advice])
    table(lines, ["记录号", "CSV 物理行", "字段", "原始值", "问题原因", "建议处理"], rows)

def render_profile(lines, report):
    q = report["dqs"]
    lines += ["## 检查覆盖与结论", "",
              "已检查维度得分：%s / 100；覆盖权重：%s%%。" % (q["score"], q["coverage_pct"]),
              q["interpretation"], "完整性得分只表示所选字段的非空单元格比例，不代表业务资料完整。", ""]
    table(lines, ["维度", "检查状态", "得分", "通过次数", "检查次数", "权重"],
          [[DIMENSION_LABELS[k], status_label(v["status"]), v["score"], v["passed"], v["checks"], str(q["weights"][k]) + "%"] for k, v in q["dimensions"].items()])
    lines += ["## 字段概览", ""]
    table(lines, ["字段", "识别类型", "非空数", "缺失数", "缺失率", "不同值数", "不同值占非空比例", "常量", "高基数"],
          [[p["column"], type_label(p["inferred_type"]), p["non_null_count"], p["null_count"], str(p["null_pct"])+"%", p["unique_count"], str(p["cardinality_pct"])+"%", p["is_constant"], p["is_high_cardinality"]] for p in report["columns"]])
    for p in report["columns"]:
        lines += ["### 字段：" + cell(p["column"]), "",
                  "类型频次：" + ("；".join(type_label(k) + " " + str(v) + " 条" for k, v in p["type_counts"].items()) or "没有非空值") + "。"]
        if len(p["type_counts"]) > 1 and not set(p["type_counts"]) <= {"int", "float"}:
            lines.append("需复核：字段中出现多种类型；先确认混合内容是否符合字段用途。")
        lines.extend(p["notes"])
        lines.append("")
        if "mean" in p:
            table(lines, ["有效数值数", "最小值", "最大值", "均值", "样本标准差", "未纳入统计的非空数"],
                  [[p["numeric_count"], p["min"], p["max"], p["mean"], p["std"], p["excluded_non_numeric_count"]]])
            lines += ["统计仅针对有效有限数值子集，使用浮点近似；原值保留。只有 1 个数值时不计算样本标准差。", ""]
        if p["top_values"]:
            lines += ["常见原值（最多 5 项，不代表全部不同值）：", ""]
            table(lines, ["原始值", "出现次数"], p["top_values"])
        render_findings(lines, "缺失位置", p["missing_records"], "missing_value")
    render_findings(lines, "业务规则未通过的记录", report["rule_findings"])
    lines += ["### 所选字段完全相同的记录", "", "相同记录是待确认信号；只有用户声明唯一键时才计入唯一性规则。", ""]
    if not report["duplicate_rows_in_selected_scope"]:
        lines += ["本次未发现所选字段完全相同的记录。", ""]
    for index, group in enumerate(report["duplicate_rows_in_selected_scope"], 1):
        lines += ["重复候选组 %s：" % index, ""]
        table(lines, ["字段", "原始值"], list(group["values"].items()))
        table(lines, ["记录号", "CSV 物理行"], [[r["record"], line_label(r)] for r in group["records"]])
    if "monitoring_draft" in report:
        lines += ["## 监测口径草案", "", "下列建议来自本次样本，尚未获业务确认；没有建立定时运行或告警。", ""]
        rows = []
        for m in report["monitoring_draft"]:
            interval = m["mean_reference_interval"]
            rows.append([m["column"], str(m["observed_null_pct"])+"%", str(m["suggested_null_alert_pct"])+"%", " 至 ".join(str(x) for x in interval) if interval is not None else "未能计算", status_label(m["status"])])
        table(lines, ["字段", "本次缺失率", "待确认缺失告警值", "均值正负两倍标准差参考区间", "状态"], rows)

def render_missing(lines, report):
    lines += ["## 缺失情况", "",
              "共识别到 %s 个缺失单元格。字段明细展示门槛：缺失比例至少 %s%%。" % (report["total_missing_cells"], report["threshold_fraction"] * 100),
              "低于展示门槛的字段仍计入汇总，不会被当成没有缺失。", ""]
    table(lines, ["字段", "缺失数", "缺失率", "明细状态"],
          [[c, n, str(round(n / report["total_rows"] * 100, 2))+"%", "未检测到约定的空值" if n == 0 else "低于展示门槛，仅保留汇总" if c in report["columns_below_threshold"] else "见下方逐行明细"] for c, n in report["all_column_null_counts"].items()])
    lines += ["空值识别口径（不区分大小写）：" + "、".join(cell(v) for v in report["null_tokens"]) + "。",
              "这些字面值按当前约定视为空值；其他业务哨兵值需另行确认。", ""]
    for p in report["columns"]:
        lines += ["### 字段：" + cell(p["column"]), "", "识别类型：" + type_label(p["col_type"]) + "。",
                  "缺失原因：尚未识别，不能从一次样本推断因果。", p["mechanism_note"], "建议：" + p["strategy"], ""]
        render_findings(lines, "缺失位置", p["missing_records"], "missing_value")
        lines += ["连续缺失记录段（记录顺序不证明业务原因）：", ""]
        table(lines, ["起始记录", "结束记录", "连续缺失数"], [[r["start_record"], r["end_record"], r["count"]] for r in p["consecutive_record_runs"]])
    lines += ["## 字段共同缺失", "", "共同缺失只描述本次样本的共现关系，不能证明缺失机制或采集原因。", ""]
    if not report["cooccurrence"]:
        lines += ["本次没有字段共同缺失记录。", ""]
    for p in report["cooccurrence"]:
        lines += ["### %s 与 %s" % (cell(p["col_a"]), cell(p["col_b"])), "",
                  "共同缺失 %s 条；共缺相似度 %s（同时缺失数 ÷ 至少一列缺失数）。" % (p["co_null_rows"], p["jaccard"]), ""]
        table(lines, ["记录号", "CSV 物理行"], [[r["record"], line_label(r)] for r in p["records"]])

def render_outliers(lines, report):
    lines += ["## 筛查方法与范围", "", "方法：%s；阈值：%s。" % (METHOD_LABELS[report["method"]], report["threshold"]),
              "异常数量与比例只针对有效数值子集；缺失和无效数字单独列出，未能评估不等于通过。", ""]
    table(lines, ["字段", "有效数值数", "未纳入统计数", "异常候选数", "候选比例", "状态"],
          [[p["column"], p["total_numeric"], p["excluded_count"], p["outlier_count"], str(p["outlier_pct"])+"%" if p["outlier_pct"] is not None else None, status_label(p["status"])] for p in report["columns"]])
    labels = {"q1": "第一四分位数", "q3": "第三四分位数", "iqr": "四分位距", "lower_bound": "下界", "upper_bound": "上界", "mean": "均值", "std": "样本标准差", "median": "中位数", "mad": "绝对偏差中位数"}
    for p in report["columns"]:
        lines += ["### 字段：" + cell(p["column"]), "", "评估状态：" + status_label(p["status"]) + "。", ""]
        metrics = [[label, p[k]] for k, label in labels.items() if k in p]
        if metrics:
            table(lines, ["方法参数", "计算值"], metrics)
        if p["status"] == "NOT_ASSESSABLE_ZERO_MAD":
            lines += ["绝对偏差中位数为 0，本方法无法评估；建议改用四分位距法或明确业务规则复核。", ""]
        elif p["status"] == "NOT_ASSESSABLE_ZERO_VARIANCE":
            lines += ["本次样本标准差为 0，标准分数法无法评估；请核对原值及业务范围，不据此称数据干净。", ""]
        elif p.get("note"):
            lines += [p["note"], ""]
        if p.get("risk_assessment"):
            lines += [p["risk_assessment"], ""]
        if p["status"].startswith("NOT_ASSESSABLE_"):
            lines += ["### 统计异常候选位置", "", "本方法未能评估，未给出候选清单；不能据此判断没有异常。", ""]
        else:
            render_findings(lines, "统计异常候选位置", p["outlier_records"], "statistical_outlier")
        render_findings(lines, "无效数值位置", p["invalid_numeric_records"])
        render_findings(lines, "缺失位置", p["missing_records"], "missing_value")

def emit(report, args, table):
    report["source"] = {"file": table["path"], "sha256": table["sha256"], "encoding": "UTF-8/UTF-8-BOM", "physical_line_locator": True}
    report["business_readiness"] = "UNKNOWN"
    report["scope_note"] = "仅报告本次所选字段和已执行规则；未检查项不是通过，统计异常不是已确认错误。"
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n" if args.format == "json" else render_text(report)
    if args.output:
        target = Path(args.output)
        if target.resolve() == Path(args.file).resolve():
            raise ValueError("output path must differ from input")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as f:
            f.write(payload)
    if hashlib.sha256(Path(args.file).read_bytes()).hexdigest() != table["sha256"]:
        raise ValueError("input changed during execution; rerun on a stable copy")
    sys.stdout.write(payload)
    return 2 if report.get("review_required") else 0

def chinese_error(error):
    """Translate CLI diagnostics without altering machine report keys or user values."""
    if isinstance(error, FileNotFoundError):
        return "找不到文件或目录：" + str(error.filename or "请核对路径")
    if isinstance(error, FileExistsError):
        return "结果文件已存在，未覆盖：%s。请使用新的输出文件名。" % (error.filename or "所选路径")
    if isinstance(error, PermissionError):
        return "没有访问权限：%s。请检查当前环境对该路径的读写权限。" % (error.filename or "所选路径")
    if isinstance(error, IsADirectoryError):
        return "所选路径是目录，请指定文件：" + str(error.filename or "所选路径")
    if isinstance(error, NotADirectoryError):
        return "路径中的某一级不是目录：" + str(error.filename or "所选路径")
    if isinstance(error, UnicodeError):
        return "无法按 UTF-8 读取文件；请保留原件，并将副本转换为 UTF-8 编码后重试。"
    if isinstance(error, json.JSONDecodeError):
        return "规则 JSON 格式无效：第 %s 行、第 %s 列（位置 %s）。请检查引号、逗号和括号。" % (error.lineno, error.colno, error.pos)
    if isinstance(error, csv.Error):
        return "CSV 格式无法完整读取，请核对引号、字段长度与分隔符；本次未生成结果。"
    if isinstance(error, OverflowError):
        return "计算超出支持的数值范围，请核对原值和计量单位；本次未生成结果。"
    message = str(error)
    exact = {
        "delimiter must be one character": "分隔符必须且只能是一个字符。",
        "CSV is empty": "CSV 为空，无法检查。",
        "CSV header names must be nonempty": "CSV 表头不能为空，请先确认字段名。",
        "CSV header contains surrounding whitespace; clarify mapping before cleaning a copy": "CSV 表头含首尾空格，请先确认字段映射，再清理副本；原件保持不变。",
        "CSV field exceeds supported 1,000,000 characters": "CSV 字段超过支持的 1,000,000 字符长度。",
        "CSV contains no data records": "CSV 只有表头，没有数据记录。",
        "--columns is required: explicitly select numeric measures; identifiers are not automatically scanned": "请用 --columns 明确选择数值指标；不会自动把编号等字段当作数值扫描。",
        "--columns must contain distinct nonempty names": "--columns 中的字段名不能为空或重复。",
        "output path must differ from input": "结果路径与输入原件相同，已拒绝覆盖。请另选新的结果路径。",
        "input changed during execution; rerun on a stable copy": "执行期间输入文件发生变化，本次结果不可作为最终结论；请使用稳定副本重新运行。",
        "rules must be a JSON object": "规则文件顶层必须是 JSON 对象。",
        "unsupported rules keys": "规则文件含不支持的规则名称，请对照字段规则说明。",
        "timestamp must be a string": "时间值必须是含显式时区的字符串。",
        "timestamp requires explicit timezone offset": "时间值缺少显式时区，请提供时区偏移，例如 +08:00。",
        "timeliness needs column, reference_timestamp, max_age_days": "时效规则必须包含字段（column）、参照时间（reference_timestamp）和允许天数（max_age_days）。",
        "max_age_days must be nonnegative and finite": "允许天数 max_age_days 必须是大于或等于 0 的有限数值。",
        "rules reference absent column": "规则引用了输入文件中不存在的字段，请核对字段名。",
        "rules reference column outside --columns scope; include it explicitly": "规则引用的字段不在 --columns 检查范围中，请明确加入该字段后再运行。",
        "threshold must be finite and between 0 and 1": "缺失比例门槛必须是 0 到 1 之间的有限数值。",
        "threshold must be finite and positive": "异常阈值必须是大于 0 的有限数值。",
        "IQR bounds overflow; reduce threshold or inspect numeric scale": "四分位距上下界计算溢出，请核对阈值与数值量级。",
    }
    if message in exact:
        return exact[message]
    prefixes = {
        "duplicate CSV headers: ": "CSV 存在重复表头：",
        "columns not found: ": "未找到以下字段：",
        "unsupported type for ": "以下字段的声明类型不受支持：",
        "ranges need min and/or max for ": "以下字段的范围必须包含下限 min 或上限 max：",
        "invalid range bound for ": "以下字段的范围边界不是有效数值：",
        "range min exceeds max for ": "以下字段的范围下限大于上限：",
        "allowed_values must contain raw strings for ": "以下字段的可选值列表必须包含非空数量的原始字符串：",
        "the following arguments are required: ": "缺少必填参数：",
        "unrecognized arguments: ": "无法识别以下参数：",
        "Invalid isoformat string: ": "时间格式无效，请使用含时区的标准日期时间：",
    }
    for prefix, translated in prefixes.items():
        if message.startswith(prefix):
            return translated + message[len(prefix):]
    match = re.fullmatch(r"CSV lines (\d+)-(\d+): expected (\d+) fields, got (\d+)", message)
    if match:
        return "CSV 第 %s—%s 物理行的字段数不一致：应有 %s 列，实际 %s 列。" % match.groups()
    for suffix, translated in ((" must be a list of distinct column names", "必须是不重复字段名组成的列表。"), (" must be an object", "必须是对象。")):
        if message.endswith(suffix):
            return "规则项 " + message[:-len(suffix)] + " " + translated
    match = re.fullmatch(r"argument (.+): invalid (.+) value: (.+)", message)
    if match:
        return "参数 %s 的值 %s 格式无效，请检查数值或类型要求。" % (match.group(1), match.group(3))
    match = re.fullmatch(r"argument (.+): invalid choice: (.+) \(choose from (.+)\)", message)
    if match:
        return "参数 %s 的选项 %s 不受支持；可选项：%s。" % match.groups()
    match = re.fullmatch(r"argument (.+): expected one argument", message)
    if match:
        return "参数 %s 后缺少一个值。" % match.group(1)
    if isinstance(error, OSError):
        return "文件访问失败（系统错误编号 %s）：%s。请检查路径、权限和可用空间。" % (error.errno, error.filename or "所选路径")
    return "输入或参数无法处理，请检查文件内容、规则格式和所选范围；本次未完成。"

def run(main):
    try:
        sys.exit(main())
    except (ValueError, OSError, UnicodeError, csv.Error, OverflowError) as error:
        print("错误：" + chinese_error(error), file=sys.stderr)
        sys.exit(3)
