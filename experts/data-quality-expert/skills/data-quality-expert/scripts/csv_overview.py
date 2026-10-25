#!/usr/bin/env python3
"""单 CSV 小样本字段概览；不包含全量质量诊断引擎。"""
import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

MAX_BYTES = 1048576
MAX_ROWS = 200
MAX_COLUMNS = 100


class InputError(Exception):
    pass


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(3, "参数错误：请核对 --input、--out 和分隔符；使用 --help 查看用法。\n")


def md(value):
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for c in ("\\", "`", "[", "]", "*", "_", "!", "|"):
        text = text.replace(c, "\\" + c)
    return text.replace("\r", " ").replace("\n", " / ")


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def load(path, delimiter):
    if not path.is_file():
        raise InputError("没有读取到指定 CSV 文件，请核对路径。")
    with path.open("rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise InputError("文件超过免费版 1 MiB（1048576 字节）上限。请提供用户明确选定的小样本，不自动拆分全量文件。")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("仅支持 UTF-8 / UTF-8-BOM CSV，请在保留原件的前提下另存后再试。")
    if "\x00" in text:
        raise InputError("文件含空字节，无法作为 CSV 文本读取。")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header = next(reader, None)
        if not header or len(header) > MAX_COLUMNS:
            raise InputError("请提供有表头的 CSV；支持 1–100 列。")
        rows = []
        for row in reader:
            if not row or len(row) != len(header):
                raise InputError("CSV 记录结构与表头不一致（截至物理行 %d），未生成统计。请检查空记录、分隔符或引号。" % reader.line_num)
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise InputError("文件超过免费版 200 条数据记录上限，未生成截断报告。请明确选取最多 200 条记录的样本，并保留样本来源。")
    except csv.Error:
        raise InputError("CSV 格式无法解析（截至物理行 %d），请修正副本中的引号或字段格式后重试。" % reader.line_num)
    return header, rows, hashlib.sha256(raw).hexdigest(), len(raw)


def main():
    parser = ChineseParser(description="免费查看单份 CSV 的字段、样例与空值初览，限 200 条记录 / 1 MiB；不修改原件。")
    parser.add_argument("--input", required=True, help="用户指定的 UTF-8 CSV")
    parser.add_argument("--out", required=True, help="尚不存在的输出目录，父目录须已存在")
    parser.add_argument("--delimiter", choices=[",", ";", "tab"], default=",", help="分隔符，默认逗号，tab 表示制表符")
    args = parser.parse_args()
    try:
        source, out = Path(args.input), Path(args.out)
        if out.exists() or out.is_symlink():
            raise InputError("输出目录已存在，已拒绝覆盖。请指定新目录。")
        if not out.parent.is_dir():
            raise InputError("输出目录的父目录不存在，请选择已有文件夹中的新目录。")
        header, rows, digest, size = load(source, "\t" if args.delimiter == "tab" else args.delimiter)
        stats = []
        for index, name in enumerate(header):
            values = [row[index] for row in rows]
            missing = sum(not value.strip() for value in values)
            samples = []
            for value in values:
                if value.strip() and value not in samples:
                    samples.append(value)
                if len(samples) == 3:
                    break
            shown = [value if len(value) <= 120 else value[:120] + "…（显示已截短）" for value in samples]
            stats.append([index + 1, name, len(rows), missing, ("%.2f%%" % (100 * missing / len(rows))) if rows else "不适用（无数据记录）", json.dumps(shown, ensure_ascii=False)])
        blanks = sum(item[3] for item in stats)
        lines = ["# CSV 字段与空值初览", "", "- 文件：%s" % md(source.name),
                 "- 本次 CSV：%d 条数据记录，%d 列（表头不计入数据记录数）。" % (len(rows), len(header)),
                 "- 输入大小：%d 字节；原文件 SHA256：`%s`。" % (size, digest),
                 "- 空值单元格：%d 个。仅空字符串或纯空白计为空值；这不等于数据有业务错误。" % blanks,
                 "- 范围：只统计本次选定文件；若它是样本，不能据此推断全量数据。", "", "## 字段概览", "",
                 "| 列序号 | 原始字段名 | 记录数 | 空值数 | 空值比例 | 最多三个非空原值样例 |", "|---|---|---|---|---|---|"]
        for item in stats:
            shown = item[:]
            if not shown[1].strip():
                shown[1] = "（空表头，以列序号区分）"
            lines.append("| " + " | ".join(md(v) for v in shown) + " |")
        lines.extend(["", "## 如何继续", "", "- 先核对字段是否属于本次业务、样例是否便于理解；需要必填口径时，由业务负责人确认。", "- 空表头或同名表头按列序号展示；本工具不修改字段名、不合并列。", "- `NULL`、`N/A`、`NaN` 等文本保留为样例，不自动视为缺失或异常，也不把编号转成数值。", "- 样例仅供理解字段，最长显示 120 个字符；报告不会给出逐条异常行号、质量评分、统计异常结论或跨表一致性结果。", "- `字段概览.csv` 可继续编辑；可能触发表格公式的字段文本加前置单引号显示保护，原件保持只读。", "- 如需完整规则校验、数值异常诊断及问题定位，可自行查看收费技能“数据质量专家”；本免费包不含其完整诊断内核。", ""])
        if not rows:
            lines.extend(["本次只有表头，没有数据记录；空值比例不适用，不能判断数据是否完整。", ""])
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise InputError("读取期间输入发生变化，未生成报告。请使用稳定的样本副本。")
        out.mkdir()
        with (out / "字段概览.csv").open("x", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["列序号", "原始字段名", "数据记录数", "空值数", "空值比例", "非空原值样例"])
            writer.writerows([[csv_cell(v) for v in row] for row in stats])
        (out / "CSV字段与空值初览.md").write_text("\n".join(lines), encoding="utf-8")
        print("已生成中文 Markdown 与字段概览 CSV：%s；%d 条记录、%d 列、%d 个空值单元格。本次未进行质量评分或异常诊断。" % (out, len(rows), len(header), blanks))
        return 0
    except (InputError, OSError) as exc:
        print("处理未完成：%s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
