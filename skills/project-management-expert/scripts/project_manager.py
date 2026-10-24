#!/usr/bin/env python3
"""Validated local project analysis and file delivery. Python standard library only."""
import argparse
import copy
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import sys

import project_schedule as schedule
import project_health_dashboard as health
import resource_capacity_planner as capacity
import risk_matrix_analyzer as risks
import localization_zh as zh

MAX_BYTES = 5_000_000
MAX_ROWS = 1000

class InputError(ValueError):
    pass

def fail(message):
    raise InputError(message)

def number(value, label, low=0, high=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{zh.field(label)}: 必须是有限数字，不能填布尔值、空值或无穷值")
    if value < low or (high is not None and value > high) or (integer and int(value) != value):
        fail(f"{zh.field(label)}: 数值须在允许范围内，且整数项不能带小数：{low}..{high if high is not None else '无上限'}")
    return value

def text(value, label, empty=False):
    if not isinstance(value, str) or len(value) > 2000 or (not empty and not value.strip()):
        fail(f"{zh.field(label)}: 须为不超过2000字的文本{'，可留空' if empty else '，不能为空'}")
    return value

def date(value, label):
    text(value, label)
    try:
        result = dt.date.fromisoformat(value)
    except ValueError:
        fail(f"{zh.field(label)}: 日期须按“年-月-日”填写，例如2026-11-02")
    if result.isoformat() != value:
        fail(f"{zh.field(label)}: 日期须按“年-月-日”填写，例如2026-11-02")
    return result

def records(value, label, allow_empty=False):
    if not isinstance(value, list) or len(value) > MAX_ROWS or (not value and not allow_empty):
        fail(f"{zh.field(label)}: 须提供{'0' if allow_empty else '1'}至{MAX_ROWS}条记录")
    if any(not isinstance(x, dict) for x in value):
        fail(f"{zh.field(label)}: 每条记录须为包含字段的对象")
    return value

def unique(rows, field, label):
    seen = set()
    for r in rows:
        ident = text(r.get(field), f"{zh.field(label)}.{field}")
        if ident in seen:
            fail(f"{zh.field(label)}: 字段“{zh.label(field)}”出现重复值{ident!r}")
        seen.add(ident)
    return seen

def strings(value, label):
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        fail(f"{zh.field(label)}: 须为文本列表")
    for x in value:
        text(x, label)
    if len(set(value)) != len(value):
        fail(f"{zh.field(label)}: 存在重复条目")
    return value

def choice(value, options, label):
    if value not in options:
        fail(f"{zh.field(label)}: 请选择以下选项：{'、'.join(str(zh.enum(v))+'（'+v+'）' for v in options)}")

def nonfinite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        fail("输入包含无效数字或无穷值")
    if isinstance(value, dict):
        for x in value.values(): nonfinite_tree(x)
    elif isinstance(value, list):
        for x in value: nonfinite_tree(x)

def validate_schedule(data):
    text(data.get("project_name"), "project_name")
    date(data.get("project_start"), "project_start")
    number(data.get("target_wd"), "target_wd", 1, 20000, True)
    holidays = strings(data.get("holidays", []), "holidays")
    for d in holidays: date(d, "holidays")
    tasks = records(data.get("tasks"), "tasks")
    ids = unique(tasks, "id", "tasks")
    for t in tasks:
        label = f"任务 {t['id']}"
        text(t.get("name"), f"{zh.field(label)}.name")
        text(t.get("owner"), f"{zh.field(label)}.owner", empty=True)
        number(t.get("duration_days"), f"{zh.field(label)}.duration_days", 0, 10000)
        deps = strings(t.get("depends_on"), f"{zh.field(label)}.depends_on")
        if set(deps) - ids: fail(f"{zh.field(label)}: 以下前置任务编号不存在：{sorted(set(deps)-ids)}")
        for key in ("deadline_wd", "not_before_wd", "available_through_wd"):
            if key in t: number(t[key], f"{zh.field(label)}.{key}", 1, 20000, True)
        if t.get("not_before_wd", 1) > t.get("available_through_wd", 20000):
            fail(f"{zh.field(label)}: 可用截止日不能早于最早开工日")
        if "key_control" in t and not isinstance(t["key_control"], bool):
            fail(f"{zh.field(label)}.独立复核要求：须填布尔值 true 或 false")
        if "reviewer" in t: text(t["reviewer"], f"{zh.field(label)}.reviewer", empty=True)
    if sum(t['duration_days'] for t in tasks) + max(t.get('not_before_wd',1) for t in tasks) > 20000:
        fail("计划跨度超过20000个工作日的上限")
    schedule.topo_order(tasks)

def validate_resource(r):
    for k in ("id", "name", "role"): text(r.get(k), f"resource.{k}")
    number(r.get("max_hours_per_week"), "max_hours_per_week", 0, 168)
    number(r.get("current_utilization"), "current_utilization", 0, 10)
    number(r.get("hourly_rate"), "hourly_rate", 0)
    skills = strings(r.get("skills"), "resource.skills")
    levels = r.get("skill_levels")
    if not isinstance(levels, dict) or set(skills) != set(levels):
        fail("成员技能水平：每个已列技能都须提供0至1之间的水平值")
    for k,v in levels.items(): number(v, f"skill_levels.{k}", 0, 1)
    # The retained aggregate model does not schedule individual absences.
    if r.get("availability_start") or r.get("availability_end"):
        fail("容量分析不处理按日期的个人可用窗口；请改用排期的最早开工日和可用截止日字段")

def validate_capacity_project(p, resource_ids):
    for k in ("id", "name"): text(p.get(k), f"project.{k}")
    choice(p.get("status"), ("planned","active","in_progress","completed","cancelled"), "project.status")
    choice(p.get("priority"), ("critical","high","medium","low"), "project.priority")
    choice(p.get("complexity"), tuple(capacity.PROJECT_COMPLEXITY_FACTORS), "project.complexity")
    number(p.get("estimated_hours"), "estimated_hours", 0)
    start = date(p.get("start_date"), "start_date")
    if date(p.get("target_end_date"), "target_end_date") <= start:
        fail("目标结束日期必须晚于开始日期")
    skills = strings(p.get("required_skills"), "required_skills")
    if not skills: fail("所需技能不能为空")
    reqs = p.get("skill_requirements")
    if not isinstance(reqs,dict) or set(reqs) != set(skills):
        fail("技能周工时需求：须为每项所需技能提供周工时")
    for k,v in reqs.items(): number(v, f"skill_requirements.{k}", 0)
    allocations = records(p.get("current_allocation"), "current_allocation", True)
    unique(allocations, "resource_id", "current_allocation")
    for a in allocations:
        if a['resource_id'] not in resource_ids: fail(f"分配中出现不存在的成员编号：{a['resource_id']}")
        number(a.get("hours_per_week"), "hours_per_week", 0, 168)

def validate_capacity(data):
    resources = records(data.get("resources"), "resources")
    rids = unique(resources,"id","resources")
    for r in resources: validate_resource(r)
    projects = records(data.get("projects"),"projects",True)
    pids = unique(projects,"id","projects")
    for p in projects: validate_capacity_project(p,rids)
    policy = data.get("capacity_policy")
    if not isinstance(policy,dict) or set(policy) != set(capacity.CAPACITY_FACTORS):
        fail("容量开销口径：须提供样例列出的五类占比，缺失值不能编造")
    for k,v in policy.items(): number(v, f"capacity_policy.{k}",0,1)
    if sum(policy.values()) >= 1: fail("五类容量开销占比之和必须小于1")
    scenarios = records(data.get("scenarios",[]),"scenarios",True)
    unique(scenarios,"name","scenarios")
    for s in scenarios:
        choice(s.get("type"),("add_resource","remove_resource","add_project","adjust_utilization"),"scenario.type")
        params=s.get("parameters")
        if not isinstance(params,dict): fail("情景参数须为包含字段的对象")
        if s['type'] in ('remove_resource','adjust_utilization'):
            if params.get('resource_id') not in rids: fail("情景引用的成员编号不存在")
            if s['type']=='adjust_utilization': number(params.get('new_utilization'),'new_utilization',0,10)
        elif s['type']=='add_resource':
            r=params.get('resource_data')
            if not isinstance(r,dict): fail("新增成员数据须为包含字段的对象")
            validate_resource(r)
            if r['id'] in rids: fail("新增成员编号已存在")
        else:
            p=params.get('project_data')
            if not isinstance(p,dict): fail("新增项目数据须为包含字段的对象")
            validate_capacity_project(p,rids)
            if p['id'] in pids: fail("新增项目编号已存在")

def validate_health(data):
    projects = records(data.get('projects'),'projects')
    unique(projects,'project_id','projects')
    for p in projects:
        text(p.get('project_name'),'project_name')
        choice(p.get('priority'),tuple(health.PRIORITY_WEIGHTS),'priority')
        statuses = tuple(x for values in health.PROJECT_STATUS_MAPPING.values() for x in values)
        choice(p.get('status'),statuses,'status')
        start = date(p.get('planned_start'),'planned_start')
        if date(p.get('planned_end'),'planned_end') <= start: fail('计划结束日期必须晚于计划开始日期')
        if date(p.get('forecasted_end'),'forecasted_end') < start: fail('预计结束日期不能早于计划开始日期')
        for k in ('planned_budget','planned_features'): number(p.get(k), k, 0.000001)
        for k in ('spent_to_date','forecasted_total_cost'): number(p.get(k), k)
        if p['forecasted_total_cost'] < p['spent_to_date']: fail('预计总成本不能低于累计已花费')
        for k in ('planned_features','completed_features','descoped_features','added_features','total_defects','resolved_defects','critical_defects','open_risks','critical_risks','team_size'):
            number(p.get(k),k,0,None,True)
        effective=p['planned_features']+p['added_features']-p['descoped_features']
        if effective <= 0 or p['completed_features'] > effective: fail('范围数量不一致：有效范围须为正数，已完成数量不能超过有效范围')
        if p['resolved_defects'] > p['total_defects'] or p['critical_defects'] > p['total_defects']-p['resolved_defects']:
            fail('已解决缺陷或未解决严重缺陷数量与缺陷总数不一致')
        if p['critical_risks'] > p['open_risks']: fail('严重风险数不能超过未关闭风险数')
        number(p.get('risk_score'),'risk_score',0,100)
        number(p.get('completion_percentage'),'completion_percentage',0,100)
        number(p.get('test_coverage'),'test_coverage',0,1)
        number(p.get('team_utilization'),'team_utilization',0,10)

def validate_risks(data):
    as_of=date(data.get('as_of'),'as_of')
    rows=records(data.get('risks'),'risks')
    unique(rows,'id','risks')
    for r in rows:
        for k in ('title','owner'): text(r.get(k),f'risk.{k}')
        choice(r.get('category'),tuple(risks.RISK_CATEGORIES),'risk.category')
        choice(r.get('status'),('open','identified','monitoring','mitigating','closed','resolved','accepted'),'risk.status')
        for k in ('probability','impact'): number(r.get(k),f'risk.{k}',1,5,True)
        if date(r.get('identified_date'),'identified_date') > as_of: fail('风险发现日期不能晚于分析日期')
        if r.get('target_resolution'):
            if date(r['target_resolution'],'target_resolution') < date(r['identified_date'],'identified_date'):
                fail('处置截止日期不能早于风险发现日期')
        text(r.get('mitigation_strategy'),'mitigation_strategy',True)
        strings(r.get('mitigation_actions'),'mitigation_actions')
        for k in ('cost_impact','schedule_impact_days'):
            if r.get(k) is not None: number(r[k],k)
        r['as_of']=data['as_of']

VALIDATORS={'schedule':validate_schedule,'capacity':validate_capacity,'health':validate_health,'risks':validate_risks}

def analyze(mode,data,delays=None):
    data=copy.deepcopy(data)
    if not isinstance(data,dict): fail('输入最外层须为包含字段的对象')
    nonfinite_tree(data)
    VALIDATORS[mode](data)
    assumptions=[]
    if mode=='schedule':
        report,code=schedule.plan(data)
        if delays:
            changed=copy.deepcopy(data)
            byid={t['id']:t for t in changed['tasks']}
            for ident,days in delays:
                if ident not in byid: fail(f'工期延长参数引用的任务不存在：{ident}')
                number(days,'delay-workdays',0,10000)
                byid[ident]['duration_days']+=days
            validate_schedule(changed)
            scenario,scenario_code=schedule.plan(changed)
            report['what_if']={'kind':'increase_task_duration_workdays','changes':[{'task_id':i,'additional_workdays':d} for i,d in delays],
                              'finish_shift_workdays':scenario['duration_workdays']-report['duration_workdays'],'report':scenario}
            code=max(code,scenario_code)
        assumptions=['工期按连续占用一位负责人全日容量的工作日计算，不是估算工时。',
                     '工作日为周一至周五，扣除已提供假期；不自动推断调休。',
                     '仅支持前置任务完成后开始的依赖；最早开工日和可用截止日限定任务负责人的可用窗口。',
                     '按依赖尽早排期并检查冲突，不会自动错峰或做资源约束最优解。',
                     '关键路径显示一条关键链，任务明细标出所有零浮时任务；零工期里程碑需结合精确偏移和时点说明判断。']
        return {'mode':mode,'assumptions':assumptions,'analysis':report},code
    if mode=='capacity':
        capacity.CAPACITY_FACTORS=dict(data['capacity_policy'])
        result=capacity.analyze_capacity(data)
        assumptions=['总工时先乘复杂度系数；周需求按结束减开始的自然日除以7，不能当作逐日排期。',
                     '当前利用率由用户提供；项目分配表是另一视图，两者须先核对口径。',
                     '技能匹配及调整建议是备选项，不是已执行或已解决冲突的分配方案。',
                     '角色效率/技能系数与复杂度系数是启发式模型，不是员工实测绩效或交付保证。']
        report=capacity.format_json_output(result)
        report['model_policy']={'overhead_fractions':data['capacity_policy'],'role_models':capacity.ROLE_TYPES,
                                'complexity_factors':capacity.PROJECT_COMPLEXITY_FACTORS,'utilization_thresholds':capacity.UTILIZATION_THRESHOLDS}
    elif mode=='health':
        result=health.analyze_portfolio_health(data)
        report=health.format_json_output(result)
        assumptions=['红黄绿是固定权重的启发式分数；不是交付成功概率。',
                     '范围维度衡量已完成范围比例，早期项目低完成度会降低评分；须结合阶段解释。',
                     '只对已提供且通过一致性校验的完整指标评分，不将未提供数据当作正常或零风险。',
                     '不计算历史趋势；已完成/已取消项目不会混入活跃组合汇总。']
    else:
        result=risks.analyze_risks(data)
        report=risks.format_json_output(result)
        report['as_of']=data['as_of']
        report['overdue_risk_ids']=[r['id'] for r in data['risks'] if risks.Risk(r).is_overdue]
        assumptions=['概率和影响均为1–5分等级，不是百分比；加权分数不是期望货币损失。',
                     '缓解措施覆盖率仅表示已记录措施，不代表措施已经有效。',
                     '截止日当天不算逾期，按指定的分析日期判断；不自动发送升级通知。',
                     '未实现历史风险速度、蒙特卡洛模拟和风险间相关性计算。']
    if 'error' in result.summary: fail(result.summary['error'])
    return {'mode':mode,'assumptions':assumptions,'analysis':report},0

def markdown(result):
    return zh.markdown(result)

def csv_text(rows):
    if not rows: return ''
    fields=list(dict.fromkeys(k for row in rows for k in row))
    buff=io.StringIO(newline=''); writer=csv.DictWriter(buff,fieldnames=fields);writer.writerow({k:zh.label(k) for k in fields})
    for row in rows:
        safe={}
        for k,v in row.items():
            v=zh.display(v,k)
            if isinstance(v,str) and (v.lstrip()[:1] in ('=','+','-','@') or v.startswith(('\t','\r','\n'))): v="'"+v
            safe[k]=v
        writer.writerow(safe)
    return '\ufeff'+buff.getvalue()

def export_files(result,source_bytes,out):
    result=zh.localize_messages(copy.deepcopy(result))
    result['labels_zh']={'fields':zh.LABELS,'values':zh.ENUMS}
    encoded=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    files={'report.json':encoded,'report.md':markdown(result)}
    r=result['analysis']
    if result['mode']=='schedule':
        files['schedule.csv']=csv_text(r['schedule'])
        if r.get('what_if'): files['scenario-schedule.csv']=csv_text(r['what_if']['report']['schedule'])
    elif result['mode']=='health': files['project-health.csv']=csv_text(r.get('project_scores',[]))
    elif result['mode']=='capacity':
        files['capacity-gaps.csv']=csv_text(r.get('project_analysis',{}).get('capacity_gaps',{}).get('gap_projects',[]))
    # Never replace an input, existing delivery directory or user file.
    out.mkdir(parents=False,exist_ok=False)
    for name,content in files.items(): (out/name).write_text(content,encoding='utf-8')
    manifest={'input_sha256':hashlib.sha256(source_bytes).hexdigest(),'files':[]}
    for name in files:
        content=(out/name).read_bytes()
        manifest['files'].append({'name':name,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return list(files)+['manifest.json']

class ChineseParser(argparse.ArgumentParser):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._positionals.title='必填模式'
        self._optionals.title='命令选项'
        for action in self._actions:
            if action.dest=='help': action.help='显示中文使用说明并退出'
    def format_usage(self):
        return super().format_usage().replace('usage:','用法：')
    def format_help(self):
        return super().format_help().replace('usage:','用法：')
    def error(self,message):
        if 'required' in message: description='缺少必填参数，请提供模式、--input 输入文件和 --out 新输出目录。'
        elif 'invalid choice' in message: description='模式不受支持，请选择 schedule（排期）、capacity（容量）、health（健康）或 risks（风险）。'
        elif 'expected one argument' in message: description='某个参数后缺少值，请检查 --input、--out 或 --extend-task 后的内容。'
        else: description='存在无法识别的命令参数，请运行 --help 查看中文使用说明。'
        print(json.dumps({'status':'INVALID_ARGUMENTS','error':description},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(3)

def error_message(exc):
    if isinstance(exc,InputError): return str(exc)
    if isinstance(exc,FileExistsError): return '输出目录已存在，为保护旧结果未覆盖；请改用新的目录名称。'
    if isinstance(exc,FileNotFoundError): return '找不到输入文件或输出目录的父目录，请核对实际路径：'+str(exc.filename or '')
    if isinstance(exc,PermissionError): return '没有读取或写入权限，请选择当前任务可访问的路径。'
    if isinstance(exc,UnicodeDecodeError): return '输入文件不是有效的UTF-8文本，请用UTF-8编码保存JSON后重试。'
    if isinstance(exc,json.JSONDecodeError): return f'JSON格式有误，请检查第{exc.lineno}行、第{exc.colno}列附近的内容。'
    if isinstance(exc,RecursionError): return '输入层级过深，请按样例使用扁平的任务、项目或风险列表。'
    if isinstance(exc,OverflowError): return '输入数字或日期超出可处理范围，请核对工期、日期及金额。'
    if isinstance(exc,OSError): return '文件读写失败，请检查文件是否可用、输出父目录和剩余空间。'
    return '输入字段类型、数值或工期延长参数格式有误，请按样例核对；延长工期写为任务编号=工作日数。'

def main(argv=None):
    p=ChineseParser(description='项目管理：本地排期、容量、健康和风险分析。仅 Python 标准库。')
    p.add_argument('mode',choices=tuple(VALIDATORS),help='模式：schedule排期、capacity容量、health健康、risks风险')
    p.add_argument('--input',required=True,type=Path,help='本次明确指定的JSON输入文件')
    p.add_argument('--out',required=True,type=Path,help='新的输出目录；其父目录必须已经存在')
    p.add_argument('--extend-task',action='append',default=[],metavar='ID=DAYS',help='仅排期模式：任务编号=增加的工作日数')
    args=p.parse_args(argv)
    try:
        if args.input.stat().st_size > MAX_BYTES: fail('输入文件超过5 MB上限')
        raw=args.input.read_bytes()
        def reject_constant(v): fail(f'输入文件包含不允许的JSON常量：{v}')
        def unique_keys(pairs):
            obj={}
            for k,v in pairs:
                if k in obj: fail(f'输入文件存在重复字段：{k!r}')
                obj[k]=v
            return obj
        data=json.loads(raw.decode('utf-8-sig'),parse_constant=reject_constant,object_pairs_hook=unique_keys)
        delays=[]
        for arg in args.extend_task:
            ident,days=arg.rsplit('=',1); delays.append((ident,float(days)))
        if delays and args.mode!='schedule': fail('延长工期参数 --extend-task 仅适用于排期模式')
        result,code=analyze(args.mode,data,delays)
        files=export_files(result,raw,args.out)
        print(json.dumps({'status':'FILES_WRITTEN','message_zh':'文件已生成，请按报告中的警告或阻断项核对结果。','analysis_exit_code':code,'mode':args.mode,'directory':str(args.out.resolve()),'files':files},ensure_ascii=False))
        return code
    except (InputError,OSError,ValueError,TypeError,KeyError,RecursionError,OverflowError) as exc:
        print(json.dumps({'status':'INVALID_INPUT_OR_OUTPUT','error':error_message(exc)},ensure_ascii=False),file=sys.stderr)
        return 3

if __name__=='__main__':
    sys.exit(main())
