#!/usr/bin/env python3
"""自有 PPT 任务服务：固定白名单操作、持久化任务与每客户端隔离。"""
from __future__ import annotations
import base64,binascii,hashlib,html,io,json,math,os,re,secrets,shutil,signal,socket,socketserver,sqlite3,subprocess,threading,time,uuid,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree as ET

DATA=Path(os.getenv('PPT_DATA','/data'));ENGINE=Path(os.getenv('PPT_ENGINE','/engine'))
DB=DATA/'state.sqlite3';JOBS=DATA/'jobs';TTL=86400;MAX_BODY=20*1024*1024
MAX_DISK=5*1024**3;MAX_QUEUE=6;SESSION_TTL=30*86400
BASE=os.getenv('PPT_PUBLIC_BASE','https://www.tuokexing.net/ppt-service/v1').rstrip('/')
LOCK=threading.Lock();STOP=threading.Event()

def sha(data):return hashlib.sha256(data).hexdigest()
def dump(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def connect():
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;return c

def initialize():
 DATA.mkdir(exist_ok=True);JOBS.mkdir(exist_ok=True)
 with connect() as c:
  c.executescript('''PRAGMA journal_mode=WAL;
 CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE,ip_hash TEXT,created REAL,expires REAL);
 CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,client_id TEXT,operation TEXT,status TEXT,created REAL,expires REAL,updated REAL,error TEXT,summary TEXT,input_bytes INTEGER);
 CREATE INDEX IF NOT EXISTS jobs_client_created ON jobs(client_id,created);
 CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY,window REAL,count INTEGER);''')
  c.execute("UPDATE jobs SET status='failed',error='服务重新启动；该任务未完成，请以新任务重试。',updated=? WHERE status='running'",(time.time(),))

def rate(key,maximum,seconds):
 now=time.time()
 with LOCK,connect() as c:
  row=c.execute('SELECT * FROM limits WHERE key=?',(key,)).fetchone()
  if row is None or now-row['window']>=seconds:
   c.execute('INSERT OR REPLACE INTO limits VALUES(?,?,?)',(key,now,1));return
  if row['count']>=maximum:raise APIError(429,'请求过于频繁，请稍后再试。')
  c.execute('UPDATE limits SET count=count+1 WHERE key=?',(key,))

class APIError(Exception):
 def __init__(self,status,message):self.status=status;self.message=message

def svg_validate(text):
 if not isinstance(text,str) or len(text.encode())>800000:raise APIError(400,'单页 SVG 必须是文本且不超过 800KB。')
 if re.search(r'<!DOCTYPE|<!ENTITY|@import',text,re.I):raise APIError(400,'页面不能包含外部实体或导入。')
 try:root=ET.fromstring(text)
 except ET.ParseError:raise APIError(400,'页面 SVG 格式不完整。')
 if root.tag.rsplit('}',1)[-1]!='svg':raise APIError(400,'页面必须是 SVG。')
 try:
  box=[float(x) for x in root.get('viewBox','').replace(',',' ').split()]
  if len(box)!=4 or not all(math.isfinite(x) for x in box) or not 100<=box[2]<=4096 or not 100<=box[3]<=4096 or box[2]*box[3]>9000000:raise ValueError()
 except ValueError:raise APIError(400,'页面画布须为有效 viewBox，宽高在 100 至 4096 之间且总面积不超过 900 万像素。')
 for node in root.iter():
  if node.tag.rsplit('}',1)[-1].lower() in {'script','foreignobject','iframe','object','audio','video','style'}:raise APIError(400,'页面包含不支持的执行或交互元素。')
  for key,value in node.attrib.items():
   local=key.rsplit('}',1)[-1].lower()
   if '\\' in value or key=='{http://www.w3.org/XML/1998/namespace}base':raise APIError(400,'页面不能包含转义资源地址或外部基准路径。')
   if local.startswith('on'):raise APIError(400,'页面不能包含事件脚本。')
   if local in {'href','src'} and value and not value.startswith(('#','data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):
    raise APIError(400,'页面图片必须已嵌入，服务不读取外部网址或本地路径。')
   if 'url(' in value.lower():
    for ref in re.findall(r'url\(\s*[\"\']?([^\)\"\']+)',value,re.I):
     if not ref.startswith('#'):raise APIError(400,'页面样式不能引用外部资源。')
 return root

def pptx_validate(raw):
 if len(raw)>10*1024**2:raise APIError(400,'上传 PPTX 不得超过 10MB。')
 try:
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   items=z.infolist()
   if len(items)>10000 or sum(x.file_size for x in items)>100*1024**2:raise APIError(400,'PPTX 解压内容过大。')
   slides=[]
   if len({x.filename for x in items}) != len(items):raise APIError(400,'PPTX 含重复的内部文件名。')
   if '[Content_Types].xml' not in z.namelist():raise APIError(400,'PPTX 缺少组件类型声明。')
   ct=z.read('[Content_Types].xml')
   if len(ct)>1048576 or b'<!DOCTYPE' in ct.upper() or b'<!ENTITY' in ct.upper():raise APIError(400,'PPTX 组件类型声明无效。')
   types=ET.fromstring(ct);defaults={x.get('Extension'):x.get('ContentType','') for x in types if x.tag.endswith('Default')};overrides={x.get('PartName','').lstrip('/'):x.get('ContentType','') for x in types if x.tag.endswith('Override')}
   if any(any(flag in value.lower() for flag in ('macroenabled','vbaproject','activex','oleobject')) for value in [*defaults.values(),*overrides.values()]):raise APIError(400,'当前不处理含宏、ActiveX 或 OLE 的 PPTX。')
   for x in items:
    parts=x.filename.split('/')
    if x.filename.startswith('/') or '\\' in x.filename or '..' in parts or (x.external_attr>>16)&0o170000==0o120000:raise APIError(400,'PPTX 包含不安全路径。')
    lower=x.filename.lower()
    if 'vbaproject' in lower or '/activex/' in lower or '/oleobjects/' in lower:raise APIError(400,'当前不处理含宏、嵌入程序或 OLE 对象的 PPTX。')
    if lower.endswith('.bin'):
     kind=overrides.get(x.filename,defaults.get('bin'))
     if not re.fullmatch(r'ppt/printerSettings/printerSettings[0-9]+\.bin',x.filename) or x.file_size>65536 or kind!='application/vnd.openxmlformats-officedocument.presentationml.printerSettings':raise APIError(400,'PPTX 含不支持的二进制组件。')
    if re.fullmatch(r'ppt/slides/slide\d+\.xml',x.filename):slides.append(x.filename)
    if lower.endswith('.svg'):
     if x.file_size>800000:raise APIError(400,'PPTX 内的 SVG 图片超过 800KB。')
     try:svg_validate(z.read(x).decode('utf-8'))
     except UnicodeDecodeError:raise APIError(400,'PPTX 内 SVG 图片编码无效。')
    if x.filename.endswith(('.xml','.rels')):
     if x.file_size>10*1024**2:raise APIError(400,'单个 XML 组件过大。')
     xml=z.read(x)
     if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():raise APIError(400,'PPTX 含不支持的外部实体。')
     if x.filename=='ppt/presentation.xml':
      sizes=[n for n in ET.fromstring(xml).iter() if n.tag.rsplit('}',1)[-1]=='sldSz']
      try:
       cx=int(sizes[0].get('cx'));cy=int(sizes[0].get('cy'))
       if min(cx,cy)<914400 or max(cx,cy)>36*914400 or (cx/914400*96)*(cy/914400*96)>9000000:raise ValueError()
      except (IndexError,TypeError,ValueError):raise APIError(400,'PPTX 画布须在 1 至 36 英寸且预览不超过 900 万像素。')
     if x.filename.endswith('.rels'):
      for rel in ET.fromstring(xml):
       if any(flag in rel.get('Type','').lower() for flag in ('vbaproject','activex','oleobject')):raise APIError(400,'PPTX 关系声明含宏或嵌入程序。')
       if rel.get('TargetMode')=='External':
        if not rel.get('Type','').endswith('/hyperlink') or not rel.get('Target','').startswith(('https://','mailto:')):raise APIError(400,'PPTX 含不支持的外部资源或文件链接，请先嵌入素材。')
   if not 1<=len(slides)<=30:raise APIError(400,'PPTX 页数须为 1 至 30 页。')
   if '[Content_Types].xml' not in z.namelist() or z.testzip():raise APIError(400,'PPTX 内容不完整。')
 except (zipfile.BadZipFile,ET.ParseError):raise APIError(400,'文件不是完整可读的 PPTX。')
 return len(slides)

def validate_input(payload,client):
 if not isinstance(payload,dict):raise APIError(400,'请求正文必须是 JSON 对象。')
 op=payload.get('operation')
 if op=='create':
  pages=payload.get('pages')
  if not isinstance(pages,list) or not 1<=len(pages)<=12:raise APIError(400,'新建演示支持 1 至 12 页。')
  for page in pages:
   if not isinstance(page,dict):raise APIError(400,'页面格式无效。')
   svg_validate(page.get('svg'));notes=page.get('notes','')
   if not isinstance(notes,str) or len(notes)>20000:raise APIError(400,'单页讲稿不能超过 2 万字符。')
 elif op=='import':
  try:raw=base64.b64decode(payload.get('pptx_base64',''),validate=True)
  except (ValueError,TypeError,binascii.Error):raise APIError(400,'PPTX 编码无效。')
  pptx_validate(raw)
 elif op=='edit':
  parent=payload.get('parent_job_id');changes=payload.get('changes')
  if not isinstance(parent,str) or not re.fullmatch('[0-9a-f]{32}',parent):raise APIError(400,'原任务编号无效。')
  with connect() as c:row=c.execute('SELECT * FROM jobs WHERE id=? AND client_id=? AND status=? AND expires>?',(parent,client['id'],'succeeded',time.time())).fetchone()
  if row is None:raise APIError(404,'原任务不存在、未完成或已过期。')
  if not isinstance(changes,list) or not 1<=len(changes)<=12:raise APIError(400,'修改项数量须为 1 至 12。')
  for change in changes:
   if not isinstance(change,dict) or type(change.get('page')) is not int or not 1<=change['page']<=30:raise APIError(400,'修改页码无效。')
   if 'svg' in change:
    if 'find' in change or 'replace' in change:raise APIError(400,'整页 SVG 与文字替换不能混用。')
    svg_validate(change['svg'])
   elif not isinstance(change.get('find'),str) or not change['find'] or not isinstance(change.get('replace'),str) or max(len(change['find']),len(change['replace']))>20000:
    raise APIError(400,'文字替换需要明确的原文和新文。')
 else:raise APIError(400,'只支持 create、import、edit 三种固定任务。')
 return op

def jobdir(row):
 if not re.fullmatch('[0-9a-f]{32}',row['id']):raise RuntimeError('invalid stored job id')
 return JOBS/row['id']

def ownjob(ident,client):
 if not re.fullmatch('[0-9a-f]{32}',ident):raise APIError(404,'任务不存在。')
 with connect() as c:row=c.execute('SELECT * FROM jobs WHERE id=? AND client_id=? AND expires>?',(ident,client['id'],time.time())).fetchone()
 if not row:raise APIError(404,'任务不存在或已过期。')
 return row

def run_command(cmd,cwd,logname,timeout=120):
 started=time.monotonic()
 p=subprocess.Popen(['python','-B',str(Path(__file__).with_name('limit_exec.py')),*cmd],cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
 try:
  while True:
   if time.monotonic()-started>timeout:raise RuntimeError('处理超过时间上限，已终止本任务进程组。')
   if sum(f.stat().st_size for f in cwd.rglob('*') if f.is_file())>200*1024**2:raise RuntimeError('本任务工作文件超过 200MB，已停止。')
   try:stdout,stderr=p.communicate(timeout=0.5);break
   except subprocess.TimeoutExpired:continue
 except BaseException:
  try:os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  p.communicate();raise
 try:os.killpg(p.pid,signal.SIGKILL)
 except ProcessLookupError:pass
 if sum(f.stat().st_size for f in cwd.rglob('*') if f.is_file())>200*1024**2:raise RuntimeError('本任务工作文件超过 200MB，未完成交付。')
 p.stdout=stdout;p.stderr=stderr
 dump(cwd/(logname+'.json'),{'command':cmd,'exit_code':p.returncode,'stdout':p.stdout[-50000:],'stderr':p.stderr[-50000:]})
 if p.returncode:raise RuntimeError('处理步骤未通过：'+logname+'。'+(p.stderr or p.stdout)[-1500:])
 return p

def core(args,root,name):
 return run_command(['python','-B',str(ENGINE/'scripts/workbuddy_ppt.py'),'--json',*map(str,args)],root,name)

def native_parts(p):
 with zipfile.ZipFile(p) as z:return {n:sha(z.read(n)) for n in z.namelist() if n.startswith(('ppt/slides/','ppt/charts/','ppt/embeddings/','ppt/notesSlides/','ppt/notesMasters/'))}

def render(pptx,output,work):
 profile=work/'lo-profile';pdfdir=work/'pdf';pdfdir.mkdir()
 run_command(['soffice','-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','pdf','--outdir',str(pdfdir),str(pptx)],work,'render-office',120)
 pdf=pdfdir/(pptx.stem+'.pdf')
 if not pdf.is_file():raise RuntimeError('未生成可读取的 PDF 预览。')
 shutil.copyfile(pdf,output/'preview.pdf')
 run_command(['pdftoppm','-png','-r','96','-scale-to','2000',str(pdf),str(output/'page')],work,'render-pages',120)
 pngs=sorted(output.glob('page-*.png'))
 if not pngs:raise RuntimeError('未生成逐页预览图片。')
 return len(pngs)

def process(row):
 root=jobdir(row);payload=json.loads((root/'request.json').read_text());output=root/'output';output.mkdir();op=row['operation'];protected={}
 if op=='create':
  original=root/'inputs';original.mkdir();(original/'svg_output').mkdir();(original/'notes').mkdir()
  for i,page in enumerate(payload['pages'],1):
   name=f'{i:02d}_slide';(original/'svg_output'/(name+'.svg')).write_text(page['svg'],encoding='utf-8');(original/'notes'/(name+'.md')).write_text(page.get('notes',''),encoding='utf-8')
  protected={str(p.relative_to(root)):sha(p.read_bytes()) for p in original.rglob('*') if p.is_file()}
  project=root/'project';shutil.copytree(original,project)
  run_command(['python','-B',str(ENGINE/'scripts/stamp_native_fallbacks.py'),str(project/'svg_output'),'--write'],root,'native-sync')
  core(['check',project,'--mode','quick'],root,'quality')
  core(['export',project,'--mode','quick','--output',output/'deck.pptx','--notes','--native-data'],root,'generate')
 elif op=='import':
  source=root/'original.pptx';source.write_bytes(base64.b64decode(payload['pptx_base64']));protected={'original.pptx':sha(source.read_bytes())};project=root/'roundtrip'
  core(['import',source,'--workspace',project],root,'import');shutil.copyfile(source,output/'deck.pptx')
 else:
  with connect() as c:parent=c.execute('SELECT * FROM jobs WHERE id=? AND client_id=?',(payload['parent_job_id'],row['client_id'])).fetchone()
  if parent is None or parent['status']!='succeeded' or parent['expires']<=time.time():raise RuntimeError('原任务已经过期，未执行修改。')
  source=root/'original.pptx';shutil.copyfile(jobdir(parent)/'output/deck.pptx',source);protected={'original.pptx':sha(source.read_bytes())};project=root/'roundtrip'
  before=native_parts(source);core(['import',source,'--workspace',project],root,'import-for-edit');changed=set()
  for change in payload['changes']:
   page=change['page'];p=project/'authoring-svg-flat'/f'slide_{page:02d}.svg'
   if not p.is_file():raise RuntimeError('指定修改页不存在：'+str(page))
   text=p.read_text()
   if 'svg' in change:new=change['svg']
   else:
    old=html.escape(change['find'],quote=False);replacement=html.escape(change['replace'],quote=False)
    tree=ET.fromstring(text);matches=[n for n in tree.iter() if n.tag.rsplit('}',1)[-1] in {'text','tspan'} and ''.join(n.itertext())==change['find']]
    if not matches or text.count(old)!=1:raise RuntimeError('替换原文未唯一匹配第 '+str(page)+' 页，请提供该页明确文字。')
    new=text.replace(old,replacement,1)
   svg_validate(new);p.write_text(new,encoding='utf-8');changed.add(page)
  core(['check',project,'--mode','roundtrip'],root,'quality-edit')
  core(['export',project,'--mode','roundtrip','--output',output/'deck.pptx'],root,'export-edit')
  after=native_parts(output/'deck.pptx');required=[n for n in before if not any(n==f'ppt/slides/slide{x}.xml' for x in changed)]
  altered=[n for n in required if after.get(n)!=before[n]]
  if altered:raise RuntimeError('未改内容保留核验未通过：'+', '.join(altered[:5]))
  dump(output/'preservation.json',{'原件保护':True,'未改组件数量':len(required),'未改组件全部相同':True,'修改页':sorted(changed)})
 if protected!={name:sha((root/name).read_bytes()) for name in protected}:raise RuntimeError('输入原件保护核验未通过。')
 inspect=json.loads(core(['inspect',output/'deck.pptx'],root,'inspect').stdout)
 previews=render(output/'deck.pptx',output,root)
 if previews!=inspect.get('slides'):raise RuntimeError('预览页数与演示页数不一致，未完成交付。')
 # Include editable page sources where import produced them; no original path is exposed.
 if (project/'authoring-svg-flat').is_dir():
  for p in sorted((project/'authoring-svg-flat').glob('slide_*.svg')):shutil.copyfile(p,output/(p.stem.replace('_','-')+'.svg'))
 dump(output/'report.json',{'状态':'已完成','原件保护':True,'演示页数':inspect.get('slides'),'原生图表':inspect.get('charts'),'原生表格':inspect.get('tables'),'讲稿页数':inspect.get('notes'),'预览页数':previews,'预览方式':'LibreOffice 转 PDF 后逐页渲染','说明':'预览成功不代表所有办公软件像素完全一致。'})
 if sum(f.stat().st_size for f in root.rglob('*') if f.is_file())>200*1024**2:raise RuntimeError('本任务工作文件超过 200MB，未完成交付。')
 artifacts=[]
 for p in sorted(output.iterdir()):
  if p.is_file():artifacts.append({'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p.read_bytes()),'url':BASE+'/jobs/'+row['id']+'/artifacts/'+p.name})
 summary={'artifacts':artifacts,'slides':inspect.get('slides'),'preview_pages':previews,'input_preserved':True,'renderer':'LibreOffice+Poppler'}
 return summary

def cleanup():
 now=time.time()
 with connect() as c:
  expired=c.execute("SELECT * FROM jobs WHERE expires<? AND status!='running'",(now,)).fetchall()
  for row in expired:
   target=jobdir(row)
   if target.is_dir() and not target.is_symlink():shutil.rmtree(target)
   c.execute('DELETE FROM jobs WHERE id=?',(row['id'],))
  c.execute('DELETE FROM clients WHERE expires<? AND id NOT IN (SELECT client_id FROM jobs)',(now,))
  c.execute('DELETE FROM limits WHERE window<?',(now-2*86400,))

def worker():
 while not STOP.is_set():
  try:
   cleanup()
   with LOCK,connect() as c:
    row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
    if row:c.execute("UPDATE jobs SET status='running',updated=? WHERE id=?",(time.time(),row['id']))
   if row:
    try:
     summary=process(row)
     with connect() as c:c.execute("UPDATE jobs SET status='succeeded',summary=?,updated=? WHERE id=?",(json.dumps(summary,ensure_ascii=False),time.time(),row['id']))
    except Exception as exc:
     # Full internal errors stay in protected task directory; client gets a bounded Chinese reason.
     error=str(exc);dump(jobdir(row)/'error.json',{'error':error,'type':type(exc).__name__})
     safe=re.sub(r'/[^\s\"\']+', '[处理文件]',error)[:700]
     with connect() as c:c.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?",('任务未完成：'+safe,time.time(),row['id']))
   else:STOP.wait(2)
  except Exception as exc:
   print('worker error:',type(exc).__name__,flush=True);STOP.wait(5)

class Handler(BaseHTTPRequestHandler):
 server_version='XinghePPT/1.1'
 def setup(self):super().setup();self.connection.settimeout(20)
 def log_message(self,*args):pass
 def respond(self,status,payload):
  data=json.dumps(payload,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
 def client(self):
  value=self.headers.get('Authorization','')
  if not value.startswith('Bearer ') or len(value)>200:raise APIError(401,'需要本机任务凭证。')
  with connect() as c:row=c.execute('SELECT * FROM clients WHERE token_hash=? AND expires>?',(sha(value[7:].encode()),time.time())).fetchone()
  if row is None:raise APIError(401,'任务凭证无效或已过期。')
  rate('client:'+row['id'],90,60);return row
 def body(self):
  if self.headers.get('Transfer-Encoding'):raise APIError(400,'不支持分块请求，请提供正文长度。')
  try:n=int(self.headers.get('Content-Length','0'))
  except ValueError:raise APIError(400,'正文长度无效。')
  if not 0<n<=MAX_BODY:raise APIError(413,'请求正文应大于 0 且不超过 20MB。')
  if self.headers.get_content_type()!='application/json':raise APIError(415,'请使用 JSON 请求。')
  try:return json.loads(self.rfile.read(n))
  except (ValueError,UnicodeDecodeError):raise APIError(400,'JSON 正文无法读取。')
 def route(self,method):
  path=self.path.split('?',1)[0]
  if method=='GET' and path=='/v1/health':return self.respond(200,{'status':'ok','version':'1.1.0','service':'PPT制作与美化','limits':{'create_pages':12,'import_pages':30,'upload_mb':10,'retention_hours':24,'daily_jobs':10}})
  ip=self.headers.get('X-Real-IP') or (self.client_address[0] if self.client_address else 'local-unix');iph=sha(ip.encode());rate('ip:'+iph,180,60)
  if method=='POST' and path=='/v1/sessions':
   self.body();rate('session:'+iph,8,86400);token=secrets.token_urlsafe(32);ident=uuid.uuid4().hex;now=time.time()
   with connect() as c:c.execute('INSERT INTO clients VALUES(?,?,?,?,?)',(ident,sha(token.encode()),iph,now,now+SESSION_TTL))
   return self.respond(201,{'client_id':ident,'token':token,'expires_at':now+SESSION_TTL})
  client=self.client()
  if method=='POST' and path=='/v1/jobs':
   payload=self.body();op=validate_input(payload,client);raw=json.dumps(payload,ensure_ascii=False).encode();now=time.time();ident=uuid.uuid4().hex
   with LOCK,connect() as c:
    if c.execute('SELECT count(*) FROM jobs WHERE client_id=? AND created>?',(client['id'],now-86400)).fetchone()[0]>=10:raise APIError(429,'今日任务额度已用完。')
    if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=MAX_QUEUE:raise APIError(429,'服务队列已满，请稍后再提交。')
    if c.execute("SELECT count(*) FROM jobs WHERE client_id=? AND status IN ('queued','running')",(client['id'],)).fetchone()[0]>=2:raise APIError(429,'您已有两个等待中的任务。')
    if sum(p.stat().st_size for p in JOBS.rglob('*') if p.is_file())>MAX_DISK:raise APIError(503,'临时存储已满，请稍后再试。')
    root=JOBS/ident;root.mkdir();(root/'request.json').write_bytes(raw)
    c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,client['id'],op,'queued',now,now+TTL,now,None,None,len(raw)))
   return self.respond(202,{'id':ident,'status':'queued','expires_at':now+TTL,'status_url':BASE+'/jobs/'+ident})
  match=re.fullmatch(r'/v1/jobs/([0-9a-f]{32})(?:/artifacts/([A-Za-z0-9._-]+))?',path)
  if method=='GET' and match:
   row=ownjob(match[1],client);name=match[2]
   if not name:
    result={k:row[k] for k in ('id','operation','status','created','expires','updated','error')}
    if row['summary']:result.update(json.loads(row['summary']))
    return self.respond(200,result)
   if row['status']!='succeeded':raise APIError(409,'任务尚未完成。')
   allowed={a['name']:a for a in json.loads(row['summary'])['artifacts']}
   if name not in allowed:raise APIError(404,'成果文件不存在。')
   p=jobdir(row)/'output'/name;digest=hashlib.sha256()
   with p.open('rb') as f:
    for block in iter(lambda:f.read(65536),b''):digest.update(block)
   if digest.hexdigest()!=allowed[name]['sha256'] or p.stat().st_size!=allowed[name]['bytes']:raise APIError(500,'成果校验不一致，已停止下载。')
   kinds={'.png':'image/png','.pdf':'application/pdf','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','.svg':'image/svg+xml','.json':'application/json'}
   self.send_response(200);self.send_header('Content-Type',kinds.get(p.suffix,'application/octet-stream'));self.send_header('Content-Length',str(p.stat().st_size));self.send_header('Content-Disposition','attachment; filename="'+name+'"');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
   with p.open('rb') as f:shutil.copyfileobj(f,self.wfile,length=65536)
   return
  raise APIError(404,'接口不存在。')
 def do_GET(self):self.dispatch('GET')
 def do_POST(self):self.dispatch('POST')
 def dispatch(self,method):
  try:self.route(method)
  except APIError as exc:self.respond(exc.status,{'error':exc.message})
  except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
  except Exception:self.respond(500,{'error':'服务未能完成请求，请稍后重试。'})

class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,*a,**kw):super().__init__(*a,**kw);self.slots=threading.BoundedSemaphore(8)
 def process_request(self,request,address):
  if not self.slots.acquire(blocking=False):request.close();return
  try:super().process_request(request,address)
  except Exception:self.slots.release();raise
 def process_request_thread(self,*a):
  try:super().process_request_thread(*a)
  finally:self.slots.release()

class UnixServer(Server):
 address_family=socket.AF_UNIX
 def server_bind(self):
  socketserver.TCPServer.server_bind(self);self.server_name='localhost';self.server_port=0

if __name__=='__main__':
 initialize();threading.Thread(target=worker,daemon=True).start()
 sock=os.getenv('PPT_SOCKET')
 if sock:
  path=Path(sock)
  if path.exists():
   if not path.is_socket():raise RuntimeError('独立服务套接字路径被其他文件占用。')
   path.unlink()
  server=UnixServer(str(path),Handler);os.chmod(path,0o666)
 else:server=Server(('0.0.0.0',8080),Handler)
 server.serve_forever()
