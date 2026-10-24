#!/usr/bin/env python3
"""WorkBuddy 中文运行与交付入口；调用包内现有核心，不替换其校验。"""
from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()

from workbuddy_fs import ensure_directory, RetainedWorkDirectory, assert_protection

import argparse
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}


class UserError(Exception):
    pass


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise UserError("参数不完整或不符合要求；请运行 --help 查看用法。技术原因：" + message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def existing_file(value):
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise UserError("未找到可读取的文件：" + str(path))
    return path


def new_path(value):
    path = Path(value).expanduser().resolve()
    if path.exists():
        raise UserError("输出路径已存在，为保留原件请换一个新路径：" + str(path))
    return path


def module_status(name):
    try:
        module = importlib.import_module(name)
        return {"available": True, "version": getattr(module, "__version__", None)}
    except (ImportError, OSError, RuntimeError) as exc:
        return {"available": False, "reason": str(exc)}


def doctor():
    required = {name: module_status(name) for name in ("pptx", "xlsxwriter", "PIL", "lxml.etree")}
    optional = {name: module_status(name) for name in ("yaml", "pathops", "uharfbuzz", "flask", "playwright.sync_api")}
    chromium = None
    if optional["playwright.sync_api"]["available"]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as runtime:
                chromium = Path(runtime.chromium.executable_path).is_file()
        except Exception:
            chromium = False
    core = sys.version_info >= (3, 9) and all(x["available"] for x in required.values())
    return {"status": "可运行核心流程" if core else "核心依赖不完整",
            "python": sys.executable, "python_version": sys.version.split()[0],
            "core_available": core, "required_modules": required, "optional_modules": optional,
            "chromium_file_present": chromium,
            "external_commands": {x: shutil.which(x) for x in ("soffice", "pdftoppm", "ffmpeg")},
            "note": "仅核对当前环境，不安装软件；模块存在不等于已经导出、渲染或完成平台验收。"}


def inspect_pptx(value):
    path = existing_file(value)
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise UserError("文件内有损坏的压缩条目：" + bad)
            names = archive.namelist()
            slides = sorted(x for x in names if x.startswith("ppt/slides/slide") and x.endswith(".xml") and "/_rels/" not in x)
            charts = sorted(x for x in names if x.startswith("ppt/charts/chart") and x.endswith(".xml"))
            notes = sorted(x for x in names if x.startswith("ppt/notesSlides/notesSlide") and x.endswith(".xml") and "/_rels/" not in x)
            if not slides:
                raise UserError("文件中没有找到演示页面，不能当作有效 PPTX 交付。")
            parsed = {x: ET.fromstring(archive.read(x)) for x in slides + charts + notes}
            return {"status": "结构读取完成", "file": str(path), "sha256": sha(path),
                    "slides": len(slides), "charts": len(charts), "notes": len(notes),
                    "tables": sum(len(parsed[x].findall(".//a:tbl", NS)) for x in slides),
                    "text_runs": sum(len(parsed[x].findall(".//a:t", NS)) for x in slides),
                    "embedded_workbooks": [x for x in names if x.startswith("ppt/embeddings/") and x.endswith(".xlsx")],
                    "chart_values": {x: [v.text for v in parsed[x].findall(".//c:numCache/c:pt/c:v", NS)] for x in charts},
                    "slide_xml_sha256": {x: hashlib.sha256(archive.read(x)).hexdigest() for x in slides},
                    "note": "结构可读取不等于页面视觉已检查，也不代表已在 PowerPoint/WPS 打开。"}
    except zipfile.BadZipFile as exc:
        raise UserError("文件不是有效的 PPTX 压缩包或已经损坏。") from exc
    except ET.ParseError as exc:
        raise UserError("演示文件内部 XML 无法解析，请重新提供完整文件。") from exc


def run_core(script, args, workspace, protected=()):
    before = {str(p): sha(p) for p in protected}
    command = [sys.executable, "-B", str(SCRIPTS / script), *map(str, args)]
    proc = subprocess.run(command, capture_output=True, text=True)
    after = {str(p): sha(p) for p in protected}
    logdir = workspace / "validation"
    ensure_directory(logdir, parents=True, exist_ok=True)
    log = logdir / ("workbuddy-" + str(time.time_ns()) + ".json")
    record = {"command": command, "exit_code": proc.returncode, "stdout": proc.stdout,
              "stderr": proc.stderr, "protected_before": before, "protected_after": after}
    log.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if before != after:
        raise UserError("原件保护检查失败，输入文件发生变化。请停止交付并检查：" + str(log))
    if proc.returncode:
        combined = proc.stdout + "\n" + proc.stderr
        hints = []
        for needle, advice in [
            ("ModuleNotFoundError", "当前 Python 缺少所需模块，请选择平台已有依赖的解释器。"),
            ("integrity check failed", "完整性检查未通过，请恢复完整安装，不修改检查程序。"),
            ("quality", "页面质量检查未通过，请先修复被指出的页、对象或布局。"),
            ("not projected", "可视预览与原生图表/表格数据定义不一致，请同步缺失细节。"),
            ("unknown source refs", "修改页引用了不属于该页的原生对象，请按源页归属修复。"),
            ("source-proxy", "此原生对象不能安全重建，请保留原对象或说明具体限制。"),
            ("No such file", "所需文件不存在或路径不正确，请核对输入与资源范围。")]:
            if needle.lower() in combined.lower():
                hints.append(advice)
        return {"status": "未完成", "exit_code": proc.returncode,
                "reasons": hints or ["核心工具拒绝了本次操作，请按技术记录中的具体文件、页或对象定位原因。"],
                "diagnostic_file": str(log), "input_preserved": before == after}
    return {"status": "执行完成", "exit_code": 0, "diagnostic_file": str(log),
            "input_preserved": before == after,
            "note": "仅表示本条命令完成；最终交付仍需核对结构、数据和逐页预览。"}


def render_svgs(project, mode, output):
    source = project / ("authoring-svg-flat" if mode == "roundtrip" else "svg_output")
    pages = sorted(source.glob("*.svg"))
    if not pages:
        raise UserError("没有可预览的 SVG 页面，请先生成或导入演示。")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise UserError("当前 Python 没有可用的 Playwright；页面预览尚未完成，不会自动安装。") from exc
    for path in pages:
        root = ET.parse(path).getroot()
        for elem in root.iter():
            if elem.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "iframe"} or any(k.lower().startswith("on") for k in elem.attrib):
                raise UserError("页面包含不支持的脚本或交互内容，未执行预览：" + path.name)
            if elem.get("data-icon"):
                raise UserError("页面仍含未内嵌图标，请按源流程准备预览副本后再检查：" + path.name)
            href = elem.get("href") or elem.get("{http://www.w3.org/1999/xlink}href") or ""
            if href and not href.startswith(("#", "data:")):
                target = (path.parent / unquote(href)).resolve()
                if "://" in href or not target.is_relative_to(project) or not target.is_file():
                    raise UserError("预览资源未在项目内准备好：" + path.name + " / " + href)
    before = {str(p): sha(p) for p in pages}
    output.mkdir(parents=True, exist_ok=False)
    results = []
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True, chromium_sandbox=True)
            page = browser.new_page(java_script_enabled=False)
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            for path in pages:
                root = ET.parse(path).getroot()
                box = [float(x) for x in root.get("viewBox", "").replace(",", " ").split()]
                if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                    raise UserError("页面画布尺寸无效：" + path.name)
                page.set_viewport_size({"width": round(box[2]), "height": round(box[3])})
                page.goto(path.as_uri(), wait_until="load")
                page.evaluate("document.fonts.ready")
                dest = output / (path.stem + ".png")
                page.screenshot(path=str(dest), full_page=True)
                results.append({"source": str(path), "png": str(dest)})
            browser.close()
    except UserError:
        raise
    except Exception as exc:
        diagnostic = output / "预览诊断.txt"
        diagnostic.write_text(str(exc), encoding="utf-8")
        hint = "浏览器启动被当前运行环境拒绝。" if "Permission denied" in str(exc) else "浏览器或页面资源未能正常加载。"
        raise UserError("本地页面预览未完成：" + hint + "未安装软件或修改安全设置。技术记录：" + str(diagnostic)) from exc
    if before != {str(p): sha(p) for p in pages}:
        raise UserError("预览后输入校验不一致，请停止交付。")
    return {"status": "SVG 逐页预览已生成", "pages": results, "input_preserved": True,
            "note": "还需逐页查看图片。SVG 预览不是导出 PPTX 在 Office 中的最终渲染。"}



def print_report(result):
    print("# PPT制作与美化专家 · 执行结果")
    print("状态：" + result.get("status", "已读取"))
    if "python" in result:
        print("运行环境：Python " + result["python_version"])
        print("解释器：" + result["python"])
        print("核心组件：")
        for name, info in result["required_modules"].items():
            print("- " + name + "：" + ("可用" if info["available"] else "缺失"))
        print("条件组件：")
        meanings = {"yaml": "模板注册", "pathops": "布尔图形", "uharfbuzz": "文字轮廓", "flask": "交互预览服务", "playwright.sync_api": "离线页面预览"}
        for name, info in result["optional_modules"].items():
            print("- " + meanings.get(name, name) + "：" + ("组件存在，仍需实际执行" if info["available"] else "组件缺失"))
    artifact = result.get("artifact", result)
    if "slides" in artifact:
        print("文件：" + artifact["file"])
        print("页数：" + str(artifact["slides"]))
        print("原生图表：" + str(artifact["charts"]) + "；原生表格：" + str(artifact["tables"]))
        print("讲稿页数：" + str(artifact["notes"]) + "；嵌入工作簿：" + str(len(artifact["embedded_workbooks"])))
        print("文件校验值：" + artifact["sha256"])
    for reason in result.get("reasons", []): print("原因与建议：" + reason)
    for item in result.get("pages", []): print("页面预览：" + item["png"])
    if "input_preserved" in result:
        print("本条命令指定的输入保护：" + ("一致" if result["input_preserved"] else "未通过"))
    if result.get("diagnostic_file"): print("技术记录：" + result["diagnostic_file"])
    if result.get("note"): print("说明：" + result["note"])
    if artifact is not result and artifact.get("note"): print("文件检查边界：" + artifact["note"])


def main():
    assert_protection()
    parser = ChineseParser(description="PPT制作与美化专家：环境检查、结构读取、核心执行与离线页面预览")
    parser.add_argument("--json", action="store_true", help="输出兼容结构化数据；默认是中文报告")
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("doctor", help="只读检查当前运行环境")
    p = subs.add_parser("inspect", help="读取实际PPTX结构"); p.add_argument("file")
    p = subs.add_parser("import", help="导入原件到全新修改工作区"); p.add_argument("file"); p.add_argument("--workspace", required=True)
    for action in ("check", "export", "render"):
        p = subs.add_parser(action, help={"check": "运行页面质量检查", "export": "导出新的可编辑PPTX", "render": "用现有浏览器离线预览SVG"}[action])
        p.add_argument("project"); p.add_argument("--mode", choices=("quick", "default", "roundtrip"), default="quick")
        if action in ("export", "render"): p.add_argument("--output", required=True)
        if action == "export":
            p.add_argument("--notes", action="store_true", help="快速生成时加入逐页讲稿")
            p.add_argument("--native-data", action="store_true", help="启用已经同步并校验的原生图表/表格")
    args = parser.parse_args()
    from package_integrity import require_skill_integrity
    require_skill_integrity()
    if args.action == "doctor": result = doctor()
    elif args.action == "inspect": result = inspect_pptx(args.file)
    elif args.action == "import":
        source = existing_file(args.file); workspace = new_path(args.workspace)
        result = run_core("pptx_to_svg.py", [source, "-o", workspace, "--inheritance-mode", "both", "--roundtrip"], workspace, (source,))
    else:
        workspace = Path(args.project).expanduser().resolve()
        if not workspace.is_dir(): raise UserError("未找到项目目录：" + str(workspace))
        if args.action == "render": result = render_svgs(workspace, args.mode, new_path(args.output))
        else:
            flags = ["--quick-generate"] if args.mode == "quick" else (["--roundtrip"] if args.mode == "roundtrip" else [])
            if args.action == "check":
                if args.mode != "roundtrip": flags += ["--canonical-authoring", "--stage", "final", "--json"]
                result = run_core("svg_quality_checker.py", [workspace, *flags], workspace)
            else:
                output = new_path(args.output)
                if output.suffix.lower() != ".pptx": raise UserError("输出文件扩展名必须是 .pptx。")
                ensure_directory(output.parent, parents=True, exist_ok=True)
                if args.notes: flags.append("--with-notes")
                if args.native_data: flags.append("--native-charts-and-tables")
                protected = [workspace / "sources/source.pptx"] if args.mode == "roundtrip" else []
                result = run_core("svg_to_pptx.py", [workspace, *flags, "-o", output], workspace, protected)
                if result["exit_code"] == 0: result["artifact"] = inspect_pptx(output)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)
    return result.get("exit_code", 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UserError, OSError, ValueError, RuntimeError, ET.ParseError) as exc:
        print("无法完成：" + str(exc), file=sys.stderr)
        raise SystemExit(2)
