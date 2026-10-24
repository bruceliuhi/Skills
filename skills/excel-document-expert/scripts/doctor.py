"""标准库只读检查：发行包完整性、指定 XLSX 内容；不安装、不改文件。"""
import argparse
import hashlib
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path

M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS = {'m': M}
PACKAGE = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_check():
    manifest = PACKAGE / 'package-manifest.json'
    if not manifest.is_file():
        return {'status': 'FAIL', 'message_zh': '发行包缺少完整性清单。', 'issues': ['package-manifest.json']}
    expected = json.loads(manifest.read_text(encoding='utf-8'))['files']
    issues = []
    for name, expected_hash in expected.items():
        path = (PACKAGE / name).resolve()
        if PACKAGE not in path.parents or not path.is_file():
            issues.append({'file': name, 'issue_zh': '文件缺失或路径不在技能包内'})
        elif digest(path) != expected_hash:
            issues.append({'file': name, 'issue_zh': '内容摘要与发行清单不符'})
    return {'status': 'PASS' if not issues else 'FAIL', 'message_zh': '完整性检查通过' if not issues else '发行包不完整或文件被改动',
            'verified_files': len(expected), 'issues': issues,
            'boundary_zh': '完整性通过不等于原生计算或付费云端已经可用。'}


def workbook_check(path):
    before = digest(path)
    issues, warnings, formulas = [], [], []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip():
            raise ValueError('压缩包有重复成员或校验失败')
        for required in ['[Content_Types].xml', 'xl/workbook.xml', 'xl/styles.xml']:
            if required not in names:
                raise ValueError('缺少必要成员：' + required)
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        sheets = [{'name': s.get('name'), 'state': s.get('state', 'visible')} for s in book.findall('m:sheets/m:sheet', NS)]
        shared_count = len(ET.fromstring(archive.read('xl/sharedStrings.xml'))) if 'xl/sharedStrings.xml' in names else 0
        count_text_ids = 0
        for member in names:
            if not (member.startswith('xl/worksheets/') and member.endswith('.xml') and '/_rels/' not in member):
                continue
            root = ET.fromstring(archive.read(member))
            coordinates = set()
            for cell in root.findall('m:sheetData/m:row/m:c', NS):
                coordinate, kind = cell.get('r'), cell.get('t', 'n')
                if not coordinate or coordinate in coordinates:
                    issues.append({'part': member, 'cell': coordinate, 'issue_zh': '坐标缺失或重复'})
                coordinates.add(coordinate)
                f, v = cell.find('m:f', NS), cell.find('m:v', NS)
                if f is None:
                    if kind in {'s', 'inlineStr'}:
                        count_text_ids += 1
                    continue
                item = {'part': member, 'cell': coordinate, 'formula': f.text, 'type': kind, 'cached_value': None if v is None else (v.text or '')}
                formulas.append(item)
                if f.get('t', 'normal') != 'normal' or 'ref' in f.attrib or cell.get('cm'):
                    warnings.append({'part': member, 'cell': coordinate, 'issue_zh': '共享/数组/数据表或动态公式需单独验收完整结果范围'})
                if v is None or (not v.text and kind not in {'str'}):
                    issues.append({'part': member, 'cell': coordinate, 'issue_zh': '公式缓存缺失，不能判定已经计算'})
                elif kind == 'e':
                    issues.append({'part': member, 'cell': coordinate, 'issue_zh': '公式返回错误', 'error_value': v.text})
                elif kind == 'n':
                    try:
                        if not Decimal(v.text).is_finite():
                            raise ValueError()
                    except (InvalidOperation, ValueError, TypeError):
                        issues.append({'part': member, 'cell': coordinate, 'issue_zh': '公式数值缓存无效或非有限数'})
                elif kind == 'b' and v.text not in {'0', '1'}:
                    issues.append({'part': member, 'cell': coordinate, 'issue_zh': '公式布尔缓存无效'})
                elif kind == 's':
                    try:
                        if not (0 <= int(v.text) < shared_count):
                            raise ValueError()
                    except (TypeError, ValueError):
                        issues.append({'part': member, 'cell': coordinate, 'issue_zh': '共享字符串缓存索引无效'})
                elif kind == 'd':
                    try:
                        datetime.fromisoformat(v.text.replace('Z', '+00:00'))
                    except (AttributeError, ValueError):
                        issues.append({'part': member, 'cell': coordinate, 'issue_zh': '公式日期缓存无效'})
                elif kind not in {'n', 'b', 'str', 'e', 's', 'd'}:
                    warnings.append({'part': member, 'cell': coordinate, 'issue_zh': '缓存类型需单独核验', 'type': kind})
        protected = [name for name in names if any(token in name for token in ['vbaProject', 'pivotTable', 'pivotCache', 'slicer', 'externalLink', 'connections.xml', 'activeX/', 'embeddings/'])]
        if protected:
            warnings.append({'issue_zh': '包含需要单独保真验收的复杂对象', 'parts': protected})
    if digest(path) != before:
        issues.append({'issue_zh': '检查期间文件发生变化'})
    return {'status': 'FAIL' if issues else ('REVIEW' if warnings else 'PASS'), 'file': str(path.resolve()), 'sha256': before,
            'sheets': sheets, 'formula_count': len(formulas), 'formula_caches': formulas,
            'text_cell_count': count_text_ids, 'native_chart_parts': [n for n in names if n.startswith('xl/charts/chart') and n.endswith('.xml')],
            'issues': issues, 'warnings': warnings,
            'boundary_zh': '只读文件结构与缓存检查；不计算公式、不证明缓存新鲜度或业务结果正确，也不替代原件对比和布局验收。'}


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        message = message.replace('unrecognized arguments:', '无法识别参数：').replace('expected one argument', '需要一个参数值')
        print('输入有误：' + message, file=sys.stderr)
        self.exit(2)


def main():
    parser = ChineseParser(description='检查 Excel 技能包及指定成果；全程只读、不安装依赖。', add_help=False)
    parser._optionals.title = '选项'
    parser.add_argument('-h', '--help', action='help', help='显示帮助')
    parser.add_argument('--workbook', type=Path, help='只检查用户指定的 .xlsx 文件')
    parser.add_argument('--json', action='store_true', help='输出完整结构化结果')
    args = parser.parse_args()
    try:
        result = {'package': package_check(), 'native_runtime_zh': '请在当前会话发现并实际验证表格读取、编辑、计算和保存能力；此标准库脚本不能读取会话工具注册表。', 'installation_performed': False}
        if args.workbook:
            if not args.workbook.is_file() or args.workbook.suffix.lower() != '.xlsx':
                parser.error('--workbook 必须是存在的 .xlsx 文件。')
            result['workbook'] = workbook_check(args.workbook)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as error:
        print(json.dumps({'status': 'FAIL', 'error_zh': '检查未完成：' + str(error)}, ensure_ascii=False))
        return 2
    failed = result['package']['status'] != 'PASS' or result.get('workbook', {}).get('status', 'PASS') != 'PASS'
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('Excel 文档专家检查')
        print('技能包：' + result['package']['message_zh'])
        for issue in result['package']['issues']:
            print('  ' + str(issue))
        if 'workbook' in result:
            w = result['workbook']
            print('成果内容：' + {'PASS': '基础检查通过', 'FAIL': '发现问题', 'REVIEW': '需要专项复核'}[w['status']])
            print('工作表 %d 张，公式 %d 个，原生图表 %d 个。' % (len(w['sheets']), w['formula_count'], len(w['native_chart_parts'])))
            for issue in w['issues'] + w['warnings']:
                print('  ' + json.dumps(issue, ensure_ascii=False))
            print(w['boundary_zh'])
        print(result['native_runtime_zh'])
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
