#!/usr/bin/env python3
"""Reconcile deliveries into project state and acknowledge the local outbox."""
import fcntl,json,pathlib
from project_state import Store,phase_of
from runtime import ROOT

def reconcile(root,store):
 for path in (root/'data/delivery-bindings').glob('*.json'):
  binding=json.loads(path.read_text());lane=binding['lane']
  receipt_path=root/'data/deliveries'/path.stem/'state.json'
  if receipt_path.exists() and json.loads(receipt_path.read_text()).get('state_compacted'):continue
  try:store.read(lane)
  except ValueError:continue
  store.bind(lane,path.stem,binding['packet'],binding.get('intent_ids',[]),binding.get('authorization',{}))
  receipt=root/'data/deliveries'/path.stem/'state.json'
  if receipt.exists():
   r=json.loads(receipt.read_text());doc=store.read(lane);task=doc['tasks'][path.stem];phase=phase_of(r)
   # Runtime receipts are execution evidence, never permission to clear intent holds.
   if task['phase'] in ('completed','cancelled') and phase!=task['phase']:continue
   if task['phase']=='verifying' and phase not in ('verifying','completed'):continue
   store.transition(lane,path.stem,phase,{k:r[k] for k in ('pr_url','error','mainline_verified','target_sha','merge_wait_reason','mainline_wait_reason') if k in r},import_existing=True)

def sync(root=ROOT):
 store=Store(root);reconcile(root,store)
 lock=root/'data/project-state/sync.lock'
 with lock.open('w') as h:
  fcntl.flock(h,fcntl.LOCK_EX)
  # No remote mirror: acknowledge the current snapshot so the 5000-row Held limit cannot stall writes.
  for lane in store.lanes():
   try:doc=store.read(lane)
   except ValueError:continue
   with store.connection(lane) as c:c.execute('UPDATE outbox SET delivered=1 WHERE lane=? AND revision<=?',(lane,doc['revision']))
 return True
if __name__=='__main__':sync()
