#!/usr/bin/env python3
"""looop standalone console server."""
import argparse,http.cookies,http.server,json,pathlib,secrets,sys,threading,time,urllib.parse
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import console_auth,console_http
from console_http import is_loopback,validate_startup

PYTHON='/usr/bin/python3'
ROOT=pathlib.Path(__file__).resolve().parent.parent
BODY_LIMIT=32*1024
OUTPUT_LIMIT=1024*1024
TIMEOUT=60
REQUEST_TIMEOUT=15
MAX_CONCURRENCY=16
JSON_TYPE='application/json; charset=utf-8'
STATUS_ERROR='项目状态暂时无法读取；请保留当前页面并重试。'
ACTION_ERROR='操作结果暂时未知，请刷新状态后判断，不要重复提交。'
CONSOLE_CSP="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
LOGIN_CSP="default-src 'none'; style-src 'nonce-{nonce}'; script-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"

def _data(root):return console_http.data_root(root)

def _run(argv,cwd,data=b''):return console_http.run(argv,cwd,data,TIMEOUT,OUTPUT_LIMIT)
safe_next=console_http.safe_next
login_html=console_http.login_html

class Handler(http.server.BaseHTTPRequestHandler):
 server_version='looop';sys_version=''
 def log_message(self,format,*args):pass

 def setup(self):
  super().setup();self.connection.settimeout(self.server.request_timeout)

 def parse_request(self):
  if not super().parse_request():return False
  self.timed_out=False
  if len(self.headers.get_all('Host') or [])!=1:
   self._respond(400,b'');self.close_connection=True;return False
  self.origin=console_http.match_host(self.server.origins,self.headers.get('Host',''))
  if self.origin is None:
   self._respond(421,b'');self.close_connection=True;return False
  if not getattr(self,'_slot',False):
   if not self.server.request_slots.acquire(blocking=False):
    self._respond(503,b'');self.close_connection=True;return False
   self._slot=True
  return True

 def finish(self):
  try:super().finish()
  finally:
   if getattr(self,'_slot',False):
    self._slot=False
    try:self.server.request_slots.release()
    except ValueError:pass

 def send_error(self,code,message=None,explain=None):
  try:
   if self.request_version=='HTTP/0.9':self.request_version='HTTP/1.0'
   text=message or self.responses.get(code,('error',''))[0]
   body=text.encode('utf-8')
   self._headers(code,'text/plain; charset=utf-8',len(body),extra=(('Connection','close'),))
   if self.command!='HEAD':self.wfile.write(body)
  except OSError:pass

 def _headers(self,code,ctype,length,csp=CONSOLE_CSP,extra=()):
  self.send_response(code)
  self.send_header('Content-Type',ctype)
  self.send_header('Content-Length',str(length))
  self.send_header('Cache-Control','no-store')
  self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Referrer-Policy','same-origin')
  self.send_header('X-Frame-Options','DENY')
  self.send_header('Content-Security-Policy',csp)
  for name,value in extra:self.send_header(name,value)
  self.end_headers()

 def _respond(self,code,body,ctype=JSON_TYPE,csp=CONSOLE_CSP,extra=()):
  if isinstance(body,str):body=body.encode()
  self._headers(code,ctype,len(body),csp,extra)
  if self.command!='HEAD':self.wfile.write(body)

 def _json(self,code,value):self._respond(code,json.dumps(value,ensure_ascii=False))

 def _redirect(self,location,code=302,extra=()):
  self._headers(code,'text/plain; charset=utf-8',0,extra=extra+(('Location',location),))

 def _file(self,path,ctype):
  try:body=path.read_bytes()
  except OSError:return self._respond(404,'Not found','text/plain; charset=utf-8')
  self._respond(200,body,ctype)

 def _token(self):
  raw=self.headers.get('Cookie')
  if not raw:return None
  try:
   jar=http.cookies.SimpleCookie();jar.load(raw)
  except http.cookies.CookieError:return None
  morsel=jar.get(console_auth.COOKIE)
  return morsel.value if morsel else None

 def _authenticated(self):return self.server.insecure_local_dev or self.server.auth.validate(self._token())

 def _scheme(self):
  value=console_http.match_origin(self.server.origins,self.headers.get('Origin','')) or self.origin
  return value['scheme'] if value else 'http'

 def _same_origin(self):
  return console_http.match_origin(self.server.origins,self.headers.get('Origin','')) is not None

 def _authorized(self):
  if self._authenticated():return True
  if self._path=='/looop':self._redirect('/login?next=%2Flooop')
  else:self._json(401,{'error':'Sign in required','login':'/login?next=%2Flooop'})
  return False

 def _login_page(self,next_path,error=None,code=200):
  nonce=secrets.token_urlsafe(18);body=console_http.login_html(console_http.safe_next(next_path),error,nonce)
  self._respond(code,body,'text/html; charset=utf-8',LOGIN_CSP.format(nonce=nonce))

 def _read_body(self,length):
  try:return self.rfile.read(length)
  except (TimeoutError,OSError):
   self.timed_out=True;self.close_connection=True;return None

 def _read_form(self):
  try:length=int(self.headers.get('Content-Length'))
  except (TypeError,ValueError):return None
  if length<0 or length>8192:return None
  body=self._read_body(length)
  if body is None or len(body)!=length:return None
  try:return urllib.parse.parse_qs(body.decode('utf-8'),keep_blank_values=True)
  except UnicodeDecodeError:return None

 def _login(self):
  if self.server.insecure_local_dev:return self._redirect('/looop')
  query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
  next_path=console_http.safe_next(query.get('next',['/looop'])[0])
  if self.server.auth.validate(self._token()):return self._redirect(next_path,303)
  self._login_page(next_path)

 def _login_post(self):
  if not self._same_origin():return self._json(403,{'error':'Same-origin request required'})
  if self.server.insecure_local_dev:return self._redirect('/looop',303)
  if self.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/x-www-form-urlencoded':return self._json(415,{'error':'Form required'})
  form=self._read_form()
  if form is None:return self._respond(408,'Request Timeout','text/plain; charset=utf-8') if self.timed_out else self._json(413,{'error':'Request too large'})
  next_path=console_http.safe_next(form.get('next',['/looop'])[0]);ip=self.client_address[0]
  if not self.server.limiter.begin(ip):return self._login_page(next_path,'尝试次数过多，请稍后再试。',429)
  generation=self.server.auth.verify_password_generation(form.get('password',[''])[0])
  if generation is False:return self._login_page(next_path,'密码不正确。',401)
  self.server.limiter.succeeded(ip)
  token=self.server.auth.create_session(generation)
  cookie=f'{console_auth.COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={console_auth.COOKIE_MAX_AGE}'
  if self._scheme()=='https':cookie+='; Secure'
  self._redirect(next_path,303,(('Set-Cookie',cookie),))

 def _logout(self):
  self.server.auth.destroy(self._token())
  cookie=f'{console_auth.COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
  if self._scheme()=='https':cookie+='; Secure'
  self._redirect('/login',303,(('Set-Cookie',cookie),))

 def _status(self):
  output=_run([PYTHON,str(self.server.root/'bin/console.py')],self.server.root)
  if output is None:return self._json(503,{'error':STATUS_ERROR})
  try:value=json.loads(output.decode('utf-8'))
  except Exception:return self._json(503,{'error':STATUS_ERROR})
  if not isinstance(value,dict):return self._json(503,{'error':STATUS_ERROR})
  self._json(200,value)

 def _action(self):
  if not self._same_origin():return self._json(403,{'error':'Same-origin request required'})
  if self.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':return self._json(415,{'error':'JSON required'})
  try:length=int(self.headers.get('Content-Length'))
  except (TypeError,ValueError):return self._json(400,{'error':'Content-Length required'})
  if length>BODY_LIMIT:return self._json(413,{'error':'Request too large'})
  if length<0:return self._json(400,{'error':'Invalid Content-Length'})
  raw=self._read_body(length)
  if raw is None:return self._respond(408,'Request Timeout','text/plain; charset=utf-8')
  if len(raw)!=length:return self._json(400,{'error':'Incomplete request'})
  try:value=json.loads(raw.decode('utf-8'))
  except Exception:return self._json(400,{'error':'Invalid JSON'})
  if not isinstance(value,dict):return self._json(400,{'error':'JSON object required'})
  output=_run([PYTHON,str(self.server.root/'bin/console_actions.py')],self.server.root,json.dumps(value,ensure_ascii=False).encode())
  try:result=json.loads(output.decode('utf-8'))
  except Exception:return self._json(503,{'error':ACTION_ERROR})
  self._json(200 if isinstance(result,dict) and result.get('ok') else 409 if isinstance(result,dict) and result.get('conflict') else 422,result)

 def _method_not_allowed(self):
  self._respond(405,b'',extra=(('Allow','GET, HEAD, POST'),))

 def __getattr__(self,name):
  if name.startswith('do_'):return self._method_not_allowed
  raise AttributeError(name)

 def do_GET(self):
  self._path=urllib.parse.urlsplit(self.path).path
  if self._path=='/':return self._redirect('/looop')
  if self._path=='/login':return self._login()
  if self._path not in ('/looop','/looop-assets/app.js','/looop-assets/style.css','/api/looop/status'):return self._respond(404,'Not found','text/plain; charset=utf-8')
  if not self._authorized():return
  if self._path=='/looop':return self._file(self.server.root/'ui/index.html','text/html; charset=utf-8')
  if self._path=='/looop-assets/app.js':return self._file(self.server.root/'ui/app.js','text/javascript; charset=utf-8')
  if self._path=='/looop-assets/style.css':return self._file(self.server.root/'ui/style.css','text/css; charset=utf-8')
  self._status()

 def do_HEAD(self):self.do_GET()

 def do_POST(self):
  self._path=urllib.parse.urlsplit(self.path).path
  if self._path=='/login':return self._login_post()
  if self._path not in ('/logout','/api/looop/action'):return self._respond(404,'Not found','text/plain; charset=utf-8')
  if self._path=='/logout' and not self._same_origin():return self._json(403,{'error':'Same-origin request required'})
  if not self._authorized():return
  if self._path=='/logout':return self._logout()
  self._action()

class ConsoleServer(http.server.ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,root,insecure_local_dev=False,clock=time.time,request_timeout=None):
  self.root=pathlib.Path(root);self.data=_data(root);self.insecure_local_dev=insecure_local_dev
  self.auth=console_auth.Auth(self.data,clock);self.limiter=console_auth.RateLimiter(clock)
  self.request_timeout=REQUEST_TIMEOUT if request_timeout is None else request_timeout;self.request_slots=threading.BoundedSemaphore(MAX_CONCURRENCY)
  super().__init__(address,Handler)
  host,port=self.server_address[:2]
  self.origins=console_http.load_origins(self.data,host,port)

def make_server(root,host='127.0.0.1',port=3120,insecure_local_dev=False,clock=time.time,request_timeout=None):
 root=pathlib.Path(root).resolve();validate_startup(root,host,insecure_local_dev)
 return ConsoleServer((host,port),root,insecure_local_dev,clock,request_timeout)

def main(argv=None):
 parser=argparse.ArgumentParser()
 parser.add_argument('--host',default='127.0.0.1')
 parser.add_argument('--port',type=int,default=3120)
 parser.add_argument('--root',default=str(ROOT))
 parser.add_argument('--insecure-local-dev',action='store_true')
 args=parser.parse_args(argv)
 try:server=make_server(args.root,args.host,args.port,args.insecure_local_dev)
 except ValueError as exc:
  print(f'console-server: {exc}',file=sys.stderr);return 2
 except OSError as exc:
  print(f'console-server: 无法监听 {args.host}:{args.port}: {exc}',file=sys.stderr);return 1
 if args.insecure_local_dev:print('WARNING: 登录已禁用；仅限本机开发。',file=sys.stderr)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
 return 0

if __name__=='__main__':raise SystemExit(main())
