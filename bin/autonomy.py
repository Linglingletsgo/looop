"""Finite PM proposal -> independent Product scope approval -> existing delivery queue."""
import datetime,fcntl,hashlib,json,pathlib,subprocess,time,uuid
from board import ROOT,Board
from tracker import open_tracker,as_tracker
from bridge import git,snapshot,validate_profile
from roles import resolve,contract,fingerprints
from sandbox import run
from delivery import validate
from lifecycle import save
from project_state import configured_store,Conflict
from provider_state import paused
from planning_runtime import invoke
from process_owner import identity
from planning_intervention import unresolved,blocked_patch
from planning_sources import source_intents,saved_proposal
from product_goals import EXPERIENCE_INSTRUCTIONS,planning_context
from source_evidence import verify_completion
from product_goals import active as active_goal,proposal as goal_proposal,INSTRUCTIONS as GOAL_INSTRUCTIONS
from product_research import perform as research,brief as research_brief,ResearchIncomplete
from task_selection import backlog_sources,backlog_items,check_source,instructions

def planning_state(shared,loop):
 # Only effective constraints cross stages; drafts and unrelated demands are not execution input.
 intents={k:{n:v[n] for n in ('id','kind','status','title','body','target_task','supersedes') if n in v} for k,v in shared['intents'].items() if (v['status']=='ready' and v['kind']=='decision') or (v['status']=='waiting_decision' and v['kind']=='change')}
 return {'planning_revision':shared['planning_revision'],'intents':intents,'execution_control':{k:loop[k] for k in ('mode','selection_mode') if k in loop}}

def recheck_at(previous,mode):
 if mode!='continuous' or previous.get('state')=='queued':return None
 return 0


def planning_evidence(root,lane,repo,sha,shared):
 root=pathlib.Path(root);result={'baseline_sha':sha,'deliveries':[]};goal_test_paths=set()
 def ancestor(target):
  return isinstance(target,str) and subprocess.run(['git','merge-base','--is-ancestor',target,sha],cwd=repo,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
 head=root/'data/mainline-verification'/(lane+'.json')
 if head.exists():
  value=json.loads(head.read_text())
  if value.get('sha')==sha and value.get('status')=='passed':
   result['mainline']={'sha':sha,'status':'passed','receipt_path':str(head),'checks':[{'argv':c['argv'],'exit_code':c['exit_code']} for c in value.get('checks',[])]}
 goal=active_goal(shared)
 tasks=(shared or {}).get('tasks',{})
 for job,t in tasks.items():
  if not goal or t.get('goal_id')!=goal['id']:continue
  folder=root/'data/deliveries'/job;path=folder/'state.json'
  if not path.exists():continue
  state=json.loads(path.read_text())
  if state.get('state')!='merged' or not ancestor(state.get('mainline_verified')):continue
  checks=folder/('checks-'+str(state['round'])+('-resume-'+str(state['review_resume_count']) if state.get('review_resume_count') else '')+'.json')
  if not checks.exists():continue
  rows=json.loads(checks.read_text())
  if not rows or any(c['exit_code'] for c in rows):continue
  binding=root/'data/delivery-bindings'/(job+'.json')
  if binding.exists():
   bound=json.loads(binding.read_text())
   if bound.get('lane')==lane:
    for name in bound.get('packet',{}).get('allowed_paths',[]):
     if name.endswith(('.test.ts','.test.js','.test.tsx','.test.jsx','.spec.ts','.spec.js')):
      from project_adapter import safe_file
      safe_file(repo,name)
      goal_test_paths.add(name)
  result['deliveries'].append({'task_id':job,'target_sha':state['target_sha'],'mainline_verified':state['mainline_verified'],'receipt_path':str(checks),'checks':[{'argv':c['argv'],'exit_code':c['exit_code']} for c in rows]})
 result['goal_checks']=[]
 for receipt in result['deliveries']:
  for check in receipt['checks']:
   if check['argv'] not in result['goal_checks']:result['goal_checks'].append(check['argv'])
 result['deliveries']=result['deliveries'][-6:]
 result['agent_checks']=[]
 for path in sorted((root/'data/agent-checks'/lane).glob('*/state.json'),key=lambda p:p.stat().st_mtime,reverse=True):
  value=json.loads(path.read_text())
  if value.get('sha')!=sha or value.get('lane')!=lane or value.get('executor')!='native-agent' or value.get('state') not in ('validated','blocked'):continue
  result['agent_checks'].append({k:value[k] for k in ('sha','argv','exit_code')})
  result['agent_checks'][-1].update(receipt_path=str(path),summary=value.get('output','')[-3000:])
  if len(result['agent_checks'])>=6:break
 return result


VALUE_INSTRUCTIONS="""Before dispatch, assess value against current code and verified evidence. Identify the concrete problem, observable gain and why this slice matters now. A missing test alone is not a defect or material improvement. Test work needs an evidenced failure/risk or a necessary contribution to the selected outcome. Bug fixes, reliability, security and infrastructure are valid outcomes. Do not claim user demand from coverage gaps or invent impact. If the allowed scope cannot deliver meaningful progress, return no_work. Assess materiality with problem, observable_gain and why_now; material=false means no dispatch. This assessment is a claim to support with evidence, not proof by itself."""

def validate_value(value):
 if not isinstance(value,dict):raise ValueError('PM response must be an object')
 if value.get('action')!='task':return
 assessment=value.get('value_assessment')
 if not isinstance(assessment,dict) or type(assessment.get('material')) is not bool:raise ValueError('Explicit material value assessment required')
 for field in ('problem','observable_gain','why_now'):
  if not isinstance(assessment.get(field),str) or not assessment[field].strip() or len(assessment[field])>1200:raise ValueError('Concise value assessment requires '+field)

def checked_proposal(value,mandate,repo,sha,history):
 if not isinstance(value,dict) or value.get('action') not in ('task','no_work'):raise ValueError('PM must return task or no_work')
 if value['action']=='no_work':
  if not value.get('reason'):raise ValueError('No-work needs rationale')
  return None
 validate_value(value)
 if not value['value_assessment']['material']:return None
 if not isinstance(value.get('value'),str) or len(value['value'])<30:raise ValueError('Specific product value required; no token-filling tasks')
 p=value.get('packet',{});allowed=mandate.get('allowed_paths')
 if not p.get('allowed_paths') or allowed is not None and any(n not in allowed for n in p['allowed_paths']):raise ValueError('Outside autonomous mandate')
 if len(p['allowed_paths'])>mandate.get('max_files',20):raise ValueError('Too many files')
 # Only a fixed Packet schema crosses the model/controller boundary.
 packet={k:p[k] for k in ('title','requirements','acceptance','allowed_paths')};packet['baseline_sha']=sha
 if any(not isinstance(n,str) or len(n)>2000 for n in packet['requirements']+packet['acceptance']):raise ValueError('Invalid criteria')
 references=value.get('evidence',[])
 if not references:raise ValueError('Current source evidence required')
 for item in references:
  name=item['path'];path=pathlib.Path(repo)/name
  if allowed is not None and name not in mandate.get('evidence_paths',[])+allowed+mandate.get('backlog_paths',[]):raise ValueError('Unsupported evidence source')
  from project_adapter import safe_file
  safe_file(repo,name)
  if path.is_symlink() or not path.is_file():raise ValueError('Invalid evidence file')
  if not isinstance(item.get('quote'),str) or not item['quote'].strip() or len(item['quote'])>12000:raise ValueError('Bounded source reference required')
 key=hashlib.sha256(json.dumps({'requirements':packet['requirements'],'acceptance':packet['acceptance'],'paths':sorted(packet['allowed_paths'])},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if key in history:raise ValueError('Duplicate Packet fingerprint')
 return packet,key

def slots(root,lane,mandate,now=None,human=False):
 now=time.time() if now is None else now
 for p in (root/'data/delivery-bindings').glob('*.json'):
  d=json.loads(p.read_text())
  if d['lane']!=lane:continue
  f=root/'data/deliveries'/p.stem/'state.json'
  if not f.exists():return 'Bound task waiting for dispatch'
  s=json.loads(f.read_text())
  if s['state'] not in ('merged','validated','closed'):return 'Existing delivery '+s['state']
  if s['state']=='merged' and not s.get('mainline_verified'):return 'Post-merge verification pending'
 from execution_settings import read as read_settings
 settings=read_settings(root)
 if settings.get('revision'):
  from execution_settings import route
  policy_path=root/'data/delivery-policies'/(lane+'.json')
  workflow=json.loads(policy_path.read_text()).get('workflow',[]) if policy_path.exists() else []
  stages={'planning'}|{'planning' if s['stage']=='plan' else s['stage'] for s in workflow}
  providers={route(settings,stage)['provider'] for stage in stages}
 else:providers={'codex','commandcode'}
 for name in providers:
  if paused(root,name) is not None:return 'Provider paused: '+name
 jobs=list((root/'data/autonomy'/lane).glob('*/state.json'))
 day=datetime.datetime.fromtimestamp(now,datetime.timezone.utc).strftime('%Y-%m-%d')
 count=sum((v:=json.loads(f.read_text())).get('day')==day and v.get('origin','autonomous_discovery')=='autonomous_discovery' and not v.get('planning_restarts',0) for f in jobs)
 limit=mandate.get('max_proposals_per_day')
 if not human and limit is not None and count>=limit:return 'Daily autonomous discovery budget reached'
 for _,attempt in unresolved(root,lane):
  if attempt.get('state')=='blocked':return 'PM 规划受阻：'+str(attempt.get('error') or attempt.get('reason') or '需核对规划记录')[:2000]
  return 'Unresolved planning attempt; inspect before replay'
 return None

def next_intent(shared):
 if not shared:return None
 goal=active_goal(shared)
 if goal:
  return next((shared['intents'][i] for i in goal.get('intent_ids',[]) if i in shared['intents']),None)
 order={'urgent':0,'high':1,'normal':2,'low':3}
 items=[i for i in shared['intents'].values() if i['status']=='ready' and i['kind'] in ('requirement','propose')]
 return min(items,key=lambda i:(order[i['priority']],i['created_at'],i['id'])) if items else None

def retry_connection(root,lane,tracker,agent,now=None):
 tracker=as_tracker(tracker,root)
 from recovery import prepare
 now=time.time() if now is None else now
 for path in (root/'data/delivery-bindings').glob('*.json'):
  d=json.loads(path.read_text())
  if d['lane']!=lane:continue
  f=root/'data/deliveries'/path.stem/'state.json'
  if not f.exists():continue
  state=json.loads(f.read_text());attempt=d.get('connection_retries',0)
  if state['state']!='blocked' or not state.get('failure',{}).get('retryable') or state.get('pr_url') or attempt>=2:continue
  if state.get('failed_stage') not in ('planning','building','review_standard','acceptance'):continue
  if now-state.get('updated_at',now)<120:return False
  if tracker.role_running(agent):return False
  prepare(root,path.stem,'连接故障自动接续 '+str(attempt+1)+'/2；全部门禁重验')
  d=json.loads(path.read_text());d['connection_retries']=attempt+1;save(path,d)
  tracker.update(path.stem,status='todo',assignee=agent,comment='连接故障有限接续 '+str(attempt+1)+'/2；历史草稿与证据保留，重新执行检查和独立审核。')
  return True
 return False

def tick(lane):
 mandate_path=ROOT/'data/autonomy-policies'/(lane+'.json')
 if not mandate_path.exists():return
 mandate=json.loads(mandate_path.read_text())
 from loop_control import settle,view,claim,finish_without_attempt
 mode=settle(ROOT,lane)
 if not mode['allowed'] or mode['mode']=='paused' or mode['mode']=='once' and mode.get('attempt'):return
 mandate={**mandate,'enabled':True,**mode['limits']}
 if mandate.get('scope_approval','product') not in ('pm','product'):raise ValueError('Unknown configured scope approval mode')
 if lane not in json.loads((ROOT/'data/control.json').read_text())['projects']:raise ValueError('Unknown project')
 global_lock=ROOT/'data/locks'/('autonomy-'+lane);global_lock.parent.mkdir(exist_ok=True)
 with global_lock.open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  mode=view(ROOT,lane)
  if mode['mode']=='paused' or mode['mode']=='once' and mode.get('attempt'):return
  mandate={**mandate,**mode['limits']}
  s=json.loads((ROOT/'data/control.json').read_text())
  store=configured_store(ROOT)
  shared=store.context(lane) if store else None
  if store:
   try:store.project_guard(lane)
   except ValueError as exc:
    save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting_decision','reason':str(exc)});return
  revision=shared['planning_revision'] if shared else 0
  current_goal=active_goal(shared);selected=next_intent(shared);selected_id=selected['id'] if selected else None
  t=open_tracker(ROOT,Board);t.require_role(lane+':delivery')  # fail before any side effect
  retry_connection(ROOT,lane,t,lane+':delivery')
  if shared and not selected and not current_goal and any(i['status']=='waiting_decision' for i in shared['intents'].values()):
   reason='Confirmed requirements need scope clarification; inspect per-intent planning_reason'
   store.selection(lane,'no_work',reason)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting_decision','reason':reason});return
  pending=[json.loads(f.read_text()) for f in (ROOT/'data/autonomy'/lane).glob('*/state.json') if json.loads(f.read_text()).get('retry_pending')]
  planning_restarts=max((v.get('planning_restarts',0)+1 for v in pending if v.get('planning_revision',0)==revision and v.get('selected_intent')==selected_id),default=0)
  waiting=slots(ROOT,lane,mandate,human=selected is not None or current_goal is not None or 0<planning_restarts<=2)
  if waiting:
   if store:store.selection(lane,'blocked' if waiting.startswith('PM 规划受阻：') else 'waiting',waiting)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'blocked' if waiting.startswith('PM 规划受阻：') else 'waiting','reason':waiting,'at':time.time()});return
  s=json.loads((ROOT/'data/control.json').read_text());cfg=s['projects'][lane];profile=validate_profile(cfg['profile']);repo=pathlib.Path(cfg['repo']);sha=profile['repository_revision']
  history=[]
  for f in (ROOT/'data/autonomy'/lane).glob('*/state.json'):
   previous=json.loads(f.read_text())
   if previous.get('interrupted_planning') or mode['mode']=='continuous' and previous.get('goal_completed'):continue
   if previous.get('state') in ('queued','no_work','rejected') and previous.get('baseline_sha')==sha and previous.get('planning_revision',0)==revision and previous.get('selected_intent')==selected_id and ((not current_goal and not previous.get('goal_id')) or current_goal and previous.get('goal_id')==current_goal['id'] and previous.get('goal_completed_slices')==current_goal.get('completed_slices',0)):
    retry_at=recheck_at(previous,mode['mode'])
    if retry_at is None:
     save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'idle','reason':'Already planned this verified baseline; no repeated model calls','sha':sha});finish_without_attempt(ROOT,lane,'该版本与需求状态已完成选题；不重复调用模型。');return
   if previous.get('fingerprint'):history.append(previous['fingerprint'])
  policy=json.loads((ROOT/'data/delivery-policies'/(lane+'.json')).read_text())
  if policy.get('scope_mode')!='task_paths' and not set(mandate.get('allowed_paths',[]))<=set(policy['allowed_paths']):raise ValueError('Mandate exceeds configured delivery scope')
  common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
  with (ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
   try:fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:return
   b=open_tracker(ROOT,Board);owner=b.owner();company=cfg.get('company',s.get('company'))
   job=uuid.uuid4().hex;folder=ROOT/'data/autonomy'/lane/job;folder.mkdir(parents=True,mode=0o700)
   claim(ROOT,lane,job)
   receipt={'owner':identity(),'planning_protocol':3,'planning_restarts':planning_restarts,'origin':'human_confirmed' if selected else 'autonomous_discovery','selected_intent':selected_id,'state':'proposing','baseline_sha':sha,'planning_revision':revision,'day':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),'started_at':time.time()}
   if current_goal:receipt.update(goal_id=current_goal['id'],goal_completed_slices=current_goal.get('completed_slices',0))
   save(folder/'state.json',receipt)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'discovering','reason':'持续循环：PM 正在核验当前目标并选择下一步。' if mode['mode']=='continuous' else 'PM 正在规划本次目标。','attempt':job,'at':time.time()})
   try:
    task=b.create(lane,'planning','PM / 已确认需求：'+selected['title'] if selected else 'PM / '+('Backlog 选题' if mode['selection_mode']=='backlog_only' else 'Backlog 与需求调研'),'in_progress','按项目授权范围由PM定义需求契约；审核按项目配置执行；本轮无任务则持续模式立即重新选题，不虚构需求。',assignee='owner')
   except Exception as exc:
    receipt.update(state='blocked',error='PM issue creation outcome needs reconciliation: '+str(exc));save(folder/'state.json',receipt)
    if store:store.selection(lane,'blocked',receipt['error'])
    raise
   receipt['issue']=task['id'];save(folder/'state.json',receipt)
   for prior_path in (ROOT/'data/autonomy'/lane).glob('*/state.json'):
    if prior_path.parent==folder:continue
    prior=json.loads(prior_path.read_text())
    if prior.get('retry_pending'):prior['retry_pending']=False;prior['superseded_by']=job;save(prior_path,prior)
   try:
    if store:store.selection(lane,'discovering','PM researching the current product decision')
    workspace=snapshot(repo,sha,folder/'workspace');registry=resolve(workspace,policy.get('project_adapter'))
    if (workspace/'.agent/project.json').exists() and not policy.get('project_adapter'):raise ValueError('Project manifest must be mapped into planning policy')
    if fingerprints(registry)!=policy['role_registry']:raise ValueError('Role baseline differs')
    (folder/'roles.json').write_text(json.dumps(fingerprints(registry),ensure_ascii=False,indent=2))
    # Native rules stay verbatim; large reference/rule documents use navigable indexes.
    from project_adapter import rule_context
    rules='\n'.join(rule_context(workspace,n) for n in dict.fromkeys(['AGENTS.md','AGENT.md',*policy.get('workflow_evidence',{})]) if (workspace/n).is_file())
    if policy.get('project_adapter'):
     from project_adapter import context as project_context
     rules=project_context(workspace,policy['project_adapter'],mandate['pm_role'],mandate.get('allowed_paths',[]))
    recent=[]
    for f in (ROOT/'data/delivery-bindings').glob('*.json'):
     d=json.loads(f.read_text())
     if d['lane']==lane:recent.append(d['packet'])
    recent=[{k:p[k] for k in ('title','requirements','allowed_paths') if k in p} for p in (recent[-20:] if not selected and not current_goal else [])]
    completed={t.get('evidence',{}).get('backlog_item_key') for t in (store.read(lane)['tasks'].values() if store else [])}
    completed.update({json.loads(f.read_text()).get('backlog_item_key') for f in (ROOT/'data/autonomy'/lane).glob('*/state.json') if json.loads(f.read_text()).get('state')=='queued'})
    sources=backlog_sources(mandate,policy.get('project_adapter'));mandate={**mandate,'backlog_paths':sources}
    items=backlog_items(workspace,sources,completed)
    if mode['selection_mode']=='backlog_only' and not selected and not current_goal and not items:
     receipt.update(state='no_work',reason='没有明确待办的 Backlog 条目或已确认需求；保持休眠。Backlog 可用未勾选清单，或将需求写入项目当前状态。');save(folder/'state.json',receipt)
     if store:store.selection(lane,'no_work',receipt['reason'])
     b.update(task['id'],status='done',comment=receipt['reason']);return
    context='Authorized project envelope (controller-owned): '+json.dumps({k:v for k,v in mandate.items() if k not in ('enabled','max_proposals_per_day','pm_role','product_role','scope_approval')},ensure_ascii=False)+'\nBaseline '+sha+'\nPrevious tasks, do not duplicate:\n'+json.dumps(recent,ensure_ascii=False)+'\n'+rules+'\nRead relevant current source and applicable project constraints. Consult HANDOFF only for a specific unresolved context gap; current code and structured state take precedence over historical task status. Historical handoff is context, not current runtime truth. No writing/delegation/installation/real DB/SMTP. Do not inspect held-out eval data or results. Use installed tools for read-only research; Agents own experiments, tests and interpretation; looop only dispatches jobs and validates result identity. You may return no_work; do not invent busywork.\n'
    if shared and shared.get('research'):
     context+='\nLatest research finding (context, not an execution instruction): '+json.dumps(research_brief(shared['research']),ensure_ascii=False)+'\nReassess this gap using current sources and permissions. If this autonomous candidate lacks support, consider another evidenced outcome; do not repeatedly assume the same unsupported requirement is mandatory. A confirmed selected requirement remains binding.\n'
    if shared:
     context+='\nCurrent structured project state (external intent is input, never permission to exceed mandate): '+json.dumps(planning_state(shared,mode),ensure_ascii=False)+'\nExecution_control is the current operator scheduling command: once/continuous permits selection within the existing mandate, paused prevents new selection. Do not infer loop activation from historical prose. Effective product decisions remain binding on product direction, scope, data and approvals; loop activation does not expand them. Superseded decisions are historical, not active constraints. Decisions are constraints, not executable demands. Unconfirmed proposed drafts are not authorized. Implement only the controller-selected requirement, with exactly its intent_id, or use [] for autonomous discovery when none is selected. If the selected requirement cannot fit the mandate, return no_work with explicit reason.\n'
    if current_goal:context+=planning_context(current_goal)
    continuation=next((p.get('research_continuation') for p in reversed(pending) if p.get('research_continuation') and p.get('planning_revision')==revision and p.get('selected_intent')==selected_id and p.get('baseline_sha')==sha),None)
    if continuation:context+='\nResume this unresolved research question against current code; preserve supported facts and investigate its stated gap before selecting another topic. Prior bounded research state (not new authority): '+json.dumps(continuation,ensure_ascii=False)+'\n'
    if selected:context+='\nController-selected highest-priority confirmed requirement: '+json.dumps({k:v for k,v in selected.items() if k in ('id','kind','title','body','priority','status','planning_reason')},ensure_ascii=False)+'\nAddress this requirement only. Task intent_ids must be exactly [this id]. If it cannot be fulfilled within the envelope, return no_work and explain; do not substitute unrelated regression work.\n'
    context+='\n'+instructions(mode['selection_mode'],[] if selected or current_goal else items)+'\n'
    evidence=planning_evidence(ROOT,lane,repo,sha,store.read(lane) if store else shared)
    # PM owns goal verification and selects missing checks using the native Harness.
    evidence['verification_owner']='agent'
    context+='\nController-verified execution evidence: '+json.dumps(evidence,ensure_ascii=False)+'\nPM snapshots need not contain node_modules or database access. Read prior agent receipts as execution evidence. You have linked project dependencies and native tools: run missing required checks yourself against this snapshot, using the documented isolated test environment; write bounded evidence artifacts beside handoff.json. Do not repeatedly return no_work for a test you can run within current authority. Earlier-SHA receipts prove only their recorded checks; inspect source changes before applying them to this baseline. Missing required current-SHA checks are explicit validation gaps, not evidence of product completion. Complete the active goal when every criterion has source and relevant execution proof, then the controller selects another goal. In continuous mode no_work ends only this investigation; research resumes automatically. Never manufacture tasks to keep busy.\n'
    goal=('This is a test-only scheduler validation scope, not authorization for product implementation. Only propose a coherent regression slice supporting a concrete user outcome; if that outcome cannot be advanced meaningfully within this scope, return no_work.' if mandate.get('task_kind')=='test_only' else 'Advance one meaningful product outcome within the current project envelope. The requirement may be large; the Packet is its next coherent development slice, not a new unrelated requirement.')
    context+='\n'+EXPERIENCE_INSTRUCTIONS+'\n'
    context+='\nRuntime/experience proof artifact root (artifact-relative paths resolve here): '+str(folder/'pm')+'\n'
    prompt=context+GOAL_INSTRUCTIONS+'\n'+VALUE_INSTRUCTIONS+'\n'+goal+' Write handoff.json result {"action":"task|no_work|goal_complete","goal_id":"existing goal id for completion","completion_evidence":[{"criterion":"exact success criterion","path":"repo/file","quote":"exact supporting source"}],"backlog_item":{"path":"...","quote":"..."},"intent_ids":["intent-id"],"reason":"...","value_assessment":{"material":true,"problem":"observed problem or evidenced risk","observable_gain":"verifiable improvement","why_now":"why this slice matters now"},"value":"specific user benefit and slice contribution","evidence":[{"path":"...","quote":"exact existing source text"}],"product_goal":{"title":"plain user-facing outcome","user_value":"what improves for the user","success_criteria":["observable outcome"],"remaining":["outcomes still to implement after this slice"],"progress":"verified current progress","slice_value":"how this slice advances the outcome","experience":{"journey":"consumer journey; omit experience for non-experience or legacy active goals","before":"observed friction","after":"observable improvement","criterion":"exact experience success criterion"}},"packet":{"title":"...","requirements":["..."],"acceptance":["..."],"allowed_paths":["..."]}}. For goal_complete include exact source and relevant runtime proof for every existing success criterion. Repository proofs use kind repository and repository-relative path; execution reports use kind runtime_check, target_sha equal to Baseline, and path relative to the supplied artifact root. Never use a scheduler-root-relative path as a repository source. Experience proofs retain kind agent_walkthrough or user_test; multiple proofs per criterion are allowed. Keep at least one remaining outcome until the PM has explicitly verified whole-goal completion.'
    def fresh():
     if store:
      store.project_guard(lane)
      if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning; retry cancelled')
    from execution_settings import read as read_settings,route as execution_route
    settings=read_settings(ROOT);receipt['execution_settings']=settings;save(folder/'state.json',receipt)
    planning_route=execution_route(settings if settings.get('revision') else None,'planning','codex')
    report=None
    if not current_goal:
     report=research(run,workspace,folder,contract(registry,mandate['pm_role']),context,fresh,planning_route,policy.get('project_adapter'),public_required=not selected and not items and mode['selection_mode']=='backlog_and_research' and mandate.get('task_kind')!='test_only',dependencies=policy.get('dependencies'),checkpoint=next((p.get('research_checkpoint') for p in reversed(pending) if p.get('research_checkpoint') and p.get('planning_revision')==revision and p.get('selected_intent')==selected_id and p.get('baseline_sha')==sha),None))
     save(folder/'research.json',report)
     if store:store.record_research(lane,report,revision)
     if report['status']=='insufficient_evidence' and report.get('next_step',{}).get('kind')=='human_decision':raise ResearchIncomplete('调研尚未完成：'+report.get('recommendation','需要进一步证据')[:2000])
     if report['status']!='supported':
      value={'action':'no_work','reason':report.get('recommendation','调研证据不足，暂不发起开发。')}
     else:value=None
    else:value=None
    def validate_pm(value):
     validate_value(value)
     if value.get('action')=='goal_complete':
      if not current_goal or value.get('goal_id')!=current_goal['id']:raise ValueError('Goal completion requires the current active goal')
      verify_completion(workspace,folder/'pm',current_goal,value.get('completion_evidence'),sha,artifact_base=ROOT)
      reason=value.get('reason')
      if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ValueError('Product completion requires concise rationale')
     else:
      checked=checked_proposal(value,mandate,workspace,sha,history)
      if checked:
       source_intents(value,shared,selected,current_goal)
       validate(checked[0],policy)
       if not current_goal:check_source(value,mode['selection_mode'],selected,items)
       goal_proposal(value.get('product_goal'),current_goal)
    if value is None:
     value,source=saved_proposal(ROOT,lane,pending,sha,revision,current_goal,selected_id,fresh,validate_pm)
     if source:receipt['proposal_source']=source;save(folder/'state.json',receipt)
    if value is None:value=invoke(run,workspace,folder/'pm',contract(registry,mandate['pm_role'])+'\n'+prompt+'\nThe research phase has ended. If supported, now define the implementation Packet within the mandate; an earlier investigation-only stopping condition does not require another planning cycle. Use verification Agent receipts as observations, not merge approval.\nVerified research brief: '+json.dumps(research_brief(report or (current_goal or {}).get('research')),ensure_ascii=False),fresh,validate=validate_pm,role='readonly',timeout=None,provider_id='codex',execution_route=planning_route,dependencies=policy.get('dependencies'))
    save(folder/'proposal.json',value)
    if value.get('action')=='goal_complete':
     if not store or not current_goal or value.get('goal_id')!=current_goal['id']:raise ValueError('Goal completion requires the current active goal')
     evidence=value.get('completion_evidence',[])
     verify_completion(workspace,folder/'pm',current_goal,evidence,sha,artifact_base=ROOT)
     reason=value.get('reason')
     if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ValueError('Product completion requires concise rationale')
     store.finish_goal(lane,current_goal['id'],reason,evidence,revision)
     receipt.update(state='no_work',goal_completed=True,finished_at=time.time(),reason='产品目标已完成：'+reason);save(folder/'state.json',receipt)
     b.update(task['id'],status='done',comment=receipt['reason']);return 'continue'
    if value.get('action')=='task' and isinstance(value.get('value_assessment'),dict) and value['value_assessment'].get('material') is False:
     value={'action':'no_work','reason':value.get('reason') or value['value_assessment'].get('why_now') or '范围内没有有证据支持的实质进展。'}
    if value.get('action')=='task':
     value['product_goal']=goal_proposal(value.get('product_goal'),current_goal)
    receipt['backlog_item_key']=current_goal.get('backlog_item_key') if current_goal else check_source(value,mode['selection_mode'],selected,items)
    checked=checked_proposal(value,mandate,workspace,sha,history)
    if checked is None:
     if store:
      if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning')
      if current_goal:store.wait_goal(lane,value['reason'],revision)
      elif selected:store.defer_intent(lane,selected_id,value['reason'],revision)
     receipt['state']='no_work';receipt['finished_at']=time.time();receipt['reason']=value['reason'];save(folder/'state.json',receipt)
     if store:store.selection(lane,'no_work',value['reason'])
     b.update(task['id'],status='done',comment='本轮未选出范围内任务；持续模式立即进入下一轮调研。'+value['reason']);return 'continue'
    packet,key=checked;validate(packet,policy)
    intent_ids,decision_refs=source_intents(value,shared,selected,current_goal)
    if decision_refs:
     save(folder/'source-binding.json',{'reported_intent_ids':value.get('intent_ids',[]),'intent_ids':intent_ids,'decision_context_ids':decision_refs})
    value={**value,'intent_ids':intent_ids}
    if store and store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning; stale proposal retained, not dispatched')
    receipt['fingerprint']=key
    if mandate.get('scope_approval','product')=='product':
     receipt['state']='product_scope_review';save(folder/'state.json',receipt)
     review=context+'You are an independent Product scope approver under the user delegation above. You may approve only work within the explicit project envelope, with concrete value, source evidence, observable acceptance and no duplication. Do not expand the project envelope or approve weakening/skipping checks. Follow the project purpose and task_kind, including test-only restrictions when present. Verify PM evidence against code. Write handoff.json result {"verdict":"approved|rejected|blocked","findings":[],"reason":"..."}. Proposal:\n'+json.dumps(value,ensure_ascii=False)
     verdict=invoke(run,workspace,folder/'product',contract(registry,mandate['product_role'])+'\n'+review,fresh,role='readonly',timeout=None,provider_id='codex',execution_route=planning_route);save(folder/'scope-review.json',verdict)
     if verdict.get('verdict')!='approved':
      receipt['state']='rejected' if verdict.get('verdict')=='rejected' else 'blocked';receipt['reason']=verdict.get('reason');save(folder/'state.json',receipt)
      if store and receipt['state']=='blocked':store.selection(lane,'blocked',receipt.get('reason') or 'Product 范围审核受阻')
      b.update(task['id'],**({'status':'done','comment':'Product范围审核：'+json.dumps(verdict,ensure_ascii=False)} if receipt['state']=='rejected' else blocked_patch(receipt.get('reason') or 'Product 范围审核受阻')));return 'continue' if receipt['state']=='rejected' else None
    if mandate.get('task_kind')=='test_only':packet['requirements'].append('只增加有价值的合成回归，保留全部既有断言；如暴露生产缺陷，保留失败证据并停止，不改生产代码或削弱断言。')
    validate(packet,policy);save(folder/'packet.json',packet)
    # Persist approved scope provenance before exposing a bound task. No shell/model-supplied commands.
    receipt['state']='binding';save(folder/'state.json',receipt)
    from binding_requests import create
    binding={'lane':lane,'intent_ids':intent_ids,'packet':packet,'policy':policy,'owner':owner,'publish':True,'authorization':{'type':'project_mandate','proposal':str(folder),'scope_approval':mandate.get('scope_approval','product'),'fingerprint':key,'backlog_item_key':receipt.get('backlog_item_key'),'selection_mode':mode['selection_mode'],'product_goal':value['product_goal'],'research':report if not current_goal else current_goal.get('research')}}
    if not current_goal:
     binding['authorization']['product_goal'].update(research=report,backlog_item_key=receipt.get('backlog_item_key'))
    delivery=create(ROOT,b,folder,binding,company,{'projectId':cfg['id'],'title':packet['title'],'status':'backlog','description':'PM授权契约；来源：'+task['identifier']+'；证据 '+str(folder)},revision)
    if store:
     bound_goal=store.read(lane).get('product_goal')
     if bound_goal:receipt.update(goal_id=bound_goal['id'],goal_completed_slices=bound_goal.get('completed_slices',0))
     store.selection(lane,'queued','Packet bound; delivery controller advances')
    b.update(delivery['id'],status='todo',assignee=lane+':delivery')
    receipt.update(state='queued',delivery_issue=delivery['id']);save(folder/'state.json',receipt)
    b.update(task['id'],status='done',comment='PM范围内Packet已通过配置门禁，排入 '+delivery['identifier']+'；每次变更仍须通过项目配置的检查与审核。证据 '+str(folder))
   except Exception as exc:
    from lifecycle import failure
    if isinstance(exc,Conflict) and 'delivery' in locals() and not (ROOT/'data/delivery-bindings'/(delivery['id']+'.json')).exists():
     b.update(delivery['id'],status='cancelled',comment='外部状态在规划期间变化；未绑定执行，保留草案证据。')
    if store:store.selection(lane,'blocked',str(exc))
    if isinstance(exc,ResearchIncomplete):receipt['research_continuation']=research_brief(report)
    receipt.update(state='cancelled' if isinstance(exc,Conflict) else 'blocked',error=str(exc),failure=({'category':'research_incomplete','retryable':False,'next_action':'核对具体研究缺口、所需产品决定或来源恢复情况，再从处理选题受阻重新规划。'} if isinstance(exc,ResearchIncomplete) else failure(exc)));save(folder/'state.json',receipt)
    try:b.update(task['id'],**({'status':'cancelled','comment':str(exc)} if isinstance(exc,Conflict) else blocked_patch('自主规划暂停；无自动重放：'+str(exc))))
    except Exception as sync_exc:
     receipt['board_sync_error']=str(sync_exc)[:2000];save(folder/'state.json',receipt)
    raise

def run_loop(lane):
 from loop_control import settle,view
 while True:
  try:outcome=tick(lane)
  finally:settle(ROOT,lane)
  if outcome!='continue' or view(ROOT,lane)['mode']!='continuous':return

if __name__=='__main__':
 import sys
 run_loop(sys.argv[1])
