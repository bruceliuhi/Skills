"""Local input and evidence validation shared by the three vendor tools."""
import math
import re
import argparse
import json
from datetime import date
from pathlib import Path

FIELD_LABELS = {
    "name": "供应商名称", "vendor": "供应商名称", "category": "供应商类别",
    "annual_spend": "年度支出", "currency": "币种", "criticality": "业务关键性",
    "uptime_pct": "可用率", "support_response_hours_p90": "支持响应P90时长",
    "incident_count_last_12m": "近12个月事件数", "security_certs": "证明材料标签",
    "renewal_terms": "续约方式", "data_access": "数据访问范围",
    "break_glass_plan": "应急替代方案", "usd_exchange_rate": "美元折算率",
    "exchange_rate_date": "汇率日期", "exchange_rate_source": "汇率来源",
    "sla_metric": "服务指标", "direction": "指标方向", "unit": "计量单位",
    "target": "服务目标", "actual_last_month": "上月实际值",
    "actual_last_quarter": "上季实际值", "breach_count_12m": "近12个月未达标次数",
    "contract": "合同条款依据", "measurements": "计量记录依据",
    "last_month": "月份范围", "last_quarter": "季度范围", "denominator": "计量分母",
    "exclusions": "排除项", "time_basis": "计时与时区口径",
}
DISPLAY = {
    "saas": "软件服务", "fintech": "金融科技", "healthcare": "医疗健康", "enterprise": "企业服务",
    "tier-1": "一级关键", "tier-2": "二级重要", "tier-3": "三级一般",
    "KEEP": "建议继续合作", "REVIEW": "需复核改进", "REPLACE": "建议评估替代",
    "Critical": "严重风险（规则分级）", "High": "较高风险（规则分级）",
    "Medium": "中等风险（规则分级）", "Low": "较低风险（规则分级）",
    "met": "服务指标达标", "at-risk": "服务指标需关注", "breached": "服务指标未达标",
    "improving": "改善", "stable": "稳定", "degrading": "下降",
    "REVIEW_REQUIRED": "待补依据、需复核", "REFERENCES_PROVIDED_NOT_VERIFIED": "已提供引用、尚未核验",
    "higher": "越高越好", "lower": "越低越好", "percent": "百分比", "hours": "小时",
    "minutes": "分钟", "seconds": "秒", "units": "单位", "requests": "请求数",
    "identity": "身份认证", "data-warehouse": "数据仓库", "crm": "客户管理",
    "analytics": "数据分析", "qa-services": "质量测试服务", "uncategorized": "未分类",
    "uptime_pct": "可用率", "support_p90_response_hours": "支持响应P90时长",
    "ticket_resolution_hours": "工单解决时长",
}


def label(value):
    return DISPLAY.get(str(value), str(value))


def field_label(value):
    if value.startswith("cert:"):
        return "证明材料依据：" + value[5:]
    if value.startswith("context:"):
        return "计量口径：" + FIELD_LABELS.get(value[8:], value[8:])
    return FIELD_LABELS.get(value, value)


def gap_labels(values):
    return "、".join(field_label(value) for value in values)


def error_text(exc):
    if isinstance(exc, FileNotFoundError):
        return "找不到文件或目录：" + str(exc.filename)
    if isinstance(exc, FileExistsError):
        return "结果文件已存在，请使用新文件名：" + str(exc.filename)
    if isinstance(exc, PermissionError):
        return "没有读取或写入权限：" + str(exc.filename)
    if isinstance(exc, json.JSONDecodeError):
        return f"JSON格式错误：第{exc.lineno}行，第{exc.colno}列"
    return str(exc)


class ChineseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "可选参数"
        self.add_argument("-h", "--help", action="help", help="显示帮助并退出")

    def format_help(self):
        return super().format_help().replace("usage:", "用法：")

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：")

    def error(self, message):
        for old, new in [("the following arguments are required:", "缺少必需参数："),
                         ("unrecognized arguments:", "无法识别的参数："),
                         ("invalid choice:", "选项无效："), ("argument ", "参数 "),
                         ("expected one argument", "需要一个参数值"), ("choose from", "可选值")]:
            message = message.replace(old, new)
        self.print_usage(__import__("sys").stderr)
        self.exit(2, "参数错误：" + message + "\n")


def number(record, key, minimum=0, maximum=None, integer=False):
    value = record.get(key)
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{field_label(key)}（{key}）：需要有限数值，缺失不能按0处理")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{field_label(key)}（{key}）：数值格式无效：{value!r}")
    if not math.isfinite(result):
        raise ValueError(f"{field_label(key)}（{key}）：必须是有限数值，不能使用NaN或Infinity")
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"{field_label(key)}（{key}）：数值超出支持范围")
    if integer and not result.is_integer():
        raise ValueError(f"{field_label(key)}（{key}）：次数必须是整数")
    return int(result) if integer else result


def text(record, key, choices=None):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_label(key)}（{key}）：需要非空文本")
    if choices is not None and value not in choices:
        raise ValueError(f"{field_label(key)}（{key}）：不支持此值：{value!r}")
    return value


def tags(record, key, choices=None, nonempty=False):
    values = record.get(key)
    if not isinstance(values, list) or any(not isinstance(x, str) or not x.strip() for x in values):
        raise ValueError(f"{field_label(key)}（{key}）：需要明确的文本列表")
    if nonempty and not values:
        raise ValueError(f"{field_label(key)}（{key}）：资料缺失不能当成没有数据访问权限")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_label(key)}（{key}）：标签不能重复")
    if choices is not None and any(x not in choices for x in values):
        raise ValueError(f"{field_label(key)}（{key}）：存在不支持的标签，请先确认映射")
    return values


def vendor_core(record):
    if not isinstance(record, dict):
        raise ValueError("每条供应商记录必须是JSON对象")
    text(record, "name")
    text(record, "category")
    text(record, "criticality", {"tier-1", "tier-2", "tier-3"})
    text(record, "currency", {"USD"})
    number(record, "annual_spend")


def normalize_spend(record):
    """Copy a user's explicit FX basis into USD without changing the input record."""
    if not isinstance(record, dict):
        raise ValueError("每条供应商记录必须是JSON对象")
    currency = text(record, "currency")
    amount = number(record, "annual_spend")
    result = dict(record)
    result["_currency_basis"] = ""
    if currency == "USD":
        if "usd_exchange_rate" in record and number(record, "usd_exchange_rate") != 1:
            raise ValueError("美元输入的美元折算率只能为1")
        return result
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("币种必须是明确的三个大写字母代码，例如CNY或USD")
    rate = number(record, "usd_exchange_rate")
    if rate <= 0:
        raise ValueError("美元折算率必须大于0，含义是每1原币可折多少美元")
    rate_date = text(record, "exchange_rate_date")
    try:
        parsed = date.fromisoformat(rate_date)
    except ValueError:
        raise ValueError("汇率日期必须采用YYYY-MM-DD格式")
    if parsed.isoformat() != rate_date:
        raise ValueError("汇率日期必须采用YYYY-MM-DD格式")
    source = text(record, "exchange_rate_source")
    converted = amount * rate
    if not math.isfinite(converted):
        raise ValueError("折算后的年度支出必须是有限数值")
    result["annual_spend"] = converted
    result["currency"] = "USD"
    result["_currency_basis"] = (
        f"原币年度支出：{amount:g} {currency}；用户提供汇率："
        f"{rate:g} 美元/{currency}；日期：{rate_date}；来源：{source}；"
        f"折算支出：{converted:g} 美元。汇率依据尚未独立核验。"
    )
    return result


def records_list(value):
    if not isinstance(value, list) or not value:
        raise ValueError("输入必须是包含至少一条记录的JSON对象列表")
    if any(not isinstance(x, dict) for x in value):
        raise ValueError("每条输入记录必须是JSON对象")


def evidence_gaps(record, fields, certificates=False):
    evidence = record.get("evidence", {})
    if not isinstance(evidence, dict):
        raise ValueError("依据字段evidence必须按字段名称填写来源引用")
    gaps = [key for key in fields if not isinstance(evidence.get(key), str) or not evidence[key].strip()]
    if certificates:
        cert_refs = record.get("cert_evidence", {})
        if not isinstance(cert_refs, dict):
            raise ValueError("证明依据cert_evidence必须按证明标签填写来源引用")
        gaps += ["cert:" + c for c in record.get("security_certs", [])
                 if not isinstance(cert_refs.get(c), str) or not cert_refs[c].strip()]
    return gaps


def write_report(path, content, input_path=None):
    if input_path is not None and path.resolve() == input_path.resolve():
        raise ValueError("输出路径不能覆盖输入文件")
    # Exclusive creation preserves both source data and prior reports.
    with path.open("x", encoding="utf-8") as output:
        output.write(content)


def cell(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
