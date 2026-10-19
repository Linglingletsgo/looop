#!/usr/bin/env python3
"""Bound diagnostic history; preserve active work, unsynced events and current state."""
import json,pathlib,shutil,time
from project_state import Store

POLICY={'log_bytes':2*1024*1024,'event_limit':500,'completed_work_limit':20,'history_days':14,'history_per_category':20,'history_bytes':1024*1024*1024,'backup_limit':3}

def compact_state(store,lane,limit=500):
 with store.connection(lane) as c:
  # Outbox acknowledgements are not execution facts; unsynced events stay intact.
  cutoff=c.execute('SELECT revision FROM events WHERE lane=? ORDER BY revision DESC LIMIT 1 OFFSET ?',(lane,limit-1)).fetchone()
  if cutoff:
   c.execute('DELETE FROM events WHERE lane=? AND revision<? AND revision NOT IN (SELECT revision FROM outbox WHERE lane=? AND delivered=0)',(lane,cutoff[0],lane))
   c.execute('DELETE FROM outbox WHERE lane=? AND delivered=1 AND revision<?',(lane,cutoff[0]))
  row=c.execute('SELECT doc FROM projects WHERE lane=?',(lane,)).fetchone()
  if row:
   doc=json.loads(row['doc']);works=doc.get('external_work',{});completed=[(k,v) for k,v in works.items() if v['status']!='active'];keep={k for k,v in sorted(completed,key=lambda x:x[1]['updated_at'])[-POLICY['completed_work_limit']:]}
   doc['external_work']={k:v for k,v in works.items() if v['status']=='active' or k in keep}
   terminal=[k for k,v in doc['tasks'].items() if v['phase'] in ('completed','cancelled')]
   for job in terminal[:-20]:
    receipt=store.root/'data/deliveries'/job/'state.json'
    if receipt.exists():
     v=json.loads(receipt.read_text());v['state_compacted']=True;receipt.write_text(json.dumps(v,indent=2))
     del doc['tasks'][job]
   retained={i for task in doc['tasks'].values() for i in task.get('intent_ids',[])}
   old=[k for k,v in doc['intents'].items() if v['status'] in ('completed','withdrawn') and k not in retained]
   for key in old[:-20]:del doc['intents'][key]
   c.execute('UPDATE projects SET doc=? WHERE lane=?',(json.dumps(doc,ensure_ascii=False),lane))
  c.execute('PRAGMA incremental_vacuum')

def trim_log(path,limit):
 if path.is_symlink() or not path.is_file() or path.stat().st_size<=limit:return False
 # Keep file inode: tmux/services may still have it open with O_APPEND.
 with path.open('r+b') as f:
  f.seek(-limit,2);tail=f.read();newline=tail.find(b'\n');tail=tail[newline+1:] if newline>=0 else tail
  f.seek(0);f.write(tail);f.truncate()
 return True

def maintain(root):
 root=pathlib.Path(root);policy_path=root/'retention.json';policy={**POLICY,**(json.loads(policy_path.read_text()) if policy_path.exists() else {})};trimmed=0
 for folder in (root/'logs',root/'data/instances/default/logs'):
  if folder.exists():
   for path in folder.rglob('*'):
    if path.suffix in ('.log','.jsonl') and trim_log(path,policy['log_bytes']):trimmed+=1
 store=Store(root)
 for lane in store.lanes():compact_state(store,lane,policy['event_limit'])
 # Completed model transcripts/workspaces are disposable; keep compact outcome receipts.
 candidates=[];removed=[];total=0
 for category in ('deliveries','autonomy','plans','verification-agents','agent-checks'):
  base=root/'data'/category
  paths=base.glob('*/*/state.json') if category in ('autonomy','agent-checks') else base.glob('*/state.json')
  if category=='plans':paths=base.glob('*/result.json')
  for statepath in paths:
   folder=statepath.parent
   if folder.is_symlink():continue
   try:v=json.loads(statepath.read_text())
   except (ValueError,OSError):continue
   state=v.get('state',v.get('action'))
   complete=state=='validated' or (state=='merged' and v.get('mainline_verified')) or state in ('closed','no_work')
   if category=='plans':complete=v.get('action') in ('task','no_work')
   if not complete:continue
   size=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file() and not p.is_symlink());total+=size
   candidates.append((statepath.stat().st_mtime,size,folder,category))
 for index,(modified,size,folder,category) in enumerate(sorted(candidates)):
  stale=modified<time.time()-policy['history_days']*86400
  over=len(candidates)-len(removed)>policy['history_per_category'] or total>policy['history_bytes']
  if not stale and not over:continue
  for child in list(folder.iterdir()):
   if child.name in ('state.json','result.json','packet.json','policy.json','receipt.json'):continue
   if child.is_symlink() or child.is_file():child.unlink()
   elif child.is_dir():shutil.rmtree(child)
  total-=size;removed.append(str(folder.relative_to(root)))
 # Bound stdout/model trace files even for long-lived services and active model runs.
 for category in ('deliveries','autonomy','plans','runs','verification-agents','agent-checks'):
  base=root/'data'/category
  if base.exists():
   for path in base.rglob('events.jsonl'):
    if trim_log(path,policy['log_bytes']):trimmed+=1
 backups=root/'data/backups'
 if backups.exists():
  folders=sorted((p for p in backups.iterdir() if p.is_dir() and not p.is_symlink()),key=lambda p:p.stat().st_mtime,reverse=True)
  for old in folders[policy['backup_limit']:]:
   if old.stat().st_mtime<time.time()-policy['history_days']*86400:shutil.rmtree(old)
 report={'trimmed_logs':trimmed,'event_window':policy['event_limit'],'compacted_runs':removed,'at':time.time()}
 p=root/'data/retention-status.json';p.write_text(json.dumps(report,indent=2));return report
if __name__=='__main__':
 from runtime import ROOT
 print(json.dumps(maintain(ROOT)))
