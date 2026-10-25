#!/usr/bin/env python3
"""在项目内新建隔离环境，从官方 PyPI 准备固定核心库。"""
from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from package_integrity import require_skill_integrity
from workbuddy_fs import assert_protection, ensure_directory

ROOT = Path(__file__).resolve().parent.parent
PINS = {'python-pptx':'1.0.2','XlsxWriter':'3.2.9','Pillow':'11.3.0','lxml':'5.4.0','typing_extensions':'4.15.0'}
PROBE = '''import importlib,json,sys
from importlib.metadata import version
from pathlib import Path
names={"python-pptx":"pptx","XlsxWriter":"xlsxwriter","Pillow":"PIL","lxml":"lxml.etree","typing_extensions":"typing_extensions"}
data={"python":sys.executable,"prefix":sys.prefix,"version":sys.version.split()[0],"modules":{}}
for dist,module in names.items():
 m=importlib.import_module(module);data["modules"][dist]={"version":version(dist),"path":str(Path(m.__file__).resolve())}
print(json.dumps(data,ensure_ascii=False))
'''

def main():
    assert_protection()
    require_skill_integrity()
    parser=argparse.ArgumentParser(description='只在指定的新目录准备固定核心依赖，不写全局或用户库，不改变安全设置')
    parser.add_argument('--runtime-dir',required=True,help='全新虚拟环境目录；不得已存在')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    if sys.version_info < (3,9) or sys.version_info >= (3,14):
        raise ValueError('自动准备支持 Python 3.9 至 3.13；当前解释器版本尚未支持。')
    runtime=Path(args.runtime_dir).expanduser().absolute()
    if runtime.exists() or runtime.is_symlink():raise FileExistsError('运行目录已存在，已停止以免覆盖：'+str(runtime))
    resolved=runtime.resolve()
    if resolved==ROOT or resolved.is_relative_to(ROOT):raise ValueError('运行环境必须建在项目工作目录，不能写入技能安装包。')
    ensure_directory(runtime.parent,parents=True)
    logs=runtime.parent/(runtime.name+'-setup-logs')
    if logs.exists():raise FileExistsError('日志目录已存在，请更换本次新运行目录。')
    logs.mkdir()
    records=[];result={'status':'未完成','runtime_dir':str(runtime),'source_python':sys.executable,'environment_modified':False,'global_install':False,'index':'https://pypi.org/simple','requirements_sha256':hashlib.sha256((ROOT/'requirements-core.txt').read_bytes()).hexdigest()}
    def run(stage,command,timeout=300):
        assert_protection()
        p=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        (logs/(stage+'.stdout.txt')).write_text(p.stdout,encoding='utf-8')
        (logs/(stage+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
        records.append({'stage':stage,'command':command,'exit_code':p.returncode})
        if p.returncode:raise RuntimeError(stage+'未完成，退出码 '+str(p.returncode)+'；已保留原始日志，不改保护重试。')
        return p
    try:
        run('01_create_venv',[sys.executable,'-B','-m','venv','--symlinks',str(runtime)])
        python=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not python.is_file():raise RuntimeError('隔离环境没有生成可执行解释器。')
        report=logs/'pip-install-report.json'
        run('02_install_core',[str(python),'-B','-m','pip','--isolated','--disable-pip-version-check','install','--no-input','--no-cache-dir','--only-binary=:all:','--no-deps','--index-url','https://pypi.org/simple','--report',str(report),'-r',str(ROOT/'requirements-core.txt')],timeout=600)
        installed=json.loads(report.read_text())
        downloads=[]
        for item in installed.get('install',[]):
            url=item.get('download_info',{}).get('url','');parsed=urlparse(url)
            if parsed.scheme!='https' or parsed.hostname not in {'pypi.org','files.pythonhosted.org'}:raise RuntimeError('安装记录包含官方 PyPI 之外的来源，环境不予通过。')
            downloads.append({'url':url,'hashes':item.get('download_info',{}).get('archive_info',{}).get('hashes',{})})
        p=run('03_verify_isolation',[str(python),'-B','-c',PROBE]);info=json.loads(p.stdout)
        if Path(info['prefix']).resolve()!=resolved:raise RuntimeError('解释器未使用指定隔离环境。')
        for dist,pin in PINS.items():
            observed=info['modules'].get(dist,{})
            if observed.get('version')!=pin or not Path(observed.get('path','')).resolve().is_relative_to(resolved):raise RuntimeError('核心组件版本或安装位置不一致：'+dist)
        run('04_dependency_check',[str(python),'-B','-m','pip','--isolated','--disable-pip-version-check','check'])
        result.update({'status':'隔离核心环境准备完成','python':str(python),'probe':info,'downloads':downloads,'next_step':'使用此隔离解释器实际执行生成/修改任务；准备完成不等于交付验收通过。'})
        (runtime/'runtime-info.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        result['error']=str(exc)
    (logs/'execution.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (logs/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        print('状态：'+result['status'])
        if result.get('python'):print('解释器：'+result['python'])
        if result.get('error'):print('原因：'+result['error'])
        print('记录：'+str(logs/'result.json'))
    return 0 if result['status']=='隔离核心环境准备完成' else 69

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as exc:
        print('环境准备未启动：'+str(exc),file=sys.stderr);raise SystemExit(2)
