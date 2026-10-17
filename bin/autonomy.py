"""Finite PM proposal -> independent Product scope approval -> existing delivery queue."""
import datetime,fcntl,hashlib,json,pathlib,subprocess,time,uuid
from board import ROOT,Board
from bridge import git,snapshot,validate_profile
from roles import resolve,contract,fingerprints
from sandbox import run
from delivery import validate
from lifecycle import save
from project_state import configured_store,Conflict
from provider_state import paused
from planning_runtime import invoke
from process_owner import identity
from product_goals import active as active_goal,proposal as goal_proposal,INSTRUCTIONS as GOAL_INSTRUCTIONS
from product_research import perform as research
from task_selection import backlog_sources,backlog_items,check_source,instructions

def planning_state(shared,loop):
 return {'product_goal':shared.get('product_goal'),'planning_revision':shared['planning_revision'],'intents':{k:v for k,v in shared['intents'].items() if v['status'] not in ('withdrawn','superseded','completed')},'execution_control':{k:loop[k] for k in ('mode','run_id','selection_mode') if k in loop}}

def checked_proposal(value,mandate,repo,sha,history):
 if not isinstance(value,dict) or value.get('action') not in ('task','no_work'):raise ValueError('PM must return task or no_work')
 if value['action']=='no_work':
  if not value.get('reason'):raise ValueError('No-work needs rationale')
  return None
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
  quote=item['quote']
  if not isinstance(quote,str) or len(quote)<20 or len(quote)>2000 or quote not in path.read_text():raise ValueError('Source quote not found')
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
 for f in jobs:
  if json.loads(f.read_text()).get('state') not in ('queued','no_work','rejected','cancelled'):return 'Unresolved planning attempt; inspect before replay'
 return None

def next_intent(shared):
 if not shared:return None
 goal=active_goal(shared)
 if goal:
  return next((shared['intents'][i] for i in goal.get('intent_ids',[]) if i in shared['intents']),None)
 order={'urgent':0,'high':1,'normal':2,'low':3}
 items=[i for i in shared['intents'].values() if i['status']=='ready' and i['kind'] in ('requirement','propose')]
 return min(items,key=lambda i:(order[i['priority']],i['created_at'],i['id'])) if items else None

def retry_connection(root,lane,board,agent,now=None):
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
  if board.api('GET','/agents/'+agent)['status']=='running':return False
  prepare(root,path.stem,'连接故障自动接续 '+str(attempt+1)+'/2；全部门禁重验')
  d=json.loads(path.read_text());d['connection_retries']=attempt+1;save(path,d)
  board.api('PATCH','/issues/'+path.stem,{'status':'todo','assigneeAgentId':agent,'assigneeUserId':None,'comment':'连接故障有限接续 '+str(attempt+1)+'/2；历史草稿与证据保留，重新执行检查和独立审核。'})
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
  retry_connection(ROOT,lane,Board(),s['agents'][lane+':delivery'])
  if shared and not selected and not current_goal and any(i['status']=='waiting_decision' for i in shared['intents'].values()):
   reason='Confirmed requirements need scope clarification; inspect per-intent planning_reason'
   store.selection(lane,'no_work',reason)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting_decision','reason':reason});return
  pending=[json.loads(f.read_text()) for f in (ROOT/'data/autonomy'/lane).glob('*/state.json') if json.loads(f.read_text()).get('retry_pending')]
  planning_restarts=max((v.get('planning_restarts',0)+1 for v in pending if v.get('planning_revision',0)==revision and v.get('selected_intent')==selected_id),default=0)
  waiting=slots(ROOT,lane,mandate,human=selected is not None or current_goal is not None or 0<planning_restarts<=2)
  if waiting:
   if store:store.selection(lane,'waiting',waiting)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting','reason':waiting,'at':time.time()});return
  s=json.loads((ROOT/'data/control.json').read_text());cfg=s['projects'][lane];profile=validate_profile(cfg['profile']);repo=pathlib.Path(cfg['repo']);sha=profile['repository_revision']
  history=[]
  for f in (ROOT/'data/autonomy'/lane).glob('*/state.json'):
   previous=json.loads(f.read_text())
   if previous.get('interrupted_planning'):continue
   if previous.get('baseline_sha')==sha and previous.get('planning_revision',0)==revision and previous.get('selected_intent')==selected_id and (not current_goal or previous.get('goal_id')==current_goal['id'] and previous.get('goal_completed_slices')==current_goal.get('completed_slices',0)):
    save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'idle','reason':'Already planned this verified baseline; no repeated model calls','sha':sha});finish_without_attempt(ROOT,lane,'该版本与需求状态已完成选题；不重复调用模型。');return
   if previous.get('fingerprint'):history.append(previous['fingerprint'])
  policy=json.loads((ROOT/'data/delivery-policies'/(lane+'.json')).read_text())
  if policy.get('scope_mode')!='task_paths' and not set(mandate.get('allowed_paths',[]))<=set(policy['allowed_paths']):raise ValueError('Mandate exceeds configured delivery scope')
  common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
  with (ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
   try:fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:return
   b=Board();owner=b.api('GET','/auth/get-session')['user']['id'];company=cfg.get('company',s.get('company'))
   job=uuid.uuid4().hex;folder=ROOT/'data/autonomy'/lane/job;folder.mkdir(parents=True,mode=0o700)
   claim(ROOT,lane,job)
   receipt={'owner':identity(),'planning_restarts':planning_restarts,'origin':'human_confirmed' if selected else 'autonomous_discovery','selected_intent':selected_id,'state':'proposing','baseline_sha':sha,'planning_revision':revision,'day':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),'started_at':time.time()}
   if current_goal:receipt.update(goal_id=current_goal['id'],goal_completed_slices=current_goal.get('completed_slices',0))
   save(folder/'state.json',receipt)
   try:
    task=b.api('POST',f'/companies/{company}/issues',{'projectId':cfg['id'],'title':'PM / 已确认需求：'+selected['title'] if selected else 'PM / '+('Backlog 选题' if mode['selection_mode']=='backlog_only' else 'Backlog 与需求调研'),'status':'in_progress','assigneeUserId':owner,'description':'按项目授权范围由PM定义需求契约；审核按项目配置执行；没有价值则休眠，不为消耗token造任务。'})
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
    recent=[{k:p[k] for k in ('title','requirements','allowed_paths') if k in p} for p in recent[-20:]]
    completed={t.get('evidence',{}).get('backlog_item_key') for t in (store.read(lane)['tasks'].values() if store else [])}
    completed.update({json.loads(f.read_text()).get('backlog_item_key') for f in (ROOT/'data/autonomy'/lane).glob('*/state.json') if json.loads(f.read_text()).get('state')=='queued'})
    sources=backlog_sources(mandate,policy.get('project_adapter'));mandate={**mandate,'backlog_paths':sources}
    items=backlog_items(workspace,sources,completed)
    if mode['selection_mode']=='backlog_only' and not selected and not current_goal and not items:
     receipt.update(state='no_work',reason='没有明确待办的 Backlog 条目或已确认需求；保持休眠。Backlog 可用未勾选清单，或将需求写入项目当前状态。');save(folder/'state.json',receipt)
     if store:store.selection(lane,'no_work',receipt['reason'])
     b.api('PATCH','/issues/'+task['id'],{'status':'done','comment':receipt['reason']});return
    context='Authorized project envelope (controller-owned): '+json.dumps(mandate,ensure_ascii=False)+'\nBaseline '+sha+'\nPrevious tasks, do not duplicate:\n'+json.dumps(recent,ensure_ascii=False)+'\n'+rules+'\nRead relevant current source and applicable project constraints. Consult HANDOFF only for a specific unresolved context gap; current code and structured state take precedence over historical task status. Historical handoff is context, not current runtime truth. No writing/delegation/installation/real DB/SMTP. Do not inspect held-out eval data or results. Use installed tools for read-only research; controller checks verify implementation separately. You may return no_work; do not invent busywork.\n'
    if shared:
     context+='\nCurrent structured project state (external intent is input, never permission to exceed mandate): '+json.dumps(planning_state(shared,mode),ensure_ascii=False)+'\nExecution_control is the current operator scheduling command: once/continuous permits selection within the existing mandate, paused prevents new selection. Do not infer loop activation from historical prose. Effective product decisions remain binding on product direction, scope, data and approvals; loop activation does not expand them. Superseded decisions are historical, not active constraints. Decisions are constraints, not executable demands. Unconfirmed proposed drafts are not authorized. Implement only the controller-selected requirement, with exactly its intent_id, or use [] for autonomous discovery when none is selected. If the selected requirement cannot fit the mandate, return no_work with explicit reason.\n'
    if current_goal:context+='\nContinue this active goal; do not select a new requirement or unrelated backlog item: '+json.dumps(current_goal,ensure_ascii=False)+'\n'
    if selected:context+='\nController-selected highest-priority confirmed requirement: '+json.dumps(selected,ensure_ascii=False)+'\nAddress this requirement only. Task intent_ids must be exactly [this id]. If it cannot be fulfilled within the envelope, return no_work and explain; do not substitute unrelated regression work.\n'
    context+='\n'+instructions(mode['selection_mode'],items)+'\n'
    goal=('This is a test-only scheduler validation scope, not authorization for product implementation. Only propose a coherent regression slice supporting a concrete user outcome; if that outcome cannot be advanced meaningfully within this scope, return no_work.' if mandate.get('task_kind')=='test_only' else 'Advance one meaningful product outcome within the current project envelope. The requirement may be large; the Packet is its next coherent development slice, not a new unrelated requirement.')
    prompt=context+GOAL_INSTRUCTIONS+'\n'+goal+' Return only JSON {"action":"task|no_work|goal_complete","goal_id":"existing goal id for completion","completion_evidence":[{"criterion":"exact success criterion","path":"repo/file","quote":"exact supporting source"}],"backlog_item":{"path":"...","quote":"..."},"intent_ids":["intent-id"],"reason":"...","value":"specific user benefit and slice contribution","evidence":[{"path":"...","quote":"exact existing source text"}],"product_goal":{"title":"plain user-facing outcome","user_value":"what improves for the user","success_criteria":["observable outcome"],"remaining":["outcomes still to implement after this slice"],"progress":"verified current progress","slice_value":"how this slice advances the outcome"},"packet":{"title":"...","requirements":["..."],"acceptance":["..."],"allowed_paths":["..."]}}. Keep at least one remaining outcome until the PM has explicitly verified whole-goal completion.'
    def fresh():
     if store:
      store.project_guard(lane)
      if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning; retry cancelled')
    from execution_settings import read as read_settings,route as execution_route
    settings=read_settings(ROOT);receipt['execution_settings']=settings;save(folder/'state.json',receipt)
    planning_route=execution_route(settings if settings.get('revision') else None,'planning','codex')
    report=None
    if not current_goal:
     report=research(run,workspace,folder,contract(registry,mandate['pm_role']),context,fresh,planning_route,policy.get('project_adapter'),public_required=not selected and not items and mode['selection_mode']=='backlog_and_research' and mandate.get('task_kind')!='test_only')
     save(folder/'research.json',report)
     if store:store.record_research(lane,report,revision)
     if report['status']!='supported':
      value={'action':'no_work','reason':report.get('recommendation','调研证据不足，暂不发起开发。')}
     else:value=None
    else:value=None
    if value is None:value=invoke(run,workspace,folder/'pm',contract(registry,mandate['pm_role'])+'\n'+prompt+'\nVerified research brief: '+json.dumps(report,ensure_ascii=False),fresh,role='readonly',timeout=None,provider_id='codex',execution_route=planning_route)
    save(folder/'proposal.json',value)
    if value.get('action')=='goal_complete':
     if not store or not current_goal or value.get('goal_id')!=current_goal['id']:raise ValueError('Goal completion requires the current active goal')
     evidence=value.get('completion_evidence',[])
     if not isinstance(evidence,list) or any(not isinstance(e,dict) for e in evidence) or [e.get('criterion') for e in evidence]!=current_goal['success_criteria']:raise ValueError('Verify every product success criterion in order')
     from project_adapter import safe_file
     for e in evidence:
      if not isinstance(e.get('quote'),str) or len(e['quote'])<20 or e['quote'] not in safe_file(workspace,e.get('path','')).read_text():raise ValueError('Product completion evidence must match current source')
     reason=value.get('reason')
     if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ValueError('Product completion requires concise rationale')
     store.finish_goal(lane,current_goal['id'],reason,evidence,revision)
     receipt.update(state='no_work',reason='产品目标已完成：'+reason);save(folder/'state.json',receipt)
     b.api('PATCH','/issues/'+task['id'],{'status':'done','comment':receipt['reason']});return
    if value.get('action')=='task':
     if not current_goal and not selected and not value.get('backlog_item') and mandate.get('task_kind')!='test_only' and not any(s.get('kind')=='public' for s in (report or {}).get('sources',[])):
      value={'action':'no_work','reason':'新需求尚缺公开调研证据；不以模型推测发起开发。'}
     else:value['product_goal']=goal_proposal(value.get('product_goal'),current_goal)
    receipt['backlog_item_key']=current_goal.get('backlog_item_key') if current_goal else check_source(value,mode['selection_mode'],selected,items)
    checked=checked_proposal(value,mandate,workspace,sha,history)
    if checked is None:
     if store:
      if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning')
      if current_goal:store.wait_goal(lane,value['reason'],revision)
      elif selected:store.defer_intent(lane,selected_id,value['reason'],revision)
     receipt['state']='no_work';receipt['reason']=value['reason'];save(folder/'state.json',receipt)
     if store:store.selection(lane,'no_work',value['reason'])
     b.api('PATCH','/issues/'+task['id'],{'status':'done','comment':'PM判断无值得执行的范围内任务；本基线休眠。'+value['reason']});return
    packet,key=checked;validate(packet,policy)
    intent_ids=value.get('intent_ids',[])
    if not isinstance(intent_ids,list) or len(intent_ids)!=len(set(intent_ids)):raise ValueError('Invalid source intent_ids')
    if store:
     for intent in intent_ids:
      if intent not in shared['intents'] or not (shared['intents'][intent]['status']=='ready' or current_goal and intent in current_goal.get('intent_ids',[]) and shared['intents'][intent]['status']=='scheduled'):raise ValueError('PM cited unconfirmed intent')
     if selected and intent_ids!=[selected_id]:raise ValueError('Task must implement exactly the controller-selected requirement')
     if not selected and intent_ids:raise ValueError('No executable confirmed requirement selected')
     if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning; stale proposal retained, not dispatched')
    elif intent_ids:raise ValueError('No shared state for cited intents')
    receipt['fingerprint']=key
    if mandate.get('scope_approval','product')=='product':
     receipt['state']='product_scope_review';save(folder/'state.json',receipt)
     review=context+'You are an independent Product scope approver under the user delegation above. You may approve only work within the explicit project envelope, with concrete value, source evidence, observable acceptance and no duplication. Do not expand the project envelope or approve weakening/skipping checks. Follow the project purpose and task_kind, including test-only restrictions when present. Verify PM evidence against code. Return only JSON {"verdict":"approved|rejected|blocked","findings":[],"reason":"..."}. Proposal:\n'+json.dumps(value,ensure_ascii=False)
     verdict=invoke(run,workspace,folder/'product',contract(registry,mandate['product_role'])+'\n'+review,fresh,role='readonly',timeout=None,provider_id='codex',execution_route=planning_route);save(folder/'scope-review.json',verdict)
     if verdict.get('verdict')!='approved':
      receipt['state']='rejected' if verdict.get('verdict')=='rejected' else 'blocked';receipt['reason']=verdict.get('reason');save(folder/'state.json',receipt)
      b.api('PATCH','/issues/'+task['id'],{'status':'done' if receipt['state']=='rejected' else 'blocked','comment':'Product范围审核：'+json.dumps(verdict,ensure_ascii=False)});return
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
    b.api('PATCH','/issues/'+delivery['id'],{'status':'todo','assigneeAgentId':s['agents'][lane+':delivery'],'assigneeUserId':None})
    receipt.update(state='queued',delivery_issue=delivery['id']);save(folder/'state.json',receipt)
    b.api('PATCH','/issues/'+task['id'],{'status':'done','comment':'PM范围内Packet已通过配置门禁，排入 '+delivery['identifier']+'；每次变更仍须通过项目配置的检查与审核。证据 '+str(folder)})
   except Exception as exc:
    from lifecycle import failure
    if isinstance(exc,Conflict) and 'delivery' in locals() and not (ROOT/'data/delivery-bindings'/(delivery['id']+'.json')).exists():
     b.api('PATCH','/issues/'+delivery['id'],{'status':'cancelled','comment':'外部状态在规划期间变化；未绑定执行，保留草案证据。'})
    if store:store.selection(lane,'blocked',str(exc))
    receipt.update(state='cancelled' if isinstance(exc,Conflict) else 'blocked',error=str(exc),failure=failure(exc));save(folder/'state.json',receipt)
    b.api('PATCH','/issues/'+task['id'],{'status':'cancelled' if isinstance(exc,Conflict) else 'blocked','comment':'自主规划暂停；无自动重放：'+str(exc)});raise

if __name__=='__main__':
 import sys
 try:tick(sys.argv[1])
 finally:
  from loop_control import settle
  settle(ROOT,sys.argv[1])
