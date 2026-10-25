#!/usr/bin/env python3
"""IQR, Z-score and modified Z-score with explicit measure selection and row evidence."""
from __future__ import annotations
import math
from dq_common import Parser, add_io_args, emit, is_null, load_csv, location, number, run, select_columns

def median(nums):
    s=sorted(nums); n=len(s); mid=n//2
    return s[mid] if n%2 else s[mid-1]/2+s[mid]/2

def percentile(nums,p):
    s=sorted(nums); n=len(s)
    if n==1: return s[0]
    idx=p/100*(n-1); lo=int(idx); hi=lo+1; frac=idx-lo
    if hi>=n: return s[-1]
    return s[lo]+frac*(s[hi]-s[lo])

def mean(nums):
    scale=max(abs(n) for n in nums)
    return scale*(math.fsum(n/scale for n in nums)/len(nums)) if scale else 0.0

def std(nums,mu):
    if len(nums)<2: return 0.0
    scale=max(abs(x-mu) for x in nums)
    return scale*math.sqrt(math.fsum(((x-mu)/scale)**2 for x in nums)/(len(nums)-1)) if scale else 0.0

def detect_iqr(nums,multiplier=1.5):
    q1=percentile(nums,25); q3=percentile(nums,75); iqr=q3-q1
    lower=q1-multiplier*iqr; upper=q3+multiplier*iqr
    if not all(math.isfinite(v) for v in (lower,upper)):
        raise ValueError("IQR bounds overflow; reduce threshold or inspect numeric scale")
    indexes=[i for i,x in enumerate(nums) if x<lower or x>upper]
    return {"method":"IQR","q1":q1,"q3":q3,"iqr":iqr,"lower_bound":lower,"upper_bound":upper,"threshold":multiplier},indexes

def detect_zscore(nums,threshold=3.0):
    mu=mean(nums); sigma=std(nums,mu)
    if sigma==0:
        return {"method":"Z-score","mean":mu,"std":sigma,"threshold":threshold,"status":"NOT_ASSESSABLE_ZERO_VARIANCE","note":"本方法无可用方差，不能据此判定字段干净。"},[]
    return {"method":"Z-score","mean":mu,"std":sigma,"threshold":threshold},[i for i,x in enumerate(nums) if abs((x-mu)/sigma)>threshold]

def detect_modified_zscore(nums,threshold=3.5):
    med=median(nums); mad=median([abs(x-med) for x in nums])
    if mad==0:
        return {"method":"Modified Z-score (MAD)","median":med,"mad":mad,"threshold":threshold,"status":"NOT_ASSESSABLE_ZERO_MAD","note":"MAD为0，改用IQR或明确业务规则复核，不把未能评估写成无异常。"},[]
    return {"method":"Modified Z-score (MAD)","median":med,"mad":mad,"threshold":threshold},[i for i,x in enumerate(nums) if .6745*abs(x-med)/mad>threshold]

def analyze_column(col,table,method,threshold):
    entries=[]; invalid=[]; missing=[]
    for i,row in enumerate(table["rows"]):
        raw=row[col]
        if is_null(raw): missing.append(location(table,i,col,raw)); continue
        n,error=number(raw)
        if error or n is None:
            invalid.append(dict(location(table,i,col,raw),issue=error or "non_numeric_in_selected_measure"))
        else: entries.append((i,n))
    nums=[n for _,n in entries]
    base={"column":col,"total_numeric":len(nums),"total_rows":len(table["rows"]),"missing_records":missing,"invalid_numeric_records":invalid,"excluded_count":len(missing)+len(invalid),"threshold":threshold,"method":method}
    if len(nums)<4:
        return dict(base,status="NOT_ASSESSABLE_FEWER_THAN_4",outlier_count=None,outlier_pct=None,outlier_records=[],note="有效数字不足4个，未执行本次数值分布检测。")
    if method=="iqr": result,indexes=detect_iqr(nums,threshold)
    elif method=="zscore": result,indexes=detect_zscore(nums,threshold)
    else: result,indexes=detect_modified_zscore(nums,threshold)
    base.update(result)
    assessed="status" not in result
    base.update(outlier_count=len(indexes) if assessed else None,outlier_pct=round(len(indexes)/len(nums)*100,2) if assessed else None,outlier_values=sorted(set(nums[i] for i in indexes))[:10],outlier_records=[dict(location(table,entries[i][0],col,table["rows"][entries[i][0]][col]),numeric_value=nums[i]) for i in indexes])
    if assessed:
        base["status"]="REVIEW_REQUIRED" if indexes or invalid or missing else "NO_OUTLIERS_IN_VALID_NUMERIC_SUBSET"
    base["risk_assessment"]="统计筛查只产生待复核候选；异常比例不证明录入错误或可自动删除。"
    return base

def main():
    parser=Parser(description="数据质量专家：指定数值字段异常检测")
    add_io_args(parser)
    parser.add_argument("--columns",help="必填；用户明确选择的数值指标，避免自动扫描编号")
    parser.add_argument("--method",choices=["iqr","zscore","mzscore"],default="iqr",help="iqr：四分位距；zscore：标准分数；mzscore：修正标准分数")
    parser.add_argument("--threshold",type=float,default=None,help="正数阈值；默认分别为 1.5、3、3.5，显式填写时按填写值执行")
    args=parser.parse_args()
    threshold=args.threshold if args.threshold is not None else {"iqr":1.5,"zscore":3.0,"mzscore":3.5}[args.method]
    if not math.isfinite(threshold) or threshold<=0:
        raise ValueError("threshold must be finite and positive")
    table=load_csv(args.file,args.delimiter); selected=select_columns(table,args.columns,required=True)
    results=[analyze_column(c,table,args.method,threshold) for c in selected]
    review=any(r["status"]!="NO_OUTLIERS_IN_VALID_NUMERIC_SUBSET" for r in results)
    report={"tool":"数值异常检查","total_rows":len(table["rows"]),"selected_columns":selected,"method":args.method,"threshold":threshold,"columns":results,"review_required":review,"status":"REVIEW_REQUIRED" if review else "NO_FINDINGS_IN_CHECKED_SCOPE"}
    return emit(report,args,table)

if __name__=="__main__":
    run(main)
