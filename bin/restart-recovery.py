"""Recover provably dead workers before publication; no time-based termination."""
import json,fcntl
from process_owner import alive
from project_state import configured_store
from recovery import prepare
from lifecycle import save
from tracker import as_tracker

def reconcile(root,tracker):
 tracker=as_tracker(tracker,root);local=tracker.name=='local'
 results=[];cfg=json.loads((root/'data/control.json').read_text())
 lock=root/'data/locks/restart-recovery';lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as handle:
  try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return []
  for path in sorted((root/'data/delivery-bindings').glob('*.json')):
   try:
    d=json.loads(path.read_text());lane=d['lane'];folder=root/'data/deliveries'/path.stem;receipt=folder/'state.json'
    if not receipt.is_file():continue
    state=json.loads(receipt.read_text());stage=state['state']
    if stage not in ('planning','building','checking','acceptance','pr_ready') and not stage.startswith('review_'):continue
    if alive(state.get('owner')) is not False:continue
    issue=tracker.get(path.stem)
    agent=None if local else cfg['agents'].get(lane+':delivery')
    if issue.get('lane')!=lane or not local and not agent:continue
    if issue['status'] not in ('todo','in_progress') or not tracker.assignee_is(issue,lane+':delivery'):continue
    store=configured_store(root)
    if store:store.project_guard(lane)
    if stage=='pr_ready' or state.get('pr_url') or d.get('interruption_retries',0)>=2:
     results.append({'job':path.stem,'state':'needs_attention','reason':'Interrupted at publication boundary or restart budget exhausted; no automatic replay'})
     continue
    archive=prepare(root,path.stem,'Confirmed dead worker; restart with all gates',interrupted=True)
    results.append({'job':path.stem,'state':'requeued','evidence':str(archive)})
    tracker.update(path.stem,status='todo',assignee=lane+':delivery')
   except Exception as exc:results.append({'job':path.stem,'state':'deferred','reason':str(exc)})
 save(root/'data/restart-recovery-status.json',{'results':results})
 return results

if __name__=='__main__':
 from board import ROOT,Board
 from tracker import open_tracker
 print(json.dumps(reconcile(ROOT,open_tracker(ROOT,Board)),ensure_ascii=False))
