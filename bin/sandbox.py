"""Compatibility entry point: native harness processes, not a model/tool runtime."""
import contextlib,json,os,pathlib,re,shutil,signal,subprocess,threading,tomllib
from runtime import ROOT
from provider_state import pause,paused

HARNESS_IDS=('codex','claude','omp')
COMPATIBILITY={'codex':('codex','commandcode'),'omp':('codex','commandcode'),'claude':('claude_subscription',)}
FLASH='deepseek/deepseek-v4.1-flash'

def claude_subscription():
 if not shutil.which('claude'):return False
 env=os.environ.copy()
 for k in ('ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL'):env.pop(k,None)
 try:
  value=json.loads(subprocess.check_output(['claude','auth','status','--json'],env=env,text=True,stderr=subprocess.DEVNULL,timeout=15))
  return value.get('loggedIn') is True and value.get('authMethod') in ('oauth_token','oauth','claude.ai') and value.get('apiProvider')=='firstParty'
 except (OSError,ValueError,subprocess.SubprocessError):return False

@contextlib.contextmanager
def workspace_environment(workspace,dependencies=None,git_metadata=None):
 """Temporary runtime links are removed before scheduler fingerprints the source."""
 workspace=pathlib.Path(workspace).resolve();created=[]
 try:
  pairs=[]
  if dependencies:
   source=pathlib.Path(dependencies).resolve();pairs.append((workspace/'node_modules',source))
   if (source.parent/'web/node_modules').is_dir():pairs.append((workspace/'web/node_modules',source.parent/'web/node_modules'))
  for dest,source in pairs:
   if dest.resolve()==source.resolve():continue
   if dest.is_dir() and not dest.is_symlink() and not any(dest.iterdir()):dest.rmdir()
   if not dest.exists() and not dest.is_symlink():
    dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to(source,target_is_directory=True);created.append(dest)
  if git_metadata and not (workspace/'.git').exists():
   # Copy metadata: native git must never mutate the controller's candidate repository.
   dest=workspace/'.git';shutil.copytree(git_metadata,dest);created.append(dest)
   subprocess.run(['git','config','--local','core.worktree',str(workspace)],cwd=workspace,check=True,stdout=subprocess.DEVNULL)
  yield
 finally:
  for p in reversed(created):
   if p.is_symlink():p.unlink()
   elif p.is_dir():shutil.rmtree(p)

def invocation(workspace,scratch,execution_route):
 harness=execution_route.get('harness','codex');provider=execution_route['provider']
 if harness not in COMPATIBILITY or provider not in COMPATIBILITY[harness]:raise ValueError('Unsupported Harness / Token Plan combination')
 if not shutil.which(harness):raise RuntimeError('Harness not installed: '+harness)
 env=os.environ.copy();env['PATH']=str(pathlib.Path.home()/'.local/bin')+':'+env.get('PATH','/usr/bin:/bin')
 # Unattended jobs use only the selected subscription, never ambient paid API keys.
 for key in list(env):
  if key.endswith('_API_KEY') or key in ('ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL','OPENAI_BASE_URL','CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY'):env.pop(key,None)
 if provider=='claude_subscription':
  if not claude_subscription():raise RuntimeError('Claude Code subscription login required: claude auth login')
  model=execution_route.get('model')
  cmd=['claude','-p','--output-format','json','--no-session-persistence','--dangerously-skip-permissions','--permission-prompts','none']
  if model:cmd+=['--model',model]
  return cmd,env,model
 if provider=='codex':
  config=tomllib.loads((pathlib.Path.home()/'.codex/config.toml').read_text());p=config['model_providers'][config['model_provider']]
  if p.get('base_url')!='http://127.0.0.1:8317/v1':raise RuntimeError('Configure existing CLIProxyAPI subscription route first')
  token=p.get('experimental_bearer_token');base=p['base_url'];model=execution_route.get('model') or config['model']
 else:
  token=(ROOT/'secrets/commandcode.key').read_text().strip();base='https://api.commandcode.ai/provider/v1';model=FLASH
 if not token:raise RuntimeError('Subscription credential unavailable')
 env['LOOOP_PROVIDER_KEY']=token
 if harness=='codex':
  cmd=['codex','exec','--skip-git-repo-check','--ephemeral','--dangerously-bypass-approvals-and-sandbox','--json','-C',str(workspace),'-m',model,'-c','model_provider="looop-subscription"','-c','model_providers.looop-subscription='+json.dumps({'name':'Selected subscription','base_url':base,'wire_api':'responses','env_key':'LOOOP_PROVIDER_KEY'}).replace(': ', ' = '),'-o',str(scratch/'result.md'),'-']
 else:
  # Harness-owned profile keeps other user providers/hooks from selecting paid fallbacks.
  registry={'providers':{provider:{'baseUrl':base,'apiKey':'LOOOP_PROVIDER_KEY','api':'openai-responses','auth':'apiKey','authHeader':True,'models':[{'id':model,'name':model,'reasoning':False,'input':['text'],'contextWindow':128000,'maxTokens':16384}]}}}
  # Per-run model file avoids configuration races between concurrent model choices.
  profile=scratch/'omp-profile';profile.mkdir(mode=0o700,exist_ok=True);(profile/'models.yml').write_text(json.dumps(registry))
  env['PI_CODING_AGENT_DIR']=str(profile);selected=provider+'/'+model
  cmd=['omp','-p','--mode','json','--no-session','--no-title','--no-prewalk','--model',selected,'--smol',selected,'--slow',selected,'--plan',selected,'--approval-mode','yolo']
 return cmd,env,model

def final_text(harness,events):
 result='';usage={'input_tokens':0,'cached_input_tokens':0,'output_tokens':0}
 for line in events.splitlines():
  try:e=json.loads(line)
  except ValueError:continue
  if not isinstance(e,dict):continue
  if harness=='claude' and e.get('type')=='result':
   if e.get('is_error'):raise RuntimeError('Claude Code failed; inspect owner-only events.jsonl')
   result=e.get('result','');u=e.get('usage',{});usage.update({k:u.get(k,0) for k in usage})
  if e.get('type')=='turn.completed':
   for k in usage:usage[k]+=e.get('usage',{}).get(k,0)
  if harness=='omp' and e.get('type')=='message_end':
   message=e.get('message',{})
   if message.get('role')=='assistant':
    if message.get('stopReason')=='error':raise RuntimeError('OMP failed; inspect owner-only events.jsonl')
    texts=[b.get('text','') for b in message.get('content',[]) if b.get('type')=='text'];result=''.join(texts)
    u=message.get('usage',{})
    for target,source in [('input_tokens','input'),('output_tokens','output'),('cached_input_tokens','cacheRead')]:usage[target]+=u.get(source,0)
 return result,usage

def run(workspace,scratch,prompt,role='product',timeout=None,provider_id='codex',app_socket=None,git_metadata=None,dependencies=None,execution_route=None):
 scratch=pathlib.Path(scratch).resolve();scratch.mkdir(parents=True,exist_ok=True,mode=0o700);scratch.chmod(0o700)
 route=execution_route or {'harness':'codex','provider':provider_id};provider=route['provider'];harness=route.get('harness','codex')
 if paused(ROOT,provider) is not None:raise RuntimeError('Provider unavailable/quota: paused; operator resume required')
 from repository import source_fingerprint
 before=source_fingerprint(workspace) if role!='builder' else None
 cmd,env,model=invocation(pathlib.Path(workspace).resolve(),scratch,route)
 if app_socket:raise RuntimeError('Source-free acceptance transport requires a project execution adapter')
 readonly='This role is read-only. Do not modify project files. ' if role!='builder' else ''
 prompt=readonly+'Execute in the current project directory using this harness and installed project tools. Do not access scheduler credentials or other projects. No model/provider switching or paid external tools.\n'+prompt
 (scratch/'prompt.txt').write_text(prompt)
 logpath=scratch/'events.jsonl';tail=bytearray();thread_error=[]
 with workspace_environment(workspace,dependencies,git_metadata):
  proc=subprocess.Popen(cmd,cwd=workspace,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
  def drain():
   try:
    with logpath.open('wb') as log:
     while block:=proc.stdout.read1(65536):
      tail.extend(block)
      if len(tail)>4*1024*1024:del tail[:-4*1024*1024]
      if log.tell()+len(block)>4*1024*1024:log.seek(0);log.truncate();log.write(tail)
      else:log.write(block)
      log.flush()
   except Exception as exc:thread_error.append(exc)
  reader=threading.Thread(target=drain,daemon=True);reader.start()
  try:
   proc.stdin.write(prompt.encode());proc.stdin.close();proc.wait(timeout=timeout or None)
  except BaseException:
   with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   raise
  finally:
   reader.join(timeout=10)
   if reader.is_alive():
    with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGTERM)
    reader.join(timeout=5)
   if not reader.is_alive():proc.stdout.close()
   else:thread_error.append(RuntimeError('Harness left its output stream open'))
 if before is not None and source_fingerprint(workspace)!=before:raise RuntimeError('Read-only Harness modified source; result rejected')
 if thread_error:raise RuntimeError('Harness log collection failed')
 events=tail.decode(errors='replace')
 status=re.search(r'(?:HTTP(?: status)?[ :]+|status(?: code)?[ :=]+)(401|402|403|429)\b',events,re.I)
 try:result,usage=final_text(harness,events)
 except RuntimeError:
  if status:
   pause(ROOT,provider,int(status[1]),None);raise RuntimeError('Provider unavailable/quota: HTTP '+status[1]+'; inspect owner-only events.jsonl')
  raise
 if harness=='codex':
  path=scratch/'result.md'
  if path.is_symlink():raise RuntimeError('Refusing symlink result artifact')
  result=path.read_text() if path.is_file() else ''
 else:(scratch/'result.md').write_text(result)
 (scratch/'usage.json').write_text(json.dumps({'harness':harness,'provider':provider,'model':model,**usage,'remaining':'unknown'},indent=2))
 if proc.returncode or not result:
  # CLI formats differ; only explicit HTTP status evidence pauses a provider.
  status=re.search(r'(?:HTTP(?: status)?[ :]+|status(?: code)?[ :=]+)(401|402|403|429)\b',events,re.I)
  if status:
   pause(ROOT,provider,int(status[1]),None);raise RuntimeError('Provider unavailable/quota: HTTP '+status[1]+'; inspect owner-only events.jsonl')
  raise RuntimeError('Harness failed; inspect owner-only events.jsonl')
 return result
