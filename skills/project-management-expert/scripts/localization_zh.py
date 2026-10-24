"""Chinese presentation only; no scheduling or scoring calculations."""
import re

LABELS = {
    'schedule':'依赖排期','capacity':'资源容量','health':'项目健康','risks':'风险分析',
    'project_name':'项目名称','project_start':'项目开始日期','target_wd':'目标工作日','holidays':'假期',
    'tasks':'任务列表','task':'任务','id':'编号','name':'名称','owner':'负责人','duration_days':'工期（工作日）',
    'depends_on':'前置任务','deadline_wd':'截止工作日','not_before_wd':'最早开工工作日','available_through_wd':'可用截止工作日',
    'key_control':'独立复核要求','reviewer':'复核人','resource':'成员','resources':'成员列表','role':'角色',
    'max_hours_per_week':'每周最多工时','current_utilization':'当前利用率','hourly_rate':'每小时费率',
    'skills':'技能','skill_levels':'技能水平','project':'项目','projects':'项目列表','status':'状态','priority':'优先级',
    'complexity':'复杂度','estimated_hours':'估算工时','start_date':'开始日期','target_end_date':'目标结束日期',
    'required_skills':'所需技能','skill_requirements':'技能周工时需求','current_allocation':'当前分配',
    'resource_id':'成员编号','hours_per_week':'每周分配工时','capacity_policy':'容量开销口径',
    'meeting_overhead':'会议占比','learning_development':'学习占比','administrative':'行政占比',
    'context_switching':'切换开销占比','vacation_sick':'休假病假占比','scenarios':'情景列表','scenario':'情景',
    'type':'类型','parameters':'参数','resource_data':'新增成员数据','project_data':'新增项目数据',
    'new_utilization':'调整后利用率','project_id':'项目编号','planned_start':'计划开始日期',
    'planned_end':'计划结束日期','forecasted_end':'预计结束日期','planned_budget':'计划预算','planned_features':'原计划范围数量',
    'spent_to_date':'累计已花费','forecasted_total_cost':'预计总成本','completed_features':'已完成范围数量',
    'descoped_features':'取消范围数量','added_features':'新增范围数量','total_defects':'缺陷总数',
    'resolved_defects':'已解决缺陷数','critical_defects':'未解决严重缺陷数','open_risks':'未关闭风险数',
    'critical_risks':'严重风险数','team_size':'团队人数','risk_score':'风险分','completion_percentage':'完成百分比',
    'test_coverage':'测试覆盖率','team_utilization':'团队利用率','as_of':'分析日期','risk':'风险','title':'标题',
    'category':'类别','probability':'概率等级','impact':'影响等级','identified_date':'发现日期','target_resolution':'处置截止日期',
    'mitigation_strategy':'处置策略','mitigation_actions':'措施清单','cost_impact':'模型周成本变化',
    'schedule_impact_days':'潜在工期影响（天）','delay-workdays':'增加工期（工作日）',
    'start_wd':'开始工作日','finish_wd':'完成工作日','start_offset_days':'开始偏移（工作日）',
    'finish_offset_days':'完成偏移（工作日）','slack_days':'总浮时（工作日）','critical':'是否关键任务',
    'finish_date':'完成日期','milestone_boundary':'里程碑时点','composite_score':'综合健康分',
    'adjusted_score':'优先级加权分','rag_status':'红黄绿状态','intervention_level':'介入级别',
    'dimension_scores':'各维度分数','score':'分数','weight':'权重','gap_hours':'每周工时缺口',
    'recommended_actions':'建议动作','risk_factors':'风险提示',
    'total_resources':'成员总数','total_projects':'项目总数','active_projects':'进行中项目数',
    'total_capacity_hours':'有效周容量（小时）','total_demand_hours':'周需求（小时）','overall_utilization':'加权利用率',
    'portfolio_average_score':'活跃组合平均健康分','portfolio_median_score':'活跃组合健康分中位数',
    'projects_needing_attention':'需关注项目数','critical_projects':'需立即介入项目数','message':'说明',
    'total_risks':'风险总数','active_risks':'活跃风险数','closed_risks':'已关闭风险数','resolved_risks':'已解决风险数',
    'accepted_risks':'已接受风险数','inactive_risks':'非活跃风险数','high_risks':'高风险数',
    'total_risk_exposure':'活跃风险累计权重分','average_risk_score':'平均风险分','overdue_risks':'逾期风险数',
    'scenario_type':'情景类型','resource_utilization':'加权利用率','total_capacity':'有效周容量（小时）',
    'capacity_gaps':'周工时缺口','under_utilized_count':'低利用率成员数','over_utilized_count':'高利用率成员数',
    'timeline':'工期','budget':'预算','scope':'范围','quality':'质量',
}

ENUMS = {
    'ON_TRACK':'按计划','AT_RISK':'存在风险','BLOCKED':'存在阻断','BLOCKER':'阻断','WARN':'警告',
    'green':'绿色（相对正常）','amber':'黄色（需关注）','red':'红色（需处理）',
    'critical':'严重','high':'高','medium':'中','low':'低','very_low':'很低',
    'planned':'待启动','planning':'规划中','active':'进行中','in_progress':'进行中','completed':'已完成','cancelled':'已取消',
    'monitoring':'跟踪中','open':'待处理','identified':'已识别','mitigating':'处置中','closed':'已关闭','resolved':'已解决','accepted':'已接受',
    'initiation':'启动中','chartered':'已立项','execution':'执行中','development':'开发中','testing':'测试中','review':'评审中',
    'delivered':'已交付','terminated':'已终止','suspended':'已中止','on_hold':'暂缓','paused':'已暂停','blocked':'受阻',
    'immediate':'立即介入','urgent':'优先处理','monitor':'持续关注','none':'无额外要求',
    'technical':'技术','resource':'资源','schedule':'工期','business':'业务','financial':'财务','regulatory':'监管','external':'外部',
    'timeline':'工期','budget':'预算','scope':'范围','quality':'质量','risk':'风险',
    'avoid':'规避','mitigate':'缓解','transfer':'转移','accept':'接受','contingency':'应急预案',
    'add_resource':'增加成员','remove_resource':'移除成员','add_project':'增加项目','adjust_utilization':'调整利用率',
    'simple':'简单','moderate':'一般','complex':'复杂','very_complex':'很复杂',
    'project_start':'项目开始边界','end_of_workday':'工作日结束时','within_workday':'工作日内',
    'under_utilized':'低利用率','optimal':'常规区间','over_utilized':'高利用率','healthy':'相对正常','concerning':'需要改善',
    'senior_engineer':'高级工程师','mid_engineer':'工程师','junior_engineer':'初级工程师',
    'product_manager':'产品经理','designer':'设计师','qa_engineer':'质量测试工程师',
    'backend':'后端开发','frontend':'前端开发','mobile':'移动端开发','devops':'开发运维','data':'数据',
    'planning_skill':'规划','stakeholder_mgmt':'相关方协调','analysis':'分析','ui_design':'界面设计',
    'ux_research':'用户体验研究','prototyping':'原型设计','manual_testing':'人工测试','automation':'自动化测试','performance':'性能测试',
}

STATIC = {
    'Low allocation efficiency detected. Review skill-to-project matching and consider reallocation.':'技能与项目的匹配分较低，建议核对分配依据，再评估是否调整。',
    'Conduct timeline recovery analysis and implement fast-tracking or crashing strategies':'评估工期恢复方案，以及并行推进或增加投入的可行性。',
    'Implement cost control measures and review budget forecasts':'核对成本控制措施，并复核预算预测。',
    'Review scope management and consider feature prioritization or descoping':'复核范围管理，考虑调整功能优先级或减少范围。',
    'Increase testing coverage and implement quality improvement processes':'提高测试覆盖，落实质量改进流程。',
    'Escalate critical risks and implement additional risk mitigation measures':'将严重风险提请负责人关注，并评估补充缓解措施。',
    'Consider project restructuring or emergency stakeholder review':'考虑调整项目安排，或组织相关方紧急评审。',
    'Critical project failure risk':'项目存在严重交付风险。',
    'Requires immediate management attention':'需要管理层立即关注。',
    'URGENT: 30%+ projects are in red status. Consider portfolio restructuring or resource reallocation.':'优先处理：超过30%的项目处于红色状态，建议评估组合调整或资源重新分配。',
    'HIGH: Significant number of projects in red status require immediate attention.':'重点关注：较多项目处于红色状态，需要立即核对原因。',
    'MEDIUM: Over half of portfolio projects need monitoring and support.':'需要关注：超过一半的组合项目需要跟踪和支持。',
    'Portfolio health is critical. Recommend executive review and strategic realignment.':'组合健康状态严重，建议管理层评审并核对战略安排。',
    'Portfolio health needs improvement. Implement enhanced monitoring and support.':'组合健康需要改善，建议加强跟踪和支持。',
    'No active projects found':'本次没有处于活跃状态的项目。',
    'Improve mitigation coverage - less than 70% of risks have defined mitigation actions.':'已记录缓解措施的风险不足70%，建议补齐措施记录。',
    'Address overdue mitigation actions - more than 20% of risks are past their target resolution date.':'超过20%的风险已过处置截止日期，建议核对逾期措施。',
    'Portfolio risk exposure is high. Consider scope reduction or additional risk mitigation investments.':'组合风险权重分较高，可评估减少范围或增加风险缓解投入。',
    'Risk exposure is well-managed. Consider taking on additional strategic initiatives.':'当前风险模型得分较低；如考虑增加任务，仍需另行确认容量和约束。',
    'Historical data required for trend analysis':'未提供历史数据，不能给出历史趋势。',
    'Historical trend computation is not implemented; supplied history is not treated as measured velocity.':'本版本未实现历史趋势计算，不将所提供历史记录当作已测得的变化速度。',
    'Proof of concept development':'开展概念验证','Technical spike implementation':'开展技术可行性验证','Expert consultation':'咨询专业人员',
    'Resource planning and buffer allocation':'规划资源并保留余量','Skill development and training':'开展技能培训','Cross-training and knowledge sharing':'开展交叉培训与知识共享',
    'Critical path analysis and optimization':'分析关键路径并评估改进方案','Buffer time allocation':'安排缓冲时间','Dependency management and coordination':'管理和协调依赖关系',
    'Market research and validation':'开展市场研究与验证','Customer feedback integration':'纳入客户反馈','Competitive analysis monitoring':'跟踪竞品分析',
    'Detailed cost estimation and tracking':'细化成本估算并跟踪','Budget reserve allocation':'安排预算预备金','Regular financial checkpoint reviews':'定期复核财务节点',
    'Legal review and approval processes':'安排法律审查及审批流程','Compliance audit preparation':'准备合规审计资料','Regulatory body engagement':'协调监管沟通',
    'Vendor assessment and backup options':'评估供应商及备选方案','Contract negotiation and SLA definition':'明确合同与服务级别约定','Environmental monitoring and adaptation':'跟踪外部环境并调整安排',
}

def enum(value):
    return ENUMS.get(value,value) if isinstance(value,str) else value

def label(value):
    # Preserve identifiers so a user can correct the actual JSON field.
    return LABELS.get(value,value)

def field(value):
    return '.'.join(LABELS.get(part,part) for part in str(value).split('.'))

def message(value):
    if value in STATIC: return STATIC[value]
    rules = [
      (r'URGENT: Redistribute workload for (\d+) critically over-allocated resources to prevent burnout\.',lambda m:f'优先处理：{m[1]}名成员利用率过高，建议核对负荷并调整工作分配。'),
      (r'Consider hiring or redistributing work - (\d+) team members are over-allocated\.',lambda m:f'{m[1]}名成员处于高利用率区间，可评估补充人员或调整工作分配。'),
      (r'Rebalance allocation - (\d+) under-utilized resources could help with over-allocated work\.',lambda m:f'{m[1]}名成员利用率较低，可核对技能与可用性后再评估支援方案。'),
      (r'Capacity shortfall of (.+) hours/week detected\. Consider hiring or timeline adjustments\.',lambda m:f'周容量缺口为{m[1]}小时，可评估补充人员或调整期限。'),
      (r'High demand for (.+) skills \((.+) hours\)\. Consider training or specialized hiring\.',lambda m:f'{enum(m[1])}的周工时需求较高（{m[2]}小时），可评估培训或补充相应能力。'),
      (r'CRITICAL: (\d+) resources are severely over-allocated \(>95%\)',lambda m:f'严重：{m[1]}名成员利用率超过95%。'),
      (r'WARNING: (\d+) resources are over-allocated \(85-95%\)',lambda m:f'警告：{m[1]}名成员利用率处于85%至95%区间。'),
      (r'OPPORTUNITY: (\d+) resources are under-utilized \(<60%\)',lambda m:f'可核对余量：{m[1]}名成员利用率较低。'),
      (r'Focus improvement efforts on (.+) - weakest portfolio dimension\.',lambda m:f'建议优先核对{enum(m[1])}，这是本次组合中得分最低的维度。'),
      (r'CRITICAL: (\d+) projects require immediate intervention within 48 hours\.',lambda m:f'严重：{m[1]}个项目需要立即介入，模型建议在48小时内安排核对。'),
      (r'Capacity alert: (\d+) projects need urgent attention - consider resource reallocation\.',lambda m:f'容量提醒：{m[1]}个项目需优先关注，可评估资源调整。'),
      (r'Multiple failing dimensions: (.+)',lambda m:'多个维度得分偏低：'+'、'.join(enum(x) for x in m[1].split(', '))+'。'),
      (r'URGENT: Address (\d+) critical risks immediately\. These require executive attention and dedicated resources\.',lambda m:f'优先处理：{m[1]}项严重风险需要管理层关注并明确处置资源。'),
      (r'Critical Risk - (.+): Implement (\w+) strategy within 48 hours\.',lambda m:f'严重风险“{m[1]}”：模型建议在48小时内核对{enum(m[2])}策略。'),
      (r'Focus mitigation efforts on (.+) risks - highest concentration of risk exposure\.',lambda m:f'建议重点核对{enum(m[1])}风险，其累计风险权重分最高。'),
      (r"project finishes WD(\d+), target WD(\d+); critical path: (.*)",lambda m:f'项目在第{m[1]}个工作日完成，晚于目标第{m[2]}个工作日；关键链：{m[3]}。'),
      (r"'(.+)' has no owner",lambda m:f'任务“{m[1]}”尚未指定负责人。'),
      (r"'(.+)' finishes WD(\d+), deadline WD(\d+)",lambda m:f'任务“{m[1]}”在第{m[2]}个工作日完成，晚于截止的第{m[3]}个工作日。'),
      (r"'(.+)' finishes after owner availability WD(\d+)",lambda m:f'任务“{m[1]}”的完成时间超过负责人可用截止日（第{m[2]}个工作日）。'),
      (r"key control '(.+)' has no reviewer",lambda m:f'需要独立复核的任务“{m[1]}”尚未指定复核人。'),
      (r"key control '(.+)' is reviewed by its own preparer \((.+)\)",lambda m:f'任务“{m[1]}”的负责人和复核人均为“{m[2]}”，不满足独立复核要求。'),
      (r'(.+) is over-booked on (.+); the plan is not achievable as staffed',lambda m:f'“{m[1]}”在以下日期的任务负荷重叠：{workdays(m[2])}；按当前人员安排无法执行。'),
      (r'(.+) owns (.+)% of the critical path',lambda m:f'“{m[1]}”承担关键链工期的{m[2]}%，存在人员集中风险。'),
    ]
    for pattern,render in rules:
        m=re.fullmatch(pattern,value)
        if m: return render(m)
    return value

def workdays(value):
    return re.sub(r'WD(\d+) \(([\d.]+)d\)',r'第\1个工作日（\2人日）',value)

TEXT_KEYS={'recommendations','recommended_actions','risk_factors','capacity_alerts','message','suggested_strategies'}
def localize_messages(value,key=None):
    if isinstance(value,dict):
        for k,v in list(value.items()): value[k]=localize_messages(v,k)
    elif isinstance(value,list): return [localize_messages(v,key) for v in value]
    elif isinstance(value,str) and key in TEXT_KEYS: return message(value)
    return value

def display(value,key=None):
    if value is None: return '未提供'
    if isinstance(value,bool): return '是' if value else '否'
    if isinstance(value,(int,float)):
        if key in {'overall_utilization','resource_utilization','team_utilization','weight','completion_percentage'}: return f'{value:.1%}'
        return str(round(value,4)) if isinstance(value,float) else str(value)
    if isinstance(value,list): return '、'.join(display(v) for v in value) or '无'
    if isinstance(value,dict): return '；'.join(f'{label(k)}：{display(v,k)}' for k,v in value.items())
    if key in {'name','project_name','title','owner','id','project_id','resource_id'}: return value
    if key=='priority' and value=='critical': return '最高'
    return enum(message(value))

def table(headers,rows):
    def safe(v): return str(v).replace('|','\\|').replace('\n',' ')
    return ['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(safe(v) for v in row)+' |' for row in rows]

def markdown(result):
    mode=result['mode'];r=result['analysis']
    names={'schedule':'依赖排期与关键路径','capacity':'资源容量与情景比较','health':'项目健康与组合看板','risks':'风险矩阵与处置优先级'}
    lines=[f'# 项目管理报告：{names[mode]}','','## 计算口径','']+['- '+x for x in result['assumptions']]
    if mode=='schedule':
        lines+=['',f"结论：{enum(r['verdict'])}；工期{r['duration_workdays']}个工作日，完成日期为{r['finish_date']}。",'',f"关键链：{' → '.join(r['critical_path'])}",'']
        rows=[[f"{x['id']} {x['name']}",x['owner'] or '待指定',f"第{x['start_wd']}个工作日",f"第{x['finish_wd']}个工作日",x['slack_days'],'是' if x['critical'] else '否'] for x in r['schedule']]
        lines+=table(['任务','负责人','开始','完成','浮时（工作日）','关键任务'],rows)
        lines+=['','## 需处理事项','']+[f"- [{enum(f['severity'])}] {f['id']}：{f['message']}" for f in r['findings']]
        if not r['findings']:lines+=['本次规则未发现排期阻断或警告。']
        if r.get('what_if'):
            w=r['what_if'];s=w['report']
            lines+=['','## 工期延长情景','',f"完成时间移动{w['finish_shift_workdays']}个工作日；新工期{s['duration_workdays']}个工作日；完成日期{s['finish_date']}；状态为{enum(s['verdict'])}。",f"新关键链：{' → '.join(s['critical_path'])}"]
            lines += [f"- [{enum(f['severity'])}] {f['id']}：{f['message']}" for f in s['findings']]
    else:
        lines+=['','## 汇总','']+table(['指标','结果'],[[label(k),display(v,k)] for k,v in r.get('summary',{}).items()])
        if mode=='health':
            lines+=['','## 项目明细','']+table(['项目','状态','健康分','红黄绿状态','介入级别'],[[x['project_name'],enum(x['status']),display(x['composite_score']),enum(x['rag_status']),enum(x['intervention_level'])] for x in r['project_scores']])
            for x in r['project_scores']:
                lines+=['',f"### {x['project_name']}的维度依据",'']+table(['维度','分数','权重'],[[label(k),v['score'],display(v['weight'],'weight')] for k,v in x['dimension_scores'].items()])
        if mode=='capacity':
            gaps=r['project_analysis']['capacity_gaps']
            lines+=['','## 项目容量缺口','',f"有缺口的项目共{gaps['projects_with_gaps']}个，每周总缺口{gaps['total_gap_hours_weekly']}小时。"]
            if gaps['gap_projects']:lines+=['']+table(['项目','优先级','每周缺口（小时）','所需技能'],[[x['name'],display(x['priority'],'priority'),x['gap_hours'],display(x['required_skills'])] for x in gaps['gap_projects']])
            lines+=['','## 人员负荷提醒','']+['- '+a for a in r['resource_analysis']['capacity_alerts']]
            if not r['resource_analysis']['capacity_alerts']:lines+=['本次规则未触发人员负荷提醒。']
            if r.get('scenario_analysis'):
                lines+=['','## 情景比较（各自相对同一基线）','']+table(['情景','类型','利用率','有效周容量（小时）','周缺口（小时）','模型周成本变化'],[[n,enum(s['scenario_type']),display(s['resource_utilization'],'resource_utilization'),s['total_capacity'],s['capacity_gaps'],s['cost_impact']] for n,s in r['scenario_analysis'].items()])
        if mode=='risks':
            lines+=['','## 风险等级分布','']+table(['等级','活跃风险数'],[[enum(k),v] for k,v in r['risk_matrix']['distribution'].items()])
            lines+=['','## 风险矩阵','', '行表示概率等级，列表示影响等级；1至5均为等级，不是百分比。','']
            matrix=r['risk_matrix'].get('matrix',{})
            lines+=table(['概率等级 / 影响等级','1','2','3','4','5'],[[prob]+[len(matrix.get(str(prob),matrix.get(prob,{})).get(str(impact),matrix.get(str(prob),matrix.get(prob,{})).get(impact,[]))) for impact in range(1,6)] for prob in range(5,0,-1)])
            lines+=['',f"分析日期：{r['as_of']}。逾期风险编号：{display(r['overdue_risk_ids'])}。"]
            ranked=[]
            for row in matrix.values():
                for items in row.values():ranked.extend(items)
            if ranked:
                lines+=['','## 活跃风险明细','']+table(['编号','风险','类别','权重分'],[[x['id'],x['title'],enum(x['category']),x['risk_score']] for x in sorted(ranked,key=lambda v:v['risk_score'],reverse=True)])
            lines+=['',r['trend_analysis'].get('message','')]
        lines+=['','## 建议（须结合实际材料核实）','']+['- '+v for v in r.get('recommendations',[])]
        if not r.get('recommendations'):lines+=['本次规则未生成额外建议。']
    lines+=['','完整计算明细见同目录 report.json。本报告没有修改输入或外部项目系统。','']
    return '\n'.join(lines)
