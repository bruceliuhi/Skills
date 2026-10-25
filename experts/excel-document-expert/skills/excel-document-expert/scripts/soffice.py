"""使用当前环境已有的 LibreOffice；不安装软件，不绕过运行环境限制。"""
import contextlib
import os
import socket
import subprocess
import tempfile
from pathlib import Path


def get_soffice_env():
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.close()
    except OSError as error:
        raise RuntimeError("当前环境不允许 LibreOffice 所需的本地通信；已停止运行，请使用已提供的原生表格工具。") from error
    return env


def run_soffice(args, **kwargs):
    args = list(args)
    with contextlib.ExitStack() as stack:
        if not any(str(arg).startswith("-env:UserInstallation") for arg in args):
            profile = stack.enter_context(tempfile.TemporaryDirectory(prefix="excel-lo-profile-"))
            args = [f"-env:UserInstallation={Path(profile).as_uri()}"] + args
        return subprocess.run(["soffice"] + args, env=get_soffice_env(), **kwargs)


if __name__ == "__main__":
    import sys
    result = run_soffice(sys.argv[1:])
    sys.exit(result.returncode)
