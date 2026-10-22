"""Release provably interrupted read-only planning attempts for bounded fresh selection."""
import fcntl,hashlib,json,pathlib,subprocess
from process_owner import alive
from lifecycle import save
from project_state import configured_store
from tracker import as_tracker

def reconcile(root,tracker):
 tracker=as_tracker(tracker,root)
 cfg=json.loads((root/'data/control.json').read_text());results=[]
 for lane,project in cfg['projects'].items():
  policy=root/'data/autonomy-policies'/(lane+'.json')
  from loop_control import view
  mode=view(root,lane)
  if not policy.exists() or mode['mode']=='paused':continue
  lock=root/'data/locks'/('autonomy-'+lane);lock.parent.mkdir(exist_ok=True)
  with lock.open('w') as h:
   try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:continue
   for receipt in (root/'data/autonomy'/lane).glob('*/state.json'):
    try:
     state=json.loads(receipt.read_text())
     if state['state'] not in ('proposing','product_scope_review') or alive(state.get('owner')) is not False:continue
     if mode['mode']=='once':
      state.update(state='blocked',error='单次规划进程已中断；保留证据，等待人工核验。');save(receipt,state)
      store=configured_store(root)
      if store:store.selection(lane,'blocked',state['error'])
      results.append({'job':receipt.parent.name,'state':'needs_attention','reason':state['error']});continue
     if state.get('planning_restarts',0)>=2:results.append({'job':receipt.parent.name,'state':'needs_attention','reason':'Planning restart budget exhausted'});continue
     issue=tracker.get(state['issue'])
     if issue['lane']!=lane or issue['status']!='in_progress':continue
     store=configured_store(root)
     if store:store.project_guard(lane)
     common=subprocess.check_output(['git','-C',project['repo'],'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()
     with (root/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
      try:fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
      except BlockingIOError:continue
      # No binding-side effects are replayed; bind-stage interruptions need separate reconciliation.
      state.update(state='cancelled',interrupted_planning=True,retry_pending=True);save(receipt,state)
      tracker.update(state['issue'],status='cancelled',comment='只读规划进程中断；证据保留，控制器允许有限重新规划。未派发开发。')
      if store:store.selection(lane,'waiting','Interrupted planning will be selected again within restart budget')
      results.append({'job':receipt.parent.name,'state':'retry_pending'})
    except Exception as exc:results.append({'job':receipt.parent.name,'state':'deferred','reason':str(exc)})
 save(root/'data/planning-recovery-status.json',{'results':results});return results
if __name__=='__main__':
 from board import ROOT,Board
 from tracker import open_tracker
 print(json.dumps(reconcile(ROOT,open_tracker(ROOT,Board)),ensure_ascii=False))
