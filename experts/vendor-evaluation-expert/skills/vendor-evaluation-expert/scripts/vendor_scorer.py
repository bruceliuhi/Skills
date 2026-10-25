#!/usr/bin/env python3
"""
vendor_scorer.py — Multi-dimensional 0-100 vendor scoring with industry profile tuning.

Scores each vendor across 5 weighted dimensions:
  1. Reliability   — uptime % + incident count
  2. Support       — P90 ticket response hours
  3. Security      — security certifications coverage
  4. Commercial    — renewal flexibility
  5. Strategic fit — criticality vs annual spend

Industry profiles ({saas,fintech,healthcare,enterprise}) re-weight the dimensions.
Output: ranked markdown scorecard with per-dimension breakdown + verdict (KEEP/REVIEW/REPLACE).

Stdlib only. Deterministic. No LLM calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from _validation import label, gap_labels, error_text, ChineseArgumentParser, normalize_spend, number, text, tags, vendor_core, records_list, evidence_gaps, write_report, cell
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------- Industry profile weights ----------

PROFILES: dict[str, dict[str, float]] = {
    "saas": {
        "reliability": 0.30,
        "support": 0.15,
        "security": 0.25,
        "commercial": 0.15,
        "strategic_fit": 0.15,
    },
    "fintech": {
        "reliability": 0.25,
        "support": 0.15,
        "security": 0.30,
        "commercial": 0.15,
        "strategic_fit": 0.15,
    },
    "healthcare": {
        "reliability": 0.25,
        "support": 0.15,
        "security": 0.35,
        "commercial": 0.10,
        "strategic_fit": 0.15,
    },
    "enterprise": {
        "reliability": 0.25,
        "support": 0.20,
        "security": 0.25,
        "commercial": 0.15,
        "strategic_fit": 0.15,
    },
}

CERT_VALUE: dict[str, int] = {
    "SOC2": 15,
    "SOC2-Type-II": 25,
    "ISO27001": 20,
    "HIPAA": 15,
    "PCI-DSS": 15,
    "FedRAMP": 20,
    "GDPR-DPA": 10,
    "CCPA": 5,
}

RENEWAL_SCORE: dict[str, int] = {
    "manual-renew": 100,
    "fixed-term": 80,
    "evergreen": 50,
    "auto-renew": 35,
}


# ---------- Data shape ----------


class Verdict(str, Enum):
    KEEP = "KEEP"
    REVIEW = "REVIEW"
    REPLACE = "REPLACE"


@dataclass
class DimensionBreakdown:
    reliability: float
    support: float
    security: float
    commercial: float
    strategic_fit: float

    def as_dict(self) -> dict[str, float]:
        return {
            "reliability": self.reliability,
            "support": self.support,
            "security": self.security,
            "commercial": self.commercial,
            "strategic_fit": self.strategic_fit,
        }


@dataclass
class ScoredVendor:
    name: str
    category: str
    annual_spend: float
    criticality: str
    overall: float
    verdict: Verdict
    dimensions: DimensionBreakdown
    notes: list[str] = field(default_factory=list)
    model_verdict: str = ""
    evidence_status: str = "REFERENCES_PROVIDED_NOT_VERIFIED"
    missing_evidence: list[str] = field(default_factory=list)


# ---------- Per-dimension scoring (deterministic) ----------


def score_reliability(uptime_pct: float, incident_count: int) -> float:
    """Reliability = uptime_pct mapped to 0-100, penalized by incidents.

    99.95 uptime -> 99 points base. Each incident over 1 in the last 12m subtracts 5.
    """
    base = max(0.0, min(100.0, (uptime_pct - 95.0) * 20.0))  # 95.0 -> 0, 100.0 -> 100
    penalty = max(0, incident_count - 1) * 5
    return max(0.0, min(100.0, base - penalty))


def score_support(p90_hours: float) -> float:
    """Support = P90 ticket response hours mapped to 0-100.

    <= 1h -> 100. 24h -> approximately 67.6. 72h -> 0.
    """
    if p90_hours <= 1.0:
        return 100.0
    if p90_hours >= 72.0:
        return 0.0
    # Linear from (1, 100) to (72, 0)
    return max(0.0, min(100.0, 100.0 - ((p90_hours - 1.0) * 100.0 / 71.0)))


def score_security(certs: list[str], profile: str) -> float:
    """Security = sum of cert values, capped at 100. Healthcare/fintech demand more."""
    total = sum(CERT_VALUE.get(c, 0) for c in certs)
    # In healthcare and fintech, raw cert score is harder to max out
    if profile in {"healthcare", "fintech"}:
        total = total * 0.85
    return max(0.0, min(100.0, float(total)))


def score_commercial(renewal_terms: str) -> float:
    """Commercial = renewal flexibility. Manual renew > fixed-term > evergreen > auto-renew."""
    return float(RENEWAL_SCORE.get(renewal_terms, 50))


def score_strategic_fit(criticality: str, annual_spend: float) -> float:
    """Strategic fit = criticality vs spend alignment.

    Tier-1 paying < $50k -> 100 (high value, low cost).
    Tier-3 paying >= $50k -> 20 (low value, high cost — kill candidate).
    """
    if criticality == "tier-1":
        if annual_spend < 50_000:
            return 100.0
        if annual_spend < 250_000:
            return 80.0
        return 60.0
    if criticality == "tier-2":
        if annual_spend < 25_000:
            return 90.0
        if annual_spend < 100_000:
            return 70.0
        return 50.0
    # tier-3
    if annual_spend < 10_000:
        return 70.0
    if annual_spend < 50_000:
        return 50.0
    return 20.0


def verdict_for(overall: float) -> Verdict:
    if overall >= 75:
        return Verdict.KEEP
    if overall >= 50:
        return Verdict.REVIEW
    return Verdict.REPLACE


def score_vendor(vendor: dict[str, Any], profile: str) -> ScoredVendor:
    vendor = normalize_spend(vendor)
    vendor_core(vendor)
    number(vendor, "uptime_pct", maximum=100)
    number(vendor, "incident_count_last_12m", integer=True)
    number(vendor, "support_response_hours_p90")
    tags(vendor, "security_certs", CERT_VALUE)
    text(vendor, "renewal_terms", RENEWAL_SCORE)
    weights = PROFILES[profile]
    rel = score_reliability(
        float(vendor.get("uptime_pct", 0.0)),
        int(vendor.get("incident_count_last_12m", 0)),
    )
    sup = score_support(float(vendor.get("support_response_hours_p90", 999.0)))
    sec = score_security(list(vendor.get("security_certs", [])), profile)
    com = score_commercial(str(vendor.get("renewal_terms", "auto-renew")))
    fit = score_strategic_fit(
        str(vendor.get("criticality", "tier-3")),
        float(vendor.get("annual_spend", 0.0)),
    )

    overall = (
        rel * weights["reliability"]
        + sup * weights["support"]
        + sec * weights["security"]
        + com * weights["commercial"]
        + fit * weights["strategic_fit"]
    )

    notes: list[str] = []
    if vendor.get("_currency_basis"):
        notes.append(vendor["_currency_basis"])
    if vendor.get("criticality") == "tier-1" and not vendor.get("security_certs"):
        notes.append("一级关键供应商未列出证明材料；续约前核对适用的安全报告与缺失依据。")
    if vendor.get("renewal_terms") == "auto-renew" and float(vendor.get("annual_spend", 0)) > 50_000:
        notes.append("年度支出超过5万美元且采用自动续约；建议复核取消窗口与手动续约条件。")
    if int(vendor.get("incident_count_last_12m", 0)) >= 5:
        notes.append(
            f"{vendor['incident_count_last_12m']}次事件发生在近12个月，建议索取根因分析与改进计划。"
        )

    gaps = evidence_gaps(vendor, ["annual_spend", "uptime_pct", "support_response_hours_p90",
                                  "incident_count_last_12m", "renewal_terms", "criticality"], certificates=True)
    if gaps:
        notes.append("待补依据：" + gap_labels(gaps) + "；当前评分仅供临时复核。")
    return ScoredVendor(
        name=str(vendor.get("name", "Unknown")),
        category=str(vendor.get("category", "uncategorized")),
        annual_spend=float(vendor.get("annual_spend", 0.0)),
        criticality=str(vendor.get("criticality", "tier-3")),
        overall=round(overall, 1),
        verdict=Verdict.REVIEW if gaps else verdict_for(overall),
        model_verdict=verdict_for(overall).value,
        evidence_status="REVIEW_REQUIRED" if gaps else "REFERENCES_PROVIDED_NOT_VERIFIED",
        missing_evidence=gaps,
        dimensions=DimensionBreakdown(
            reliability=round(rel, 1),
            support=round(sup, 1),
            security=round(sec, 1),
            commercial=round(com, 1),
            strategic_fit=round(fit, 1),
        ),
        notes=notes,
    )


# ---------- Markdown rendering ----------


def render_markdown(scored: list[ScoredVendor], profile: str) -> str:
    scored_sorted = sorted(scored, key=lambda s: s.overall, reverse=True)
    weights = PROFILES[profile]
    lines: list[str] = []
    lines.append(f"# 供应商绩效评分表｜{label(profile)}口径")
    lines.append("")
    lines.append(
        f"评分权重：可靠性 **{int(weights['reliability'] * 100)}%** · "
        f"支持响应 **{int(weights['support'] * 100)}%** · "
        f"安全材料 **{int(weights['security'] * 100)}%** · "
        f"商务条件 **{int(weights['commercial'] * 100)}%** · "
        f"战略匹配 **{int(weights['strategic_fit'] * 100)}%**"
    )
    lines.append("")
    lines.append("来源引用尚未独立核验。继续合作或评估替代均为规则建议，不代表已批准续约、解约或停用。")
    lines.append("")
    lines.append("## 供应商评分排序")
    lines.append("")
    lines.append(
        "| 排名 | 供应商 | 类别 | 关键性 | 年度支出（美元） | 综合分 | 建议行动 | 依据状态 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, sv in enumerate(scored_sorted, start=1):
        lines.append(
            f"| {i} | {cell(sv.name)} | {cell(label(sv.category))} | {label(sv.criticality)} | "
            f"{sv.annual_spend:,.0f} | **{sv.overall}** | {label(sv.verdict.value)} | {label(sv.evidence_status)} |"
        )
    lines.append("")

    lines.append("## 五维评分明细")
    lines.append("")
    lines.append(
        "| 供应商 | 可靠性 | 支持响应 | 安全材料 | 商务条件 | 战略匹配 |"
    )
    lines.append("|---|---|---|---|---|---|")
    for sv in scored_sorted:
        d = sv.dimensions
        lines.append(
            f"| {cell(sv.name)} | {d.reliability} | {d.support} | {d.security} | "
            f"{d.commercial} | {d.strategic_fit} |"
        )
    lines.append("")

    lines.append("## 建议行动汇总")
    lines.append("")
    keep = [s for s in scored_sorted if s.verdict == Verdict.KEEP]
    review = [s for s in scored_sorted if s.verdict == Verdict.REVIEW]
    replace = [s for s in scored_sorted if s.verdict == Verdict.REPLACE]
    lines.append(f"- **建议继续合作（{len(keep)}家）：** " + (", ".join(s.name for s in keep) or "无"))
    lines.append(
        f"- **需复核改进（{len(review)}家）：** " + (", ".join(s.name for s in review) or "无")
    )
    lines.append(
        f"- **建议评估替代（{len(replace)}家）：** " + (", ".join(s.name for s in replace) or "无")
    )
    lines.append("")

    flagged = [s for s in scored_sorted if s.notes]
    if flagged:
        lines.append("## 后续核查与改进建议")
        lines.append("")
        for sv in flagged:
            lines.append(f"### {sv.name} ({label(sv.verdict.value)} · {sv.overall}分)")
            for n in sv.notes:
                lines.append(f"- {n}")
            lines.append("")

    return "\n".join(lines)


# ---------- Sample data ----------


SAMPLE_CATALOG: list[dict[str, Any]] = [
    {
        "name": "示例供应商01",
        "category": "identity",
        "annual_spend": 180_000,
        "contract_end_date": "2026-09-30",
        "criticality": "tier-1",
        "uptime_pct": 99.91,
        "support_response_hours_p90": 4.5,
        "incident_count_last_12m": 3,
        "security_certs": ["SOC2-Type-II", "ISO27001", "FedRAMP", "GDPR-DPA"],
        "renewal_terms": "manual-renew",
    },
    {
        "name": "示例供应商02",
        "category": "data-warehouse",
        "annual_spend": 420_000,
        "contract_end_date": "2027-01-15",
        "criticality": "tier-1",
        "uptime_pct": 99.97,
        "support_response_hours_p90": 2.0,
        "incident_count_last_12m": 1,
        "security_certs": ["SOC2-Type-II", "ISO27001", "HIPAA", "GDPR-DPA"],
        "renewal_terms": "fixed-term",
    },
    {
        "name": "示例供应商03",
        "category": "crm",
        "annual_spend": 95_000,
        "contract_end_date": "2026-06-30",
        "criticality": "tier-2",
        "uptime_pct": 98.20,
        "support_response_hours_p90": 38.0,
        "incident_count_last_12m": 11,
        "security_certs": ["SOC2"],
        "renewal_terms": "auto-renew",
    },
    {
        "name": "示例供应商04",
        "category": "analytics",
        "annual_spend": 8_000,
        "contract_end_date": "2026-08-01",
        "criticality": "tier-3",
        "uptime_pct": 99.50,
        "support_response_hours_p90": 14.0,
        "incident_count_last_12m": 2,
        "security_certs": ["SOC2", "GDPR-DPA"],
        "renewal_terms": "evergreen",
    },
    {
        "name": "示例供应商05",
        "category": "qa-services",
        "annual_spend": 220_000,
        "contract_end_date": "2026-12-31",
        "criticality": "tier-3",
        "uptime_pct": 99.00,
        "support_response_hours_p90": 22.0,
        "incident_count_last_12m": 6,
        "security_certs": [],
        "renewal_terms": "auto-renew",
    },
]


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="按行业口径生成供应商五维评分与证据缺口清单。"
    )
    parser.add_argument("--input", type=Path, help="供应商目录JSON文件路径。")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default="saas",
        help="评分口径：saas软件服务、fintech金融科技、healthcare医疗健康、enterprise企业服务；默认saas。",
    )
    parser.add_argument("--output", type=Path, help="新建Markdown评分报告的路径。")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="使用内置5家格式样例，不代表真实客户或供应商表现。",
    )
    args = parser.parse_args(argv)

    if not args.sample and not args.input:
        parser.error("请提供--input输入文件，或使用--sample查看格式样例")

    if args.sample:
        catalog = SAMPLE_CATALOG
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
        scored = [score_vendor(v, args.profile) for v in catalog]
        md = render_markdown(scored, args.profile)
        if args.sample:
            md = "# 仅供格式演示，不代表真实供应商表现\n\n" + md
        if args.output:
            write_report(args.output, md, args.input)
            print(f"报告已保存：{args.output}")
        else:
            print(md)
        return 3 if any(v.missing_evidence for v in scored) else 0
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        print(f"输入或输出错误：{error_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
