# 输入、命令与可交付文件

全部计算只用 Python 3.9+ 标准库。脚本不联网，不读凭据，不递归扫描目录，不改输入。单输入最大 5 MB、每类最多 1000 条，排期跨度最多 20000 工作日。入口为 `scripts/project_manager.py`；其余脚本是被调用的核心模块，不直接当作导入命令。

## 排期 schedule

完整样例：`assets/schedule-example.json`。这份数据可以直接执行：

```bash
python3 scripts/project_manager.py schedule --input assets/schedule-example.json --out ./plan-output
```

输入字段：

- `project_name`：项目名；`project_start`：YYYY-MM-DD；`target_wd`：目标完成的工作日编号，WD1 从开始日当天起遇到的第一个工作日计。
- `holidays`：要剔除的 YYYY-MM-DD 列表；不自动知道当地假日或周末补班。
- `tasks`：`id/name/owner/duration_days/depends_on` 必填。每项任务工期假设全日占用一位负责人；0 是明确的里程碑，不能用于未知工期。
- `deadline_wd`：任务硬截止工作日，可选。`not_before_wd`：最早可开工工作日（默认 WD1）；`available_through_wd`：负责人可用至该工作日结束，可选。
- `key_control:true`：需要独立复核的任务；`reviewer` 必须非空且不同于 owner。这是本次计划约定的检查，不代表完成审批。

输出 `schedule.csv` 和 JSON 包含最早开始/完成工作日及日期、浮时、所有零浮时任务标记。`critical_path` 给出一条关键链；如有多条，查看所有 `critical:true` 任务。`start_offset_days/finish_offset_days` 是从项目开始边界起的精确工作日偏移，适用于半日和零工期里程碑；同日里程碑用 `milestone_boundary` 区分开始、日末及日内，不能将日末误读为下一天开工。

加 `--extend-task 任务ID=工作日数` 比较单项工期增加，可重复传多个任务；基线保留，另输出 `scenario-schedule.csv`。若只是开始时间推迟，应修改 `not_before_wd` 后另跑一版。

阻断：C1 无负责人；C2 超过项目目标；C3 超过任务截止；C4 同一负责人同一工作日安排超过 1 人日；C5 独立复核人缺失或与负责人相同；C7 超过可用窗口。C6 关键链一人负责超过一半是集中风险警告。发现冲突后给调整选项，由用户确认，不擅自选择“自动加人”。

## 容量 capacity

完整样例：`assets/capacity-example.json`。模型是周容量，不是逐日排班。

- `resources`：唯一 `id/name/role`、`max_hours_per_week`、`current_utilization`、`hourly_rate`、`skills`、`skill_levels`（每种技能 0–1）必须明确提供；零费率合法，未提供不能代填市场价。
- `capacity_policy`：会议、学习、行政、切换、休假病假的五个占比，名称与样例相同；总和须小于 1，必须来自用户口径。
- `projects`：唯一 `id/name`、`priority`（critical/high/medium/low）、`status`（planned/active/in_progress/completed/cancelled）、`complexity`（simple/moderate/complex/very_complex）、`estimated_hours`、起止日期、所需技能及其周工时、成员当前分配。
- `estimated_hours` 是复杂度调整前的工时；若已经调整过，选 simple（系数 1）并注明。其他复杂度系数为 1.2/1.5/2。周需求＝调整后工时÷两日期之间自然日÷7 的倒数，即调整后工时÷自然周数；不要把它称为按工作日的交付日期预测。
- `current_utilization` 是用户提供的当前总利用率；`current_allocation` 是本次项目分配。两者可能含不同范围，必须说明覆盖哪些项目。
- `scenarios` 支持 `add_resource/remove_resource/add_project/adjust_utilization`，参数以样例和 `project_manager.py` 校验为准。每个情景都从同一基线开始，新增人员需完整资源字段，新增项目需完整项目字段。场景名须唯一。

有效容量＝每周工时×（1−开销占比）；总利用率按有效容量加权。技能匹配效率是分配工时加权的角色/技能模型分，不是实际生产率，可能因角色系数超过 1。`model_policy` 显示全部系数。成本使用提供的费率与有效周容量，同一输入的币种必须一致。`cost_impact` 是模型周容量成本变化，不是实际支出或节约承诺。

已完成和已取消项目不计入当前需求。候选人员可出现在多个项目建议中，各建议是备选方案，不能同时全量承诺。个人日期可用性应使用 schedule 模式，capacity 不接受假装生效的日期可用字段。

## 项目健康 health

完整样例：`assets/health-example.json`。需提供项目 ID/名称/状态/优先级，计划起止及预计结束，完成比例，计划预算/已花/预计总成本，原始/增加/取消/完成范围数量，全部/已解决/未解决严重缺陷，测试覆盖率，风险分、未关闭及严重风险数量，团队规模与利用率。

字段与样例名称一致；比例有两种：`completion_percentage` 为 0–100，`test_coverage` 为 0–1。缺少预算或预测等关键数据不打分，可先做排期或风险分析。输入不一致会报错，不自动截断。

五维权重：工期25%、预算25%、范围20%、质量20%、风险10%。综合分 ≥80 绿、≥60 黄、其余红。范围衡量完成比例，处于早期的正常项目也可能低分；不能把分数直接当作“会延期”。结果是固定口径的提示，需要负责人结合阶段判断。源输入中的 `risk_score` 是 0–100 已确认分，不把 risks 模式的累计权重分直接塞入。

## 风险 risks

完整样例：`assets/risks-example.json`。

- 顶层 `as_of` 指定分析日期；每条风险 ID/标题/负责人/类别/状态/发现日/概率等级/影响等级/缓解策略/措施清单明确提供。
- 概率与影响只能是 1–5 的整数等级，不能把 4 当作 400% 或转换成 80% 的真实概率。风险分＝两级相乘×类别权重（technical1.2/resource1.1/schedule1/business1.3/financial1.4/regulatory1.5/external1）。
- `target_resolution` 为截止日期；当天不逾期，只有在 as_of 之前且风险仍活跃才计逾期。`cost_impact/schedule_impact_days` 是已提供的潜在影响，不是期望损失。
- 活跃状态：open/identified/monitoring/mitigating；closed/resolved/accepted 为不再活跃的处理状态，不从“已接受”推断风险已经消除。

历史趋势未实现，提供历史数据也不会生成速度数字。矩阵、分类、措施覆盖率都依据本次风险清单，措施记录覆盖不能当作措施成效证明。

## 文件与错误

每次生成新目录，包含 `report.md`、`report.json`、`manifest.json`。排期另有 `schedule.csv`（情景另有 CSV），容量另有 `capacity-gaps.csv`，健康另有 `project-health.csv`。CSV 中疑似公式的文本会加单引号，JSON 保留原值；不要为了“还原漂亮”移除安全前缀。

0=成功计算；2=有警告；4=计划有阻断，结果仍真实生成；3=输入或输出错误。读到 `FILES_WRITTEN` 后仍需读取生成文件验证，尤其退出码 2/4 不能误报为“没有结果”或“计划通过”。输出目录已存在时不会覆盖，改用新名称。

输入中的附件/材料标识可由 WorkBuddy 在解释中引用，但脚本不自动扫描文件、不假造页码或行号。只有读取到的实际页码/行号才可引用。

## 中文呈现与技术字段

报告标题、表头、结论状态、风险等级、建议和错误提示默认中文。CSV使用中文表头与中文枚举值。JSON保留原技术字段和状态码，并增加 `labels_zh` 中文映射，便于程序继续读取；对客户解释时使用中文报告。输入中的项目名、姓名、编号和自定义技能不擅自改名。
