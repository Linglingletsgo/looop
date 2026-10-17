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

def checked_proposal(value,mandate,repo,sha,history):
 if not isinstance(value,dict) or value.get('action') not in ('task','no_work'):raise ValueError('PM must return task or no_work')
 if value['action']=='no_work':
  if not value.get('reason'):raise ValueError('No-work needs rationale')
  return None
 if not isinstance(value.get('value'),str) or len(value['value'])<30:raise ValueError('Specific product value required; no token-filling tasks')
 p=value.get('packet',{});allowed=mandate['allowed_paths']
 if not p.get('allowed_paths') or any(n not in allowed for n in p['allowed_paths']):raise ValueError('Outside autonomous mandate')
 if len(p['allowed_paths'])>mandate.get('max_files',2):raise ValueError('Too many files')
 # Only a fixed Packet schema crosses the model/controller boundary.
 packet={k:p[k] for k in ('title','requirements','acceptance','allowed_paths')};packet['baseline_sha']=sha
 if any(not isinstance(n,str) or len(n)>2000 for n in packet['requirements']+packet['acceptance']):raise ValueError('Invalid criteria')
 references=value.get('evidence',[])
 if not references:raise ValueError('Current source evidence required')
 for item in references:
  name=item['path'];path=pathlib.Path(repo)/name
  if name not in mandate['evidence_paths']+mandate['allowed_paths']:raise ValueError('Unsupported evidence source')
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
 for name in ('codex','commandcode'):
  if paused(root,name) is not None:return 'Provider paused: '+name
 jobs=list((root/'data/autonomy'/lane).glob('*/state.json'))
 day=datetime.datetime.fromtimestamp(now,datetime.timezone.utc).strftime('%Y-%m-%d')
 count=sum((v:=json.loads(f.read_text())).get('day')==day and v.get('origin','autonomous_discovery')=='autonomous_discovery' and not v.get('planning_restarts',0) for f in jobs)
 if not human and count>=mandate['max_proposals_per_day']:return 'Daily autonomous discovery budget reached'
 for f in jobs:
  if json.loads(f.read_text()).get('state') not in ('queued','no_work','rejected','cancelled'):return 'Unresolved planning attempt; inspect before replay'
 return None

def next_intent(shared):
 if not shared:return None
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
 mandate={**mandate,'enabled':True}
 if mandate.get('scope_approval','product') not in ('pm','product'):raise ValueError('Unknown configured scope approval mode')
 if lane not in json.loads((ROOT/'data/control.json').read_text())['projects']:raise ValueError('Unknown project')
 global_lock=ROOT/'data/locks'/('autonomy-'+lane);global_lock.parent.mkdir(exist_ok=True)
 with global_lock.open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  mode=view(ROOT,lane)
  if mode['mode']=='paused' or mode['mode']=='once' and mode.get('attempt'):return
  s=json.loads((ROOT/'data/control.json').read_text())
  store=configured_store(ROOT)
  shared=store.context(lane) if store else None
  if store:
   try:store.project_guard(lane)
   except ValueError as exc:
    save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting_decision','reason':str(exc)});return
  revision=shared['planning_revision'] if shared else 0
  selected=next_intent(shared);selected_id=selected['id'] if selected else None
  retry_connection(ROOT,lane,Board(),s['agents'][lane+':delivery'])
  if shared and not selected and any(i['status']=='waiting_decision' for i in shared['intents'].values()):
   reason='Confirmed requirements need scope clarification; inspect per-intent planning_reason'
   store.selection(lane,'no_work',reason)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting_decision','reason':reason});return
  pending=[json.loads(f.read_text()) for f in (ROOT/'data/autonomy'/lane).glob('*/state.json') if json.loads(f.read_text()).get('retry_pending')]
  planning_restarts=max((v.get('planning_restarts',0)+1 for v in pending if v.get('planning_revision',0)==revision and v.get('selected_intent')==selected_id),default=0)
  waiting=slots(ROOT,lane,mandate,human=selected is not None or 0<planning_restarts<=2)
  if waiting:
   if store:store.selection(lane,'waiting',waiting)
   save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'waiting','reason':waiting,'at':time.time()});return
  s=json.loads((ROOT/'data/control.json').read_text());cfg=s['projects'][lane];profile=validate_profile(cfg['profile']);repo=pathlib.Path(cfg['repo']);sha=profile['repository_revision']
  history=[]
  for f in (ROOT/'data/autonomy'/lane).glob('*/state.json'):
   previous=json.loads(f.read_text())
   if previous.get('interrupted_planning'):continue
   if previous.get('baseline_sha')==sha and previous.get('planning_revision',0)==revision and previous.get('selected_intent')==selected_id:
    save(ROOT/'data/autonomy'/(lane+'-status.json'),{'state':'idle','reason':'Already planned this verified baseline; no repeated model calls','sha':sha});finish_without_attempt(ROOT,lane,'该版本与需求状态已完成选题；不重复调用模型。');return
   if previous.get('fingerprint'):history.append(previous['fingerprint'])
  policy=json.loads((ROOT/'data/delivery-policies'/(lane+'.json')).read_text())
  if not set(mandate['allowed_paths'])<=set(policy['allowed_paths']):raise ValueError('Mandate exceeds configured delivery scope')
  common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
  with (ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
   try:fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:return
   b=Board();owner=b.api('GET','/auth/get-session')['user']['id'];company=cfg.get('company',s.get('company'))
   job=uuid.uuid4().hex;folder=ROOT/'data/autonomy'/lane/job;folder.mkdir(parents=True,mode=0o700)
   claim(ROOT,lane,job)
   receipt={'owner':identity(),'planning_restarts':planning_restarts,'origin':'human_confirmed' if selected else 'autonomous_discovery','selected_intent':selected_id,'state':'proposing','baseline_sha':sha,'planning_revision':revision,'day':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),'started_at':time.time()}
   save(folder/'state.json',receipt)
   try:
    task=b.api('POST',f'/companies/{company}/issues',{'projectId':cfg['id'],'title':'PM / 已确认需求：'+selected['title'] if selected else 'PM / 有限自主队列：发现下一项高价值回归','status':'in_progress','assigneeUserId':owner,'description':'按项目授权范围由PM定义需求契约；审核按项目配置执行；没有价值则休眠，不为消耗token造任务。'})
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
    if store:store.selection(lane,'discovering','PM selecting a bounded task')
    workspace=snapshot(repo,sha,folder/'workspace');registry=resolve(workspace,policy.get('project_adapter'))
    if (workspace/'.agent/project.json').exists() and not policy.get('project_adapter'):raise ValueError('Project manifest must be mapped into planning policy')
    if fingerprints(registry)!=policy['role_registry']:raise ValueError('Role baseline differs')
    (folder/'roles.json').write_text(json.dumps(fingerprints(registry),ensure_ascii=False,indent=2))
    # Carry project workflow/rules verbatim; role definitions remain project-owned.
    rules='\n'.join('PROJECT FILE '+n+'\n'+(workspace/n).read_text() for n in dict.fromkeys(['AGENTS.md','AGENT.md',*policy.get('workflow_evidence',{})]) if (workspace/n).is_file())
    if policy.get('project_adapter'):
     from project_adapter import context as project_context
     rules=project_context(workspace,policy['project_adapter'],mandate['pm_role'],mandate['allowed_paths'])
    recent=[]
    for f in (ROOT/'data/delivery-bindings').glob('*.json'):
     d=json.loads(f.read_text())
     if d['lane']==lane:recent.append(d['packet'])
    recent=recent[-20:]
    context='Authorized project envelope (controller-owned): '+json.dumps(mandate,ensure_ascii=False)+'\nBaseline '+sha+'\nPrevious tasks, do not duplicate:\n'+json.dumps(recent,ensure_ascii=False)+'\n'+rules+'\nRead HANDOFF and relevant current source. Historical handoff is context, not current runtime truth. No writing/delegation/installation/real DB/network/SMTP. Do not inspect held-out eval data or results. Node is deliberately absent from this read-only planning snapshot; execution dependencies/checks are verified externally. You may return no_work; do not invent busywork.\n'
    if shared:
     context+='\nCurrent structured project state (external intent is input, never permission to exceed mandate): '+json.dumps({'planning_revision':revision,'intents':shared['intents']},ensure_ascii=False)+'\nDecisions are constraints, not executable demands. Unconfirmed proposed drafts are not authorized. Implement only the controller-selected requirement, with exactly its intent_id, or use [] for autonomous discovery when none is selected. If the selected requirement cannot fit the mandate, return no_work with explicit reason.\n'
    if selected:context+='\nController-selected highest-priority confirmed requirement: '+json.dumps(selected,ensure_ascii=False)+'\nAddress this requirement only. Task intent_ids must be exactly [this id]. If it cannot be fulfilled within the envelope, return no_work and explain; do not substitute unrelated regression work.\n'
    prompt=context+'Propose ONE small test-only improvement to an existing, current product behavior within allowed_paths. Cite actual current source quote and describe the missing behavior coverage, customer impact and what would falsify the proposal. No new product behavior or production fixes. Return only JSON {"action":"task|no_work","intent_ids":["intent-id"],"reason":"...","value":"specific value and nonduplication rationale","evidence":[{"path":"...","quote":"exact existing source text"}],"packet":{"title":"...","requirements":["..."],"acceptance":["..."],"allowed_paths":["..."]}}.'
    def fresh():
     if store:
      store.project_guard(lane)
      if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning; retry cancelled')
    value=invoke(run,workspace,folder/'pm',contract(registry,mandate['pm_role'])+'\n'+prompt,fresh,role='readonly',timeout=None,provider_id='codex')
    save(folder/'proposal.json',value);checked=checked_proposal(value,mandate,workspace,sha,history)
    if checked is None:
     if store:
      if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning')
      if selected:store.defer_intent(lane,selected_id,value['reason'],revision)
     receipt['state']='no_work';receipt['reason']=value['reason'];save(folder/'state.json',receipt)
     if store:store.selection(lane,'no_work',value['reason'])
     b.api('PATCH','/issues/'+task['id'],{'status':'done','comment':'PM判断无值得执行的范围内任务；本基线休眠。'+value['reason']});return
    packet,key=checked;validate(packet,policy)
    intent_ids=value.get('intent_ids',[])
    if not isinstance(intent_ids,list) or len(intent_ids)!=len(set(intent_ids)):raise ValueError('Invalid source intent_ids')
    if store:
     for intent in intent_ids:
      if intent not in shared['intents'] or shared['intents'][intent]['status']!='ready':raise ValueError('PM cited unconfirmed intent')
     if selected and intent_ids!=[selected_id]:raise ValueError('Task must implement exactly the controller-selected requirement')
     if not selected and intent_ids:raise ValueError('No executable confirmed requirement selected')
     if store.read(lane)['planning_revision']!=revision:raise Conflict('External decisions changed during planning; stale proposal retained, not dispatched')
    elif intent_ids:raise ValueError('No shared state for cited intents')
    receipt['fingerprint']=key
    if mandate.get('scope_approval','product')=='product':
     receipt['state']='product_scope_review';save(folder/'state.json',receipt)
     review=context+'You are an independent Product scope approver under the user delegation above. You may approve only existing-behavior tests in the explicit envelope, with concrete value, source evidence, observable acceptance and no duplication. Do not approve new scope, real data/service operations, production changes, or weakening/skipping tests. If a genuine production defect is exposed, delivery must stop and report it. Verify PM evidence against code. Return only JSON {"verdict":"approved|rejected|blocked","findings":[],"reason":"..."}. Proposal:\n'+json.dumps(value,ensure_ascii=False)
     verdict=invoke(run,workspace,folder/'product',contract(registry,mandate['product_role'])+'\n'+review,fresh,role='readonly',timeout=None,provider_id='codex');save(folder/'scope-review.json',verdict)
     if verdict.get('verdict')!='approved':
      receipt['state']='rejected' if verdict.get('verdict')=='rejected' else 'blocked';receipt['reason']=verdict.get('reason');save(folder/'state.json',receipt)
      b.api('PATCH','/issues/'+task['id'],{'status':'done' if receipt['state']=='rejected' else 'blocked','comment':'Product范围审核：'+json.dumps(verdict,ensure_ascii=False)});return
    packet['requirements'].append('只增加有价值的合成回归，保留全部既有断言；如暴露生产缺陷，保留失败证据并停止，不改生产代码或削弱断言。')
    validate(packet,policy);save(folder/'packet.json',packet)
    # Persist approved scope provenance before exposing a bound task. No shell/model-supplied commands.
    receipt['state']='binding';save(folder/'state.json',receipt)
    from binding_requests import create
    binding={'lane':lane,'intent_ids':intent_ids,'packet':packet,'policy':policy,'owner':owner,'publish':True,'authorization':{'type':'project_mandate','proposal':str(folder),'scope_approval':mandate.get('scope_approval','product'),'fingerprint':key}}
    delivery=create(ROOT,b,folder,binding,company,{'projectId':cfg['id'],'title':packet['title'],'status':'backlog','description':'PM授权契约；来源：'+task['identifier']+'；证据 '+str(folder)},revision)
    if store:store.selection(lane,'queued','Packet bound; delivery controller advances')
    b.api('PATCH','/issues/'+delivery['id'],{'status':'todo','assigneeAgentId':s['agents'][lane+':delivery'],'assigneeUserId':None})
    receipt.update(state='queued',delivery_issue=delivery['id']);save(folder/'state.json',receipt)
    b.api('PATCH','/issues/'+task['id'],{'status':'done','comment':'PM范围内Packet已通过配置门禁，排入 '+delivery['identifier']+'；每次变更仍需独立检查、Reviewer及独立最终验收。证据 '+str(folder)})
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
