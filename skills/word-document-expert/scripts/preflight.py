#!/usr/bin/env python3
"""Check only the current runtime, with no install, network or guessed availability."""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from run import choose_python
ROOT = Path(__file__).resolve().parent.parent

MODES = {
    'full': ['python', 'defusedxml', 'lxml', 'node_docx', 'pandoc', 'soffice', 'pdftoppm'],
    'core': ['python', 'defusedxml', 'lxml', 'node_docx'],
    'create': ['node_docx'],
    'accept-text': ['python'],
    'read': ['pandoc'],
    'edit': ['python', 'defusedxml', 'lxml'],
    'render': ['python', 'soffice', 'pdftoppm'],
    'accept': ['python', 'defusedxml', 'soffice'],
}
LABELS = {'python': 'Python 3.10或以上', 'defusedxml': '安全XML库', 'lxml': 'XML结构校验库', 'node_docx': 'Node与DOCX生成库', 'pandoc': '文档读取转换器', 'soffice': 'LibreOffice文档引擎', 'pdftoppm': '逐页图像转换器'}

def inspect_runtime(mode='full'):
    selected, attempts = choose_python(False)
    values = {'python': {'available':bool(selected), 'path':selected, 'runtime_checks':attempts}}
    library = ROOT / 'defusedxml'
    required = ['__init__.py','minidom.py','ElementTree.py','common.py','expatbuilder.py','expatreader.py']
    values['defusedxml'] = {'available':all((library/f).is_file() for f in required), 'path':str(library), 'reason_zh':'随包完整安全XML库，实际操作通过统一入口加载'}
    selected_xml, xml_attempts = choose_python(True)
    values['lxml'] = {'available':bool(selected_xml),'python':selected_xml,'runtime_checks':xml_attempts,'reason_zh':'已找到平台结构校验环境' if selected_xml else '未找到平台lxml环境；未安装全局依赖'}
    for name in ['pandoc', 'soffice', 'pdftoppm']:
        path = shutil.which(name)
        if name == 'soffice' and not path:
            path = shutil.which('libreoffice')
            known = Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')
            if not path and known.is_file(): path = str(known)
        rejected = bool(path and ('codex-runtimes' in path or '/.codex/' in path))
        values[name] = {'available': bool(path) and not rejected, 'path': path, 'reason_zh': '开发工具专用路径，不能视为产品依赖' if rejected else ('已发现命令；仍需真实执行验收' if path else '当前环境未找到')}
    node = shutil.which('node')
    values['node_docx'] = {'available': False, 'node': node, 'reason_zh': '未找到Node或DOCX生成库'}
    if node:
        try:
            r = subprocess.run([node, '-e', "const p=process.argv[1];const d=require(p); console.log(JSON.stringify({path:p,Document:typeof d.Document,Packer:typeof d.Packer}))", str(ROOT/'vendor/docx.cjs')], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                d = json.loads(r.stdout)
                rejected = 'codex-runtimes' in d['path'] or '/.codex/' in d['path']
                values['node_docx'] = {'available': not rejected and d['Document'] == 'function' and d['Packer'] == 'function', 'node': node, 'path': d['path'], 'reason_zh': '命中开发工具库，不能视为产品依赖' if rejected else '生成库可加载'}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            values['node_docx']['reason_zh'] = '依赖探测失败或超时'
    missing = [LABELS[k] for k in MODES[mode] if not values[k]['available']]
    return {'mode': mode, 'ready_for_requested_mode': not missing, 'message_zh': '当前模式依赖可用，仍须真实执行和验收。' if not missing else '当前模式无法完整执行，请补齐平台运行能力后重试；未安装软件，也未降级冒充完成。', 'missing_zh': missing, 'checks': values, 'release_ready': False, 'remaining_zh': '依赖检查不代表已生成文件、已完成视觉验收或已在所有WorkBuddy环境可用。'}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Word文档专家运行前检查；不安装、不联网。')
    p.add_argument('--mode', choices=MODES, default='full', help='full完整链路/core离线新建编辑校验/create新建/read转换读取/edit编辑/render渲染/accept接受修订/accept-text普通文字接受')
    r = inspect_runtime(p.parse_args().mode)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    raise SystemExit(0 if r['ready_for_requested_mode'] else 3)
