#!/usr/bin/env python3
"""
sla_compliance_tracker.py — Per-vendor SLA compliance tracking.

Takes JSON of SLA records {vendor, sla_metric, target, actual_last_month,
actual_last_quarter, breach_count_12m}. Computes:
  - Compliance % vs target (last month, last quarter)
  - Trend classification (improving / stable / degrading)
  - Credit-claim eligibility flag (per typical SLA credit clauses)

Output: per-vendor compliance scorecard markdown with action items.

Stdlib only. Deterministic. No LLM calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from _validation import label, gap_labels, error_text, ChineseArgumentParser, number, text, records_list, evidence_gaps, write_report, cell
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Trend(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DEGRADING = "degrading"


class ComplianceState(str, Enum):
    MET = "met"
    AT_RISK = "at-risk"
    BREACHED = "breached"


@dataclass
class SLAResult:
    vendor: str
    sla_metric: str
    target: float
    actual_last_month: float
    actual_last_quarter: float
    breach_count_12m: int
    compliance_month_pct: float
    compliance_quarter_pct: float
    state: ComplianceState
    trend: Trend
    credit_review_candidate: bool
    action_items: list[str]
    direction: str
    unit: str
    evidence_status: str
    missing_evidence: list[str]


# A small library of typical SLA credit-claim thresholds.
# breach_count_12m >= 2  OR  actual_last_quarter < target by > 0.5pp  -> eligible.
# This is "SIG-Lite-ish" — operators tune per actual contract.
CREDIT_CLAIM_DELTA_PP = 0.5  # percentage points (or hours) below/above target


# Metrics where lower is better (response time, resolution hours, etc.).
# Anything else (uptime_pct, throughput, etc.) is "higher is better."
_LOWER_IS_BETTER_HINTS = (
    "response",
    "resolution",
    "latency",
    "hours",
    "minutes",
    "mttr",
    "time_to",
)


def _is_lower_better(sla_metric: str) -> bool:
    metric_lc = sla_metric.lower()
    return any(h in metric_lc for h in _LOWER_IS_BETTER_HINTS)


def _compute_compliance_pct(actual: float, target: float, lower_is_better: bool) -> float:
    """Compliance % capped at 100. Direction depends on metric semantics."""
    if target <= 0:
        raise ValueError("服务目标必须大于0")
    if lower_is_better:
        # actual <= target -> 100%. actual = 2*target -> 50%. actual = 4*target -> 25%.
        return round(min(100.0, (target / actual) * 100.0), 2) if actual > 0 else 100.0
    return round(min(100.0, (actual / target) * 100.0), 2)


def _classify_state(
    actual_last_quarter: float, target: float, lower_is_better: bool
) -> ComplianceState:
    if lower_is_better:
        if actual_last_quarter <= target:
            return ComplianceState.MET
        return ComplianceState.BREACHED
    # higher is better
    if actual_last_quarter >= target:
        return ComplianceState.MET
    return ComplianceState.BREACHED


def _classify_trend(
    actual_last_month: float, actual_last_quarter: float, lower_is_better: bool
) -> Trend:
    delta = actual_last_month - actual_last_quarter
    # For lower-is-better metrics, a negative delta (smaller now) is improving.
    if lower_is_better:
        delta = -delta
    if delta > 0.1:
        return Trend.IMPROVING
    if delta < -0.1:
        return Trend.DEGRADING
    return Trend.STABLE


def _credit_eligible(
    actual_last_quarter: float,
    target: float,
    breach_count_12m: int,
    lower_is_better: bool,
) -> bool:
    if breach_count_12m >= 2:
        return True
    if lower_is_better:
        if actual_last_quarter > (target + CREDIT_CLAIM_DELTA_PP):
            return True
    else:
        if actual_last_quarter < (target - CREDIT_CLAIM_DELTA_PP):
            return True
    return False


def _build_action_items(
    state: ComplianceState,
    trend: Trend,
    credit_eligible: bool,
    breach_count_12m: int,
) -> list[str]:
    items: list[str] = []
    if credit_eligible:
        items.append("核对签署合同、排除项、计量依据和申报期限；此处仅是补偿条款待核线索，不代表已确认索赔资格。")
    if state == ComplianceState.BREACHED:
        items.append("建议提交供应商负责人复核，并索取根因分析与改进计划。")
    if state == ComplianceState.AT_RISK and trend == Trend.DEGRADING:
        items.append("建议在30天内安排业务评审，核对指标下降原因与改进计划。")
    if breach_count_12m >= 4:
        items.append(
            f"{breach_count_12m}次未达标记录发生在近12个月，下次评审列为“需复核改进”。"
        )
    if state == ComplianceState.MET and trend == Trend.IMPROVING and breach_count_12m == 0:
        items.append("本规则未提出即时改进项，下一次供应商业务评审继续核对。")
    if not items:
        items.append("继续观察；本规则未提出即时行动。")
    return items


def evaluate_sla(record: dict[str, Any]) -> SLAResult:
    text(record, "vendor")
    sla_metric = text(record, "sla_metric")
    direction = text(record, "direction", {"higher", "lower"})
    unit = text(record, "unit")
    target = number(record, "target")
    if target <= 0:
        raise ValueError("服务目标必须大于0；零容忍指标需要单独规则，不能按100%达标处理")
    actual_month = number(record, "actual_last_month")
    actual_quarter = number(record, "actual_last_quarter")
    if unit == "percent" and max(target, actual_month, actual_quarter) > 100:
        raise ValueError("百分比必须采用0到100的数值口径")
    breach_count = number(record, "breach_count_12m", integer=True)
    lower_is_better = direction == "lower"
    gaps = evidence_gaps(record, ["contract", "measurements", "breach_count_12m"])
    context = record.get("measurement_context", {})
    if not isinstance(context, dict):
        raise ValueError("计量口径measurement_context必须是JSON对象")
    gaps += ["context:" + key for key in ["last_month", "last_quarter", "denominator", "exclusions", "time_basis"]
             if not isinstance(context.get(key), str) or not context[key].strip()]

    state = _classify_state(actual_quarter, target, lower_is_better)
    trend = _classify_trend(actual_month, actual_quarter, lower_is_better)
    eligible = _credit_eligible(actual_quarter, target, breach_count, lower_is_better)
    return SLAResult(
        vendor=str(record["vendor"]),
        sla_metric=sla_metric,
        target=target,
        actual_last_month=actual_month,
        actual_last_quarter=actual_quarter,
        breach_count_12m=breach_count,
        compliance_month_pct=_compute_compliance_pct(
            actual_month, target, lower_is_better
        ),
        compliance_quarter_pct=_compute_compliance_pct(
            actual_quarter, target, lower_is_better
        ),
        state=state,
        trend=trend,
        credit_review_candidate=eligible,
        action_items=(["当前为临时比较，待补依据与口径：" + gap_labels(gaps)] if gaps else []) + _build_action_items(state, trend, eligible, breach_count),
        direction=direction,
        unit=unit,
        evidence_status="REVIEW_REQUIRED" if gaps else "REFERENCES_PROVIDED_NOT_VERIFIED",
        missing_evidence=gaps,
    )


# ---------- Markdown rendering ----------


def render_markdown(results: list[SLAResult]) -> str:
    lines: list[str] = []
    lines.append("# 供应商服务指标检查报告")
    lines.append("")

    # Summary
    total = len(results)
    breached = sum(1 for r in results if r.state == ComplianceState.BREACHED)
    at_risk = sum(1 for r in results if r.state == ComplianceState.AT_RISK)
    eligible = [r for r in results if r.credit_review_candidate]
    lines.append(
        f"**汇总：** {total}项服务指标 · {breached}项指标未达标 · {at_risk}项需关注 · "
        f"{len(eligible)}项补偿条款待核线索（尚未确认索赔资格）。"
    )
    lines.append("")

    # Detail table
    lines.append("比例表示目标达成比（实际值/目标值，或目标值/实际值，封顶100%），不是请求达标率。季度实际值未达到目标时标为“服务指标未达标”，不直接认定已确认合同违约。趋势以0.1个输入单位为稳定范围；补偿线索采用2次未达标或偏差0.5个单位的通用规则，资格须按实际合同核对。")
    lines.append("")
    lines.append("## 各项服务指标")
    lines.append("")
    lines.append(
        "| 供应商 | 服务指标 | 目标 | 上月实际 | 上季实际 | "
        "季度目标达成比 | 季度指标状态 | 趋势 | 近12个月未达标次数 | 补偿条款核查 | 方向/单位 | 依据状态 |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    for r in results:
        lines.append(
            f"| {cell(r.vendor)} | {cell(label(r.sla_metric))} | {r.target} | {r.actual_last_month} | "
            f"{r.actual_last_quarter} | {r.compliance_quarter_pct}% | "
            f"{label(r.state.value)} | {label(r.trend.value)} | {r.breach_count_12m} | "
            f"{'需核对条款' if r.credit_review_candidate else '未触发通用线索'} | {label(r.direction)}/{cell(label(r.unit))} | {label(r.evidence_status)} |"
        )
    lines.append("")

    # Action items
    lines.append("## 后续核查与改进建议")
    lines.append("")
    for r in results:
        lines.append(f"### {r.vendor} — {label(r.sla_metric)}")
        for item in r.action_items:
            lines.append(f"- {item}")
        lines.append("")

    # Credit-claim shortlist
    if eligible:
        lines.append("## 补偿条款待核清单（尚未确认索赔资格）")
        lines.append("")
        lines.append("| 供应商 | 服务指标 | 目标 | 上季实际 | 近12个月未达标次数 |")
        lines.append("|---|---|---|---|---|")
        for r in eligible:
            lines.append(
                f"| {cell(r.vendor)} | {cell(label(r.sla_metric))} | {r.target} | {r.actual_last_quarter} | "
                f"{r.breach_count_12m} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------- Sample data ----------

SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "vendor": "示例供应商01",
        "sla_metric": "uptime_pct",
        "target": 99.99,
        "actual_last_month": 99.95,
        "actual_last_quarter": 99.91,
        "breach_count_12m": 3,
    },
    {
        "vendor": "示例供应商02",
        "sla_metric": "uptime_pct",
        "target": 99.9,
        "actual_last_month": 99.98,
        "actual_last_quarter": 99.97,
        "breach_count_12m": 1,
    },
    {
        "vendor": "示例供应商03",
        "sla_metric": "support_p90_response_hours",
        "target": 8.0,
        "actual_last_month": 36.0,
        "actual_last_quarter": 38.0,
        "breach_count_12m": 11,
    },
    {
        "vendor": "示例供应商04",
        "sla_metric": "uptime_pct",
        "target": 99.5,
        "actual_last_month": 99.6,
        "actual_last_quarter": 99.5,
        "breach_count_12m": 0,
    },
    {
        "vendor": "示例供应商05",
        "sla_metric": "ticket_resolution_hours",
        "target": 24.0,
        "actual_last_month": 30.0,
        "actual_last_quarter": 28.0,
        "breach_count_12m": 6,
    },
]


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="检查供应商服务指标差距与趋势，列出补偿条款待核线索。"
    )
    parser.add_argument("--input", type=Path, help="服务指标记录JSON文件路径。")
    parser.add_argument("--output", type=Path, help="新建Markdown检查报告的路径。")
    parser.add_argument(
        "--sample", action="store_true", help="使用内置服务指标格式样例，不代表真实表现。"
    )
    args = parser.parse_args(argv)

    if not args.sample and not args.input:
        parser.error("请提供--input输入文件，或使用--sample查看格式样例")

    if args.sample:
        records = SAMPLE_RECORDS
    else:
        try:
            records = json.loads(args.input.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"读取输入失败：{args.input}；{error_text(exc)}", file=sys.stderr)
            return 2
        if not isinstance(records, list):
            print("输入JSON必须是服务指标记录列表", file=sys.stderr)
            return 2

    try:
        records_list(records)
        if args.sample:
            records = [dict(r, direction="lower" if _is_lower_better(r["sla_metric"]) else "higher",
                            unit="hours" if _is_lower_better(r["sla_metric"]) else "percent") for r in records]
        results = [evaluate_sla(r) for r in records]
        md = render_markdown(results)
        if args.sample:
            md = "# 仅供格式演示，不代表真实供应商表现\n\n" + md
        if args.output:
            write_report(args.output, md, args.input)
            print(f"报告已保存：{args.output}")
        else:
            print(md)
        return 3 if any(v.missing_evidence for v in results) else 0
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        print(f"输入或输出错误：{error_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
