#!/usr/bin/env python3
"""PPT 云端客户端：只传选定材料、调用固定 API、下载并核验真实成果。"""
from __future__ import annotations
import argparse,base64,hashlib,json,os,re,sys,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path
BASE='https://www.tuokexing.net/ppt-service/v1'
class UserError(Exception):pass
class Parser(argparse.ArgumentParser):
 def error(self,message):raise UserError('参数不完整，请运行 --help 查看用法。')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):raise UserError('服务发生重定向，已停止传送凭证。请核对正式 HTTPS 地址。')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write_new(path,data,private=False):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600 if private else 0o644)
 with os.fdopen(fd,'wb') as f:f.write(data)
def dump(path,value):write_new(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
def request(base,path,token=None,body=None,binary=False):
 if not path.startswith('/') or '..' in path:raise UserError('接口路径无效。')
 headers={'Accept':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 data=None
 if body is not None:data=json.dumps(body,ensure_ascii=False,allow_nan=False).encode();headers['Content-Type']='application/json'
 req=urllib.request.Request(base+path,data=data,headers=headers,method='POST' if body is not None else 'GET')
 try:
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=45) as r:
   raw=r.read(70*1024**2+1)
   if len(raw)>70*1024**2:raise UserError('返回文件超过本地下载限额。')
   return raw if binary else json.loads(raw)
 except urllib.error.HTTPError as exc:
  try:message=json.loads(exc.read(5000)).get('error','服务拒绝了本次请求。')
  except Exception:message='服务拒绝了本次请求。'
  raise UserError('服务响应 '+str(exc.code)+'：'+message)
 except (urllib.error.URLError,TimeoutError):raise UserError('无法连接 PPT 服务，请检查网络后重试；不要反复重复提交。')
def credential(path,base):
 p=Path(path)
 if p.exists():
  if p.is_symlink():raise UserError('凭证文件不能是符号链接。')
  record=json.loads(p.read_text())
  if record.get('base_url')!=base:raise UserError('凭证属于其他服务地址，不能复用。')
  if record.get('expires_at',0)<=time.time():raise UserError('本机凭证已到期，请选择新的 --credential 文件路径重新建立会话。')
  if os.name=='posix' and p.stat().st_mode&0o077:raise UserError('凭证文件权限过宽，请将其设为仅当前用户可读写（0600）。')
 else:
  record=request(base,'/sessions',body={});record['base_url']=base
  write_new(p,(json.dumps(record)+'\n').encode(),True)
 if not isinstance(record.get('token'),str):raise UserError('凭证文件不完整。')
 return record['token']
def ident(value):
 if not re.fullmatch('[0-9a-f]{32}',value):raise UserError('任务编号无效。')
 return value
def status(base,token,job):return request(base,'/jobs/'+ident(job),token)
def wait(base,token,job,seconds):
 end=time.monotonic()+seconds
 while True:
  result=status(base,token,job)
  if result['status']=='succeeded':return result
  if result['status']=='failed':raise UserError(result.get('error') or '任务未完成。')
  if time.monotonic()>end:raise UserError('任务仍在处理中，请稍后使用 status 或 wait 查询原任务，不要重复提交。任务编号：'+job)
  time.sleep(3)
def download(base,token,job,out):
 result=status(base,token,job)
 if result['status']!='succeeded':raise UserError('任务尚未完成，不能下载。')
 target=Path(out)
 if target.exists():raise UserError('输出目录已存在，请使用新目录以保护原文件。')
 target.mkdir(parents=True)
 written=[]
 for item in result.get('artifacts',[]):
  name=item['name']
  if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]*',name):raise UserError('服务返回的文件名无效，已停止下载。')
  # Derive same-origin path; never trust an arbitrary URL from the response.
  raw=request(base,'/jobs/'+ident(job)+'/artifacts/'+name,token,binary=True)
  if len(raw)!=item['bytes'] or sha(raw)!=item['sha256']:raise UserError('下载校验不一致，已停止交付：'+name)
  write_new(target/name,raw);written.append({'文件':name,'字节数':len(raw),'sha256':sha(raw)})
 dump(target/'下载记录.json',{'任务编号':job,'文件':written,'说明':'下载完整且哈希一致；还应逐页查看预览，再交付可编辑 PPTX。'})
 return {'状态':'下载完成','目录':str(target.resolve()),'文件数':len(written),'任务编号':job}
def main():
 p=Parser(description='PPT制作与美化专家：云端生成、导入、修改、预览与下载。只需 Python 3 标准库和 HTTPS 网络。')
 p.add_argument('--base-url',default=BASE);p.add_argument('--credential',default='.ppt-cloud-credential.json',help='本地私密凭证文件；不要上传或分享')
 sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('health');sub.add_parser('init')
 c=sub.add_parser('create');c.add_argument('--project',required=True,help='只读取 svg_output/*.svg 和同名 notes/*.md');c.add_argument('--receipt',required=True)
 c=sub.add_parser('import');c.add_argument('--pptx',required=True);c.add_argument('--receipt',required=True)
 c=sub.add_parser('edit');c.add_argument('--parent',required=True);c.add_argument('--changes',required=True,help='JSON 修改数组');c.add_argument('--receipt',required=True)
 for mode in ('status','wait','download'):
  c=sub.add_parser(mode);c.add_argument('--job',required=True)
  if mode=='wait':c.add_argument('--seconds',type=int,default=360)
  if mode=='download':c.add_argument('--out',required=True)
 a=p.parse_args();base=a.base_url.rstrip('/');u=urllib.parse.urlsplit(base)
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise UserError('服务地址必须是无用户名、密码或查询串的 HTTPS 地址。')
 if a.command=='health':result=request(base,'/health')
 else:
  token=credential(a.credential,base)
  if a.command=='init':result={'状态':'本机凭证已准备','提示':'凭证仅存于指定文件，不在结果中显示。'}
  elif a.command in ('status','wait','download'):
   result=status(base,token,a.job) if a.command=='status' else wait(base,token,a.job,a.seconds) if a.command=='wait' else download(base,token,a.job,a.out)
  else:
   if Path(a.receipt).exists():raise UserError('任务回执已存在，请使用新文件路径。')
   protected={}
   if a.command=='create':
    project=Path(a.project).resolve();files=sorted((project/'svg_output').glob('*.svg'))
    if not 1<=len(files)<=12:raise UserError('项目须包含 1 至 12 个 svg_output/*.svg 页面。')
    pages=[]
    for f in files:
     if f.is_symlink():raise UserError('页面不能是符号链接。')
     raw=f.read_bytes();protected[str(f)]=sha(raw);notes=project/'notes'/(f.stem+'.md');note=''
     if notes.is_file():
      if notes.is_symlink():raise UserError('讲稿不能是符号链接。')
      nr=notes.read_bytes();protected[str(notes)]=sha(nr);note=nr.decode('utf-8')
     pages.append({'svg':raw.decode('utf-8'),'notes':note})
    payload={'operation':'create','pages':pages}
   elif a.command=='import':
    f=Path(a.pptx).resolve();raw=f.read_bytes()
    if len(raw)>10*1024**2:raise UserError('PPTX 不得超过 10MB。')
    protected[str(f)]=sha(raw);payload={'operation':'import','pptx_base64':base64.b64encode(raw).decode()}
   else:
    f=Path(a.changes).resolve();raw=f.read_bytes();protected[str(f)]=sha(raw);changes=json.loads(raw)
    if not isinstance(changes,list):raise UserError('修改文件必须是 JSON 数组。')
    payload={'operation':'edit','parent_job_id':ident(a.parent),'changes':changes}
   result=request(base,'/jobs',token,body=payload)
   preserved=all(sha(Path(k).read_bytes())==v for k,v in protected.items())
   dump(a.receipt,{**result,'input_sha256':protected,'input_preserved':preserved})
   if not preserved:raise UserError('本地输入在提交期间发生变化，请停止交付并检查原文件。')
   result={**result,'输入原件保持不变':True,'回执':str(Path(a.receipt).resolve())}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except (UserError,FileExistsError) as exc:print('未完成：'+str(exc),file=sys.stderr);sys.exit(2)
 except (OSError,ValueError,KeyError,TypeError) as exc:print('未完成：文件或返回数据无法读取，请检查路径、格式及完整性。'+type(exc).__name__,file=sys.stderr);sys.exit(3)
