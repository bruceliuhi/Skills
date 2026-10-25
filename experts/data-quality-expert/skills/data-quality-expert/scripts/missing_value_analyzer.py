#!/usr/bin/env python3
"""Missing counts, row patterns and co-occurrence without causal claims."""
from __future__ import annotations
import math
from dq_common import Parser, add_io_args, emit, is_null, load_csv, location, numeric_issues, run, select_columns
from data_profiler import infer_type

def compute_null_mask(headers, rows):
    return {col:[is_null(row[col]) for row in rows] for col in headers}

def null_stats(mask):
    return {"count":sum(mask),"pct":round(sum(mask)/len(mask)*100,2) if mask else 0}

def classify_mechanism(col, mask, all_masks):
    return "UNKNOWN" if any(mask) else "NOT_APPLICABLE"

def recommend_strategy(pct, col_type):
    if pct == 0:
        return "本次未识别到约定空值；仍需核对业务哨兵值。"
    if pct < 10:
        return "先确认缺失是否允许及来源；可比较保留缺失、标记缺失或填补方案，未经确认不删行、不填补。"
    if pct < 30:
        return "核查采集与字段适用范围，评估对目标指标的影响；如需填补，先确认依据、保留原值和填补标记。"
    return "较多值缺失，优先确认采集和字段适用口径；不能仅凭比例认定应删列或某种填补安全。"

def compute_cooccurrence(headers, masks, table):
    pairs = []
    for i,a in enumerate(headers):
        for b in headers[i+1:]:
            overlap = [j for j,(x,y) in enumerate(zip(masks[a],masks[b])) if x and y]
            union = sum(x or y for x,y in zip(masks[a],masks[b]))
            if overlap:
                pairs.append({"col_a":a,"col_b":b,"co_null_rows":len(overlap),"jaccard":round(len(overlap)/union,4),"records":[location(table,j) for j in overlap],"interpretation":"共缺描述，不证明MAR或MNAR。"})
    return sorted(pairs,key=lambda x:-x["co_null_rows"])

def main():
    parser=Parser(description="数据质量专家：缺失值统计与逐行定位")
    add_io_args(parser)
    parser.add_argument("--columns", help="检查字段，多个字段以逗号分隔；未指定时检查全部字段")
    parser.add_argument("--threshold",type=float,default=0.0,help="仅展示缺失比例>=该值且确有缺失的字段；范围0到1")
    args=parser.parse_args()
    if not math.isfinite(args.threshold) or not 0<=args.threshold<=1:
        raise ValueError("threshold must be finite and between 0 and 1")
    table=load_csv(args.file,args.delimiter); headers=select_columns(table,args.columns)
    masks=compute_null_mask(headers,table["rows"]); output=[]
    for col in headers:
        mask=masks[col]; stats=null_stats(mask)
        if not stats["count"] or stats["count"]/len(mask)<args.threshold:
            continue
        kind=infer_type([row[col] for row in table["rows"] if not is_null(row[col])])
        indexes=[i for i,v in enumerate(mask) if v]
        runs=[]
        for i in indexes:
            if runs and i==runs[-1][-1]+1: runs[-1].append(i)
            else: runs.append([i])
        output.append({"column":col,"null_count":stats["count"],"null_pct":stats["pct"],"col_type":kind,"mechanism":classify_mechanism(col,mask,masks),"mechanism_note":"单次观测的行顺序与共缺不能识别缺失机制，需要采集过程和额外证据。","strategy":recommend_strategy(stats["pct"],kind),"missing_records":[location(table,i,col,table["rows"][i][col]) for i in indexes],"consecutive_record_runs":[{"start_record":r[0]+1,"end_record":r[-1]+1,"count":len(r)} for r in runs]})
    issues=numeric_issues(table,headers)
    total_missing=sum(sum(mask) for mask in masks.values())
    report={"tool":"缺失值检查","total_rows":len(table["rows"]),"selected_columns":headers,"threshold_fraction":args.threshold,"columns":sorted(output,key=lambda x:-x["null_pct"]),"all_column_null_counts":{c:sum(masks[c]) for c in headers},"complete_columns":[c for c in headers if not any(masks[c])],"columns_below_threshold":[c for c in headers if 0<sum(masks[c])/len(masks[c])<args.threshold],"cooccurrence":compute_cooccurrence(headers,masks,table),"numeric_issues":issues,"null_tokens":sorted(__import__('dq_common').NULL_STRINGS),"total_missing_cells":total_missing,"review_required":bool(total_missing or issues),"status":"REVIEW_REQUIRED" if total_missing or issues else "NO_FINDINGS_IN_CHECKED_SCOPE"}
    return emit(report,args,table)

if __name__=="__main__":
    run(main)
