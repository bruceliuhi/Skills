#!/usr/bin/env python3
"""Compare exact OOXML part bytes; never writes or normalizes either document."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

def snapshot(path):
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith('/')]
        if len(names) != len(set(names)): raise ValueError('文档包含重复的内部文件名，不能可靠比较。')
        if 'word/document.xml' not in names: raise ValueError('文件不包含Word正文部件。')
        if zf.testzip(): raise ValueError('文档压缩包校验失败。')
        return {name: hashlib.sha256(zf.read(name)).hexdigest() for name in names}

def compare(original, modified, allowed):
    before, after = snapshot(original), snapshot(modified)
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    unexpected = sorted((set(changed) | set(added) | set(removed)) - set(allowed))
    return {'message_zh': '未发现允许范围之外的部件变化。' if not unexpected else '存在允许范围之外的变化，请复核后再交付。', 'passed': not unexpected, 'original_sha256': hashlib.sha256(Path(original).read_bytes()).hexdigest(), 'modified_sha256': hashlib.sha256(Path(modified).read_bytes()).hexdigest(), 'allowed_parts': sorted(allowed), 'changed_parts': changed, 'added_parts': added, 'removed_parts': removed, 'unexpected_parts': unexpected, 'unchanged_part_count': sum(before[k] == after[k] for k in before.keys() & after.keys()), 'limits_zh': '部件字节相同可证明该部件未改；允许变化的正文仍须逐项检查修改范围，并渲染验证版式。'}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='检查Word局部修改是否影响未授权部件；不修改输入。')
    p.add_argument('original', type=Path, help='原文件')
    p.add_argument('modified', type=Path, help='新文件')
    p.add_argument('--allow-part', action='append', default=[], help='允许变化的OOXML部件，需逐个指定')
    a = p.parse_args()
    try:
        r = compare(a.original, a.modified, a.allow_part)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r['passed'] else 2)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print(json.dumps({'passed': False, 'message_zh': '无法完成文档保护检查：' + str(e)}, ensure_ascii=False))
        sys.exit(3)
