#!/usr/bin/env python3
"""平层发行适配：显式模块索引与只读资源索引。

所有源码和资源均为包内可扫描的普通明文文件。此模块只使用标准 Python
加载器读取对应 .py，不解包、不还原嵌套源码目录、不联网、不修改系统保护。
资源对象仅表示随包文件；客户工作目录仍使用原生 pathlib.Path。
此适配器不是安全沙箱，操作系统与 WorkBuddy 的保护始终保持原状。
"""
from __future__ import annotations
import fnmatch
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import posixpath
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
_layout = json.loads((ROOT / 'bundle-layout.json').read_text(encoding='utf-8'))
if _layout.get('product') != 'ppt-presentation-expert' or _layout.get('format') != 1:
    raise RuntimeError('平层发行索引产品或格式不正确。')
FILES = _layout['files']
MODULES = _layout['modules']
ALIASES = _layout['aliases']
for _relative in FILES.values():
    _parts = PurePosixPath(_relative)
    if _parts.is_absolute() or '..' in _parts.parts or len(_parts.parts) > 2:
        raise RuntimeError('平层索引包含不安全或超过两级的文件路径。')
    _target = ROOT / _relative
    if _target.is_symlink() or not _target.resolve().is_relative_to(ROOT):
        raise RuntimeError('平层索引不能读取包外文件或符号链接。')

class _FlatFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        canonical = ALIASES.get(fullname, fullname)
        info = MODULES.get(canonical)
        if info is None:
            return None
        file = info.get('file')
        if file is None:
            if not info.get('package'):
                raise ImportError('平层模块没有源码文件：' + fullname)
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = [str(ROOT / 'scripts')]
            return spec
        if file not in FILES.values() or not file.endswith('.py'):
            raise ImportError('平层模块源码未列入资源索引：' + fullname)
        source = ROOT / file
        loader = importlib.machinery.SourceFileLoader(fullname, str(source))
        return importlib.util.spec_from_file_location(
            fullname, source, loader=loader,
            submodule_search_locations=[str(ROOT / 'scripts')] if info.get('package') else None,
        )

def activate():
    """仅注册本包明确列出的模块；未知模块沿用 Python 正常导入。"""
    if not any(isinstance(f, _FlatFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _FlatFinder())

class BundlePath(os.PathLike):
    """只读随包资源，不修改 Path 类、不拦截客户目录访问。"""
    def __init__(self, logical=''):
        raw = str(logical).replace('\\', '/')
        pure = PurePosixPath(raw)
        if pure.is_absolute() or '..' in pure.parts:
            raise ValueError('资源路径必须在技能包内。')
        self.logical = '' if raw in ('', '.') else pure.as_posix()

    @property
    def actual(self):
        path = ROOT / FILES.get(self.logical, self.logical)
        if self.logical in FILES and (path.is_symlink() or not path.resolve().is_relative_to(ROOT)):
            raise PermissionError('随包文件指向包外或符号链接，已停止读取。')
        return path

    def _indexed_file(self):
        if self.logical not in FILES:
            raise FileNotFoundError('该文件未列入随包资源索引：' + self.logical)
        return self.actual

    def __fspath__(self):
        return str(self.actual)

    def __str__(self):
        return str(self.actual)

    def __repr__(self):
        return 'BundlePath(' + repr(self.logical) + ')'

    def __truediv__(self, other):
        return BundlePath(posixpath.join(self.logical, os.fspath(other)))

    def joinpath(self, *others):
        value = self
        for other in others:
            value = value / other
        return value

    @property
    def parent(self):
        return BundlePath(posixpath.dirname(self.logical)) if self.logical else ROOT.parent

    @property
    def parents(self):
        result = []
        current = self
        while isinstance(current, BundlePath):
            current = current.parent
            result.append(current)
        result.extend(current.parents)
        return tuple(result)

    @property
    def name(self):
        return PurePosixPath(self.logical).name if self.logical else ROOT.name

    @property
    def stem(self):
        return PurePosixPath(self.logical).stem

    @property
    def suffix(self):
        return PurePosixPath(self.logical).suffix

    @property
    def suffixes(self):
        return PurePosixPath(self.logical).suffixes

    @property
    def parts(self):
        return self.actual.parts

    def with_name(self, name):
        if not self.logical:
            return ROOT.with_name(name)
        return self.parent / name

    def with_suffix(self, suffix):
        return self.with_name(str(PurePosixPath(self.name).with_suffix(suffix)))

    def resolve(self, strict=False):
        if strict and not self.exists():
            raise FileNotFoundError(str(self))
        return self

    absolute = resolve
    expanduser = resolve

    def is_absolute(self):
        return True

    def is_file(self):
        return self.logical in FILES and self.actual.is_file()

    def is_dir(self):
        prefix = self.logical + '/' if self.logical else ''
        return not self.logical or any(k.startswith(prefix) for k in FILES)

    def exists(self):
        return self.is_file() or self.is_dir()

    def is_symlink(self):
        return self.actual.is_symlink()

    def stat(self, **kwargs):
        return self.actual.stat(**kwargs)

    def read_bytes(self):
        return self._indexed_file().read_bytes()

    def read_text(self, encoding='utf-8', errors=None):
        return self._indexed_file().read_text(encoding=encoding, errors=errors)

    def open(self, mode='r', *args, **kwargs):
        if any(c in mode for c in 'wax+'):
            raise PermissionError('随包资源只读；请把修改写入新的客户项目目录。')
        return self._indexed_file().open(mode, *args, **kwargs)

    def iterdir(self):
        if not self.is_dir():
            raise NotADirectoryError(str(self))
        prefix = self.logical + '/' if self.logical else ''
        children = sorted({k[len(prefix):].split('/')[0] for k in FILES if k.startswith(prefix)})
        return iter(self / name for name in children)

    def glob(self, pattern):
        prefix = self.logical + '/' if self.logical else ''
        candidates = set()
        for logical in FILES:
            if not logical.startswith(prefix):
                continue
            parts = PurePosixPath(logical[len(prefix):]).parts
            candidates.update('/'.join(parts[:i]) for i in range(1, len(parts) + 1))
        recursive = '**' in PurePosixPath(pattern).parts
        depth = len(PurePosixPath(pattern).parts)
        for relative in sorted(candidates):
            if not recursive and len(PurePosixPath(relative).parts) != depth:
                continue
            match = PurePosixPath(relative).match(pattern)
            if pattern.startswith('**/'):
                match = match or PurePosixPath(relative).match(pattern[3:])
            if match:
                yield self / relative

    def rglob(self, pattern):
        return self.glob('**/' + pattern)

    def relative_to(self, other):
        if isinstance(other, BundlePath):
            if not other.logical:
                return self.actual.relative_to(ROOT)
            return PurePosixPath(self.logical).relative_to(PurePosixPath(other.logical or '.'))
        return self.actual.relative_to(Path(other))

    def is_relative_to(self, other):
        try:
            self.relative_to(other)
            return True
        except ValueError:
            return False

    def as_posix(self):
        return self.actual.as_posix()

    def as_uri(self):
        return self.actual.as_uri()

    def __hash__(self):
        return hash(self.actual)

    def __eq__(self, other):
        if isinstance(other, BundlePath):
            return self.logical == other.logical
        if isinstance(other, (Path, str, os.PathLike)):
            return self.actual == Path(other)
        return False

    def __lt__(self, other):
        return str(self) < str(other)

def asset(logical=''):
    return BundlePath(logical)

def serve_asset(prefix, filename):
    """可选本地界面按原 HTTP 路径读取对应平层文件；拒绝目录穿越。"""
    from flask import abort, send_file
    pure = PurePosixPath(filename)
    if pure.is_absolute() or '..' in pure.parts or '\\' in filename:
        abort(404)
    source = asset(prefix) / filename
    if not source.is_file():
        abort(404)
    return send_file(source.actual)
