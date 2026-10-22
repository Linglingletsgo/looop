"""Current unresolved PM receipts and explicit read-only planning recovery."""
import fcntl,json,pathlib,re
from lifecycle import save
from tracker import as_tracker
from process_owner import alive
from project_state import Store,Conflict

TERMINAL={'queued','no_work','rejected','cancelled'}
def unresolved(root,lane):
 result=[]
 for path in (root/'data/autonomy'/lane).glob('*/state.json'):
  state=json.loads(path.read_text())
  if state.get('state') not in TERMINAL:result.append((path,state))
 return sorted(result,key=lambda item:(item[1].get('started_at',0),item[0].parent.name))

def preview(root,lane):
 values=[]
 for path,state in unresolved(root,lane):
  if state.get('state')!='blocked':continue
  job=path.parent.name;reason=state.get('error') or state.get('reason') or '规划结果需要人工核对'
  eligible=bool(state.get('issue')) and not state.get('delivery_issue') and not (path.parent/'binding-request.json').exists() and not (path.parent/'packet.json').exists() and alive(state.get('owner')) is False
  values.append({'kind':'planning','job':job,'title':'PM 规划受阻','reason':reason[:4000],'retry_allowed':eligible,'instruction':(('调研未完成。请处理具体证据缺口；需要产品政策决定时先补充产品决定，公开来源不可用时等待恢复。确认后重新规划。' if state.get('failure',{}).get('category')=='research_incomplete' else '修复原因后可重新规划。旧提案保留，PM 会读取最新代码和项目状态；不会重跑已完成开发。') if eligible else '规划进程尚未确认停止，或已进入任务绑定阶段；需要维护对话核对，不能直接重跑。'),'diagnostic':f'项目: {lane}\nPM 记录: {job}\n原因: {reason[:4000]}\n证据目录: {path.parent}\n请保留提案并核对当前代码与状态后恢复。'})
 return values

def retry(root,lane,job,reason,expected,tracker):
 tracker=as_tracker(tracker,root)
 if not isinstance(job,str) or not re.fullmatch('[a-zA-Z0-9-]{1,80}',job):raise ValueError('Invalid planning id')
 if not isinstance(reason,str) or len(reason.strip())<4:raise ValueError('请说明已处理或核验的内容。')
 lock=root/'data/locks'/('autonomy-'+lane);lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  store=Store(root);doc=store.read(lane)
  if doc['revision']!=expected:raise Conflict('项目状态已更新，请刷新后重新判断。')
  store.project_guard(lane)
  if any(t['phase'] not in ('completed','cancelled') for t in doc['tasks'].values()):raise ValueError('当前还有开发任务未结束，请先核对任务状态。')
  item=next((v for v in preview(root,lane) if v['job']==job),None)
  if not item or not item['retry_allowed']:raise ValueError('该规划不能直接重试，请刷新并核对进程与绑定状态。')
  path=root/'data/autonomy'/lane/job/'state.json';state=json.loads(path.read_text())
  if state.get('issue'):
   issue=tracker.get(state['issue'])
   if issue['lane']!=lane or issue['status'] not in ('in_progress','blocked','cancelled'):raise ValueError('PM 任务状态不匹配，需要先核对。')
   tracker.update(state['issue'],status='cancelled',comment='人工核验后重新规划，原提案保留：'+reason[:2000])
  if state.get('error')=='No executable confirmed requirement selected' and (path.parent/'proposal.json').is_file():
   state['reuse_saved_proposal']=job
  state['research_checkpoint']=str(path.parent)
  report=path.parent/'research.json'
  if report.is_file():
   from product_research import brief
   state.setdefault('research_continuation',brief(json.loads(report.read_text())))
  state.update(state='cancelled',interrupted_planning=True,retry_pending=True,recovery_reason=reason[:2000]);save(path,state)
  store.selection(lane,'waiting','已保留旧提案；等待根据最新代码与状态重新规划。')
 return {'queued':True,'message':'旧提案已保留。将按当前循环设置重新规划；暂停模式下请启动单次或持续运行。'}

def blocked_patch(reason):
 return {'status':'blocked','unblockDescriptor':{'owner':'board','action':'在 looop 的“处理选题受阻”中核对原因并重新规划；绑定阶段异常交给维护对话。'},'comment':str(reason)[:4000]}

def resume_completion(root,lane,job,reason,expected,tracker,run_id='pm'):
 """Validate a saved PM conclusion without another model call or development replay."""
 tracker=as_tracker(tracker,root)
 import hashlib,time
 from handoff import read
 from repository import git
 from project_adapter import safe_file
 from product_goals import active
 from source_evidence import verify_completion
 root=pathlib.Path(root).absolute()
 if not re.fullmatch('[a-zA-Z0-9_-]{1,80}',lane) or not re.fullmatch('[a-zA-Z0-9-]{1,80}',job) or not re.fullmatch(r'pm(?:-retry-[12])?',run_id):raise ValueError('Invalid planning/run id')
 if not isinstance(reason,str) or not 4<=len(reason.strip())<=2000:raise ValueError('Concise recovery reason required')
 lock=root/'data/locks'/('autonomy-'+lane);lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  store=Store(root);doc=store.read(lane)
  if doc['revision']!=expected:raise Conflict('Project state changed; refresh before recovery')
  store.project_guard(lane)
  folder=root/'data/autonomy'/lane/job
  path=safe_file(folder,'state.json');state=json.loads(path.read_text())
  if state.get('state')!='blocked' or alive(state.get('owner')) is not False:raise ValueError('Saved completion requires a stopped blocked PM')
  if state.get('delivery_issue') or any((folder/n).exists() for n in ('binding-request.json','packet.json')):raise ValueError('Planning already entered binding; reconcile first')
  goal=active(doc)
  if not goal or state.get('goal_id')!=goal['id'] or state.get('planning_revision')!=doc['planning_revision']:raise Conflict('Active goal or planning contract changed')
  cfg=json.loads((root/'data/control.json').read_text())['projects'][lane];repo=pathlib.Path(cfg['repo'])
  common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
  with (root/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
   fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   sha=state['baseline_sha']
   if git(repo,'rev-parse','HEAD').decode().strip()!=sha or git(repo,'status','--porcelain').strip():raise ValueError('Completion baseline moved or checkout dirty')
   schema=json.loads(safe_file(folder,run_id+'/handoff.schema.json').read_text())
   safe_file(folder,run_id+'/handoff.json')
   identity={k:schema['properties'][k]['enum'][0] for k in ('version','run_id','nonce')}
   if identity['run_id']!=run_id:raise ValueError('Saved PM run identity mismatch')
   value=read(folder/run_id,schema['properties']['result'],identity)
   if value.get('action')!='goal_complete' or value.get('goal_id')!=goal['id']:raise ValueError('Saved result is not completion of the active goal')
   evidence=value.get('completion_evidence')
   verify_completion(repo,folder/'pm',goal,evidence,sha,artifact_base=root)
   rationale=value.get('reason')
   if not isinstance(rationale,str) or not 1<=len(rationale.strip())<=2000:raise ValueError('Concise completion rationale required')
   task=tracker.get(state['issue'])
   if task['lane']!=lane or task['status'] not in ('blocked','in_progress'):raise ValueError('PM board issue mismatch')
   save(folder/'completion-resume.json',{'previous_state':state,'source_run':run_id,'reason':reason,'target_sha':sha})
   save(folder/'proposal.json',value)
   store.finish_goal(lane,goal['id'],rationale,evidence,doc['planning_revision'])
   state.update(state='no_work',goal_completed=True,finished_at=time.time(),reason='产品目标已完成：'+rationale,recovery_reason=reason,completion_source_run=run_id)
   for key in ('error','failure'):state.pop(key,None)
   save(path,state)
   save(root/'data/autonomy'/(lane+'-status.json'),{'state':'ready','reason':'已核验并接收保存的 PM 完成结果；后续遵循当前循环设置。','at':time.time()})
   try:tracker.update(state['issue'],status='done',comment=state['reason']+'；保存结果接续：'+reason)
   except Exception as exc:
    state['completion_board_sync_pending']=str(exc)[:1000];save(path,state)
   return {'goal_completed':True,'source_run':run_id,'model_calls':0,'board_sync_pending':bool(state.get('completion_board_sync_pending'))}


if __name__=='__main__':
 import argparse,pathlib
 from runtime import ROOT
 from board import Board
 from tracker import open_tracker
 p=argparse.ArgumentParser()
 p.add_argument('action',choices=['resume-completion']);p.add_argument('lane');p.add_argument('job')
 p.add_argument('--reason',required=True);p.add_argument('--expected',type=int,required=True);p.add_argument('--run-id',default='pm')
 a=p.parse_args()
 print(json.dumps(resume_completion(ROOT,a.lane,a.job,a.reason,a.expected,open_tracker(ROOT,Board),a.run_id),ensure_ascii=False))
