"""Durable create/bind journal. Uncertain remote creation is queried, never reposted."""
import fcntl,json,pathlib,subprocess,uuid
from lifecycle import save
from project_state import configured_store
from delivery import validate
from tracker import as_tracker

def finish(root,tracker,path,record,issue):
 tracker=as_tracker(tracker,root)
 binding=record['binding'];lane=binding['lane']
 if issue.get('lane')!=lane or issue.get('status')!='backlog' or issue.get('assignee'):raise ValueError('Remote issue changed; preserve manual state')
 policy=root/'data/delivery-policies'/(lane+'.json')
 if json.loads(policy.read_text())!=binding['policy']:raise ValueError('Policy changed during binding recovery')
 validate(binding['packet'],binding['policy'])
 head=subprocess.check_output(['git','-C',binding['policy']['repo'],'rev-parse','HEAD'],text=True).strip()
 if head!=binding['packet']['baseline_sha']:raise ValueError('Baseline changed during binding recovery')
 store=configured_store(root)
 if store:
  store.project_guard(lane)
  store.bind(lane,issue['id'],binding['packet'],binding.get('intent_ids',[]),binding.get('authorization',{}),planning_revision=record.get('planning_revision'))
 target=root/'data/delivery-bindings'/(issue['id']+'.json')
 if target.exists():
  if json.loads(target.read_text())!=binding:raise ValueError('Conflicting immutable binding')
 else:save(target,binding)
 record.update(state='bound',issue=issue);save(path,record)
 return issue

def create(root,tracker,folder,binding,company,payload,planning_revision=None):
 tracker=as_tracker(tracker,root);folder=pathlib.Path(folder);folder.mkdir(parents=True,exist_ok=True,mode=0o700);path=folder/'binding-request.json'
 if path.exists():raise ValueError('Existing binding request; use reconciliation instead of reposting')
 token=uuid.uuid4().hex;marker='<!-- binding-request:'+token+' -->'
 payload={**payload,'description':payload.get('description','')+'\n\n'+marker}
 record={'state':'posting','marker':marker,'binding':binding,'company':company,'payload':payload,'planning_revision':planning_revision}
 if tracker.idempotent_create:record['job_id']=token
 save(path,record)
 # The posting journal is durable before sending. Local creation is idempotent; remote POST is never retried.
 issue=tracker.create(binding['lane'],'delivery',payload['title'],payload['status'],payload['description'],job_id=token if tracker.idempotent_create else None,company=company)
 record.update(state='binding',issue=issue);save(path,record)
 return finish(root,tracker,path,record,issue)

def reconcile(root,tracker):
 tracker=as_tracker(tracker,root);results=[];lock=root/'data/locks/binding-requests';lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as h:
  try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return []
  paths=list((root/'data/autonomy').glob('*/*/binding-request.json'))+list((root/'data/operator-requests').glob('*/binding-request.json'))
  for path in paths:
   try:
    record=json.loads(path.read_text())
    if record['state']=='bound':continue
    # An active creator holds the project repository lock. Avoid concurrent advancement.
    binding=record['binding'];repo=binding['policy']['repo']
    common=subprocess.check_output(['git','-C',repo,'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()
    import hashlib
    with (root/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
     try:fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
     except BlockingIOError:continue
     if record.get('issue'):
      target=root/'data/delivery-bindings'/(record['issue']['id']+'.json')
      if target.exists() and json.loads(target.read_text())==binding:
       record['state']='bound';save(path,record);results.append({'job':record['issue']['id'],'state':'bound'});continue
      issue=tracker.get(record['issue']['id'])
     elif tracker.idempotent_create:
      payload=record['payload']
      if not record.get('job_id'):raise ValueError('Journal predates the local job table; rerun scripts/migrate-jobs.py and reconcile again')
      try:issue=tracker.get(record['job_id'])
      except KeyError:issue=tracker.create(binding['lane'],'delivery',payload['title'],payload['status'],payload['description'],job_id=record['job_id'])
      record.update(state='binding',issue=issue);save(path,record)
     else:
      matches=tracker.find(binding['lane'],record['marker'],record.get('company'),record['payload'].get('projectId'))
      if len(matches)!=1:raise ValueError('Remote create result unresolved; query again, never repost')
      issue=matches[0];record.update(state='binding',issue=issue);save(path,record)
     finish(root,tracker,path,record,issue);results.append({'job':issue['id'],'state':'bound'})
   except Exception as exc:results.append({'job':path.parent.name,'state':'deferred','reason':str(exc)})
 save(root/'data/binding-recovery-status.json',{'results':results});return results

if __name__=='__main__':
 from runtime import ROOT
 from tracker import open_tracker
 print(json.dumps(reconcile(ROOT,open_tracker(ROOT)),ensure_ascii=False))
