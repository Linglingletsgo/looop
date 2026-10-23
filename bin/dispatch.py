"""Repair assignment after durable binding; never replay an existing execution."""
import fcntl,json,pathlib
from project_state import configured_store
from lifecycle import save
from tracker import CLEAR_AGENT,as_tracker

def settle_planner(root,lane,job,d,store,tracker=None):
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
 if receipt.get('dispatch_reconciled') and receipt.get('issue') and not receipt.get('planner_board_reconciled') and tracker:
  issue=tracker.get(receipt['issue'])
  if issue and issue.get('status')=='in_progress':
   tracker.update(receipt['issue'],status='done',assignee=CLEAR_AGENT,comment='已固定的Packet绑定与派发证据已对账；规划完成，没有重新调用模型。')
  receipt['planner_board_reconciled']=True;save(folder/'state.json',receipt)

def reconcile(root,tracker):
 tracker=as_tracker(tracker,root);local=tracker.name=='local'
 config=json.loads((root/'data/control.json').read_text());lock=root/'data/locks/dispatch';lock.parent.mkdir(parents=True,exist_ok=True)
 results=[]
 with lock.open('w') as h:
  try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return []
  for path in sorted((root/'data/delivery-bindings').glob('*.json')):
   try:
    d=json.loads(path.read_text());lane=d['lane'];cfg=config['projects'].get(lane);role=lane+':delivery'
    agent=None if local else config['agents'].get(role)
    if not cfg or not local and (not cfg.get('id') or not agent):continue
    # Existing receipt means execution has started, even if its board status drifted.
    store=configured_store(root)
    if (root/'data/deliveries'/path.stem).exists():
     if (root/'data/deliveries'/path.stem/'state.json').is_file():settle_planner(root,lane,path.stem,d,store,tracker)
     continue
    if store:
     store.project_guard(lane);doc=store.read(lane);task=doc['tasks'].get(path.stem)
     if task and task['phase']!='queued':continue
    issue=tracker.get(path.stem)
    if issue.get('lane')!=lane:raise ValueError('Binding project mismatch')
    if issue['status'] not in ('backlog','todo','in_progress'):continue
    if tracker.agent_assigned(issue) and not tracker.assignee_is(issue,role):continue
    already_assigned=tracker.assignee_is(issue,role) and issue['status'] in ('todo','in_progress')
    # Rebuild shared state from durable authorization before exposing dispatch.
    if store:store.bind(lane,path.stem,d['packet'],d.get('intent_ids',[]),d.get('authorization',{}))
    if not already_assigned:
     tracker.update(path.stem,status='todo',assignee=role)
     results.append({'job':path.stem,'state':'dispatched'})
    settle_planner(root,lane,path.stem,d,store,tracker)
   except Exception as exc:
    results.append({'job':path.stem,'state':'deferred','reason':str(exc)})
 return results

if __name__=='__main__':
 from board import ROOT,Board
 from tracker import open_tracker
 print(json.dumps(reconcile(ROOT,open_tracker(ROOT,Board)),ensure_ascii=False))
