#!/usr/bin/env python3
"""
vendor_risk_classifier.py — Classify third-party risk across 4 vectors.

Inspired by Shared Assessments SIG-Lite + NIST SP 800-161 supply chain risk.
Classifies each vendor as Critical / High / Medium / Low across:

  1. Data sensitivity      — PII / PHI / cardholder / source code access
  2. Financial exposure    — annual spend × tier multiplier
  3. Operational dependency — tier-1 + no break-glass = Critical
  4. Regulatory exposure   — industry profile drives weighting

Industry profile ({saas,fintech,healthcare,enterprise}) re-weights regulatory.

Output: risk matrix markdown + per-vendor mitigation recommendations.

Stdlib only. Deterministic. No LLM calls.
"""

from __future__ import annotations

import argparse
import json
import sys
import math
from _validation import label, gap_labels, error_text, ChineseArgumentParser, normalize_spend, number, tags, vendor_core, records_list, evidence_gaps, write_report, cell
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


_LEVEL_RANK = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


@dataclass
class RiskBreakdown:
    data_sensitivity: RiskLevel
    financial_exposure: RiskLevel
    operational_dependency: RiskLevel
    regulatory_exposure: RiskLevel


@dataclass
class RiskClassification:
    vendor: str
    category: str
    overall: RiskLevel
    breakdown: RiskBreakdown
    mitigations: list[str]
    evidence_status: str
    missing_evidence: list[str]


# ---------- Per-vector classifiers ----------


_DATA_SENSITIVITY_KEYS = {
    "PHI": RiskLevel.CRITICAL,
    "PII": RiskLevel.HIGH,
    "cardholder": RiskLevel.CRITICAL,
    "source-code": RiskLevel.HIGH,
    "financial-records": RiskLevel.HIGH,
    "employee-records": RiskLevel.HIGH,
    "customer-emails": RiskLevel.MEDIUM,
    "logs-only": RiskLevel.LOW,
    "no-customer-data": RiskLevel.LOW,
}


def classify_data_sensitivity(vendor: dict[str, Any]) -> RiskLevel:
    """Choose worst of declared data_access tags. Default Medium if unspecified."""
    tags = vendor.get("data_access") or []
    if not tags:
        return RiskLevel.MEDIUM
    levels = [_DATA_SENSITIVITY_KEYS.get(t, RiskLevel.MEDIUM) for t in tags]
    return max(levels, key=lambda lv: _LEVEL_RANK[lv])


def classify_financial_exposure(vendor: dict[str, Any]) -> RiskLevel:
    spend = float(vendor.get("annual_spend", 0))
    crit = str(vendor.get("criticality", "tier-3"))
    multiplier = {"tier-1": 1.5, "tier-2": 1.0, "tier-3": 0.6}.get(crit, 0.6)
    weighted = spend * multiplier
    if not math.isfinite(weighted):
        raise ValueError("年度支出计算后的风险暴露必须是有限数值")
    if weighted >= 500_000:
        return RiskLevel.CRITICAL
    if weighted >= 150_000:
        return RiskLevel.HIGH
    if weighted >= 50_000:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def classify_operational_dependency(vendor: dict[str, Any]) -> RiskLevel:
    crit = str(vendor.get("criticality", "tier-3"))
    has_breakglass = bool(vendor.get("break_glass_plan", False))
    if crit == "tier-1" and not has_breakglass:
        return RiskLevel.CRITICAL
    if crit == "tier-1":
        return RiskLevel.HIGH
    if crit == "tier-2" and not has_breakglass:
        return RiskLevel.HIGH
    if crit == "tier-2":
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


_REGULATORY_PROFILE: dict[str, dict[str, RiskLevel]] = {
    # Per-profile, mapping of cert presence to risk reduction.
    # Worst case before mitigations:
    # healthcare requires HIPAA, fintech requires SOC2-Type-II + PCI-DSS (if cardholder).
    "saas": {},
    "fintech": {},
    "healthcare": {},
    "enterprise": {},
}


def classify_regulatory_exposure(
    vendor: dict[str, Any], profile: str
) -> RiskLevel:
    certs = set(vendor.get("security_certs") or [])
    data_tags = set(vendor.get("data_access") or [])

    if profile == "healthcare":
        if "PHI" in data_tags and "HIPAA" not in certs:
            return RiskLevel.CRITICAL
        if "PHI" in data_tags:
            return RiskLevel.HIGH
        if "PII" in data_tags and "SOC2-Type-II" not in certs:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    if profile == "fintech":
        if "cardholder" in data_tags and "PCI-DSS" not in certs:
            return RiskLevel.CRITICAL
        if "cardholder" in data_tags:
            return RiskLevel.HIGH
        if "SOC2-Type-II" not in certs and "ISO27001" not in certs:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    if profile == "enterprise":
        if "PII" in data_tags and "SOC2-Type-II" not in certs:
            return RiskLevel.HIGH
        if "SOC2" not in certs and "SOC2-Type-II" not in certs:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # saas (default)
    if "PII" in data_tags and "SOC2" not in certs and "SOC2-Type-II" not in certs:
        return RiskLevel.HIGH
    if "PII" in data_tags:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def overall_risk(breakdown: RiskBreakdown) -> RiskLevel:
    # Overall = worst-of, with one nuance: two HIGH vectors -> CRITICAL.
    levels = [
        breakdown.data_sensitivity,
        breakdown.financial_exposure,
        breakdown.operational_dependency,
        breakdown.regulatory_exposure,
    ]
    worst = max(levels, key=lambda lv: _LEVEL_RANK[lv])
    high_count = sum(1 for lv in levels if lv == RiskLevel.HIGH)
    if worst == RiskLevel.HIGH and high_count >= 2:
        return RiskLevel.CRITICAL
    return worst


def build_mitigations(
    vendor: dict[str, Any], breakdown: RiskBreakdown, profile: str
) -> list[str]:
    mits: list[str] = []
    certs = set(vendor.get("security_certs") or [])
    data_tags = set(vendor.get("data_access") or [])

    if breakdown.data_sensitivity in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        mits.append(
            "核对数据处理协议是否仍适用，以及静态存储和传输加密的实际依据。"
        )
    if breakdown.financial_exposure in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        mits.append(
            "复核责任限额是否与暴露相称（模型参考值为12个月费用），并核对保险材料；以实际合同为准。"
        )
    if breakdown.operational_dependency == RiskLevel.CRITICAL:
        mits.append(
            "补充72小时应急替代预案，并由负责人核对备用供应商的可用性。"
        )
    if breakdown.regulatory_exposure == RiskLevel.CRITICAL:
        if profile == "healthcare" and "HIPAA" not in certs:
            mits.append("涉及受保护健康信息时，先由负责人核对适用协议及处理依据，再决定访问安排；工具不自动停用权限。")
        if profile == "fintech" and "cardholder" in data_tags and "PCI-DSS" not in certs:
            mits.append("涉及持卡人数据时，先核对适用的PCI-DSS符合性证明，再由负责人决定访问安排。")
    if breakdown.regulatory_exposure in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        mits.append("索取适用的近期SOC2 Type II报告，并核对例外项及覆盖范围。")
    if not mits:
        mits.append("本规则未列出紧急改进项，仍需完成例行复核。")
    return mits


def classify_vendor(vendor: dict[str, Any], profile: str) -> RiskClassification:
    vendor = normalize_spend(vendor)
    vendor_core(vendor)
    tags(vendor, "data_access", _DATA_SENSITIVITY_KEYS, nonempty=True)
    tags(vendor, "security_certs")
    if not isinstance(vendor.get("break_glass_plan"), bool):
        raise ValueError("应急替代方案break_glass_plan必须明确填写JSON布尔值true或false，不能用文本代替")
    gaps = evidence_gaps(vendor, ["annual_spend", "criticality", "data_access", "break_glass_plan"], certificates=True)
    breakdown = RiskBreakdown(
        data_sensitivity=classify_data_sensitivity(vendor),
        financial_exposure=classify_financial_exposure(vendor),
        operational_dependency=classify_operational_dependency(vendor),
        regulatory_exposure=classify_regulatory_exposure(vendor, profile),
    )
    mitigations = build_mitigations(vendor, breakdown, profile)
    if vendor.get("_currency_basis"):
        mitigations.insert(0, vendor["_currency_basis"])
    if gaps:
        mitigations.insert(0, "临时风险判断，待补依据：" + gap_labels(gaps))
    return RiskClassification(
        vendor=str(vendor.get("name", "Unknown")),
        category=str(vendor.get("category", "uncategorized")),
        overall=overall_risk(breakdown),
        breakdown=breakdown,
        mitigations=mitigations,
        evidence_status="REVIEW_REQUIRED" if gaps else "REFERENCES_PROVIDED_NOT_VERIFIED",
        missing_evidence=gaps,
    )


# ---------- Markdown rendering ----------


def render_markdown(results: list[RiskClassification], profile: str) -> str:
    by_overall = sorted(
        results, key=lambda r: _LEVEL_RANK[r.overall], reverse=True
    )
    lines: list[str] = []
    lines.append(f"# 供应商风险矩阵｜{label(profile)}口径")
    lines.append("")

    crit = [r for r in by_overall if r.overall == RiskLevel.CRITICAL]
    high = [r for r in by_overall if r.overall == RiskLevel.HIGH]
    lines.append(
        f"**汇总：** {len(crit)}家严重风险 · {len(high)}家较高风险 · "
        f"{sum(1 for r in by_overall if r.overall == RiskLevel.MEDIUM)}家中等风险 · "
        f"{sum(1 for r in by_overall if r.overall == RiskLevel.LOW)}家较低风险"
    )
    lines.append("")

    lines.append("以下风险为规则分级，不是合规结论。来源引用、证明材料的真实性和适用范围仍需核验。")
    lines.append("")
    lines.append("## 四维风险明细")
    lines.append("")
    lines.append(
        "| 供应商 | 类别 | 数据敏感性 | 支出暴露 | 运营依赖 | 合规暴露 | 综合风险 | 依据状态 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in by_overall:
        b = r.breakdown
        lines.append(
            f"| {cell(r.vendor)} | {cell(label(r.category))} | {label(b.data_sensitivity.value)} | "
            f"{label(b.financial_exposure.value)} | {label(b.operational_dependency.value)} | "
            f"{label(b.regulatory_exposure.value)} | **{label(r.overall.value)}** | {label(r.evidence_status)} |"
        )
    lines.append("")

    lines.append("## 待核事项与改进建议")
    lines.append("")
    for r in by_overall:
        lines.append(f"### {r.vendor} — {label(r.overall.value)}")
        for m in r.mitigations:
            lines.append(f"- {m}")
        lines.append("")

    return "\n".join(lines)


# ---------- Sample data ----------

SAMPLE_VENDORS: list[dict[str, Any]] = [
    {
        "name": "示例供应商01",
        "category": "identity",
        "annual_spend": 180_000,
        "criticality": "tier-1",
        "data_access": ["PII", "employee-records"],
        "security_certs": ["SOC2-Type-II", "ISO27001", "FedRAMP", "GDPR-DPA"],
        "break_glass_plan": True,
    },
    {
        "name": "示例供应商02",
        "category": "data-warehouse",
        "annual_spend": 420_000,
        "criticality": "tier-1",
        "data_access": ["PII", "PHI", "financial-records"],
        "security_certs": ["SOC2-Type-II", "ISO27001", "HIPAA", "GDPR-DPA"],
        "break_glass_plan": False,
    },
    {
        "name": "示例供应商03",
        "category": "crm",
        "annual_spend": 95_000,
        "criticality": "tier-2",
        "data_access": ["PII", "customer-emails"],
        "security_certs": ["SOC2"],
        "break_glass_plan": False,
    },
    {
        "name": "示例供应商04",
        "category": "analytics",
        "annual_spend": 8_000,
        "criticality": "tier-3",
        "data_access": ["logs-only"],
        "security_certs": ["SOC2", "GDPR-DPA"],
        "break_glass_plan": True,
    },
    {
        "name": "示例供应商05",
        "category": "qa-services",
        "annual_spend": 220_000,
        "criticality": "tier-3",
        "data_access": ["source-code", "PII"],
        "security_certs": [],
        "break_glass_plan": False,
    },
]


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="按行业口径生成供应商四维风险矩阵与核查建议。"
    )
    parser.add_argument("--input", type=Path, help="供应商目录JSON文件路径。")
    parser.add_argument(
        "--profile",
        choices=["saas", "fintech", "healthcare", "enterprise"],
        default="saas",
        help="风险口径：saas软件服务、fintech金融科技、healthcare医疗健康、enterprise企业服务；默认saas。",
    )
    parser.add_argument("--output", type=Path, help="新建Markdown风险报告的路径。")
    parser.add_argument(
        "--sample", action="store_true", help="使用内置5家格式样例，不代表真实客户或供应商表现。"
    )
    args = parser.parse_args(argv)

    if not args.sample and not args.input:
        parser.error("请提供--input输入文件，或使用--sample查看格式样例")

    if args.sample:
        catalog = SAMPLE_VENDORS
    else:
        try:
            catalog = json.loads(args.input.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"读取输入失败：{args.input}；{error_text(exc)}", file=sys.stderr)
            return 2
        if not isinstance(catalog, list):
            print("输入JSON必须是供应商记录列表", file=sys.stderr)
            return 2

    try:
        records_list(catalog)
        if args.sample:
            catalog = [dict(v, currency="USD") for v in catalog]
        results = [classify_vendor(v, args.profile) for v in catalog]
        md = render_markdown(results, args.profile)
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
