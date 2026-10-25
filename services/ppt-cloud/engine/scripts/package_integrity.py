#!/usr/bin/env python3
"""PPT制作与美化专家发行完整性校验：逐文件哈希、产品信息与实际入口检查。"""
from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from workbuddy_fs import assert_protection

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = 'PACKAGE_MANIFEST.json'
DIGEST = 'PACKAGE_MANIFEST.sha256'
PRODUCT = 'ppt-presentation-expert'
VERSION = '1.0.0'
GATES = (
    'scripts/console_encoding.py', 'scripts/project_manager.py',
    'scripts/project_management__cli.py', 'scripts/svg_quality_checker.py',
    'scripts/svg_quality__cli.py', 'scripts/svg_to_pptx.py',
    'scripts/svg_to_pptx__pptx_package__cli.py', 'scripts/register_template.py',
    'scripts/template_preview_pptx.py', 'scripts/workbuddy_ppt.py',
    'scripts/run_workbuddy.py', 'scripts/bootstrap_runtime.py', 'scripts/bundle_resources.py',
)

def _identity_valid(text):
    if not text.startswith('---\n') or '\n---\n' not in text[4:]: return False
    front = text[4:].split('\n---\n', 1)[0]
    expected = {'name': PRODUCT, 'version': VERSION, 'author': '星河卓越'}
    for key, value in expected.items():
        hits = re.findall(r'(?m)^' + re.escape(key) + r':\s*(.*?)\s*$', front)
        if len(hits) != 1 or hits[0].strip('"\'') != value: return False
    return text.count('python3 "${SKILL_DIR}/scripts/package_integrity.py"') == 1

def _gate_valid(path):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    imported = any(isinstance(n, ast.ImportFrom) and n.module == 'package_integrity' and any(x.name == 'require_skill_integrity' for x in n.names) for n in ast.walk(tree))
    called = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'require_skill_integrity' for n in ast.walk(tree))
    return imported and called

def verify_package():
    assert_protection()
    raw = (ROOT / MANIFEST).read_bytes()
    expected_digest = (ROOT / DIGEST).read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[a-f0-9]{64}', expected_digest) or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError('发行清单校验值不一致')
    manifest = json.loads(raw)
    if manifest.get('product') != PRODUCT or manifest.get('version') != VERSION:
        raise ValueError('发行清单产品或版本不一致')
    files = manifest.get('files')
    if not isinstance(files, dict) or len(files) < 100:
        raise ValueError('发行清单缺少完整核心文件')
    for relative, digest in files.items():
        rel = Path(relative)
        if rel.is_absolute() or '..' in rel.parts or relative in (MANIFEST, DIGEST):
            raise ValueError('发行清单包含不合法路径')
        path = ROOT / rel
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('缺少完整文件：' + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('文件校验不一致：' + relative)
    for path in (ROOT / 'scripts').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py', '.js', '.sh'} and path.relative_to(ROOT).as_posix() not in files:
            raise ValueError('出现清单之外的可执行脚本：' + path.relative_to(ROOT).as_posix())
    if not _identity_valid((ROOT / 'SKILL.md').read_text(encoding='utf-8')):
        raise ValueError('技能产品信息不一致')
    if not all(path in files and _gate_valid(ROOT / path) for path in GATES):
        raise ValueError('关键执行入口的完整性检查缺失')
    console = (ROOT / 'scripts/console_encoding.py').read_text(encoding='utf-8')
    if console.count('_require_release_identity()') < 2:
        raise ValueError('独立产品身份检查缺失')
    return {'product': PRODUCT, 'version': VERSION, 'files_checked': len(files)}

def require_skill_integrity():
    try:
        return verify_package()
    except (OSError, ValueError, RuntimeError, SyntaxError, UnicodeError) as exc:
        print('技能完整性检查未通过：' + str(exc) + '。请重新安装完整发行包；不要跳过检查或修改安全保护。', file=sys.stderr)
        raise SystemExit(78)

def main():
    result = require_skill_integrity()
    print('完整性检查通过：PPT制作与美化专家 ' + VERSION + '，已核对 ' + str(result['files_checked']) + ' 个文件。')
    return 0

if __name__ == '__main__': raise SystemExit(main())
