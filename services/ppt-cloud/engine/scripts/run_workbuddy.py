#!/usr/bin/env python3
"""只使用平台已有 Python 与依赖的中文启动器；不安装、不改环境或保护。"""
from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from package_integrity import require_skill_integrity
from workbuddy_fs import assert_protection

ROOT = Path(__file__).resolve().parent.parent
PROBE = '''import importlib,json,sys
result={"python":sys.executable,"version":sys.version.split()[0],"version_ok":sys.version_info>=(3,9),"modules":{}}
for name in ("pptx","xlsxwriter","PIL","lxml.etree"):
 try:
  m=importlib.import_module(name);result["modules"][name]={"available":True,"version":getattr(m,"__version__",None)}
 except Exception as e:result["modules"][name]={"available":False,"reason":type(e).__name__+": "+str(e)}
print(json.dumps(result,ensure_ascii=False))
'''

def candidates():
    paths=[sys.executable]
    for name in ('python3','python'):
        found=shutil.which(name)
        if found: paths.append(found)
    paths.extend(['/usr/bin/python3','/usr/local/bin/python3'])
    # Optional, existing WorkBuddy managed environment. Do not install or alter it.
    home=Path.home()
    paths.extend([str(home/'.workbuddy/binaries/python/envs/default/bin/python'),str(home/'.workbuddy/binaries/python/envs/default/Scripts/python.exe')])
    seen=set()
    for raw in paths:
        p=Path(raw).expanduser()
        try: resolved=p.resolve()
        except OSError: continue
        if not resolved.is_file() or not os.access(resolved,os.X_OK): continue
        lowered=str(resolved).lower()
        if 'codex-runtimes' in lowered or '/.codex/' in lowered: continue
        if str(resolved) not in seen:
            seen.add(str(resolved));yield resolved

def probe(path):
    try:
        p=subprocess.run([str(path),'-B','-c',PROBE],capture_output=True,text=True,timeout=30)
        if p.returncode: return {'python':str(path),'usable':False,'reason':'解释器探测未成功，退出码 '+str(p.returncode)}
        result=json.loads(p.stdout)
        result['usable']=result['version_ok'] and all(x['available'] for x in result['modules'].values())
        return result
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        return {'python':str(path),'usable':False,'reason':type(exc).__name__+': '+str(exc)}

def main():
    assert_protection()
    require_skill_integrity()
    args=sys.argv[1:] or ['doctor']
    selected=None
    if args and args[0] in ('--runtime','--prepare'):
        if len(args)<2: raise ValueError('缺少运行环境目录。')
        mode,runtime=args[:2];args=args[2:] or ['doctor']
        runtime=Path(runtime).expanduser().absolute()
        if mode=='--prepare':
            prepared=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/bootstrap_runtime.py'),'--runtime-dir',str(runtime)])
            if prepared.returncode:return prepared.returncode
        explicit=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not explicit.is_file():raise ValueError('指定运行环境没有可用解释器。')
        choices=[explicit]
    else:
        choices=list(candidates())
    observations=[]
    for path in choices:
        info=probe(path);observations.append(info)
        if info['usable']:
            selected=path;break
    if selected is None:
        result={'status':'运行环境不满足核心要求','selected':None,'required':['Python 3.9+','python-pptx','XlsxWriter','Pillow','lxml'],'probes':observations,'action':'当前平台缺少可用依赖，尚不能生成或修改PPTX。请由发布方在实际平台环境完成依赖验收；不会要求用户提供第三方账号或手工安装，也不会输出假文件。','environment_modified':False}
        if '--json' in args:print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            print('当前环境还不能完成可编辑 PPTX。需要平台已有 Python 3.9+、python-pptx、XlsxWriter、Pillow、lxml。')
            print('已只读探测现有解释器，没有安装软件或更改安全设置。请由发布方解决运行环境后再使用。')
        return 69
    # Inherit the environment unchanged, including all protection hooks.
    return subprocess.run([str(selected),'-B',str(ROOT/'scripts/workbuddy_ppt.py'),*args]).returncode

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,RuntimeError,ValueError) as exc:
        print('无法启动：'+str(exc),file=sys.stderr);raise SystemExit(2)
