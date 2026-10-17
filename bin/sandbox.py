"""Restricted local Codex launcher. No host HOME, API credentials, or host network."""
import contextlib,http.client,http.server,json,os,pathlib,socketserver,subprocess,threading,tomllib,uuid,tempfile
from runtime import ROOT,CODE_ROOT
from provider_state import pause,paused
class Gateway(socketserver.ThreadingUnixStreamServer):daemon_threads=True

def gateway_directory(root):
 path=pathlib.Path(root)/'data/gateways'/uuid.uuid4().hex[:12]
 # Linux AF_UNIX paths are limited to 107 bytes; runtime roots may be much longer.
 if len(str(path/'model.sock').encode())>100:return pathlib.Path(tempfile.mkdtemp(prefix='agent-gateway-'))
 path.mkdir(parents=True,mode=0o700);return path

def run(workspace,scratch,prompt,role='product',timeout=None,provider_id='codex',app_socket=None,git_metadata=None,dependencies=None):
 scratch=pathlib.Path(scratch);scratch.mkdir(parents=True,exist_ok=True,mode=0o700)
 if provider_id not in ['codex','commandcode']:raise RuntimeError('Unapproved provider')
 quota=ROOT/'data'/('quota-'+provider_id+'.json')
 if paused(ROOT,provider_id) is not None:raise RuntimeError('Provider unavailable/quota: paused; operator resume required')
 if provider_id=='codex':
  config=tomllib.loads((pathlib.Path.home()/'.codex/config.toml').read_text())
  provider=config['model_providers'][config['model_provider']]
  if provider.get('base_url')!='http://127.0.0.1:8317/v1':raise RuntimeError('Unapproved provider route')
  token=provider.get('experimental_bearer_token');model=config['model'];upstream='127.0.0.1';port=8317;prefix=''
 else:
  token=(ROOT/'secrets/commandcode.key').read_text().strip();model='deepseek/deepseek-v4.1-flash';upstream='api.commandcode.ai';port=443;prefix='/provider'
 if not token:raise RuntimeError('Proxy credential unavailable')
 gateway_dir=gateway_directory(ROOT)
 failed=[]
 requests=[0]
 request_lock=threading.Lock()
 class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):self.forward()
  def do_POST(self):self.forward()
  def forward(self):
   if self.path not in ['/v1/responses','/v1/models']:
    self.send_error(403);return
   with request_lock:
    requests[0]+=1
    if failed or requests[0]>80:
     self.send_error(429);return
   n=int(self.headers.get('Content-Length','0'))
   if n>8*1024*1024:self.send_error(413);return
   body=self.rfile.read(n)
   if body:
    try:
     d=json.loads(body)
     if d.get('model')!=model:self.send_error(403);return
    except ValueError:self.send_error(400);return
   conn=(http.client.HTTPSConnection if port==443 else http.client.HTTPConnection)(upstream,port,timeout=180)
   try:
    conn.request(self.command,prefix+self.path,body or None,{'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':self.headers.get('Accept','application/json'),'User-Agent':'CommandCode/1.0'})
    r=conn.getresponse()
    if r.status in (401,402,403,429):
     failed.append(r.status);pause(ROOT,provider_id,r.status,r.getheader('Retry-After'))
    self.send_response(r.status)
    self.send_header('Content-Type',r.getheader('Content-Type','application/json'));self.send_header('Connection','close');self.end_headers()
    while block:=r.read1(65536):self.wfile.write(block);self.wfile.flush()
   except (OSError,TimeoutError):
    failed.append(503)
   finally:conn.close()
 server=Gateway(str(gateway_dir/'model.sock'),Handler)
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 home=scratch/'home';home.mkdir(exist_ok=True)
 (home/'.codex').mkdir(exist_ok=True)
 # No copied auth, plugins, skills, MCP servers, or global project permissions.
 (home/'.codex/config.toml').write_text(f'''model = {json.dumps(model)}
model_provider = "bounded-proxy"
model_reasoning_effort = "medium"
approval_policy = "never"
web_search = "disabled"
[features]
unified_exec = false
[model_providers.bounded-proxy]
name = "Existing subscription proxy only"
base_url = "http://127.0.0.1:8317/v1"
wire_api = "responses"
experimental_bearer_token = "sandbox-placeholder"
''')
 (scratch/'prompt.txt').write_text(prompt)
 codex=str((pathlib.Path.home()/'.local/bin/codex').resolve())
 cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/etc','--dir','/tools','--ro-bind','/etc/ssl','/etc/ssl','--ro-bind',str(pathlib.Path(codex).parent),'/opt','--ro-bind',str(CODE_ROOT/'bin/sandbox_http.py'),'/relay.py','--ro-bind',str(gateway_dir),'/gateway', '--bind' if role=='builder' else '--ro-bind',str(pathlib.Path(workspace).resolve()),'/workspace','--bind',str(scratch.resolve()),'/scratch','--setenv','SHELL','/bin/bash','--setenv','USER','worker','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','HOME','/scratch/home','--setenv','CODEX_HOME','/scratch/home/.codex','--setenv','PATH','/opt:/bin:/usr/bin','--chdir','/workspace','/bin/bash','-c','python3 /relay.py & relay=$!; trap "kill $relay 2>/dev/null || true" EXIT; codex exec --skip-git-repo-check --ephemeral --dangerously-bypass-approvals-and-sandbox --json -o /scratch/result.md - < /scratch/prompt.txt']
 rg=(pathlib.Path.home()/'.local/bin/rg').resolve()
 if rg.exists():
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(rg),'/tools/rg','--setenv','PATH','/opt:/tools:/bin:/usr/bin']
 if git_metadata:
  (pathlib.Path(workspace)/'.git').mkdir(exist_ok=True)
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(pathlib.Path(git_metadata).resolve()),'/workspace/.git','--setenv','GIT_OPTIONAL_LOCKS','0']
 if dependencies:
  (pathlib.Path(workspace)/'node_modules').mkdir(exist_ok=True)
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(pathlib.Path(dependencies).resolve()),'/workspace/node_modules']
  node=(pathlib.Path.home()/'.local/bin/node').resolve()
  cmd[idx:idx]=['--ro-bind',str(node),'/tools/node']
 if dependencies:
  from package_tools import mount_npm
  mount_npm(cmd,agent=True)
 if dependencies and (pathlib.Path(dependencies).parent/'web/node_modules').is_dir():
  (pathlib.Path(workspace)/'web/node_modules').mkdir(parents=True,exist_ok=True)
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str((pathlib.Path(dependencies).parent/'web/node_modules').resolve()),'/workspace/web/node_modules']
 browser_root=ROOT/'data/browsers'
 browsers=list(browser_root.glob('chromium-*/chrome-linux*/chrome'))
 if browsers:
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(browser_root),'/browsers','--setenv','CHROMIUM_PATH','/browsers/'+str(browsers[0].relative_to(browser_root))]
  if pathlib.Path('/etc/fonts').exists():cmd[idx:idx]=['--ro-bind','/etc/fonts','/etc/fonts']
 if app_socket:
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(app_socket),'/app.sock']
 # The bypass is confined to the externally isolated namespace above.
 try:
  with (scratch/'events.jsonl').open('w') as log:
   proc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=timeout or None,env={'PATH':'/usr/bin:/bin'})
  result_path=scratch/'result.md'
  if result_path.is_symlink():raise RuntimeError('Refusing symlink result artifact')
  result=result_path.read_text() if result_path.is_file() else ''
  if failed:
   if set(failed)=={503}:raise RuntimeError('Model connection failed; inspect gateway/events')
   raise RuntimeError('Provider unavailable/quota: '+str(sorted(set(failed))))
  usage={'provider':provider_id,'model':model,'input_tokens':0,'cached_input_tokens':0,'output_tokens':0,'remaining':'unknown'}
  for line in (scratch/'events.jsonl').read_text().splitlines():
   try:event=json.loads(line)
   except ValueError:continue
   if event.get('type')=='turn.completed':
    for key in ['input_tokens','cached_input_tokens','output_tokens']:usage[key]+=event.get('usage',{}).get(key,0)
  (scratch/'usage.json').write_text(json.dumps(usage,indent=2))
  if proc.returncode or not result:raise RuntimeError('Harness failed; inspect owner-only events.jsonl')
  return result
 finally:
  server.shutdown();server.server_close()
  with contextlib.suppress(FileNotFoundError):(gateway_dir/'model.sock').unlink()
  gateway_dir.rmdir()
