#!/usr/bin/env python3
"""Project-local context and independent work journal; Paperclip is optional."""
import argparse,fcntl,json,pathlib,sys,uuid
from project_state import Store

def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2));t.chmod(0o600);t.replace(p)

def snapshot(repo,local):
 link=json.loads((local/'link.json').read_text()) if (local/'link.json').exists() else None
 pending=json.loads((local/'pending.json').read_text()) if (local/'pending.json').exists() else []
 cached=json.loads((local/'snapshot.json').read_text()) if (local/'snapshot.json').exists() else None
 local_work={}
 for event in pending:
  c=event['command'];local_work[c['id']]={'status':{'start':'active','progress':'active','finish':'completed','cancel':'cancelled'}[c['action']],'summary':c['summary'],'verification':'self_reported','synchronization':'pending'}
 return {'project_state':cached,'local_pending_work':local_work,'pending_events':len(pending),'linked':bool(link),'notice':'Cached state; read again before decisions. Offline records do not reserve scheduler execution.'}

def refresh(repo,local):
 if not (local/'link.json').exists():return snapshot(repo,local)
 link=json.loads((local/'link.json').read_text());root=pathlib.Path(link['runtime'])
 if not root.is_dir():raise ValueError('Linked runtime unavailable; cached state and pending events retained')
 store=Store(root);v=store.context(link['lane']);save(local/'snapshot.json',v);return snapshot(repo,local)

def publish(repo,local):
 link=json.loads((local/'link.json').read_text());root=pathlib.Path(link['runtime'])
 if not root.is_dir():raise ValueError('Linked runtime unavailable; pending events retained')
 store=Store(root);pending=json.loads((local/'pending.json').read_text());results=[]
 while pending:
  e=pending[0];result=store.external_work(link['lane'],e['command'],e['expected_revision'],e['request_id'],e['source']);results.append(result)
  pending.pop(0);save(local/'pending.json',pending)
  # Later offline events follow our last accepted revision, but never rebase over a concurrent writer.
  if pending and pending[0]['expected_revision'] is None:pending[0]['expected_revision']=result['revision'];save(local/'pending.json',pending)
 refresh(repo,local);return results

def operate(repo,action,work_id=None,summary=None,runtime=None,lane=None):
 repo=pathlib.Path(repo).resolve();local=repo/'.agent/local';local.mkdir(parents=True,exist_ok=True)
 with (local/'session.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if action=='init':
   if (local/'link.json').exists():raise ValueError('Already linked; do not overwrite project binding')
   if runtime:
    root=pathlib.Path(runtime).resolve()
    if not root.is_dir():raise ValueError('Runtime does not exist')
    store=Store(root);store.read(lane)
    if store.database(lane)!=store.path:root=store.database(lane).parents[2]
   else:
    root=local/'runtime';lane=lane or 'project';Store(root).ensure(lane,{'repository':str(repo),'integration':'standalone'})
   save(local/'link.json',{'runtime':str(root),'lane':lane});save(local/'pending.json',[]);return refresh(repo,local)
  if action=='connect':
   if not runtime or not lane:raise ValueError('connect requires runtime and lane')
   old=json.loads((local/'link.json').read_text());oldroot=pathlib.Path(old['runtime']).resolve()
   if oldroot!=(local/'runtime').resolve():raise ValueError('Already scheduler-linked; do not replace the authority')
   if json.loads((local/'pending.json').read_text()):raise ValueError('Resolve local pending events before connecting')
   target=pathlib.Path(runtime).resolve()
   if not target.is_dir():raise ValueError('Target runtime unavailable')
   targetstore=Store(target);current=targetstore.read(lane)
   if targetstore.database(lane)!=targetstore.path:target=targetstore.database(lane).parents[2]
   events=Store(oldroot).events(old['lane']);pending=[];seen=set()
   for e in events:
    event=json.loads(e['event'])
    if event['type']!='external_work':continue
    item=event['data'];status=item['status'];action='start' if item['id'] not in seen else {'active':'progress','completed':'finish','cancelled':'cancel'}[status];seen.add(item['id'])
    pending.append({'request_id':e['request_id'],'expected_revision':None if pending else current['revision'],'source':item['source'],'command':{'action':action,'id':item['id'],'summary':item['summary']}})
   save(local/'standalone-link.json',old);save(local/'link.json',{'runtime':str(target),'lane':lane});save(local/'pending.json',pending);save(local/'snapshot.json',current)
   try:return {'accepted':publish(repo,local),'standalone_state_preserved':str(oldroot)}
   except (OSError,ValueError) as exc:return {'pending_events':len(json.loads((local/'pending.json').read_text())),'error':str(exc),'next_action':'Resolve controller conflict; local history is retained'}
  if action=='context':
   try:return refresh(repo,local)
   except (OSError,ValueError) as exc:return {**snapshot(repo,local),'refresh_error':str(exc),'stale':True}
  if action=='cached':return snapshot(repo,local)
  if action=='sync':return {'accepted':publish(repo,local),'mirror':'Paperclip mirror is asynchronous when linked to a scheduler runtime'}
  if not work_id or not summary:raise ValueError('Work ID and summary required')
  pending=json.loads((local/'pending.json').read_text());cached=json.loads((local/'snapshot.json').read_text())
  # Refresh before online writes; do not silently reinterpret an older pending batch.
  if not pending:
   try:refresh(repo,local);cached=json.loads((local/'snapshot.json').read_text())
   except (OSError,ValueError):pass
  source='project-session:'+str(repo)
  e={'request_id':'external-'+uuid.uuid4().hex,'expected_revision':None if pending else cached['revision'],'source':source,'command':{'action':action,'id':work_id,'summary':summary}}
  pending.append(e);save(local/'pending.json',pending)
  try:return {'accepted':publish(repo,local),'pending_events':0}
  except (OSError,ValueError) as exc:return {'pending_events':len(json.loads((local/'pending.json').read_text())),'error':str(exc),'next_action':'Read current state and resolve conflict before retry; do not overwrite state or silently rebase events'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['init','connect','context','cached','sync','start','progress','finish','cancel']);p.add_argument('--repo',default='.');p.add_argument('--runtime');p.add_argument('--lane');p.add_argument('--id');p.add_argument('--summary');a=p.parse_args()
 try:
  if a.runtime and not a.lane:p.error('--runtime requires --lane')
  print(json.dumps(operate(a.repo,a.action,a.id,a.summary,a.runtime,a.lane),ensure_ascii=False,indent=2))
 except (OSError,ValueError,KeyError) as exc:print(json.dumps({'error':str(exc)},ensure_ascii=False));return 2
if __name__=='__main__':sys.exit(main())
