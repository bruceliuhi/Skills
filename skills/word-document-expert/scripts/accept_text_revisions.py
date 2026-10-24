#!/usr/bin/env python3
"""Accept only ordinary inline text revisions, preserving all other OOXML bytes."""
import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import zipfile
from xml.parsers import expat

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS_PREFIXES = (W, 'http://schemas.microsoft.com/office/word/')
REVISION_NAMES = {'ins','del','moveFrom','moveTo','moveFromRangeStart','moveFromRangeEnd',
 'moveToRangeStart','moveToRangeEnd','cellIns','cellDel','cellMerge','numberingChange',
 'customXmlInsRangeStart','customXmlInsRangeEnd','customXmlDelRangeStart','customXmlDelRangeEnd',
 'customXmlMoveFromRangeStart','customXmlMoveFromRangeEnd','customXmlMoveToRangeStart',
 'customXmlMoveToRangeEnd','conflictIns','conflictDel','customXmlConflictInsRangeStart',
 'customXmlConflictInsRangeEnd','customXmlConflictDelRangeStart','customXmlConflictDelRangeEnd'}
MAX_PART = 32 * 1024 * 1024
MAX_PACKAGE = 256 * 1024 * 1024

def q(local): return W + '}' + local

def revision(name):
    ns, _, local = name.rpartition('}')
    return (ns == W or ns.startswith(NS_PREFIXES[1])) and (local in REVISION_NAMES or local.endswith('PrChange') or local == 'tblGridChange')

def digest(data): return hashlib.sha256(data).hexdigest()

def tag_end(data, pos):
    quote = None
    for i in range(pos, len(data)):
        c = data[i]
        if quote:
            if c == quote: quote = None
        elif c in (34, 39): quote = c
        elif c == 62: return i + 1
    raise ValueError('XML标签没有结束。')

def scan_xml(data):
    if len(data) > MAX_PART: raise ValueError('XML部件超过32MB，未执行操作。')
    # Byte-range edits are deliberately UTF-8 only; no serialization/reformatting.
    if b'\x00' in data: raise ValueError('离线修订操作不处理UTF-16或含空字节的XML。')
    declaration = re.match(br'(?:\xef\xbb\xbf)?<\?xml[^?]*encoding\s*=\s*[\"\']([^\"\']+)', data, re.I)
    if declaration and declaration.group(1).lower() not in (b'utf-8', b'utf8', b'us-ascii'):
        raise ValueError('离线修订操作仅支持UTF-8 XML。')
    try: data.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('离线修订操作仅支持UTF-8 XML，请使用支持原编码的文档引擎。')
    parser = expat.ParserCreate(namespace_separator='}')
    parser.buffer_text = True
    nodes, stack = [], []
    def reject(*unused): raise ValueError('文档XML包含DTD或实体声明，未执行操作。')
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    def start(name, attrs):
        offset = parser.CurrentByteIndex
        end = tag_end(data, offset)
        node = {'name':name,'attrs':attrs,'start':offset,'start_end':end,'end_start':None,'end':None,
                'parent':stack[-1] if stack else None,'children':[], 'self_closing':data[offset:end].rstrip().endswith(b'/>')}
        if stack: stack[-1]['children'].append(node)
        stack.append(node); nodes.append(node)
    def finish(name):
        node = stack.pop()
        if node['self_closing']:
            node['end_start'] = node['start_end']; node['end'] = node['start_end']
        else:
            node['end_start'] = parser.CurrentByteIndex
            node['end'] = tag_end(data, parser.CurrentByteIndex)
    parser.StartElementHandler = start
    parser.EndElementHandler = finish
    try: parser.Parse(data, True)
    except expat.ExpatError as exc: raise ValueError(f'XML解析失败：{exc}')
    return nodes

def descendants(node):
    for child in node['children']:
        yield child
        yield from descendants(child)

def accepted_main_xml(data, nodes):
    revisions = [n for n in nodes if revision(n['name'])]
    patches, counts = [], {'insertions':0,'deletions':0}
    for node in revisions:
        kind = node['name'].rsplit('}',1)[-1]
        if node['name'] not in (q('ins'), q('del')):
            raise ValueError(f'发现超出离线文字范围的修订：{kind}；请用经过验收的Word文档引擎处理。')
        if any(a not in {q('id'), q('author'), q('date')} for a in node['attrs']):
            raise ValueError('修订包含额外继承属性或扩展属性，不能直接移除包装。')
        parent = node['parent']
        if parent is None or parent['name'] != q('p') or node['self_closing']:
            raise ValueError('发现段落标记、嵌套或非段落内文字修订；不能按普通文字接受。')
        ancestors = []; a = parent
        while a: ancestors.append(a['name']); a = a['parent']
        if q('body') not in ancestors:
            raise ValueError('修订不在主文档正文范围，未执行操作。')
        opening = data[node['start']:node['start_end']]
        if b'xmlns' in opening:
            raise ValueError('修订节点声明了局部命名空间，不能直接去除包装；请用文档引擎处理。')
        if not node['children'] or any(c['name'] != q('r') for c in node['children']):
            raise ValueError('修订包含图片、域、批注边界或其他复杂内容，未执行操作。')
        for run in node['children']:
            text_children = [c for c in run['children'] if c['name'] != q('rPr')]
            expected = q('t') if kind == 'ins' else q('delText')
            if not text_children or any(c['name'] != expected or c['children'] for c in text_children):
                raise ValueError('修订不是普通文字run（可能含域、图片、换行或批注引用），未执行操作。')
            for child in descendants(run):
                if revision(child['name']):
                    raise ValueError('发现嵌套或属性修订，未执行操作。')
        if kind == 'ins':
            patches.extend([(node['start'],node['start_end'],b''),(node['end_start'],node['end'],b'')])
            counts['insertions'] += 1
        else:
            patches.append((node['start'],node['end'],b'')); counts['deletions'] += 1
    if not revisions: return data, counts, []
    patches.sort()
    for a,b in zip(patches,patches[1:]):
        if a[1] > b[0]: raise ValueError('修订范围发生重叠，未执行操作。')
    result, cursor = [], 0
    for start,end,replacement in patches:
        result.extend([data[cursor:start],replacement]); cursor=end
    result.append(data[cursor:]); new=b''.join(result)
    remaining = scan_xml(new)
    if any(revision(n['name']) or n['name']==q('delText') for n in remaining):
        raise ValueError('处理后仍有修订或删除文字标记，未交付结果。')
    return new,counts,[{'start_byte':a,'end_byte':b} for a,b,_ in patches]

def read_package(path):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist(); names=[x.filename for x in infos]
        if len(names)!=len(set(names)): raise ValueError('压缩包存在重复部件名称，未执行操作。')
        if len(names)>20000 or sum(x.file_size for x in infos)>MAX_PACKAGE:
            raise ValueError('文件规模超过离线安全处理范围，未执行操作。')
        for info in infos:
            name=info.filename
            if '\\' in name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or stat.S_ISLNK(info.external_attr>>16):
                raise ValueError('压缩包存在不规范路径或符号链接，未执行操作。')
            if name.lower().startswith('_xmlsignatures/') or 'vbaproject' in name.lower():
                raise ValueError('包含签名或宏的文件不属于本操作范围，未执行操作。')
        if 'word/document.xml' not in names or '[Content_Types].xml' not in names:
            raise ValueError('不是完整的DOCX文档。')
        parts={i.filename:z.read(i.filename) for i in infos}
        if b'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' not in parts['[Content_Types].xml']:
            raise ValueError('此操作只接受普通DOCX，不处理宏文档、模板或其它格式。')
        return infos,parts,z.comment

def accept_text_revisions(source, destination):
    source,destination=Path(source),Path(destination)
    if not source.is_file() or source.suffix.lower()!='.docx': raise ValueError('请提供存在的DOCX原件。')
    if destination.exists() or source.resolve()==destination.resolve(): raise ValueError('请使用尚不存在的新输出文件，不能覆盖原件或已有结果。')
    if destination.suffix.lower()!='.docx' or not destination.parent.is_dir(): raise ValueError('输出应为DOCX，且父目录必须已经存在。')
    source_hash=digest(source.read_bytes())
    infos,parts,comment=read_package(source)
    main_nodes=None
    for name,data in parts.items():
        if name.endswith('.xml') or name.endswith('.rels'):
            nodes=scan_xml(data)
            if name=='word/document.xml': main_nodes=nodes
            elif any(revision(n['name']) or n['name']==q('delText') for n in nodes):
                raise ValueError(f'其它部件含修订：{name}。离线模式不会只处理正文后宣称全部接受。')
    new,counts,patches=accepted_main_xml(parts['word/document.xml'],main_nodes)
    expected={**parts,'word/document.xml':new}
    with tempfile.TemporaryDirectory(prefix='word_text_accept_',dir=destination.parent) as temp:
        staged=Path(temp)/'result.docx'
        with zipfile.ZipFile(staged,'w') as z:
            z.comment=comment
            for info in infos: z.writestr(info,expected[info.filename])
        _,actual,_=read_package(staged)
        if actual!=expected: raise ValueError('写出后部件核对失败，未交付结果。')
        if digest(source.read_bytes())!=source_hash: raise ValueError('输入在执行期间变化，未交付结果。')
        with destination.open('xb') as f: f.write(staged.read_bytes())
    changed=[n for n in parts if parts[n]!=actual[n]]
    return {'success':True,'message_zh':'已生成普通文字修订的清洁副本；其它部件保持字节一致。' if patches else '未发现修订，已生成内容不变的新副本。',
      'scope_zh':'仅主文档段落中普通文字run的插入/删除；不处理段落标记、移动、属性、表格结构或复杂嵌套修订。',
      'input_sha256':source_hash,'output':str(destination),'output_sha256':digest(destination.read_bytes()),
      'accepted':counts,'changed_parts':changed,'untouched_parts_byte_identical':True,
      'byte_edit_ranges':patches,'visual_verified':False,
      'next_zh':'继续执行完整XSD检查、正文和编号核对及最新页面预览；本操作不计算目录页码、不接受未支持的复杂修订。'}

class ChineseParser(argparse.ArgumentParser):
    def error(self,message):
        self.print_usage(sys.stderr)
        self.exit(2,'参数错误：请同时提供 --input 原件.docx 和 --output 新文件.docx。\n')

if __name__=='__main__':
    p=ChineseParser(description='只接受普通文字插入/删除修订；保留原件、其它部件和未改XML字节。')
    p.add_argument('--input',required=True,help='原DOCX文件')
    p.add_argument('--output',required=True,help='尚不存在的新DOCX文件')
    args=p.parse_args()
    try: result=accept_text_revisions(args.input,args.output)
    except (OSError,ValueError,zipfile.BadZipFile,RuntimeError,RecursionError) as exc:
        print(json.dumps({'success':False,'message_zh':f'未执行或未完成：{exc}','output_delivered':False},ensure_ascii=False,indent=2));sys.exit(3)
    print(json.dumps(result,ensure_ascii=False,indent=2))
