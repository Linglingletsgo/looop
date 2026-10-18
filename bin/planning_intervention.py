"""Current unresolved PM receipts and explicit read-only planning recovery."""
import fcntl,json,re
from lifecycle import save
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

def retry(root,lane,job,reason,expected,board):
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
   cfg=json.loads((root/'data/control.json').read_text())['projects'][lane]
   issue=board.api('GET','/issues/'+state['issue'])
   if issue.get('projectId')!=cfg['id'] or issue.get('status') not in ('in_progress','blocked','cancelled'):raise ValueError('PM 任务状态不匹配，需要先核对。')
   board.api('PATCH','/issues/'+state['issue'],{'status':'cancelled','comment':'人工核验后重新规划，原提案保留：'+reason[:2000]})
  state.update(state='cancelled',interrupted_planning=True,retry_pending=True,recovery_reason=reason[:2000]);save(path,state)
  store.selection(lane,'waiting','已保留旧提案；等待根据最新代码与状态重新规划。')
 return {'queued':True,'message':'旧提案已保留。将按当前循环设置重新规划；暂停模式下请启动单次或持续运行。'}

def blocked_patch(reason):
 return {'status':'blocked','unblockDescriptor':{'owner':'board','action':'在 looop 的“处理选题受阻”中核对原因并重新规划；绑定阶段异常交给维护对话。'},'comment':str(reason)[:4000]}
