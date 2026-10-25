#!/usr/bin/env python3
"""读取平层模板清单，或把明确选定的非代码模板复制到新工作目录。"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from _flat_layout import FILES, ROOT, activate
activate()
from package_integrity import require_skill_integrity
from workbuddy_fs import assert_protection, ensure_directory

ALLOWED = {'.svg', '.md', '.json', '.txt', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.wav', '.mp3'}

def main():
    assert_protection()
    require_skill_integrity()
    parser = argparse.ArgumentParser(description='列出内置模板，或复制选定素材到全新工作目录；不复制源码、不覆盖原件。')
    parser.add_argument('command', choices=['list', 'materialize'])
    parser.add_argument('prefix', help='清单中的逻辑素材目录，例如 templates/layouts/editorial_bleed')
    parser.add_argument('--output', help='materialize 必需：本次全新目标目录')
    args = parser.parse_args()
    prefix = PurePosixPath(args.prefix)
    if prefix.is_absolute() or '..' in prefix.parts or not prefix.parts or prefix.parts[0] not in {'templates', 'references'}:
        raise ValueError('只能选择内置 templates 或 references 素材目录。')
    stem = prefix.as_posix().rstrip('/') + '/'
    selected = {k: v for k, v in FILES.items() if k.startswith(stem)}
    if not selected:
        raise ValueError('该目录没有随包素材，请先查看平层资源索引。')
    if any(PurePosixPath(k).suffix.lower() not in ALLOWED for k in selected):
        raise ValueError('所选目录含不支持复制的文件；不能复制或还原程序源码。')
    if args.command == 'list':
        print('可用素材：' + str(len(selected)) + ' 个')
        for logical, actual in sorted(selected.items()):
            print(logical + ' → ' + str(ROOT / actual))
        return 0
    if not args.output:
        raise ValueError('复制素材需要 --output 指定全新工作目录。')
    output = Path(args.output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('目标目录已经存在；已停止，未覆盖任何内容。')
    if output.resolve().is_relative_to(ROOT):
        raise ValueError('不能向技能安装目录写入客户工作文件。')
    ensure_directory(output.parent, parents=True)
    output.mkdir()
    records = []
    for logical, actual in sorted(selected.items()):
        relative = PurePosixPath(logical[len(stem):])
        target = output / relative
        ensure_directory(target.parent, parents=True)
        data = (ROOT / actual).read_bytes()
        with target.open('xb') as stream:
            stream.write(data)
        digest = hashlib.sha256(data).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError('素材复制校验失败：' + str(relative))
        records.append({'resource': logical, 'output': str(target), 'sha256': digest})
    print(json.dumps({'状态': '选定模板已复制到新工作目录', '目录': str(output), '文件数': len(records), '文件': records}, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print('模板处理未完成：' + str(exc), file=sys.stderr)
        raise SystemExit(2)
