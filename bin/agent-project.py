#!/usr/bin/env python3
"""Scheduler-independent project setup, context, immutable task binding and execution."""
import argparse,fcntl,json,pathlib,re,sys
from runtime import ROOT
from project_adapter import load,validate,summary,context,evidence,check_policy
from project_state import Store,valid_lane
from roles import resolve,contract,fingerprints
from repository import git

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)

def config_for(repo,manifest):
 return validate(json.loads(pathlib.Path(manifest).read_text())) if manifest else load(repo)

def configure(lane,repo,adapter,policy):
 from delivery import validate as validate_packet
 valid_lane(lane);repo=pathlib.Path(repo).resolve()
 if not adapter:raise ValueError('Explicit project manifest required for configuration')
 policy={**policy,'repo':str(repo),'project_adapter':adapter}
 check_policy(policy)
 if not policy.get('enabled'):raise ValueError('An enabled, operator-reviewed execution policy is required')
 policy['role_registry']=fingerprints(resolve(repo,adapter))
 policy['workflow_evidence']={**policy.get('workflow_evidence',{}),**evidence(repo,adapter)}
 for step in policy['workflow']:contract(resolve(repo,adapter),step['role'])
 sha=git(repo,'rev-parse','HEAD').decode().strip()
 validate_packet({'title':'Validate project configuration','requirements':['Configuration validation only'],'acceptance':['No execution'],'allowed_paths':policy['allowed_paths'],'baseline_sha':sha},policy)
 locks=ROOT/'data/locks';locks.mkdir(parents=True,exist_ok=True)
 with (locks/'config').open('w') as h:
  fcntl.flock(h,fcntl.LOCK_EX)
  path=ROOT/'data/control.json';cfg=json.loads(path.read_text()) if path.exists() else {'projects':{},'agents':{}}
  if lane in cfg['projects']:raise ValueError('Project already registered; configure must not overwrite an existing integration')
  save(ROOT/'data/delivery-policies'/(lane+'.json'),policy)
  cfg['projects'][lane]={'repo':str(repo),'integration':'standalone'};save(path,cfg)
  Store(ROOT).ensure(lane,{'repository':str(repo),'allowed_paths':policy['allowed_paths'],'scope_source':str(ROOT/'data/delivery-policies'/(lane+'.json'))})
  (ROOT/'data/project-state/enabled').touch()
 return {'lane':lane,'runtime':str(ROOT),'configured':True,'automatic_scheduling':False}

def bind(lane,packet,job,publish=False):
 from delivery import validate as validate_packet
 valid_lane(lane)
 if not re.fullmatch('[a-zA-Z0-9-]{1,80}',job):raise ValueError('Invalid job id')
 policy=json.loads((ROOT/'data/delivery-policies'/(lane+'.json')).read_text());validate_packet(packet,policy)
 if publish and not policy.get('github_repo'):raise ValueError('No approved publication repository')
 if git(policy['repo'],'rev-parse','HEAD').decode().strip()!=packet['baseline_sha']:raise ValueError('Baseline moved; regenerate Packet')
 path=ROOT/'data/delivery-bindings'/(job+'.json');lock=ROOT/'data/locks/bind';lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as h:
  fcntl.flock(h,fcntl.LOCK_EX)
  if path.exists():raise ValueError('Task already bound; use run to inspect/preserve existing attempt')
  config_path=ROOT/'data/control.json'
  if config_path.exists() and json.loads(config_path.read_text()).get('projects',{}).get(lane,{}).get('id'):
   raise ValueError('Registered lane: create new bindings via delivery-control.py submit; standalone run of existing bindings uses this same state and lock. New independent projects use a separate runtime root.')
  store=Store(ROOT);store.project_guard(lane);store.bind(lane,job,packet,provenance={'source':'operator-cli'})
  save(path,{'lane':lane,'packet':packet,'policy':policy,'publish':publish,'source':'operator-cli'})
 return {'job':job,'phase':'queued','publish':publish}

def run_bound(job):
 from delivery import execute
 if not re.fullmatch('[a-zA-Z0-9-]{1,80}',job):raise ValueError('Invalid job id')
 d=json.loads((ROOT/'data/delivery-bindings'/(job+'.json')).read_text())
 return execute(d['packet'],d['policy'],job,emit=lambda stage:print(stage,file=sys.stderr),publish=d.get('publish',False))

def plan(lane,brief,plan_id):
 from repository import snapshot
 from sandbox import run
 from delivery import validate as validate_packet
 import hashlib
 valid_lane(lane)
 if not re.fullmatch('[a-zA-Z0-9-]{1,80}',plan_id):raise ValueError('Invalid plan id')
 policy=json.loads((ROOT/'data/delivery-policies'/(lane+'.json')).read_text());check_policy(policy)
 if not policy.get('enabled'):raise ValueError('Project execution policy disabled')
 store=Store(ROOT);store.project_guard(lane);before=store.context(lane)
 repo=pathlib.Path(policy['repo']);sha=git(repo,'rev-parse','HEAD').decode().strip()
 common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
 lockpath=ROOT/'data/locks'/hashlib.sha256(common.encode()).hexdigest();lockpath.parent.mkdir(parents=True,exist_ok=True)
 with lockpath.open('w') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  folder=ROOT/'data/plans'/plan_id
  if folder.exists():raise ValueError('Existing planning attempt; inspect evidence rather than replay')
  folder.mkdir(parents=True,mode=0o700)
  workspace=snapshot(repo,sha,folder/'workspace');adapter=policy.get('project_adapter');registry=resolve(workspace,adapter)
  if fingerprints(registry)!=policy.get('role_registry'):raise ValueError('Role baseline changed')
  for name,expected in policy.get('workflow_evidence',{}).items():
   if hashlib.sha256((workspace/name).read_bytes()).hexdigest()!=expected:raise ValueError('Workflow evidence changed: '+name)
  role=adapter.get('planning_role','product-manager') if adapter else 'product-manager'
  prompt=contract(registry,role)+'\n'+context(workspace,adapter,role,policy['allowed_paths'])
  prompt+='\nRead-only planning. Define at most one bounded task; do not implement or dispatch. Allowed paths: '+json.dumps(policy['allowed_paths'])+'\nCurrent project state: '+json.dumps(before,ensure_ascii=False)+'\nOperator brief: '+brief
  prompt+='\nReturn only JSON {"action":"task|no_work","reason":"...","packet":{"title":"...","requirements":["..."],"acceptance":["..."],"allowed_paths":["..."]}}. Do not expand authorization or treat drafts as confirmed. Baseline SHA is fixed by the controller.'
  result=json.loads(run(workspace,folder/'pm',prompt,role='readonly',timeout=None,provider_id='codex'))
  save(folder/'result.json',result)
  if store.read(lane)['planning_revision']!=before['planning_revision']:raise ValueError('External decisions changed during planning; proposal stale')
  if result.get('action')=='task':
   packet={k:result['packet'][k] for k in ('title','requirements','acceptance','allowed_paths')};packet['baseline_sha']=sha;validate_packet(packet,policy);save(folder/'packet.json',packet)
  elif result.get('action')!='no_work' or not result.get('reason'):raise ValueError('Invalid PM output')
  return {'result':result,'evidence':str(folder),'bound':False}

def main():
 p=argparse.ArgumentParser();sp=p.add_subparsers(dest='action',required=True)
 for name in ('inspect','context','configure'):
  a=sp.add_parser(name);a.add_argument('--repo',required=True);a.add_argument('--manifest')
  if name=='context':a.add_argument('--role',required=True);a.add_argument('--target',action='append',default=[])
  if name=='configure':a.add_argument('--lane',required=True);a.add_argument('--policy',required=True)
 a=sp.add_parser('plan');a.add_argument('lane');a.add_argument('--brief-file',required=True);a.add_argument('--plan-id',required=True)
 a=sp.add_parser('state');a.add_argument('lane')
 a=sp.add_parser('bind');a.add_argument('lane');a.add_argument('--packet',required=True);a.add_argument('--job',required=True);a.add_argument('--publish',action='store_true')
 a=sp.add_parser('run');a.add_argument('--job',required=True)
 args=p.parse_args()
 try:
  if args.action in ('inspect','context','configure'):
   config=config_for(args.repo,args.manifest)
   if args.action=='inspect':result=summary(args.repo,config)
   elif args.action=='context':result={'role':contract(resolve(args.repo,config),args.role),'rules':context(args.repo,config,args.role,args.target)}
   else:result=configure(args.lane,args.repo,config,json.loads(pathlib.Path(args.policy).read_text()))
  elif args.action=='plan':result=plan(args.lane,pathlib.Path(args.brief_file).read_text(),args.plan_id)
  elif args.action=='state':result=Store(ROOT).context(args.lane)
  elif args.action=='bind':result=bind(args.lane,json.loads(pathlib.Path(args.packet).read_text()),args.job,args.publish)
  else:result=run_bound(args.job)
  print(json.dumps(result,ensure_ascii=False,indent=2))
 except (ValueError,KeyError,OSError) as exc:print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
 return 0
if __name__=='__main__':sys.exit(main())
