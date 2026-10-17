"""Repair assignment after durable binding; never replay an existing execution."""
import fcntl,json,pathlib
from project_state import configured_store
from lifecycle import save

def settle_planner(root,lane,job,d,store,board=None):
 # Only a controller-written binding can establish that planning completed.
 proposal=d.get('authorization',{}).get('proposal')
 if not proposal:return
 folder=pathlib.Path(proposal).resolve();base=(root/'data/autonomy'/lane).resolve()
 if folder.parent!=base or not (folder/'state.json').is_file():return
 receipt=json.loads((folder/'state.json').read_text())
 if receipt['state'] in ('binding','blocked'):
  receipt.update(state='queued',delivery_issue=job,dispatch_reconciled=True)
  save(folder/'state.json',receipt)
  if store:store.selection(lane,'queued','Durable Packet assignment reconciled')
 if receipt.get('dispatch_reconciled') and receipt.get('issue') and not receipt.get('planner_board_reconciled') and board:
  issue=board.api('GET','/issues/'+receipt['issue'])
  if issue and issue.get('status')=='in_progress':
   board.api('PATCH','/issues/'+receipt['issue'],{'status':'done','assigneeAgentId':None,'comment':'已固定的Packet绑定与派发证据已对账；规划完成，没有重新调用模型。'})
  receipt['planner_board_reconciled']=True;save(folder/'state.json',receipt)

def reconcile(root,board):
 config=json.loads((root/'data/control.json').read_text());lock=root/'data/locks/dispatch';lock.parent.mkdir(parents=True,exist_ok=True)
 results=[]
 with lock.open('w') as h:
  try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return []
  for path in sorted((root/'data/delivery-bindings').glob('*.json')):
   try:
    d=json.loads(path.read_text());lane=d['lane'];cfg=config['projects'].get(lane);agent=config['agents'].get(lane+':delivery')
    if not cfg or not cfg.get('id') or not agent:continue
    # Existing receipt means execution has started, even if its board status drifted.
    store=configured_store(root)
    if (root/'data/deliveries'/path.stem).exists():
     if (root/'data/deliveries'/path.stem/'state.json').is_file():settle_planner(root,lane,path.stem,d,store,board)
     continue
    if store:
     store.project_guard(lane);doc=store.read(lane);task=doc['tasks'].get(path.stem)
     if task and task['phase']!='queued':continue
    issue=board.api('GET','/issues/'+path.stem)
    if issue.get('projectId')!=cfg['id']:raise ValueError('Binding project mismatch')
    if issue['status'] not in ('backlog','todo','in_progress'):continue
    assigned=issue.get('assigneeAgentId')
    if assigned and assigned!=agent:continue
    already_assigned=assigned==agent and issue['status'] in ('todo','in_progress')
    # Rebuild shared state from durable authorization before exposing dispatch.
    if store:store.bind(lane,path.stem,d['packet'],d.get('intent_ids',[]),d.get('authorization',{}))
    if not already_assigned:
     board.api('PATCH','/issues/'+path.stem,{'status':'todo','assigneeAgentId':agent,'assigneeUserId':None})
     results.append({'job':path.stem,'state':'dispatched'})
    settle_planner(root,lane,path.stem,d,store,board)
   except Exception as exc:
    results.append({'job':path.stem,'state':'deferred','reason':str(exc)})
 return results

if __name__=='__main__':
 from board import ROOT,Board
 print(json.dumps(reconcile(ROOT,Board()),ensure_ascii=False))
