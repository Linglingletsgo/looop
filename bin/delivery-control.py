#!/usr/bin/env python3
"""Explicit per-project delivery setup and operator Packet submission."""
import argparse,hashlib,json,pathlib,sys,datetime,fcntl
from board import ROOT,Board
from delivery import validate
from roles import resolve,fingerprints,safe_path
from bridge import validate_profile

def config():return json.loads((ROOT/'data/control.json').read_text())
def project(s,lane):
 if lane not in s['projects']:raise ValueError('Unknown executable project lane (DS1 is excluded)')
 return s['projects'][lane]
def configure(lane,path=None):
 from execution_config import inherited_policy,inherited_mandate
 s=config();p=project(s,lane);repo=pathlib.Path(p['repo']).resolve()
 if not path and (ROOT/'data/delivery-policies'/(lane+'.json')).exists():
  print('Existing project execution configuration retained:',lane);return
 policy=json.loads(pathlib.Path(path).read_text()) if path else inherited_policy(repo)
 if pathlib.Path(policy['repo']).resolve()!=repo:raise ValueError('Policy repository differs from lane')
 validate_profile(p['profile'])
 registry=resolve(repo,policy.get('project_adapter'))
 # Prose workflows cannot be inferred safely from role names alone.
 for name in ('docs/project/single-developer-workflow.md','docs/project/agent-os-convergence-policy.md'):
  f=repo/name
  if f.is_file() and policy.get('workflow_evidence',{}).get(name)!=hashlib.sha256(f.read_bytes()).hexdigest():
   raise ValueError('Explicit project workflow mapping/hash required: '+name)
 for name,digest in policy.get('workflow_evidence',{}).items():
  if hashlib.sha256(safe_path(repo,name).read_bytes()).hexdigest()!=digest:raise ValueError('Workflow evidence changed: '+name)
 policy['role_registry']=fingerprints(registry)
 for step in policy.get('workflow',[]):
  if step.get('role') not in registry['roles']:raise ValueError('Undefined role '+str(step.get('role')))
 if registry['workflow'] is not None and registry['workflow']!=policy['workflow']:raise ValueError('Map project workflow before enabling')
 if not path:
  from delivery import validate
  validate({'title':'Configuration check','requirements':['Configuration only'],'acceptance':['No task execution'],'allowed_paths':policy.get('allowed_paths') or ['configuration-check.txt'],'baseline_sha':__import__('repository').git(repo,'rev-parse','HEAD').decode().strip()},policy)
 b=Board();company=p.get('company',s.get('company'));key=lane+':delivery'
 if key not in s['agents']:
  a=b.api('POST',f'/companies/{company}/agents',{'name':lane+' / packet delivery','role':'engineer','adapterType':'process','adapterConfig':{'command':'/usr/bin/python3','args':[str(ROOT/'bin/delivery-worker.py'),lane],'cwd':str(ROOT),'timeoutSec':0},'runtimeConfig':{'heartbeat':{'enabled':True,'intervalSec':60,'wakeOnDemand':True,'maxConcurrentRuns':1}},'permissions':{'canCreateAgents':False,'canCreateSkills':False}})
  s['agents'][key]=a['id']
 else:
  old=b.api('GET','/agents/'+s['agents'][key])
  b.api('PATCH','/agents/'+s['agents'][key],{'adapterConfig':{**old['adapterConfig'],'timeoutSec':0},'runtimeConfig':{'heartbeat':{'enabled':True,'intervalSec':60,'wakeOnDemand':True,'maxConcurrentRuns':1}}})
  a=b.api('GET','/agents/'+s['agents'][key])
  if a['status']=='paused':b.api('POST','/agents/'+s['agents'][key]+'/resume',{})
 # No arbitrary task gets a Packet or authorization merely by creating an Agent.
 folder=ROOT/'data/delivery-policies';folder.mkdir(exist_ok=True,mode=0o700)
 (folder/(lane+'.json')).write_text(json.dumps(policy,indent=2))
 (ROOT/'data/control.json').write_text(json.dumps(s,indent=2))
 if not path:
  from lifecycle import save
  target=ROOT/'data/autonomy-policies'/(lane+'.json')
  if not target.exists():save(target,inherited_mandate(policy))
 print('Packet execution configured:',lane)

def sync_prs():
 import subprocess
 b=Board()
 for folder in (ROOT/'data/deliveries').glob('*'):
  path=folder/'state.json'
  if not path.exists():continue
  state=json.loads(path.read_text())
  if state['state']=='merged' and (ROOT/'data/delivery-bindings'/(folder.name+'.json')).exists():
   finish_mainline(folder,state,b);continue
  if state['state']!='waiting_for_merge' or not state.get('pr_url'):continue
  pr=json.loads(subprocess.check_output([str(pathlib.Path.home()/'.local/bin/gh'),'pr','view',state['pr_url'],'--json','state,mergedAt,mergeCommit,url,headRefOid,baseRefOid,baseRefName,isDraft,mergeable,mergeStateStatus,statusCheckRollup']))
  binding=ROOT/'data/delivery-bindings'/(folder.name+'.json')
  if pr['state']=='OPEN' and binding.exists():
   d=json.loads(binding.read_text());policy_path=ROOT/'data/merge-policies'/(d['lane']+'.json')
   if policy_path.exists():
    from merging import merge
    try:
     pr=merge(folder,state,d,json.loads(policy_path.read_text()),pr)
     state['merge_authority']='product_approved';state.pop('merge_wait_reason',None)
    except Exception as exc:
     reason=str(exc)
     if state.get('merge_wait_reason')!=reason:
      state['merge_wait_reason']=reason;temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2));temp.replace(path)
      b.api('PATCH','/issues/'+folder.name,{'comment':'Product automatic merge deferred: '+reason})
     print(folder.name,'merge deferred:',reason)
     continue
  if pr['state']=='MERGED':
   b.api('PATCH','/issues/'+folder.name,{'status':'done','comment':'Verified merge ('+state.get('merge_authority','external')+'): '+pr['mergeCommit']['oid']})
   state.update(state='merged',merge_commit=pr['mergeCommit']['oid'],merged_at=pr['mergedAt'])
   temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2));temp.replace(path);print(folder.name,'merged')
   if binding.exists():finish_mainline(folder,state,b)
  elif pr['state']=='CLOSED':
   b.api('PATCH','/issues/'+folder.name,{'status':'cancelled','comment':'PR closed without merge; no automatic retry.'})
   state['state']='closed';path.write_text(json.dumps(state,indent=2));print(folder.name,'closed')

def finish_mainline(folder,state,b):
 if state.get('mainline_verified'):return
 from lifecycle import refresh,save
 d=json.loads((ROOT/'data/delivery-bindings'/(folder.name+'.json')).read_text())
 try:
  receipt=refresh(ROOT,d['lane'],d,state['merge_commit'])
  state['mainline_verified']=receipt['sha'];state.pop('mainline_wait_reason',None)
  save(folder/'state.json',state)
  b.api('PATCH','/issues/'+folder.name,{'comment':'合并后主线验证通过；执行仓库/profile已刷新：'+receipt['sha']})
 except Exception as exc:
  reason=str(exc)
  if state.get('mainline_wait_reason')!=reason:
   state['mainline_wait_reason']=reason;save(folder/'state.json',state)
   b.api('PATCH','/issues/'+folder.name,{'comment':'合并已完成，后续队列暂停等待主线核验：'+reason})

def submit(lane,path,publish,issue=None):
 s=config();p=project(s,lane);validate_profile(p['profile'])
 packet=json.loads(pathlib.Path(path).read_text());policy=json.loads((ROOT/'data/delivery-policies'/(lane+'.json')).read_text());validate(packet,policy)
 if publish and not policy.get('github_repo'):raise ValueError('No approved publication repository')
 if lane+':delivery' not in s['agents']:raise ValueError('Configure delivery first')
 b=Board();owner=b.api('GET','/auth/get-session')['user']['id'];company=p.get('company',s.get('company'))
 # Start unassigned; persist the binding before exposing the task to the worker.
 if issue:
  t=b.api('GET','/issues/'+issue)
  if t['projectId']!=p['id'] or t['status']!='backlog':raise ValueError('Existing issue must be project backlog')
  if (ROOT/'data/delivery-bindings'/(issue+'.json')).exists():raise ValueError('Issue already bound')
 else:
  from binding_requests import create
  key=hashlib.sha256(json.dumps({'lane':lane,'packet':packet,'publish':publish},sort_keys=True).encode()).hexdigest()
  request=ROOT/'data/operator-requests'/key;request.mkdir(parents=True,exist_ok=True,mode=0o700)
  with (request/'submit.lock').open('w') as request_lock:
   fcntl.flock(request_lock,fcntl.LOCK_EX)
   prior=request/'binding-request.json'
   if prior.exists():
    record=json.loads(prior.read_text())
    if record['state']!='bound':raise ValueError('Binding request pending reconciliation; do not repost')
    t=record['issue'];print(t.get('identifier',t['id']),t['id']);return
   import subprocess
   common=subprocess.check_output(['git','-C',policy['repo'],'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()
   (ROOT/'data/locks').mkdir(parents=True,exist_ok=True)
   with (ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as repo_lock:
    fcntl.flock(repo_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    d={'lane':lane,'packet':packet,'policy':policy,'owner':owner,'publish':publish}
    t=create(ROOT,b,request,d,company,{'projectId':p['id'],'title':packet['title'],'description':'Operator-bound immutable Packet.','status':'backlog'})
  b.api('PATCH','/issues/'+t['id'],{'status':'todo','assigneeUserId':None,'assigneeAgentId':s['agents'][lane+':delivery']})
  print(t['identifier'],t['id']);return
 folder=ROOT/'data/delivery-bindings';folder.mkdir(exist_ok=True,mode=0o700)
 d={'lane':lane,'packet':packet,'policy':policy,'owner':owner,'publish':publish}
 from project_state import configured_store
 store=configured_store(ROOT)
 if store:
  store.project_guard(lane);store.bind(lane,t['id'],packet,provenance={'source':'operator-submit'})
 from lifecycle import save
 target=folder/(t['id']+'.json');save(target,d)
 b.api('PATCH','/issues/'+t['id'],{'status':'todo','assigneeUserId':None,'assigneeAgentId':s['agents'][lane+':delivery']})
 print(t['identifier'],t['id'])

def retry(issue,reason):
 # Explicit operator recovery only. All approval/check gates run again in fresh contexts.
 from recovery import prepare
 b=Board();task=b.api('GET','/issues/'+issue)
 if task['status']!='blocked':raise ValueError('Only blocked tasks can be retried')
 path=ROOT/'data/delivery-bindings'/(issue+'.json');d=json.loads(path.read_text());s=config();agent=s['agents'][d['lane']+':delivery']
 if b.api('GET','/agents/'+agent)['status']=='running':raise ValueError('Worker still running')
 archive=prepare(ROOT,issue,reason)
 b.api('PATCH','/issues/'+issue,{'status':'todo','assigneeUserId':None,'assigneeAgentId':agent,'comment':'Explicit operator retry: '+reason+'; preserved evidence: '+str(archive)})
 print('Retry queued:',issue)

def resume_repair(issue,reason,receipt=False,evidence=False):
 # Resume a stopped scheduler failure without discarding its candidate.
 from delivery import execute
 path=ROOT/'data/delivery-bindings'/(issue+'.json');d=json.loads(path.read_text())
 b=Board();task=b.api('GET','/issues/'+issue)
 if task['status'] not in ('blocked','in_progress'):raise ValueError('Task must be blocked or retain an interrupted in-progress board projection')
 s=config();cfg=s['projects'][d['lane']]
 if task.get('projectId')!=cfg['id']:raise ValueError('Project mismatch')
 agent=s['agents'][d['lane']+':delivery']
 if b.api('GET','/agents/'+agent)['status']=='running':raise ValueError('Worker still running')
 result=execute(d['packet'],d['policy'],issue,publish=d['publish'],resume_repair=not (receipt or evidence),resume_receipt=receipt,resume_evidence=evidence)
 if result['state']=='queued':return
 if result['state'] not in ('waiting_for_merge','validated'):raise ValueError('Repair did not complete delivery gates')
 b.api('PATCH','/issues/'+issue,{'status':'in_review' if result['state']=='waiting_for_merge' else 'done','assigneeAgentId':None,'assigneeUserId':d['owner'],'comment':'Continued preserved candidate: '+reason+'; fresh checks and independent review passed. '+result.get('pr_url','')})
 print('Repair completed:',issue,result['state'])


if __name__=='__main__':
 p=argparse.ArgumentParser();sp=p.add_subparsers(dest='action',required=True)
 sp.add_parser('sync-prs')
 a=sp.add_parser('clarify');a.add_argument('issue')
 a=sp.add_parser('resume-evidence');a.add_argument('issue');a.add_argument('--reason',required=True)
 a=sp.add_parser('resume-receipt');a.add_argument('issue');a.add_argument('--reason',required=True)
 a=sp.add_parser('resume-repair');a.add_argument('issue');a.add_argument('--reason',required=True)
 a=sp.add_parser('retry');a.add_argument('issue');a.add_argument('--reason',required=True)
 a=sp.add_parser('roles');a.add_argument('repo')
 a=sp.add_parser('configure');a.add_argument('lane');a.add_argument('--policy')
 a=sp.add_parser('submit');a.add_argument('lane');a.add_argument('--packet',required=True);a.add_argument('--publish',action='store_true');a.add_argument('--issue')
 args=p.parse_args()
 if args.action=='roles':
  r=resolve(args.repo);print(json.dumps({'project_roles':r['project_roles'],'roles':fingerprints(r),'workflow':r['workflow']},ensure_ascii=False,indent=2))
 elif args.action=='sync-prs':sync_prs()
 elif args.action=='configure':configure(args.lane,args.policy)
 elif args.action=='clarify':
  from delivery_clarification import clarify
  clarify(ROOT,args.issue);print('Product clarification saved:',args.issue)
 elif args.action=='resume-evidence':resume_repair(args.issue,args.reason,evidence=True)
 elif args.action=='resume-receipt':resume_repair(args.issue,args.reason,receipt=True)
 elif args.action=='resume-repair':resume_repair(args.issue,args.reason)
 elif args.action=='retry':retry(args.issue,args.reason)
 else:submit(args.lane,args.packet,args.publish,args.issue)
