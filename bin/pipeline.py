"""Bounded fixture delivery PoC. Not enabled against business repositories."""
import contextlib,fcntl,hashlib,http.server,json,pathlib,re,shutil,socketserver,subprocess,threading,time,uuid
from runtime import ROOT
from repository import snapshot,git
from executor import command
from sandbox import run
from gates import validate_packet,require_reviews,update_target,require_pr,GateError

from gates import verdict

def files(root):
 result={}
 for p in pathlib.Path(root).rglob('*'):
  if p.is_symlink():raise GateError('symlink in candidate')
  if p.is_file():result[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return result

class UnixServer(socketserver.ThreadingUnixStreamServer):daemon_threads=True
@contextlib.contextmanager
def blackbox(candidate,entry):
 folder=ROOT/'data/bb'/uuid.uuid4().hex[:10];folder.mkdir(parents=True,mode=0o700)
 class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   if self.path!='/invoke':self.send_error(404);return
   n=int(self.headers.get('Content-Length','0'))
   if n>8192:self.send_error(413);return
   raw=self.rfile.read(n).decode()
   try:
    json.loads(raw);p=command(candidate,['python3',entry],timeout=10,stdin=raw)
    data=json.dumps({'exit_code':p.returncode,'output':p.stdout[:16000]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
   except Exception:self.send_error(400)
 server=UnixServer(str(folder/'app.sock'),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:yield folder/'app.sock'
 finally:server.shutdown();server.server_close();(folder/'app.sock').unlink();folder.rmdir()

def execute_fixture(packet,job_id,emit=print,publish=False):
 validate_packet(packet)
 repo=ROOT/'data/fixture-repo'
 if pathlib.Path(packet.get('repo','')).resolve()!=repo.resolve():raise GateError('PoC restricted to isolated fixture repository')
 root=ROOT/'data/pipelines'/job_id
 root.mkdir(parents=True,exist_ok=True,mode=0o700)
 statefile=root/'state.json'
 if statefile.exists():
  old=json.loads(statefile.read_text())
  if old.get('state')=='waiting_for_merge':emit('Already completed; '+old.get('pr_url',''));return old
  raise GateError('Previous run exists; inspect evidence before explicit new attempt')
 lockpath=ROOT/'data/locks/fixture';lockpath.parent.mkdir(exist_ok=True)
 with lockpath.open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  state={'job_id':job_id,'risk':packet['risk'],'state':'planning','reviews':{},'acceptance':None}
  def persist(stage):
   state['state']=stage;tmp=statefile.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2));tmp.replace(statefile);emit(stage)
  visible_packet={**packet,'repo':'/workspace'}
  def agent(role,workspace,prompt,provider='codex',app_socket=None,git_metadata=None):
   rid=role+'-'+uuid.uuid4().hex[:12]
   result=run(workspace,root/rid,prompt,role,timeout=600,provider_id=provider,app_socket=app_socket,git_metadata=git_metadata)
   return rid,result
  try:
   baseline=snapshot(repo,packet['baseline_sha'],root/'baseline')
   _,plan=agent('product',baseline,'唯一工作目录 /workspace。你是 Product。只读规划以下合成测试任务，不实现、不批准实现，给出最多10行方案：\n'+json.dumps(visible_packet,ensure_ascii=False))
   candidate=root/'candidate';subprocess.run(['git','clone','--quiet','--no-hardlinks',str(repo),str(candidate)],check=True)
   git(candidate,'checkout','-b','agent/'+job_id,packet['baseline_sha'])
   feedback=''
   for roundno in range(1,packet['max_rounds']+1):
    persist('building');workspace=snapshot(candidate,git(candidate,'rev-parse','HEAD').decode().strip(),root/f'build-{roundno}')
    before=files(workspace)
    rid,result=agent('builder',workspace,'你是 Builder。实现下列已授权的合成测试 Packet，仅可修改 allowed_paths，运行已有测试。源码在 /workspace。不得改规则/测试或创建 .git；最终简述修改。\n'+json.dumps(visible_packet,ensure_ascii=False)+'\nProduct plan:\n'+plan+'\nAdmitted findings:\n'+feedback,provider='commandcode')
    after=files(workspace);changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    if not changed or not changed<=set(packet['allowed_paths']):raise GateError('No change or outside approved write scope')
    for path in changed:
     target=candidate/path;src=workspace/path
     if src.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
     elif target.exists():target.unlink()
    git(candidate,'add','--',*sorted(changed));git(candidate,'-c','core.hooksPath=/dev/null','-c','user.name=Agent Fixture','-c','user.email=agent-fixture@localhost','commit','-m',f'fixture: {packet["bundle"]} round {roundno}')
    target=git(candidate,'rev-parse','HEAD').decode().strip();update_target(state,target);state['builder_run']=rid;state['round']=roundno;persist('checking')
    reviewspace=snapshot(candidate,target,root/f'review-{roundno}')
    checks=[]
    for args in packet['checks']:
     p=command(reviewspace,args);checks.append({'command':args,'exit_code':p.returncode,'output':p.stdout})
    (root/f'checks-{roundno}.json').write_text(json.dumps(checks,indent=2))
    if any(c['exit_code'] for c in checks):feedback='Checks failed: '+json.dumps(checks);continue
    for mode in (['standard','adversarial'] if packet['risk']=='high' else ['standard']):
     persist('review_'+mode)
     rr,report=agent('reviewer',reviewspace,'唯一工作目录 /workspace；挂载的 .git 是可信控制器提供的目标提交元数据，可运行 git rev-parse HEAD / git diff 验证。你是独立 Reviewer，mode='+mode+'。源码只读，不修改。按 Packet 认真审查实现与已有测试，可运行测试。你没有 Builder 或其它 Reviewer 对话。最终仅返回 JSON {"verdict":"approved|changes_requested|blocked","findings":[...]}。有阻塞缺陷必须 changes_requested。\nPacket:\n'+json.dumps(visible_packet,ensure_ascii=False)+'\nTarget SHA:'+target,git_metadata=candidate/'.git')
     v=verdict(report);state['reviews'][mode]={**v,'target_sha':target,'mode':mode,'run_id':rr}
     if v['verdict']=='blocked':raise GateError('Reviewer infrastructure/authority block: '+report)
     if v['verdict']!='approved':feedback=report;break
    try:require_reviews(state)
    except GateError:continue
    persist('acceptance');empty=root/'blackbox-workspace';empty.mkdir(exist_ok=True)
    with blackbox(reviewspace,packet['entry']) as sock:
     ar,report=agent('acceptance',empty,'你是 Acceptance，只能黑盒验证，当前没有源码。依据以下需求设计 synthetic cases，包括边界与错误输入。用 Python http.client.HTTPConnection 子类通过 Unix socket /app.sock 向 POST /invoke 发送 JSON 输入；响应 JSON 含 exit_code/output（output为被测程序输出）。不得访问源码，不要假定通过。最终仅返回 JSON {"verdict":"approved|changes_requested|blocked","findings":[...],"cases":[...]}。需求：\n'+json.dumps(packet['acceptance'],ensure_ascii=False),app_socket=sock)
    av=verdict(report);state['acceptance']={**av,'target_sha':target,'run_id':ar}
    require_pr(state);persist('pr_ready')
    if publish:
     origin=packet['remote'];git(candidate,'remote','set-url','origin',origin);git(candidate,'push','-u','origin','agent/'+job_id)
     body=root/'pr-body.md';body.write_text(f'Synthetic fixture only.\n\nBaseline: {packet["baseline_sha"]}\nCandidate: {target}\n\nProduct → Builder → checks → fresh standard/adversarial review → source-free black-box Acceptance passed.\n\nNo auto-merge. Evidence: {root}\n')
     url=subprocess.check_output([str(pathlib.Path.home()/'.local/bin/gh'),'pr','create','--repo',packet['github_repo'],'--head','agent/'+job_id,'--base','main','--title','Fixture: bounded agent delivery validation','--body-file',str(body)],text=True).strip();state['pr_url']=url
    persist('waiting_for_merge');return state
   raise GateError('Review/test round limit reached; Product disposition required')
  except Exception as exc:
   state['error']=str(exc);persist('blocked');raise
