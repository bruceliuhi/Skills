# 字段规则与结果使用

画像支持 --columns 选择字段、--rules 载入业务规则。规则提到的字段必须包含在所选范围内；没有规则的维度保持 UNKNOWN。规则来自用户明确要求，不能自行默认订单号一定唯一、金额必须为正或某个时间必须小于现在。

```json
{
  "required": ["编号", "金额"],
  "unique_keys": ["编号"],
  "types": {"金额": "number", "状态": "string"},
  "ranges": {"金额": {"min": "0", "max": "100000"}},
  "allowed_values": {"状态": ["待处理", "已完成"]},
  "timeliness": {
    "column": "更新时间",
    "reference_timestamp": "2026-10-24T00:00:00+08:00",
    "max_age_days": 7
  }
}
```

示例仅演示格式，不是默认业务标准。types 支持 number、integer、boolean、string、timestamp；timestamp 要显式时区，boolean只接受true/false。范围按十进制比较，精确边界推荐字符串表达；allowed_values按原始字符串比较，不静默去空格或转换大小写。unique_keys可以多个字段组成联合键，空键或重复键均单独定位。范围/类型/枚举对空值不重复计失败，必填由required和完整性报告单独核查。

时效由用户指定参照时间和允许天数；缺失、无时区、格式错误、未来时间及过期时间会被标出。不会用运行当天或隐含时区替代业务口径。暂不支持自定义SQL、跨文件外键或任意代码规则，不能把这些写成已检查。

## 输出字段

- 每个报告含tool、status、total_rows、selected_columns、review_required、business_readiness、source。
- source含输入路径、运行时SHA256、编码与物理行定位说明。源文件在执行结束再次核对hash，不被脚本写入。
- record是从1开始的数据记录号，line_start/line_end是真实CSV物理行号；带引号的多行字段会横跨多行。raw_value保留原字面值，避免长编号与前导零丢失。
- 画像的columns含缺失、类型频次、不同值数、常量/高基数描述及有限数值子集的min/max/mean/样本std。单值std为null，编号样式字段不自动计算分布。不同值比较保持原始字符串，"A"与"A "不合并。
- duplicate_rows_in_selected_scope报告所选字段相同的记录，只有明确的unique_keys规则才计入唯一性分数。
- missing报告完整缺失计数与共缺记录；threshold只筛选详细columns，低于阈值的字段仍在all_column_null_counts中，review_required不会因此隐藏已有缺失。
- outlier必须指定数值列。invalid_numeric_records记录非数值、NaN/inf和超范围数值；这些值被排除于统计但数量和原值完整披露。outlier_records保留所有候选，不只有前10个样本；outlier_values最多10个是预览。
- NOT_ASSESSABLE表示样本不足、MAD为0或方差为0，outlier_count为null，不能解释为零异常。

## 得分与覆盖

权重用于显示覆盖：完整性30、类型一致性25、业务有效性20、唯一性15、时效10。它们是本工具的报告口径，不是官方认证阈值。得分只对已实际执行且有观测值的维度按权重归一化；各维度另列checks/passed。无规则时通常只有完整性，覆盖30%，即使分数100也不是全数据无问题。

类型、范围等规则只有非空可检查值时才计覆盖；整列为空时这些维度仍UNKNOWN。时效规则将缺失时间计失败。一个有效性维度可能有多条逐值规则，分母是实际执行检查次数，不是去重后的记录数。必填问题和默认完整性对所有选中单元格计数的定义不同，需同时查看问题清单。

## 数值及格式限制

原值始终保留。统计使用有限浮点近似，不能替代财务精确计量；有效数值绝对值上限1e150。NaN、Infinity、超大值及浮点下溢被明确列为numeric issue，不自动改为0或空值。空值词为：空串/null/none/n-a写法中的n/a/na/nil/undefined/missing（不区分大小写）。NaN专列异常数字，不计作普通空值。0、-1、9999等业务哨兵不能未经确认当空值。

CSV重复/空表头、表头周边空格、行列数不齐、坏引号或编码错误明确拒绝并输出中文错误提示；不静默丢列或覆盖同名字段。text 是中文业务报告，包含本次范围、覆盖、统计、问题原因、行定位和建议；JSON 保留完整结构化明细，不含非标准 NaN/Infinity 字面量。现有结果路径拒绝覆盖，重新执行请换输出文件名。

## 中文交付与结构化数据兼容

默认报告为中文 Markdown 文本，技术标识只在使用参数、JSON 或说明方法时保留。不要翻译用户的原始字段名或原值；中文报告用“↵”展示原值换行、用“（空字符串）”展示空串，JSON 的 raw_value 保留真正的原始字符串。文本报告表格会转义竖线，不应反向解析文本表格替代 JSON。

需要后续筛选、比较或精确读取时，用相同参数另存 JSON 文件。以下是稳定技术状态的中文含义，字段与状态码不因中文化而改名：

| 技术状态 | 客户报告中的含义 |
| --- | --- |
| REVIEW_REQUIRED | 发现需复核事项 |
| NO_FINDINGS_IN_CHECKED_SCOPE | 所检查范围暂未发现需复核事项 |
| NO_OUTLIERS_IN_VALID_NUMERIC_SUBSET | 有效数值子集暂未发现统计异常候选 |
| NOT_ASSESSABLE_FEWER_THAN_4 | 未能评估：有效数字不足 4 个 |
| NOT_ASSESSABLE_ZERO_VARIANCE | 未能评估：样本标准差为 0 |
| NOT_ASSESSABLE_ZERO_MAD | 未能评估：绝对偏差中位数为 0 |
| MEASURED | 已检查 |
| UNKNOWN | 未检查或证据不足；业务可用性尚未确认 |
| NOT_APPLICABLE | 本次不适用 |
| DRAFT_REQUIRES_BUSINESS_CONFIRMATION_NOT_SCHEDULED | 待确认草案，未建立监测任务 |

维度 completeness、consistency、validity、uniqueness、timeliness 依次对应完整性、类型一致性、业务取值有效性、声明键唯一性和业务时效。issue 中的类型不符、必填缺失、超范围、枚举不符、时间失败、唯一键失败与异常数字均由脚本映射为中文原因及建议；原始 issue 代码继续保留在 JSON。缺失筛选门槛仅控制字段明细，低于门槛的缺失不会从汇总消失。
