# 供应商资料与服务指标模板

评分与风险工具读取供应商目录，服务指标工具读取单独的指标记录列表。以下样例仅说明格式，不代表真实客户或供应商表现。字段名保留英文供程序识别，说明、结果和建议使用中文。

## 使用方法

1. 将目录JSON保存为新文件`vendor_catalog.json`，用本次真实材料替换示例。
2. 将服务指标JSON另存为`sla_records.json`。
3. 只运行本次需要的流程；报告路径必须是未使用过的新文件。

```sh
python3 scripts/vendor_scorer.py --input vendor_catalog.json --profile saas --output scorecard.md
python3 scripts/sla_compliance_tracker.py --input sla_records.json --output sla_report.md
python3 scripts/vendor_risk_classifier.py --input vendor_catalog.json --profile saas --output risk_matrix.md
```

## 供应商目录字段

每家供应商是一条JSON对象，全部放在顶层数组中。

| 字段 | 中文含义与类型 | 适用流程 | 口径 |
|---|---|---|---|
| `name` | 供应商名称，文本 | 评分、风险 | 保留原名称；与指标记录的vendor一致 |
| `category` | 类别，文本 | 评分、风险 | identity身份认证、data-warehouse数据仓库、crm客户管理、analytics数据分析；也可保留用户明确类别 |
| `annual_spend` | 年度支出，数值 | 评分、风险 | 使用currency声明的原币金额；不擅自把缺失填0 |
| `currency` | 币种，文本 | 评分、风险 | 三个大写字母，例如CNY或USD；模型阈值以美元计 |
| `usd_exchange_rate` | 美元折算率，正数 | 非USD输入 | 每1原币可折多少美元，由用户提供；例如0.14美元/人民币元 |
| `exchange_rate_date` | 汇率日期 | 非USD输入 | YYYY-MM-DD |
| `exchange_rate_source` | 汇率来源，文本 | 非USD输入 | 用户提供的依据，不代表工具已核验 |
| `contract_end_date` | 合同到期日，文本 | 补充资料 | YYYY-MM-DD；工具不自动续约或解约 |
| `criticality` | 业务关键性，枚举 | 评分、风险 | tier-1一级关键、tier-2二级重要、tier-3三级一般 |
| `uptime_pct` | 最近12个月可用率 | 评分 | 0–100的百分比 |
| `support_response_hours_p90` | 支持响应P90时长 | 评分 | 单位小时；不能与解决时长混用 |
| `incident_count_last_12m` | 近12个月事件数 | 评分 | 非负整数；事件统计范围须一致 |
| `security_certs` | 证明材料标签列表 | 评分、风险 | 标签不得重复；空列表只能表达用户明确提供的空列表 |
| `renewal_terms` | 续约方式，枚举 | 评分 | manual-renew手动续约、fixed-term固定期限、evergreen持续有效、auto-renew自动续约 |
| `data_access` | 数据访问标签列表 | 风险 | 使用下方明确映射；缺失不代表无访问 |
| `break_glass_plan` | 是否有应急替代方案 | 风险 | 必须是JSON true/false，不能写字符串"false" |
| `evidence` | 字段到来源引用的对象 | 评分、风险 | 缺引用会产生临时报告与待补清单 |
| `cert_evidence` | 证明标签到来源引用的对象 | 评分、风险 | 仅保存引用，不证明真实性、有效期或覆盖范围 |

### 证明材料标签

支持`SOC2`、`SOC2-Type-II`、`ISO27001`、`HIPAA`、`PCI-DSS`、`FedRAMP`、`GDPR-DPA`、`CCPA`。这些包括标准、审计报告、协议和法规相关标签，并非每项都是认证；HIPAA标签不代表取得了政府颁发的认证。按本次材料填写，不为了提高分数添加不存在的标签。

### 数据访问标签

| 程序标签 | 中文含义 |
|---|---|
| PHI | 受保护健康信息 |
| PII | 可识别个人身份的信息 |
| cardholder | 持卡人数据 |
| source-code | 源代码 |
| financial-records | 财务记录 |
| employee-records | 员工记录 |
| customer-emails | 客户邮箱 |
| logs-only | 仅日志 |
| no-customer-data | 明确不访问客户数据 |

## 五家供应商格式样例

证据对象故意留空，因此运行后会得到临时报告和退出码3。请补真实来源引用，不要编造证明。

```json
[
  {
    "name": "示例供应商01",
    "category": "identity",
    "annual_spend": 180000,
    "contract_end_date": "2026-09-30",
    "criticality": "tier-1",
    "uptime_pct": 99.91,
    "support_response_hours_p90": 4.5,
    "incident_count_last_12m": 3,
    "security_certs": [
      "SOC2-Type-II",
      "ISO27001",
      "FedRAMP",
      "GDPR-DPA"
    ],
    "renewal_terms": "manual-renew",
    "data_access": [
      "PII",
      "employee-records"
    ],
    "break_glass_plan": true,
    "currency": "USD",
    "evidence": {},
    "cert_evidence": {}
  },
  {
    "name": "示例供应商02",
    "category": "data-warehouse",
    "annual_spend": 420000,
    "contract_end_date": "2027-01-15",
    "criticality": "tier-1",
    "uptime_pct": 99.97,
    "support_response_hours_p90": 2.0,
    "incident_count_last_12m": 1,
    "security_certs": [
      "SOC2-Type-II",
      "ISO27001",
      "HIPAA",
      "GDPR-DPA"
    ],
    "renewal_terms": "fixed-term",
    "data_access": [
      "PII",
      "PHI",
      "financial-records"
    ],
    "break_glass_plan": false,
    "currency": "USD",
    "evidence": {},
    "cert_evidence": {}
  },
  {
    "name": "示例供应商03",
    "category": "crm",
    "annual_spend": 95000,
    "contract_end_date": "2026-06-30",
    "criticality": "tier-2",
    "uptime_pct": 98.2,
    "support_response_hours_p90": 38.0,
    "incident_count_last_12m": 11,
    "security_certs": [
      "SOC2"
    ],
    "renewal_terms": "auto-renew",
    "data_access": [
      "PII",
      "customer-emails"
    ],
    "break_glass_plan": false,
    "currency": "USD",
    "evidence": {},
    "cert_evidence": {}
  },
  {
    "name": "示例供应商04",
    "category": "analytics",
    "annual_spend": 8000,
    "contract_end_date": "2026-08-01",
    "criticality": "tier-3",
    "uptime_pct": 99.5,
    "support_response_hours_p90": 14.0,
    "incident_count_last_12m": 2,
    "security_certs": [
      "SOC2",
      "GDPR-DPA"
    ],
    "renewal_terms": "evergreen",
    "data_access": [
      "logs-only"
    ],
    "break_glass_plan": true,
    "currency": "USD",
    "evidence": {},
    "cert_evidence": {}
  },
  {
    "name": "示例供应商05",
    "category": "qa-services",
    "annual_spend": 220000,
    "contract_end_date": "2026-12-31",
    "criticality": "tier-3",
    "uptime_pct": 99.0,
    "support_response_hours_p90": 22.0,
    "incident_count_last_12m": 6,
    "security_certs": [],
    "renewal_terms": "auto-renew",
    "data_access": [
      "source-code",
      "PII"
    ],
    "break_glass_plan": false,
    "currency": "USD",
    "evidence": {},
    "cert_evidence": {}
  }
]
```

## 服务指标记录字段

一条记录是一家供应商的一项指标。需确认同一目标与口径适用于输入的月、季度；不能把不同计量范围的数据强行比较。

| 字段 | 中文含义 | 口径 |
|---|---|---|
| `vendor` | 供应商名称 | 对应目录name |
| `sla_metric` | 服务指标名称 | uptime_pct可用率、support_p90_response_hours支持响应P90时长、ticket_resolution_hours工单解决时长，或用户明确的指标名称 |
| `direction` | 指标方向 | higher越高越好，lower越低越好；不能靠名称猜测 |
| `unit` | 单位 | percent百分比、hours小时等；percent采用0–100 |
| `target` | 服务目标 | 必须大于0；零容忍指标需要单独规则 |
| `actual_last_month` | 上月实际值 | 与目标同单位、同分母口径 |
| `actual_last_quarter` | 上季实际值 | 与目标同单位、同分母口径 |
| `breach_count_12m` | 近12个月未达标次数 | 明确的非负整数，缺失不填0 |
| `measurement_context` | 计量口径对象 | last_month月份范围、last_quarter季度范围、denominator分母、exclusions排除项、time_basis计时与时区口径 |
| `evidence` | 依据对象 | contract合同条款、measurements计量记录、breach_count_12m未达标记录的来源引用 |

### 服务指标格式样例

```json
[
  {
    "vendor": "示例供应商01",
    "sla_metric": "uptime_pct",
    "target": 99.99,
    "actual_last_month": 99.95,
    "actual_last_quarter": 99.91,
    "breach_count_12m": 3,
    "direction": "higher",
    "unit": "percent",
    "measurement_context": {},
    "evidence": {}
  },
  {
    "vendor": "示例供应商02",
    "sla_metric": "uptime_pct",
    "target": 99.9,
    "actual_last_month": 99.98,
    "actual_last_quarter": 99.97,
    "breach_count_12m": 1,
    "direction": "higher",
    "unit": "percent",
    "measurement_context": {},
    "evidence": {}
  },
  {
    "vendor": "示例供应商03",
    "sla_metric": "support_p90_response_hours",
    "target": 8.0,
    "actual_last_month": 36.0,
    "actual_last_quarter": 38.0,
    "breach_count_12m": 11,
    "direction": "lower",
    "unit": "hours",
    "measurement_context": {},
    "evidence": {}
  },
  {
    "vendor": "示例供应商04",
    "sla_metric": "uptime_pct",
    "target": 99.5,
    "actual_last_month": 99.6,
    "actual_last_quarter": 99.5,
    "breach_count_12m": 0,
    "direction": "higher",
    "unit": "percent",
    "measurement_context": {},
    "evidence": {}
  },
  {
    "vendor": "示例供应商05",
    "sla_metric": "ticket_resolution_hours",
    "target": 24.0,
    "actual_last_month": 30.0,
    "actual_last_quarter": 28.0,
    "breach_count_12m": 6,
    "direction": "lower",
    "unit": "hours",
    "measurement_context": {},
    "evidence": {}
  }
]
```

## 中文结果术语

| 内部状态 | 客户看到的中文 | 解释 |
|---|---|---|
| KEEP | 建议继续合作 | 规则建议，不代表已经批准续约 |
| REVIEW | 需复核改进 | 先核对缺失依据或讨论改进 |
| REPLACE | 建议评估替代 | 评估备选，不自动停用或解约 |
| met | 服务指标达标 | 给定数据与口径下达到目标 |
| breached | 服务指标未达标 | 不直接定性为已确认合同违约 |
| Critical | 严重风险（规则分级） | 需要优先核查，不是合规结论 |
| High / Medium / Low | 较高 / 中等 / 较低风险（规则分级） | 同一规则下的核查优先级 |
| REVIEW_REQUIRED | 待补依据、需复核 | 输出仍为临时结果 |
| REFERENCES_PROVIDED_NOT_VERIFIED | 已提供引用、尚未核验 | 引用存在不代表证据已验证 |

## 准备资料时注意

- 只使用本轮上传或指定的采购、合同、工单、监测导出材料；无需连接外部系统。
- 可用率和事件记录要写清期间与来源；不同报告的口径不能直接混用。
- 数据访问范围及应急方案须有实际依据，不按印象填写。
- 非USD金额仅按用户给定汇率折算，报告保留原币和换算依据，原文件不改。
- 临时报告仍可供补资料讨论；不能把缺材料说成低风险或已达标。
- 运行成功后保留原文件、字段映射、口径、原始报告和中文摘要。
