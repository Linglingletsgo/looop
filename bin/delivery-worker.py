"""Paperclip adapter: executes only operator-bound immutable Packet files."""
import hashlib,json,os,sys
from board import Board,ROOT
from delivery import execute

def heartbeat(lane):
 state=json.loads((ROOT/'data/control.json').read_text());cfg=state['projects'][lane]
 agent=state['agents'].get(lane+':delivery')
 if os.environ.get('PAPERCLIP_AGENT_ID')!=agent:raise ValueError('Agent identity mismatch')
 b=Board();company=cfg.get('company',state.get('company'))
 for task in b.api('GET',f'/companies/{company}/issues?assigneeAgentId={agent}&status=todo,in_progress'):
  if task.get('projectId')!=cfg['id'] or task['status'] not in ('todo','in_progress'):continue
  binding=ROOT/'data/delivery-bindings'/(task['id']+'.json')
  if not binding.exists():
   b.api('PATCH','/issues/'+task['id'],{'status':'blocked','assigneeAgentId':None,'comment':'没有操作员绑定的执行 Packet。看板任务描述不作为执行授权；请通过 delivery-control.py submit 绑定。'});continue
  raw=binding.read_bytes();d=json.loads(raw)
  if d['lane']!=lane:raise ValueError('Lane mismatch')
  prior=ROOT/'data/deliveries'/task['id']/'state.json'
  if prior.exists():
   from lifecycle import terminal
   prior_state=json.loads(prior.read_text())
   status=terminal(prior_state['state'])
   if status:
    b.api('PATCH','/issues/'+task['id'],{'status':status,'assigneeAgentId':None,'assigneeUserId':d['owner'],'comment':'Preserved terminal delivery receipt; no replay.'});continue
   if prior_state['state']!='blocked':
    print('Existing attempt retained; active worker or restart reconciliation owns recovery.');return
  try:
   b.api('PATCH','/issues/'+task['id'],{'status':'in_progress'})
   result=execute(d['packet'],d['policy'],task['id'],publish=d['publish'])
   if result['state']=='queued':return
   if result['state'] not in ('waiting_for_merge','validated','merged'):raise ValueError('Existing attempt needs operator disposition: '+result['state'])
   patch={'status':'in_review' if result['state']=='waiting_for_merge' else 'done','assigneeAgentId':None,'assigneeUserId':d['owner'],'comment':'Delivery '+result['state']+'\n'+result.get('pr_url','')+'\nEvidence: '+str(ROOT/'data/deliveries'/task['id'])}
   b.api('PATCH','/issues/'+task['id'],patch)
  except Exception as exc:
   b.api('PATCH','/issues/'+task['id'],{'status':'blocked','assigneeAgentId':None,'assigneeUserId':d['owner'],'comment':'执行暂停，未自动重放：'+str(exc)+'\n'+__import__('json').dumps(__import__('lifecycle').failure(exc),ensure_ascii=False)});raise
  finally:
   from metrics import record
   folder=ROOT/'data/deliveries'/task['id']
   if folder.exists():
    try:record(b,folder,company,agent,task['id'],cfg['id'])
    except Exception:print('Usage import pending; run sync-usage later.',flush=True)
  return
 print('No bound task; no model call.')

if __name__=='__main__':heartbeat(sys.argv[1])
