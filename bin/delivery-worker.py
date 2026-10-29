"""Delivery worker: executes only operator-bound immutable Packet files."""
import json,sys
from runtime import ROOT
from delivery import execute
from tracker import CLEAR_AGENT,open_tracker

LEASE=7*24*3600

def run_task(lane,tracker,task):
 binding=ROOT/'data/delivery-bindings'/(task['id']+'.json')
 if not binding.exists():
  tracker.update(task['id'],status='blocked',assignee=CLEAR_AGENT,comment='没有操作员绑定的执行 Packet。任务描述不作为执行授权；请通过 delivery-control.py submit 绑定。');return 'continue'
 d=json.loads(binding.read_bytes())
 if d['lane']!=lane:raise ValueError('Lane mismatch')
 prior=ROOT/'data/deliveries'/task['id']/'state.json'
 if prior.exists():
  from lifecycle import terminal
  prior_state=json.loads(prior.read_text())
  status=terminal(prior_state['state'])
  if status:
   tracker.update(task['id'],status=status,assignee='owner',owner_id=d['owner'],comment='Preserved terminal delivery receipt; no replay.');return 'continue'
  if prior_state['state']!='blocked':
   print('Existing attempt retained; active worker or restart reconciliation owns recovery.');return 'stop'
 try:
  tracker.update(task['id'],status='in_progress')
  result=execute(d['packet'],d['policy'],task['id'],publish=d['publish'])
  if result['state']=='queued':return 'stop'
  if result['state'] not in ('waiting_for_merge','validated','merged'):raise ValueError('Existing attempt needs operator disposition: '+result['state'])
  tracker.update(task['id'],status='in_review' if result['state']=='waiting_for_merge' else 'done',assignee='owner',owner_id=d['owner'],comment='Delivery '+result['state']+'\n'+result.get('pr_url','')+'\nEvidence: '+str(ROOT/'data/deliveries'/task['id']))
 except Exception as exc:
  tracker.update(task['id'],status='blocked',assignee='owner',owner_id=d['owner'],comment='执行暂停，未自动重放：'+str(exc)+'\n'+json.dumps(__import__('lifecycle').failure(exc),ensure_ascii=False));raise
 return 'done'

def heartbeat(lane):
 from process_owner import identity
 tracker=open_tracker(ROOT)
 for task in tracker.assigned(lane,lane+':delivery',('todo','in_progress')):
  owner=identity()
  if not tracker.jobs.claim(task['id'],owner,LEASE):continue
  try:
   if run_task(lane,tracker,task)!='continue':return
  finally:
   tracker.jobs.release(task['id'],owner)
 print('No bound task; no model call.')

if __name__=='__main__':heartbeat(sys.argv[1])
