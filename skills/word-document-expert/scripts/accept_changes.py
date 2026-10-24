"""Accept tracked changes through LibreOffice and verify the resulting DOCX."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from office_soffice import run_soffice, find_soffice

ACCEPT_CHANGES_MACRO = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub AcceptAllTrackedChanges()
 Dim document As Object
 Dim dispatcher As Object
 document = ThisComponent.CurrentController.Frame
 dispatcher = createUnoService("com.sun.star.frame.DispatchHelper")
 dispatcher.executeDispatch(document, ".uno:AcceptAllTrackedChanges", "", 0, Array())
 ThisComponent.store()
 ThisComponent.close(True)
End Sub
</script:module>'''
WORD_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
TRACKED = {WORD_NS + x for x in ('ins', 'del', 'moveFrom', 'moveTo', 'rPrChange', 'pPrChange', 'sectPrChange', 'tblPrChange', 'trPrChange', 'tcPrChange', 'tblGridChange', 'cellIns', 'cellDel', 'cellMerge', 'numberingChange')}

def _verify_clean(path):
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() or 'word/document.xml' not in zf.namelist():
            raise ValueError('输出不是完整的 DOCX 文件。')
        for name in zf.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                root = ET.fromstring(zf.read(name))
                if any(e.tag in TRACKED for e in root.iter()):
                    raise ValueError(f'输出仍含修订标记：{name}。未声明接受完成。')

def accept_changes(input_file, output_file, timeout=60):
    source, destination = Path(input_file), Path(output_file)
    if not source.is_file() or source.suffix.lower() != '.docx':
        return None, '错误：请提供存在的 DOCX 文件。'
    if destination.exists() or source.resolve() == destination.resolve():
        return None, '错误：为保护原件和既有结果，请选择尚不存在的新输出文件。'
    if destination.suffix.lower() != '.docx' or not destination.parent.is_dir():
        return None, '错误：输出应为 DOCX，且父目录必须已经存在。'
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        executable = find_soffice()
        with tempfile.TemporaryDirectory(prefix='word_accept_', dir=destination.parent) as temp:
            work = Path(temp)
            profile = work / 'profile'
            profile.mkdir()
            profile_arg = f'-env:UserInstallation={profile.as_uri()}'
            init = run_soffice([profile_arg, '--headless', '--terminate_after_init'], executable=executable, capture_output=True, text=True, timeout=min(timeout, 20))
            if init.returncode:
                raise RuntimeError('LibreOffice 用户配置初始化失败。')
            macros = profile / 'user/basic/Standard'
            macros.mkdir(parents=True, exist_ok=True)
            (macros / 'Module1.xba').write_text(ACCEPT_CHANGES_MACRO, encoding='utf-8')
            staged = work / 'accepted.docx'
            shutil.copy2(source, staged)
            command = [profile_arg, '--headless', '--norestore', 'vnd.sun.star.script:Standard.Module1.AcceptAllTrackedChanges?language=Basic&location=application', str(staged)]
            run = run_soffice(command, executable=executable, capture_output=True, text=True, timeout=timeout)
            if run.returncode:
                raise RuntimeError('LibreOffice 未成功完成接受修订。')
            _verify_clean(staged)
            if hashlib.sha256(source.read_bytes()).hexdigest() != original_hash:
                raise RuntimeError('输入文件在操作期间发生变化，未交付结果。')
            with destination.open('xb') as out:
                out.write(staged.read_bytes())
        return None, f'已接受修订并校验输出：{destination}。请继续核对正文、段落边界和版式。'
    except subprocess.TimeoutExpired:
        return None, '错误：接受修订执行超时，未交付输出，也未宣称完成。'
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ET.ParseError, DefusedXmlException) as exc:
        return None, f'错误：{exc}'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='接受 DOCX 修订，保留原件并生成经过检查的新文件。')
    parser.add_argument('input_file', help='原 DOCX')
    parser.add_argument('output_file', help='尚不存在的新 DOCX')
    _, message = accept_changes(**vars(parser.parse_args()))
    print(message)
    raise SystemExit(3 if message.startswith('错误：') else 0)
