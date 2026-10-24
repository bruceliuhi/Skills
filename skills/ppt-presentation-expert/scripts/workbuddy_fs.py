"""兼容受保护文件代理；只使用正常文件 API，不改变权限或保护配置。"""
from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
import os
import uuid
from pathlib import Path

PROTECTION_VARIABLES = ("CODEBUDDY_SAFE_DELETE_SANDBOX", "CODEBUDDY_BROKERED_FS_HOOK_ENABLED")

def assert_protection(environ=None):
    values = os.environ if environ is None else environ
    for key in PROTECTION_VARIABLES:
        if key in values and str(values[key]).strip().lower() not in {"1", "true", "yes", "on", "enabled"}:
            raise RuntimeError("安全保护设置不符合要求，已停止执行：" + key + "。请保持平台默认保护，不修改或删除保护变量来继续运行。")

def ensure_directory(path, mode=0o777, parents=False, exist_ok=True):
    """不对已有目录重复 mkdir；权限错误不吞掉，不改用其它写入位置。"""
    path = Path(path)
    if path.is_dir():
        if exist_ok:
            return
        raise FileExistsError("输出目录已存在：" + str(path))
    if path.exists() or path.is_symlink():
        raise FileExistsError("目录路径被文件或链接占用：" + str(path))
    if parents:
        ensure_directory(path.parent, parents=True)
    path.mkdir(mode=mode)

class RetainedWorkDirectory:
    """全新工作目录；不自动删除，失败产物供检查和人工清理。"""
    def __init__(self, prefix=".ppt-work-", dir=None):
        assert_protection()
        if dir is None:
            raise ValueError("必须明确指定项目内的工作目录。")
        parent = Path(dir)
        ensure_directory(parent, parents=True)
        self.name = str(parent / (prefix + uuid.uuid4().hex))
        Path(self.name).mkdir(mode=0o700)
    def __enter__(self):
        return self.name
    def __exit__(self, *args):
        return False
    def cleanup(self):
        # Deliberately retain this newly created workspace; never relax delete protection.
        return None
