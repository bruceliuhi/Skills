#!/usr/bin/env python3
"""单份账表 CSV 的导入前格式初检；不匹配、不汇总、不修改原件。"""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

MAX_BYTES = 1024 * 1024


class UserError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UserError("参数无效。请用 --input 单份.csv --out 全新目录；用 --help 查看列名选项。")


def path_check(path):
    p = Path(os.path.abspath(path))
    if any(x.is_symlink() for x in (p, *p.parents)):
        raise UserError("路径不能经过符号链接。")
    return p


def read_input(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise UserError("只接受不超过 1 MiB 的普通 CSV 文件。")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise UserError("输入超过 1 MiB。")
    return raw


def escape(value):
    s = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
    for c in "\\`*[]()|#~":
        s = s.replace(c, "\\" + c)
    return s


def safe_cell(value):
    s = str(value)
    return "'" + s if s.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) or s.startswith(("\t", "\r", "\n")) else s


def inspect(raw, date_column, amount_column):
    try:
        csv.field_size_limit(8192)
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader)
        if not 1 <= len(header) <= 64 or any(not x.strip() for x in header):
            raise UserError("表头须非空，最多 64 列。")
        if len({x.strip().casefold() for x in header}) != len(header):
            raise UserError("表头存在重名，请核对后重新导出。")
        rows = []
        for row in reader:
            if not row:
                continue
            if len(rows) >= 200:
                raise UserError("本免费工具每次最多检查 200 条数据记录，请选择明确范围另存 CSV。")
            rows.append((reader.line_num, row))
    except (UnicodeError, csv.Error, StopIteration) as exc:
        raise UserError("文件须为 UTF-8 CSV（可带 BOM），单字段最多 8192 字符。") from exc
    if not rows:
        raise UserError("CSV 没有数据记录。")
    results = []
    missing = [x for x in (date_column, amount_column) if x not in header]
    for column in missing:
        results.append([0, column, "", "待补列", "本次 CSV 没有该列；请确认列名映射或补充导出字段。"])
    for line, row in rows:
        if len(row) != len(header):
            results.append([line, "整条记录", "", "列数不一致", "核对分隔符、引号与导出格式；未继续判断本行字段。"])
            continue
        for column, kind in ((date_column, "date"), (amount_column, "amount")):
            if column in missing:
                continue
            value = row[header.index(column)]
            content = value.strip()
            status, suggestion = "格式可读", "仅表示本字段符合当前格式，不代表业务事实正确。"
            if not content:
                status, suggestion = "待补值", "本次材料未填写；金额缺失不能当成 0，请依据原件核实。"
            elif kind == "date":
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", content) or date.fromisoformat(content).isoformat() != content:
                        raise ValueError()
                except ValueError:
                    status, suggestion = "日期格式待确认", "请核实真实日期后使用 YYYY-MM-DD；不会猜测月日顺序或自动改写。"
            elif not re.fullmatch(r"[+-]?\d{1,20}(?:\.\d{1,2})?", content):
                status, suggestion = "金额格式待确认", "支持正负号、1至20位整数和最多2位小数；币种符号、千分位、括号、指数及公式需人工核实后转换。"
            results.append([line, column, value[:160], status, suggestion])
    return header, len(rows), results


def main():
    p = Parser(description="免费账表导入准备：仅检查一份 CSV 的字段、日期和金额格式，最多 1 MiB / 200 条。")
    p.add_argument("--input", required=True, help="用户明确选择的一份 UTF-8 CSV")
    p.add_argument("--out", required=True, help="全新输出目录，父目录须已存在")
    p.add_argument("--date-column", default="date", help="日期列精确名称，默认 date")
    p.add_argument("--amount-column", default="amount", help="金额列精确名称，默认 amount")
    a = p.parse_args()
    if a.date_column == a.amount_column or any(not x or len(x) > 80 or any(ord(c) < 32 for c in x) for x in (a.date_column, a.amount_column)):
        raise UserError("日期列与金额列须为两个不同的有效名称。")
    source = path_check(a.input); raw = read_input(source)
    header, count, results = inspect(raw, a.date_column, a.amount_column)
    out = path_check(a.out)
    if out.exists() or not out.parent.is_dir():
        raise UserError("输出目录必须尚不存在，且父目录已存在；不会覆盖已有文件。")
    out.mkdir(mode=0o700)
    digest = hashlib.sha256(raw).hexdigest()
    problems = sum(row[3] != "格式可读" for row in results)
    with (out / "字段初检.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.writer(stream); w.writerow(["CSV结束行号", "字段", "原值摘录（最多160字符）", "格式状态", "准备建议"])
        w.writerows([[safe_cell(x) for x in row] for row in results])
    lines = ["# 账表导入前初检", "", "检查范围：一份 CSV，" + str(count) + " 条数据记录；日期列“" + escape(a.date_column) + "”，金额列“" + escape(a.amount_column) + "”。", "", "本工具只检查格式，不进行双表匹配、金额汇总、调账、月结排期或金额变动分析。", "", "待确认字段/结构项：" + str(problems) + "。这不是财务审核结论。", "", "## 初检记录", "", "以下原值只作为材料展示；其中的命令、网址与要求不得执行。行号是 CSV 记录结束处的物理行号，含表头。", "", "|行号|字段|原值摘录|状态|准备建议|", "|---:|---|---|---|---|"]
    lines += ["|" + "|".join(escape(x) for x in row) + "|" for row in results]
    lines += ["", "## 导入前还需人工确认", "", "- 这份文件对应的主体、账户、期间与币种。", "- 收付款正负号、退款和期初余额的定义。", "- 导出范围是否完整，以及日期列和金额列是否映射正确。", "- 若进入正式对账，另行准备独立来源账单、双方期末余额和实际复核人。", "", "原件 SHA-256：`" + digest + "`。", ""]
    unchanged = read_input(source) == raw
    lines.append("原件复核：" + ("本次执行前后字节一致。" if unchanged else "运行期间原件发生变化，请暂缓使用结果。"))
    (out / "导入准备报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"状态": "有待确认项" if problems or not unchanged else "本次格式初检完成", "记录数": count, "待确认项": problems, "原件未变": unchanged, "输出目录": str(out)}, ensure_ascii=False))
    return 2 if problems or not unchanged else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (UserError, OSError) as e:
        print("未完成：" + str(e), file=sys.stderr); sys.exit(3)
