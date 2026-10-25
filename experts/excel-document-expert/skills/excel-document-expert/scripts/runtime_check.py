"""只读检查当前表格运行能力，不读取业务文件或安装依赖。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


PROBE = r'''
import importlib,json,sys
result={'executable':sys.executable,'version':sys.version.split()[0],'modules':{}}
for name in ['openpyxl','pandas','xlsxwriter','markitdown','PIL','defusedxml','lxml']:
    try:
        module=importlib.import_module(name)
        result['modules'][name]={'available':True,'version':getattr(module,'__version__','未提供版本号')}
    except Exception as error:
        result['modules'][name]={'available':False,'error_type':type(error).__name__}
print(json.dumps(result,ensure_ascii=False))
'''


def detect():
    candidates = [sys.executable, shutil.which('python3'), shutil.which('python')]
    # A small, explicit list of system interpreters; no disk scan or dependence on another product's cache.
    if os.name != 'nt':
        candidates.append('/usr/bin/python3')
    paths = []
    for item in candidates:
        if item and Path(item).is_file():
            path = str(Path(item).resolve())
            if path not in paths:
                paths.append(path)
    interpreters = []
    for executable in paths:
        try:
            run = subprocess.run([executable, '-B', '-c', PROBE], capture_output=True, text=True, timeout=25)
            payload = json.loads(run.stdout)
            payload['probe_exit_code'] = run.returncode
            interpreters.append(payload)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            interpreters.append({'executable':executable, 'probe_error_type':type(error).__name__})
    ready = [item for item in interpreters if item.get('modules',{}).get('openpyxl',{}).get('available') and tuple(int(n) for n in item['version'].split('.')[:2]) >= (3,9)]
    soffice = shutil.which('soffice')
    return {
        'scope_zh':'仅代表本次执行环境，不代表其它客户端或付费云端',
        'python_interpreters':interpreters,
        'recommended_python':ready[0]['executable'] if ready else None,
        'workbook_read_write_ready':bool(ready),
        'soffice_on_path':soffice,
        'local_recalculation_candidate':bool(ready and soffice),
        'recalculation_verified':False,
        'native_tools_zh':'请由当前会话检查原生表格编辑/计算/保存工具并实际验证；此脚本不能检查会话工具注册表。',
        'next_step_zh':('可使用已检测到的解释器读改普通xlsx；公式必须经实际计算与复读验收。' if ready else '当前已检查的解释器缺少核心读改库；请使用已提供的原生表格工具，不能声称本地文件处理已完成。'),
        'installation_performed':False,
    }


def main():
    parser = argparse.ArgumentParser(description='检查当前 Excel 文件处理能力；不安装依赖、不读取业务资料。')
    parser.add_argument('--json', action='store_true', help='输出完整结构化检测结果')
    args = parser.parse_args()
    result = detect()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('Excel 运行能力检查')
        print('普通工作簿读改：' + ('已有可用解释器' if result['workbook_read_write_ready'] else '需使用原生工具或补齐运行环境'))
        if result['recommended_python']:
            print('可用解释器：' + result['recommended_python'])
        print('本地公式引擎：' + ('检测到 soffice，仍须实际计算验证' if result['soffice_on_path'] else '未检测到 soffice；需要已验证的原生计算工具'))
        print(result['next_step_zh'])
        print(result['scope_zh'])
    sys.exit(0 if result['local_recalculation_candidate'] else 3)


if __name__ == '__main__':
    main()
