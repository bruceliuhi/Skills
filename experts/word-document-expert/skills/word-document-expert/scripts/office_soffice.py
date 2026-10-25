"""LibreOffice execution with an isolated profile; never alter process sandboxing."""
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

def find_soffice():
    for name in ('soffice', 'libreoffice'):
        executable = shutil.which(name)
        if executable:
            return executable
    app = Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    if app.is_file():
        return str(app)
    raise FileNotFoundError('当前环境没有 LibreOffice，不能执行转换、渲染或接受修订。')

def get_soffice_env():
    env = os.environ.copy()
    env['SAL_USE_VCLPLUGIN'] = 'svp'
    return env

def run_soffice(args, **kwargs):
    args = list(args)
    executable = kwargs.pop('executable', None) or find_soffice()
    with contextlib.ExitStack() as stack:
        if not any(str(a).startswith('-env:UserInstallation') for a in args):
            profile = stack.enter_context(tempfile.TemporaryDirectory(prefix='word_profile_'))
            args = [f'-env:UserInstallation={Path(profile).as_uri()}'] + args
        kwargs.setdefault('env', get_soffice_env())
        return subprocess.run([executable] + args, **kwargs)

if __name__ == '__main__':
    import sys
    try:
        result = run_soffice(sys.argv[1:])
        sys.exit(result.returncode)
    except OSError as exc:
        print(f'执行失败：{exc}', file=sys.stderr)
        sys.exit(3)
