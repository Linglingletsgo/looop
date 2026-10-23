"""Helpers for the standalone console: login page, origin trust and bounded children."""
import html,ipaddress,json,os,pathlib,select,subprocess,time,urllib.parse
import console_auth

DEFAULT_PORTS={'http':80,'https':443}
CHUNK=64*1024

def safe_next(value):
 if not isinstance(value,str) or not value.startswith('/') or value.startswith('//') or value.startswith('/\\'):return '/looop'
 if any(ord(char)<33 or ord(char)>126 for char in value):return '/looop'
 return value

def data_root(root):
 return pathlib.Path(os.environ.get('AGENT_RUNTIME_ROOT') or root).expanduser().resolve()

def is_loopback(host):
 if host=='localhost':return True
 try:return ipaddress.ip_address(host).is_loopback
 except ValueError:return False

def validate_startup(root,host,insecure_local_dev):
 auth=console_auth.Auth(data_root(root));loopback=is_loopback(host)
 if insecure_local_dev and not loopback:raise ValueError('--insecure-local-dev 只允许绑定回环地址。')
 if not loopback and not auth.password_set():raise ValueError('非回环地址必须先设置控制台密码（bin/console-auth.py set-password）。')
 if loopback and not insecure_local_dev and not auth.password_set():raise ValueError('尚未设置控制台密码；请运行 bin/console-auth.py set-password，或使用 --insecure-local-dev。')

def login_html(next_path,error,nonce):
 message=f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ''
 return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>looop · 登录</title><style nonce="{nonce}">body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0a;color:#f5f5f5;font:14px/1.6 sans-serif}}main{{width:min(360px,90vw);background:#111;border:1px solid #333;border-radius:10px;padding:28px}}label{{display:block;margin:16px 0 6px}}input{{width:100%;background:#0a0a0a;border:1px solid #444;color:#f5f5f5;padding:10px}}button{{width:100%;margin-top:16px;padding:10px;border:1px solid #f5f5f5;background:#f5f5f5;color:#111;font:inherit}}.error{{color:#fff;border-left:3px solid #fff;padding-left:10px}}</style></head><body><main><h1>looop 控制台</h1>{message}<form method="post" action="/login"><input type="hidden" name="next" value="{html.escape(next_path,quote=True)}"><label for="password">密码</label><input id="password" name="password" type="password" required minlength="12" autocomplete="current-password" autofocus><button type="submit">登录</button></form></main></body></html>'''

def _origin(value):
 if not isinstance(value,str):return None
 value=value.strip()
 if value.endswith('/'):value=value[:-1]
 if not value or any(char in value for char in ' \t\r\n\\'):return None
 try:parts=urllib.parse.urlsplit(value)
 except ValueError:return None
 scheme=(parts.scheme or '').lower()
 if scheme not in DEFAULT_PORTS or not parts.hostname:return None
 if parts.username is not None or parts.password is not None or parts.path or parts.query or parts.fragment:return None
 try:port=parts.port
 except ValueError:return None
 host=parts.hostname.lower()
 explicit=port is not None
 if port is None:port=DEFAULT_PORTS[scheme]
 return {'scheme':scheme,'host':host,'port':port,'explicit':explicit,'text':scheme+'://'+parts.netloc.lower()}

def _host(value):
 if not isinstance(value,str):return None
 value=value.strip().lower()
 if not value or any(char in value for char in ' \t\r\n/\\@?#,'):return None
 try:parts=urllib.parse.urlsplit('//'+value)
 except ValueError:return None
 if not parts.hostname or parts.path or parts.query or parts.fragment or parts.username is not None:return None
 try:return parts.hostname.lower(),parts.port
 except ValueError:return None

def load_origins(data,host,port):
 origins=[]
 for value in (f'http://127.0.0.1:{port}',f'http://localhost:{port}')+((f'http://[::1]:{port}',) if host=='::1' else ()):
  parsed=_origin(value)
  if parsed:origins.append(parsed)
 try:
  settings=json.loads((data/'data/local-settings.json').read_text())
 except (OSError,ValueError):settings=None
 console=settings.get('console') if isinstance(settings,dict) else None
 values=console.get('origins') if isinstance(console,dict) else None
 for value in values if isinstance(values,list) else ():
  parsed=_origin(value)
  if parsed and all(parsed['text']!=item['text'] for item in origins):origins.append(parsed)
 return origins

def match_host(origins,value):
 parsed=_host(value)
 if not parsed:return None
 host,port=parsed
 matches=[]
 for item in origins:
  if item['host']!=host:continue
  if port is None:
   if item['port']!=DEFAULT_PORTS[item['scheme']]:continue
  elif port!=item['port']:continue
  matches.append(item)
 if not matches:return None
 return next((item for item in matches if item['scheme']=='https'),matches[0])

def match_origin(origins,value):
 parsed=_origin(value)
 if not parsed:return None
 return next((item for item in origins if (item['scheme'],item['host'],item['port'])==(parsed['scheme'],parsed['host'],parsed['port'])),None)

def run(argv,cwd,data=b'',timeout=60,limit=1024*1024):
 try:proc=subprocess.Popen(argv,cwd=str(cwd),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 except OSError:return None
 deadline=time.monotonic()+timeout;chunks=[];total=0
 try:
  try:proc.stdin.write(data);proc.stdin.close()
  except (OSError,ValueError):return None
  descriptor=proc.stdout.fileno()
  while True:
   remaining=deadline-time.monotonic()
   if remaining<=0:return None
   try:ready,_,_=select.select([descriptor],[],[],min(remaining,0.1))
   except (OSError,ValueError):return None
   if not ready:continue
   try:chunk=os.read(descriptor,CHUNK)
   except OSError:return None
   if not chunk:break
   total+=len(chunk)
   if total>limit:return None
   chunks.append(chunk)
  try:proc.wait(timeout=max(0.01,deadline-time.monotonic()))
  except subprocess.TimeoutExpired:return None
  return b''.join(chunks) if proc.returncode==0 else None
 finally:
  if proc.poll() is None:
   proc.kill()
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:pass
  try:proc.stdout.close()
  except (OSError,ValueError):pass
  try:
   if proc.stdin and not proc.stdin.closed:proc.stdin.close()
  except (OSError,ValueError):pass
