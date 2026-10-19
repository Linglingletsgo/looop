"""Packet-driven bounded delivery, using explicit per-project execution policies."""
import fcntl,hashlib,json,pathlib,re,shutil,subprocess,uuid,time
from runtime import ROOT
from repository import git,snapshot
from executor import command
from sandbox import run
from gates import GateError,require_pr,update_target
from output_protocol import delivery_schema
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
 if any(s.get('provider','codex') not in ('codex','commandcode','claude_subscription','magpie_chatgpt','magpie_deepseek') for s in policy.get('workflow',[])):raise GateError('Unapproved provider')
 for argv in policy['checks']:
  if not isinstance(argv,list) or not argv or not all(isinstance(x,str) and x for x in argv):raise GateError('Unsupported check executable')
 if not 1<=len(packet['allowed_paths'])<=20:raise GateError('Invalid write scope')
 for name in packet['allowed_paths']:
  p=pathlib.PurePosixPath(name)
  if p.is_absolute() or not name or any(x in ('.','..','.git','node_modules','.paperclip','.agents','.codex','.agent') for x in p.parts):raise GateError('Invalid scope '+name)
  if any(x.startswith('.env') for x in p.parts) or p.suffix in ('.key','.pem','.db','.sqlite'):raise GateError('Secret/data scope forbidden')
  if p.name.lower() in ('agents.md','agent.md','handoff.md') or name.startswith('docs/project/agent-roles/'):raise GateError('Rules/handoff not writable')
  if policy.get('scope_mode')!='task_paths' and name not in policy['allowed_paths']:raise GateError('Path outside project execution policy: '+name)
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
  if set(p.relative_to(root).parts)&{'.git','node_modules','.venv','__pycache__','.pytest_cache','.next','dist','build','coverage'}:continue
  if p.is_symlink():raise GateError('Symlink output refused')
  if p.is_file():result[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return result

def check_result(text):
 from gates import verdict
 return verdict(text)

def saved_result(report,stage='build'):
 # Modern runs hand off through a file; legacy attempts retain their original transport.
 repaired=report.parent/'repaired-result.json'
 if repaired.is_file() and not repaired.is_symlink():return check_result(repaired.read_text())
 path=report.parent/'handoff.json'
 if path.exists() or path.is_symlink() or (report.parent/'handoff.schema.json').exists():
  from handoff import read
  schema=json.loads((report.parent/'handoff.schema.json').read_text())
  identity={'version':1,'run_id':report.parent.name,'nonce':schema['properties']['nonce']['enum'][0]}
  result=read(report.parent,delivery_schema(stage),identity)
  return check_result(json.dumps(result,ensure_ascii=False))
 return check_result(report.read_text())

def check_context(target,checks,receipt):
 # Successful output is evidence on disk, not repeated prompt context.
 return ('\nVerification Agent receipt: '+json.dumps({'target_sha':target,'receipt_path':str(receipt),'checks':[{'argv':c['argv'],'exit_code':c['exit_code']} for c in checks]},ensure_ascii=False)+
  '\nThese checks already ran on this exact target. Read the receipt for full output when needed. Run additional targeted checks for a specific suspected defect or project requirement; do not repeat the full suite solely for confirmation.\n')

def review_navigation(candidate,baseline,target,previous,folder):
 changed=git(candidate,'diff','--name-status',baseline,target).decode().strip()
 text='\nReview navigation (controller facts, not an approval):\nFull change: git diff '+baseline+' '+target+'\nChanged files:\n'+changed+'\n'
 if previous and previous.get('target_sha') and previous.get('run_id'):
  prior=previous['target_sha']
  git(candidate,'merge-base','--is-ancestor',prior,target)
  report=folder/previous['run_id']/'validated-result.json'
  text+='Previous independent review at '+prior+'; verdict '+previous['verdict']+'. Full findings: '+str(report)+'\n'
  text+='Prior findings (navigation only): '+json.dumps(previous.get('findings',[]),ensure_ascii=False)[:6000]+'\n'
  if prior!=target:text+='Repair delta: git diff '+prior+' '+target+'\n'
 text+=('Start with the diff and trace changed behavior into relevant callers and tests. For re-review, verify prior findings and repair regressions first, then independently assess the complete baseline-to-target change. Prior approval never approves a new SHA. '
  'Read focused ranges; expand only to resolve a concrete correctness question. Conclude when requirements, changed paths and relevant failure cases are covered; do not keep searching solely to produce more findings. No Builder conversation is supplied.\n')
 return text

def execute(packet,policy,job,emit=print,publish=True,resume_review=False,resume_builder=False):
 validate(packet,policy)
 if resume_review and resume_builder:raise GateError('Choose one resume stage')
 from execution_settings import read as read_settings,route as execution_route
 execution_settings=read_settings(ROOT)
 # No explicit owner settings yet: keep existing project provider mappings.
 if not execution_settings.get('revision'):execution_settings=None
 task_guard(ROOT,job)
 if not re.fullmatch('[a-zA-Z0-9-]{1,80}',job):raise GateError('Invalid job id')
 repo=pathlib.Path(policy['repo']).resolve();sha=packet['baseline_sha']
 common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
 lockpath=ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest();lockpath.parent.mkdir(parents=True,exist_ok=True)
 with lockpath.open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'state':'queued','reason':'repository busy'}
  root=ROOT/'data/deliveries'/job;statefile=root/'state.json'
  resumed=None
  if statefile.exists():
   old=json.loads(statefile.read_text())
   if not (resume_review or resume_builder):emit('Existing attempt: '+old['state']+'; no replay');return old
   from process_owner import alive
   candidate=root/'candidate';target=old.get('target_sha')
   stage_ok=old.get('failed_stage')=='building' if resume_builder else old.get('failed_stage','').startswith('review_')
   if old['state']!='blocked' or not stage_ok or old.get('pr_url') or alive(old.get('owner')) is not False:raise GateError('Review resume requires an unpublished stopped review worker' if not resume_builder else 'Builder resume requires an unpublished stopped build worker')
   if resume_builder:
    pending=old.get('pending_builder',{})
    if not re.fullmatch(r'[a-zA-Z0-9-]+',pending.get('run_id','')) or pending.get('workspace')!='build-'+str(old['round']) or pending.get('previous_target')!=target:raise GateError('Missing original Builder receipt')
    source=root/pending['workspace'];report=root/pending['run_id']/'result.md'
    if saved_result(report)['verdict']!='approved':raise GateError('Builder did not report ready; no format-only resume')
    before=tree(candidate);after=tree(source)
    changes={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)}
    if not changes or not changes<=set(packet['allowed_paths']):raise GateError('Preserved Builder changes outside Packet scope')
   if old.get('failure',{}).get('category')!='model_output' and not old.get('error','').startswith(('Expecting value:','Extra data:','invalid review output','Expected one JSON object','Invalid JSON fence','Ambiguous conclusions outside JSON')):raise GateError('Only review output format failures can resume without Builder')
   if old.get('review_resume_count',0)>=2:raise GateError('Review resume budget exhausted')
   if json.loads((root/'packet.json').read_text())!=packet or json.loads((root/'policy.json').read_text())!=policy:raise GateError('Resume contract or policy changed')
   if git(candidate,'rev-parse','HEAD').decode().strip()!=target or git(candidate,'status','--porcelain').strip():raise GateError('Resume candidate changed or dirty')
   git(candidate,'merge-base','--is-ancestor',sha,target)
   changed=set(git(candidate,'diff','--name-only',sha,target).decode().splitlines())
   if (not changed and not resume_builder) or not changed<=set(packet['allowed_paths']):raise GateError('Resume outside Packet scope')
   from lifecycle import save
   save(root/('review-resume-'+str(old.get('review_resume_count',0)+1)+'.json'),old)
   resumed=old
  elif resume_review or resume_builder:raise GateError('No failed review to resume')
  if git(repo,'rev-parse','HEAD').decode().strip()!=sha:raise GateError('Baseline moved; regenerate Packet')
  root.mkdir(parents=True,exist_ok=bool(resumed),mode=0o700)
  from process_owner import identity
  state={'execution_settings':execution_settings,'owner':identity(),'state':'planning','risk':policy.get('risk','low'),'reviews':{},'acceptance':None,'job_id':job}
  if resumed:
   state.update({k:resumed[k] for k in ('round','target_sha','builder_run') if k in resumed})
   state['review_resume_count']=resumed.get('review_resume_count',0)+1
  def persist(stage):
   state['state']=stage;state['updated_at']=time.time();p=statefile.with_suffix('.tmp');p.write_text(json.dumps(state,indent=2));p.replace(statefile);record_phase(ROOT,job,phase_of(state),{'target_sha':state.get('target_sha'),'pr_url':state.get('pr_url'),'error':state.get('error')});emit(stage)
  def role(step,workspace,prompt,metadata=None):
   task_guard(ROOT,job)
   rid=step['role']+'-'+uuid.uuid4().hex[:12]
   full_prompt=contract(registry,step['role'])+'\n'+(project_context(baseline,policy['project_adapter'],step['role'],packet['allowed_paths']) if policy.get('project_adapter') else rules)+'\n'+prompt
   kwargs={'role':'builder' if step['stage']=='build' else 'readonly','provider_id':step.get('provider','codex'),'timeout':policy.get('timeout'),'git_metadata':metadata or candidate/'.git','dependencies':dependencies,'execution_route':execution_route(execution_settings,'planning' if step['stage']=='plan' else step['stage'],step.get('provider','codex'))}
   kwargs['handoff_schema']=delivery_schema(step['stage'])
   full_prompt+='\nWrite the stage result to the supplied handoff.json file. Each finding must retain severity, source location, evidence and required fix as one concise string. Chat may be natural language.'
   if step['stage']=='build':
    state.setdefault('target_sha',git(candidate,'rev-parse','HEAD').decode().strip())
    state['pending_builder']={'run_id':rid,'workspace':workspace.name,'previous_target':git(candidate,'rev-parse','HEAD').decode().strip()}
    persist('building')
    try:result=run(workspace,root/rid,full_prompt,**kwargs)
    except (__import__('output_protocol').OutputError,json.JSONDecodeError) as exc:
     from planning_runtime import invoke
     repair=root/(rid+'-handoff')
     repair_prompt='Repair ONLY this completed Builder handoff. Do not implement, edit project source, rerun checks, commit or publish. Read the original report files at '+str(root/rid)+' (handoff.json and result.md); preserve the actual verdict and all findings, including unresolved caveats. If no clear completion conclusion exists, report blocked rather than infer readiness. Write the result to your new handoff.json. Original Packet: '+json.dumps(packet,ensure_ascii=False)
     def unchanged():
      task_guard(ROOT,job)
      if git(repo,'rev-parse','HEAD').decode().strip()!=sha:raise GateError('Baseline moved during Builder handoff repair')
     options={**kwargs,'role':'readonly'}
     result=json.dumps(invoke(run,workspace,repair,repair_prompt,unchanged,validate=lambda v:check_result(json.dumps(v)),**options),ensure_ascii=False)
     # Keep the Builder identity/workspace receipt; save the independently validated handoff result.
     from lifecycle import save
     save(root/rid/'repaired-result.json',json.loads(result))
   else:
    from planning_runtime import invoke,InvalidOutput
    def checked_run(workspace,scratch,prompt,**options):
     text=run(workspace,scratch,prompt,**options)
     fresh()
     try:
      value=check_result(text)
      if 'findings' not in value:raise GateError('findings array required')
      return json.dumps(value,ensure_ascii=False)
     except (ValueError,TypeError) as exc:raise InvalidOutput('Handoff result requires verdict approved|changes_requested|blocked and findings array') from exc
    def fresh():
     task_guard(ROOT,job)
     if git(candidate,'rev-parse','HEAD').decode().strip()!=state.get('target_sha',sha):raise GateError('Review target changed')
     if git(repo,'rev-parse','HEAD').decode().strip()!=sha:raise GateError('Baseline moved during review')
    full_prompt+='\nIf correcting output format, preserve the independently assessed verdict and findings; never change a blocker into approval to satisfy the protocol.'
    result=json.dumps(invoke(checked_run,workspace,root/rid,full_prompt,fresh,**kwargs),ensure_ascii=False)
    recovery=root/(rid+'-recovery.json')
    if recovery.exists():rid+='-retry-'+str(json.loads(recovery.read_text())['attempts']-1)
   normalized=json.dumps(check_result(result),ensure_ascii=False)
   (root/rid).mkdir(parents=True,exist_ok=True)
   (root/rid/'validated-result.json').write_text(normalized)
   return rid,normalized
  try:
   if resumed:record_phase(ROOT,job,'queued',{'recovery_reason':'Builder output recovery without re-execution' if resume_builder else 'Review format recovery at unchanged target SHA'})
   persist('building' if resumed else 'planning')
   (root/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2))
   (root/'policy.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2))
   candidate=root/'candidate';branch='agent/delivery-'+job
   if not resumed:
    subprocess.run(['git','clone','--quiet','--no-hardlinks',str(repo),str(candidate)],check=True)
    git(candidate,'checkout','-b',branch,sha)
   baseline=snapshot(candidate,sha,root/('baseline-resume-'+str(state['review_resume_count']) if resumed else 'baseline'));registry=resolve(baseline,policy.get('project_adapter'))
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
   context='Use the existing project environment and exact configured checks; do not install dependencies. Installed host tools and linked project dependencies are available. Read targeted source ranges before implementing. Checks for the verification Agent: '+json.dumps(policy['checks'])+'\n'
   context+='Packet (already scoped by operator; do not expand):\n'+json.dumps(packet,ensure_ascii=False)+'\nThe current directory is a controller-verified baseline snapshot. Use the selected native harness and project environment. No installation, delegation, commits, push, merge or release. Existing project gates remain mandatory.\n'
   plans=[]
   for step in policy['workflow']:
    if not resumed and step['stage'] in ('plan','advisory'):
     _,result=role(step,baseline,context+'This is PRE-IMPLEMENTATION planning/advice, not acceptance of existing baseline. Unimplemented functions or failing baseline tests are the authorized work to be done, not blockers by themselves. Mark blocked only for unresolved requirements, incompatible project rules or missing prerequisites that prevent Builder from proceeding. Read-only bounded '+step['stage']+'; identify actual unresolved blockers. Write handoff.json result {"verdict":"approved|blocked","findings":[],"plan":"..."}.')
     if check_result(result)['verdict']!='approved':raise GateError('Planning blocked: '+result)
     plans.append(result)
   if resume_builder:
    pending=resumed['pending_builder'];source=root/pending['workspace'];before=tree(candidate);after=tree(source)
    changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)}
    if not changed or not changed<=set(packet['allowed_paths']):raise GateError('Preserved Builder changed before adoption')
    for name in changed:
     dest=candidate/name;origin=source/name
     if origin.is_file():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(origin,dest)
     elif dest.exists():dest.unlink()
    git(candidate,'add','--',*sorted(changed));git(candidate,'-c','core.hooksPath=/dev/null','-c','user.name=Agent Control','-c','user.email=agent-control@localhost','commit','-m',packet['title'])
    update_target(state,git(candidate,'rev-parse','HEAD').decode().strip());state['builder_run']=pending['run_id']
    artifact=root/pending['run_id']/'result.md';raw=artifact.with_name('result.raw.md')
    if not raw.exists():raw.write_text(artifact.read_text())
    (artifact.parent/'validated-result.json').write_text(json.dumps(saved_result(artifact),ensure_ascii=False))
   feedback='';buildstep=next(s for s in policy['workflow'] if s['stage']=='build')
   review_history=dict(state.get('reviews',{}))
   for roundno in range(resumed['round'] if resumed else 1,policy['max_rounds']+1):
    state['round']=roundno
    if not resumed or roundno!=resumed['round']:
     persist('building')
     workspace=snapshot(candidate,git(candidate,'rev-parse','HEAD').decode().strip(),root/f'build-{roundno}')
     before=tree(workspace)
     rid,build_result=role(buildstep,workspace,context+'Implement only allowed_paths; preserve prior assertions and behavior. Write handoff.json result {"verdict":"approved|blocked","findings":[],"summary":"..."}; approved means ready for independent checks, never approval to merge. If a production defect prevents an authorized test-only task, return blocked with evidence. Run only focused tests; a verification Agent runs the configured checks; additional roles run only when configured.\nPlans:\n'+'\n'.join(plans)+'\nFindings:\n'+feedback)
     if check_result(build_result)['verdict']=='blocked':raise GateError('Builder blocked: '+build_result)
     state.pop('pending_builder',None)
     after=tree(workspace);changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
     if not changed or not changed<=set(packet['allowed_paths']):raise GateError('No change or outside Packet scope')
     for name in changed:
      dest=candidate/name;source=workspace/name
      if source.is_file():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
      elif dest.exists():dest.unlink()
     git(candidate,'add','--',*sorted(changed));git(candidate,'-c','core.hooksPath=/dev/null','-c','user.name=Agent Control','-c','user.email=agent-control@localhost','commit','-m',packet['title'])
     target=git(candidate,'rev-parse','HEAD').decode().strip();update_target(state,target);state['builder_run']=rid
    target=state['target_sha']
    review=snapshot(candidate,target,root/(f'review-{roundno}-resume-'+str(state['review_resume_count']) if resumed else f'review-{roundno}'));persist('checking');checks=[]
    for argv in policy['checks']:
     result=command(review,argv,dependencies=dependencies,timeout=policy.get('check_timeout'));checks.append({'argv':argv,'exit_code':result.returncode,'output':result.stdout[-24000:]})
    (root/(f'checks-{roundno}-resume-'+str(state['review_resume_count'])+'.json' if resumed else f'checks-{roundno}.json')).write_text(json.dumps(checks,indent=2))
    if any(c['exit_code'] for c in checks):
     if policy.get('on_check_failure')=='stop':raise GateError('Test-only check failed; preserve evidence; Product disposition required')
     feedback=json.dumps(checks);continue
    receipt=root/(f'checks-{roundno}-resume-'+str(state['review_resume_count'])+'.json' if resumed else f'checks-{roundno}.json')
    check_summary=check_context(target,checks,receipt)
    failed=False
    for step in policy['workflow']:
     if step['stage']!='review':continue
     mode=step.get('mode','standard');persist('review_'+mode)
     rr,text=role(step,review,context+check_summary+review_navigation(candidate,sha,target,review_history.get(mode),root)+'Independently review full baseline-to-target diff. Target SHA '+target+'; baseline '+sha+'. A private copy of candidate Git metadata is available. Write handoff.json result {"verdict":"approved|changes_requested|blocked","findings":[]}. No Builder conversation shared.',metadata=candidate/'.git')
     v=check_result(text);state['reviews'][mode]={**v,'mode':mode,'run_id':rr,'target_sha':target}
     review_history[mode]=dict(state['reviews'][mode])
     if v['verdict']=='blocked':raise GateError('Review blocked: '+text)
     if v['verdict']!='approved':feedback=text;failed=True;break
    if failed:continue
    if any(s['stage']=='acceptance' for s in policy['workflow']):
     step=next(s for s in policy['workflow'] if s['stage']=='acceptance');persist('acceptance')
     ar,text=role(step,review,context+check_summary+'Independently verify acceptance criteria against target SHA '+target+' and available synthetic checks. Source visible; this is not black-box or production acceptance. Run permitted checks if useful. Write handoff.json result {"verdict":"approved|changes_requested|blocked","findings":[],"evidence":[]}.',metadata=candidate/'.git')
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
   state['error']=str(exc);state['failure']=({'category':'model_output','next_action':'修正输出协议后，从同一提交重新检查并独立审核','retryable':False} if isinstance(exc,(__import__('planning_runtime').InvalidOutput,__import__('output_protocol').OutputError,json.JSONDecodeError)) else failure(exc));state['failed_stage']=state['state'];persist('blocked');raise
