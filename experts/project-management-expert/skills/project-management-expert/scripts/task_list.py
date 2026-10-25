#!/usr/bin/env python3
"""单份任务清单整理；仅 Python 标准库，不执行依赖排期或容量计算。"""
import argparse
import csv
import hashlib
import io
import re
import sys
from datetime import date
from pathlib import Path

MAX_BYTES = 1048576
MAX_ROWS = 200
MAX_COLUMNS = 100
ALIASES = {
    "task": ("任务", "任务名称", "任务名", "task", "title"),
    "owner": ("责任人", "负责人", "owner", "assignee"),
    "due": ("截止日", "截止日期", "到期日", "due", "due_date", "deadline"),
    "next": ("下一步", "下一步动作", "next", "next_step"),
}
PLACEHOLDERS = {"待定", "待确认", "未指定", "未提供", "未知", "-", "—"}


class InputError(Exception):
    pass


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(3, "参数错误：请核对 --input、--out、分隔符及列名；使用 --help 查看用法。\n")


def md(value):
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for c in ("\\", "`", "[", "]", "*", "_", "!", "|"):
        text = text.replace(c, "\\" + c)
    return text.replace("\r", " ").replace("\n", " / ")


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def write_csv(path, rows):
    with path.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows([[csv_cell(v) for v in row] for row in rows])


def read_input(path, delimiter):
    if not path.is_file():
        raise InputError("没有读取到指定的 CSV 文件，请核对路径。")
    with path.open("rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise InputError("文件超过免费版 1 MiB（1048576 字节）上限。请提供一份范围明确的小型任务清单；不会自动拆分批量处理。")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("文件不是 UTF-8 CSV。请另存 UTF-8 CSV 后再处理，保留原文件。")
    if "\x00" in text:
        raise InputError("CSV 含空字节，无法作为文本清单读取。")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header = next(reader, None)
        if not header or len(header) > MAX_COLUMNS:
            raise InputError("请提供带表头的 CSV，列数须在 1–100 之间。")
        normalized = [v.strip().casefold() for v in header]
        if any(not v for v in normalized) or len(set(normalized)) != len(normalized):
            raise InputError("表头有空名称或重名，无法可靠识别责任人和截止日。请在副本中补全或区分表头。")
        rows = []
        for row in reader:
            if not row:
                raise InputError("CSV 含空记录（物理行 %d），请在副本中明确该行是否为任务。" % reader.line_num)
            if len(row) != len(header):
                raise InputError("CSV 记录列数与表头不一致（截至物理行 %d），请检查分隔符或引号。" % reader.line_num)
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise InputError("任务超过免费版 200 条上限，未生成部分结果。请指定本次要整理的一份小型清单。")
    except csv.Error:
        raise InputError("CSV 引号或字段格式无法解析（截至物理行 %d），请修正副本后重试。" % reader.line_num)
    return header, rows, hashlib.sha256(raw).hexdigest(), len(raw)


def select_column(header, key, explicit):
    if explicit:
        matches = [i for i, name in enumerate(header) if name == explicit]
    else:
        matches = [i for i, name in enumerate(header) if name.strip().casefold() in ALIASES[key]]
    if len(matches) > 1:
        raise InputError("有多个可作为%s的列，请用 --%s-column 指定准确表头。" % ({"task": "任务名称", "owner": "责任人", "due": "截止日", "next": "下一步"}[key], key))
    if explicit and not matches:
        raise InputError("没有找到指定列“%s”，请按原表头填写。" % explicit)
    if not matches and key == "task":
        raise InputError("未识别到任务名称列；可使用“任务”表头，或用 --task-column 指定。")
    return matches[0] if matches else None


def is_pending(value):
    return not value.strip() or value.strip() in PLACEHOLDERS


def inspect_rows(header, rows, indexes):
    result = []
    for number, row in enumerate(rows, 1):
        values = {key: row[i] if i is not None else "" for key, i in indexes.items()}
        task, owner, due = (values[k] for k in ("task", "owner", "due"))
        issues, actions = [], []
        if is_pending(task):
            issues.append("任务名称未明确")
            actions.append("补充这项任务要完成的具体工作")
        if is_pending(owner):
            issues.append("责任人待确认")
            actions.append("确认一位责任人并写回清单副本")
        if is_pending(due):
            issues.append("截止日待确认")
            actions.append("与责任人确认截止日，按 YYYY-MM-DD 填写")
        else:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due.strip()):
                    raise ValueError()
                date.fromisoformat(due.strip())
            except ValueError:
                issues.append("截止日格式或日期无效")
                actions.append("核对截止日原意并改为有效的 YYYY-MM-DD 日期，不推定月日顺序")
        if not is_pending(values["next"]):
            actions.append("原清单下一步：" + values["next"])
        elif not issues:
            actions.append("请责任人确认具体执行动作与完成标准，再按清单推进")
        result.append({"number": number, "row": row, "task": task, "issues": issues, "next": "；".join(actions)})
    return result


def main():
    parser = ChineseParser(description="免费整理单份任务清单，生成中文 Markdown 和 CSV；不改原件、不计算排期。")
    parser.add_argument("--input", required=True, help="用户指定的 UTF-8 CSV")
    parser.add_argument("--out", required=True, help="尚不存在的输出目录；父目录须已存在")
    parser.add_argument("--delimiter", choices=[",", ";", "tab"], default=",", help="分隔符，默认逗号，tab 表示制表符")
    for key in ALIASES:
        parser.add_argument("--" + key + "-column", help="可选：准确指定原始表头")
    args = parser.parse_args()
    try:
        source, out = Path(args.input), Path(args.out)
        if out.exists() or out.is_symlink():
            raise InputError("输出目录已存在，已拒绝覆盖。请换一个新目录。")
        if not out.parent.is_dir():
            raise InputError("输出目录的父目录不存在，请选择已有文件夹中的新目录。")
        header, rows, digest, size = read_input(source, "\t" if args.delimiter == "tab" else args.delimiter)
        indexes = {key: select_column(header, key, getattr(args, key + "_column")) for key in ALIASES}
        result = inspect_rows(header, rows, indexes)
        pending = sum(bool(item["issues"]) for item in result)
        missing_columns = [label for key, label in (("owner", "责任人"), ("due", "截止日")) if indexes[key] is None]
        lines = ["# 任务清单整理报告", "", "- 文件：%s" % md(source.name),
                 "- 本次任务：%d 条；其中 %d 条有待补信息或日期格式问题。" % (len(rows), pending),
                 "- 输入大小：%d 字节；原文件 SHA256：`%s`。" % (size, digest),
                 "- 本次只检查任务名称、责任人和截止日的明确性及日期格式；不推算工期、依赖、关键路径、人员冲突或延期。", ""]
        if missing_columns:
            lines.extend(["原清单本次未提供这些列：%s。相关任务列为待确认，不虚构人员或日期。" % "、".join(missing_columns), ""])
        lines.extend(["## 可执行下一步", "", "| 清单序号 | 任务 | 待补事项 | 下一步 |", "|---|---|---|---|"])
        for item in result:
            lines.append("| %d | %s | %s | %s |" % (item["number"], md(item["task"] or "（未填写）"), md("；".join(item["issues"]) or "本次字段检查未发现缺项"), md(item["next"])))
        if not result:
            lines.append("| — | 本次清单没有任务记录 | 不作完成性判断 | 请提供要梳理的任务 |")
        lines.extend(["", "## 文件与使用说明", "", "- `任务清单.csv` 保留原列与原值，追加待补事项和下一步。`下一步清单.csv` 便于分派确认。", "- CSV 中可能被表格软件当作公式的文本加前置单引号作为显示保护；原文件未改动。", "- 本次字段齐全不代表任务已经执行、计划可行或项目不会延期。日期只做格式校验，不判断是否逾期。", "- 需要依赖排期、关键路径或容量分析，可自行查看收费技能“项目管理专家”；本包不含该收费引擎。", ""])
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise InputError("输入文件在读取期间发生变化，未生成结果。请使用稳定的文件副本。")
        out.mkdir()
        extra = []
        for name in ["整理_待补事项", "整理_下一步"]:
            while name in header or name in extra:
                name += "_新"
            extra.append(name)
        write_csv(out / "任务清单.csv", [header + extra] + [item["row"] + ["；".join(item["issues"]), item["next"]] for item in result])
        write_csv(out / "下一步清单.csv", [["清单序号", "任务", "待补事项", "下一步"]] + [[item["number"], item["task"], "；".join(item["issues"]), item["next"]] for item in result])
        (out / "任务清单整理报告.md").write_text("\n".join(lines), encoding="utf-8")
        print("已生成中文报告与两份 CSV：%s；共 %d 条任务、%d 条待补记录。原文件保持只读。" % (out, len(rows), pending))
        return 2 if pending or missing_columns else 0
    except (InputError, OSError) as exc:
        print("处理未完成：%s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
