"""Packet-driven bounded delivery, using explicit per-project execution policies."""
import fcntl,hashlib,json,pathlib,re,shutil,subprocess,uuid,time
from runtime import ROOT
from repository import git,snapshot
from executor import command
from sandbox import run
from gates import GateError,require_pr,update_target
from roles import resolve,contract,fingerprints,safe_path
from project_state import task_guard,record_phase,phase_of
from project_adapter import check_policy,context as project_context,files as adapter_files,native_files

STAGES={'plan','advisory','build','review','acceptance'}
def validate(packet,policy):
 check_policy(policy)
 if not policy.get('enabled'):raise GateError('Delivery policy disabled')
 for k in ('title','requirements','acceptance','allowed_paths','baseline_sha'):
  if not packet.get(k):raise GateError('Missing packet '+k)
 if not re.fullmatch('[0-9a-f]{40}',packet['baseline_sha']):raise GateError('Full baseline SHA required')
 if not isinstance(packet['title'],str) or '\n' in packet['title'] or packet['title'].startswith('-'):raise GateError('Invalid task title')
 if not isinstance(packet['requirements'],list) or not isinstance(packet['acceptance'],list) or not all(isinstance(x,str) and x for x in packet['requirements']+packet['acceptance']):raise GateError('Criteria must be string lists')
 if not isinstance(packet['allowed_paths'],list) or not all(isinstance(x,str) for x in packet['allowed_paths']):raise GateError('Write scope must be a list of files')
 if not 1<=policy.get('max_rounds',0)<=6:raise GateError('Invalid round limit')
 if not policy.get('checks'):raise GateError('Explicit checks required')
 if any(s.get('provider','codex') not in ('codex','commandcode') for s in policy.get('workflow',[])):raise GateError('Unapproved provider')
 for argv in policy['checks']:
  if not isinstance(argv,list) or not argv or argv[0] not in ('python3','node'):raise GateError('Unsupported check executable')
 if not 1<=len(packet['allowed_paths'])<=20:raise GateError('Invalid write scope')
 for name in packet['allowed_paths']:
  p=pathlib.PurePosixPath(name)
  if p.is_absolute() or not name or any(x in ('.','..','.git','node_modules','.paperclip','.agents','.codex','.agent') for x in p.parts):raise GateError('Invalid scope '+name)
  if any(x.startswith('.env') for x in p.parts) or p.suffix in ('.key','.pem','.db','.sqlite'):raise GateError('Secret/data scope forbidden')
  if p.name.lower() in ('agents.md','agent.md','handoff.md') or name.startswith('docs/project/agent-roles/'):raise GateError('Rules/handoff not writable')
  if name not in policy['allowed_paths']:raise GateError('Path outside project execution policy: '+name)
 steps=policy.get('workflow',[])
 if not steps or any(s.get('stage') not in STAGES or not s.get('role') for s in steps):raise GateError('Explicit workflow required')
 modes=[s.get('mode','standard') for s in steps if s['stage']=='review']
 if len(modes)!=len(set(modes)):raise GateError('Review modes must be distinct')
 stages=[s['stage'] for s in steps]
 if stages.count('build')!=1 or stages.count('review')<1 or stages.count('acceptance')>1:raise GateError('One builder and independent review required; at most one optional acceptance')
 build=stages.index('build')
 if (stages.count('acceptance') and stages[-1]!='acceptance') or stages[-1] not in ('review','acceptance') or any(i<build for i,s in enumerate(stages) if s in ('review','acceptance')) or any(s in ('plan','advisory') for s in stages[build+1:]):raise GateError('Unsupported workflow order')
 if policy.get('risk','low') not in ('low','high'):raise GateError('Invalid risk')
 if policy.get('risk')=='high' and not any(s.get('mode')=='adversarial' for s in steps if s['stage']=='review'):raise GateError('High risk requires adversarial review')
 if not any(s.get('mode','standard')=='standard' for s in steps if s['stage']=='review'):raise GateError('Standard review required')
 if policy.get('github_repo') and not re.fullmatch(r'[\w.-]+/[\w.-]+',policy['github_repo']):raise GateError('Invalid GitHub repository')

def tree(root):
 result={}
 for p in pathlib.Path(root).rglob('*'):
  if p.is_symlink():raise GateError('Symlink output refused')
  if p.is_file():result[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return result

def check_result(text):
 from gates import verdict
 return verdict(text)

def execute(packet,policy,job,emit=print,publish=True):
 validate(packet,policy)
 task_guard(ROOT,job)
 if not re.fullmatch('[a-zA-Z0-9-]{1,80}',job):raise GateError('Invalid job id')
 repo=pathlib.Path(policy['repo']).resolve();sha=packet['baseline_sha']
 common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
 lockpath=ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest();lockpath.parent.mkdir(parents=True,exist_ok=True)
 with lockpath.open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'state':'queued','reason':'repository busy'}
  root=ROOT/'data/deliveries'/job;statefile=root/'state.json'
  if statefile.exists():
   old=json.loads(statefile.read_text());emit('Existing attempt: '+old['state']+'; no replay');return old
  if git(repo,'rev-parse','HEAD').decode().strip()!=sha:raise GateError('Baseline moved; regenerate Packet')
  root.mkdir(parents=True,mode=0o700)
  from process_owner import identity
  state={'owner':identity(),'state':'planning','risk':policy.get('risk','low'),'reviews':{},'acceptance':None,'job_id':job}
  def persist(stage):
   state['state']=stage;state['updated_at']=time.time();p=statefile.with_suffix('.tmp');p.write_text(json.dumps(state,indent=2));p.replace(statefile);record_phase(ROOT,job,phase_of(state),{'target_sha':state.get('target_sha'),'pr_url':state.get('pr_url'),'error':state.get('error')});emit(stage)
  def role(step,workspace,prompt,metadata=None):
   task_guard(ROOT,job)
   rid=step['role']+'-'+uuid.uuid4().hex[:12]
   result=run(workspace,root/rid,contract(registry,step['role'])+'\n'+(project_context(baseline,policy['project_adapter'],step['role'],packet['allowed_paths']) if policy.get('project_adapter') else rules)+'\n'+prompt,
    role='builder' if step['stage']=='build' else 'readonly',provider_id=step.get('provider','codex'),timeout=policy.get('timeout'),git_metadata=metadata,dependencies=dependencies)
   return rid,result
  try:
   persist('planning')
   (root/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2))
   (root/'policy.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2))
   candidate=root/'candidate';subprocess.run(['git','clone','--quiet','--no-hardlinks',str(repo),str(candidate)],check=True)
   branch='agent/delivery-'+job;git(candidate,'checkout','-b',branch,sha)
   baseline=snapshot(candidate,sha,root/'baseline');registry=resolve(baseline,policy.get('project_adapter'))
   if (baseline/'.agent/project.json').exists() and not policy.get('project_adapter'):raise GateError('Project manifest must be mapped into execution policy before running')
   if policy.get('role_registry') and policy['role_registry']!=fingerprints(registry):raise GateError('Project role baseline differs from configured policy')
   for name,digest in policy.get('workflow_evidence',{}).items():
    if hashlib.sha256(safe_path(baseline,name).read_bytes()).hexdigest()!=digest:raise GateError('Workflow evidence changed: '+name)
   # Project workflow requirements must be explicitly mapped rather than silently replaced.
   for name in ('docs/project/single-developer-workflow.md','docs/project/agent-os-convergence-policy.md'):
    f=baseline/name
    if f.is_file() and policy.get('workflow_evidence',{}).get(name)!=hashlib.sha256(f.read_bytes()).hexdigest():raise GateError('Project workflow mapping/hash absent: '+name)
   if registry['workflow'] is not None and registry['workflow']!=policy['workflow']:raise GateError('Project workflow differs from execution policy')
   for step in policy['workflow']:contract(registry,step['role'])
   protected=set(native_files(baseline,packet['allowed_paths']))
   if policy.get('project_adapter'):protected.update(adapter_files(policy['project_adapter']))
   protected.update({r['source'][8:].split('#')[0] for r in registry['roles'].values() if r['source'].startswith('project:')})
   if (protected|set(policy.get('workflow_evidence',{}))).intersection(packet['allowed_paths']):raise GateError('Role definitions are not implementation scope')
   (root/'roles.json').write_text(json.dumps(fingerprints(registry),ensure_ascii=False,indent=2))
   rules='\n'.join('PROJECT RULES '+n+'\n'+(baseline/n).read_text() for n in dict.fromkeys(['AGENTS.md','AGENT.md','Agent.md','agents.md','docs/project/single-developer-workflow.md','docs/project/agent-os-convergence-policy.md',*policy.get('workflow_evidence',{})]) if (baseline/n).is_file())
   dependencies=pathlib.Path(policy['dependencies']) if policy.get('dependencies') else None
   context='Execution environment: Node and python3 are available when dependencies are mounted; npm/npx are not exposed. Use the exact controller check argv below, not npm/npx or installation. For Vitest focused runs insert the target test path into the configured command; keep --configLoader=runner and --no-cache. Do not add shell timeout wrappers. Read targeted source ranges before implementing; avoid repeatedly exploring the same files. Controller checks: '+json.dumps(policy['checks'])+'\n'
   context+='Packet (already scoped by operator; do not expand):\n'+json.dumps(packet,ensure_ascii=False)+'\nSource /workspace is a controller-verified baseline snapshot. No host credentials/network. No installation, delegation, commits, push, merge or release. Existing project gates remain mandatory.\n'
   plans=[]
   for step in policy['workflow']:
    if step['stage'] in ('plan','advisory'):
     _,result=role(step,baseline,context+'This is PRE-IMPLEMENTATION planning/advice, not acceptance of existing baseline. Unimplemented functions or failing baseline tests are the authorized work to be done, not blockers by themselves. Mark blocked only for unresolved requirements, incompatible project rules or missing prerequisites that prevent Builder from proceeding. Read-only bounded '+step['stage']+'; identify actual unresolved blockers. Return JSON {"verdict":"approved|blocked","findings":[],"plan":"..."}.')
     if check_result(result)['verdict']!='approved':raise GateError('Planning blocked: '+result)
     plans.append(result)
   feedback='';buildstep=next(s for s in policy['workflow'] if s['stage']=='build')
   for roundno in range(1,policy['max_rounds']+1):
    state['round']=roundno;persist('building')
    workspace=snapshot(candidate,git(candidate,'rev-parse','HEAD').decode().strip(),root/f'build-{roundno}')
    before=tree(workspace)
    rid,build_result=role(buildstep,workspace,context+'Implement only allowed_paths; preserve prior assertions and behavior. Return only JSON {"verdict":"approved|blocked","findings":[],"summary":"..."}; approved means ready for independent checks, never approval to merge. If a production defect prevents an authorized test-only task, return blocked with evidence. Run only focused tests; the controller runs the full configured checks; additional roles run only when configured.\nPlans:\n'+'\n'.join(plans)+'\nFindings:\n'+feedback)
    if check_result(build_result)['verdict']=='blocked':raise GateError('Builder blocked: '+build_result)
    after=tree(workspace);changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    if not changed or not changed<=set(packet['allowed_paths']):raise GateError('No change or outside Packet scope')
    for name in changed:
     dest=candidate/name;source=workspace/name
     if source.is_file():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
     elif dest.exists():dest.unlink()
    git(candidate,'add','--',*sorted(changed));git(candidate,'-c','core.hooksPath=/dev/null','-c','user.name=Agent Control','-c','user.email=agent-control@localhost','commit','-m',packet['title'])
    target=git(candidate,'rev-parse','HEAD').decode().strip();update_target(state,target);state['builder_run']=rid
    review=snapshot(candidate,target,root/f'review-{roundno}');persist('checking');checks=[]
    for argv in policy['checks']:
     result=command(review,argv,dependencies=dependencies,timeout=policy.get('check_timeout'));checks.append({'argv':argv,'exit_code':result.returncode,'output':result.stdout[-24000:]})
    (root/f'checks-{roundno}.json').write_text(json.dumps(checks,indent=2))
    if any(c['exit_code'] for c in checks):
     if policy.get('on_check_failure')=='stop':raise GateError('Test-only check failed; preserve evidence; Product disposition required')
     feedback=json.dumps(checks);continue
    failed=False
    for step in policy['workflow']:
     if step['stage']!='review':continue
     mode=step.get('mode','standard');persist('review_'+mode)
     rr,text=role(step,review,context+'Independently review full baseline-to-target diff. Target SHA '+target+'; baseline '+sha+'. Read-only git metadata is available. Return only JSON {"verdict":"approved|changes_requested|blocked","findings":[]}. No Builder conversation shared.',metadata=candidate/'.git')
     v=check_result(text);state['reviews'][mode]={**v,'mode':mode,'run_id':rr,'target_sha':target}
     if v['verdict']=='blocked':raise GateError('Review blocked: '+text)
     if v['verdict']!='approved':feedback=text;failed=True;break
    if failed:continue
    if any(s['stage']=='acceptance' for s in policy['workflow']):
     step=next(s for s in policy['workflow'] if s['stage']=='acceptance');persist('acceptance')
     ar,text=role(step,review,context+'Independently verify acceptance criteria against target SHA '+target+' and available synthetic checks. Source visible; this is not black-box or production acceptance. Run permitted checks if useful. Return only JSON {"verdict":"approved|changes_requested|blocked","findings":[],"evidence":[]}.',metadata=candidate/'.git')
     av=check_result(text)
     if av['verdict']=='blocked':raise GateError('Acceptance blocked: '+text)
     if av['verdict']!='approved':feedback=text;continue
     state['acceptance']={**av,'target_sha':target,'run_id':ar}
    require_pr(state,policy);persist('pr_ready')
    if publish:
     task_guard(ROOT,job)
     if not policy.get('github_repo'):raise GateError('Publication repository absent')
     remote='git@github.com:'+policy['github_repo']+'.git';git(candidate,'remote','set-url','origin',remote);git(candidate,'push','-u','origin',branch)
     body=root/'pr-body.md';body.write_text(packet['title']+'\n\n'+ '\n'.join(packet['requirements'])+'\n\nValidation: configured checks, fresh independent review passed; acceptance stage: '+('passed' if any(s['stage']=='acceptance' for s in policy['workflow']) else 'not configured')+'.\nBaseline: '+sha+'\nCandidate: '+target+'\nEvidence: '+str(root)+'\n\nMerge follows the configured project controller policy. No deployment.\n')
     gh=str(pathlib.Path.home()/'.local/bin/gh');args=[gh,'pr','list','--repo',policy['github_repo'],'--head',branch,'--state','all','--json','url'];existing=json.loads(subprocess.check_output(args))
     state['pr_url']=existing[0]['url'] if existing else subprocess.check_output([gh,'pr','create','--repo',policy['github_repo'],'--head',branch,'--base',policy.get('base_branch','main'),'--title',packet['title'],'--body-file',str(body)],text=True).strip()
     persist('waiting_for_merge')
    else:persist('validated')
    return state
   raise GateError('Round limit reached; Product disposition required')
  except Exception as exc:
   from lifecycle import failure
   state['error']=str(exc);state['failure']=failure(exc);state['failed_stage']=state['state'];persist('blocked');raise
