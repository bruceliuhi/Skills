#!/usr/bin/env python3
"""Run preserved document utilities with bundled XML safety library and a verified runtime."""
import json, os, shutil, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
COMMANDS={
 'validate':'office_validate.py','comment':'comment.py','merge-runs':'merge_runs.py',
 'accept-all':'accept_changes.py','accept-text':'accept_text_revisions.py',
 'preserve':'verify_preservation.py','convert':'office_soffice.py'}
LABELS={'validate':'结构及修订检查','comment':'批注部件处理','merge-runs':'同格式文字片段合并','accept-all':'文档引擎接受修订','accept-text':'普通文字修订清洁副本','preserve':'未改部件核对','convert':'文档引擎转换'}

def private_dev(path):return 'codex-runtimes' in str(path) or '/.codex/' in str(path)
def candidate_pythons():
 values=[os.environ.get('WORD_EXPERT_PYTHON'),sys.executable,str(Path.home()/'.workbuddy/binaries/python/envs/default/bin/python'),str(Path.home()/'.workbuddy/binaries/python/envs/default/Scripts/python.exe'),shutil.which('python3')]
 seen=set()
 for x in values:
  if x and x not in seen and Path(x).is_file() and not private_dev(x):seen.add(x);yield x

def choose_python(require_lxml=False):
 attempts=[]
 code="import sys,json; d={'version':list(sys.version_info[:3]),'executable':sys.executable};"+("import lxml.etree as l;d['lxml']=l.__file__;" if require_lxml else '')+"print(json.dumps(d))"
 for exe in candidate_pythons():
  try:
   r=subprocess.run([exe,'-I','-c',code],capture_output=True,text=True,timeout=10)
   d=json.loads(r.stdout) if r.returncode==0 else {}
   good=bool(d) and d['version'][:2]>=[3,10] and not private_dev(d.get('lxml',''))
   attempts.append({'python':exe,'usable':good,'lxml_path':d.get('lxml'),'version':d.get('version')})
   if good:return exe,attempts
  except (OSError,ValueError,subprocess.TimeoutExpired):attempts.append({'python':exe,'usable':False})
 return None,attempts

def main():
 if len(sys.argv)<2 or sys.argv[1] not in COMMANDS:
  print(json.dumps({'success':False,'message_zh':'请选择操作：validate结构检查、comment批注、merge-runs合并、accept-text普通文字接受、accept-all引擎接受、preserve保留核对、convert转换。'},ensure_ascii=False));return 2
 name=sys.argv[1];exe,attempts=choose_python(name=='validate')
 if not exe:
  print(json.dumps({'success':False,'message_zh':'当前缺少可用的Python 3.10+运行环境'+('或lxml结构校验库。' if name=='validate' else '。')+'未执行任务；可使用平台环境，或在独立目录准备固定依赖。','runtime_checks':attempts},ensure_ascii=False,indent=2));return 3
 env=os.environ.copy();env['PYTHONPATH']=str(ROOT);env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
 try:
  r=subprocess.run([exe,str(HERE/COMMANDS[name])]+sys.argv[2:],capture_output=True,text=True,env=env,timeout=180)
 except (OSError,subprocess.TimeoutExpired) as exc:
  print(json.dumps({'success':False,'message_zh':f'{LABELS[name]}未完成：执行失败或超时。','detail':str(exc)},ensure_ascii=False,indent=2));return 3
 print(json.dumps({'success':r.returncode==0,'message_zh':LABELS[name]+('已完成，请按技能继续核对实际文件。' if r.returncode==0 else '未通过，请根据诊断修复；不能宣称交付完成。'),'python':exe,'exit_code':r.returncode,'diagnostics':{'stdout':r.stdout,'stderr':r.stderr}},ensure_ascii=False,indent=2))
 return r.returncode
if __name__=='__main__':sys.exit(main())
