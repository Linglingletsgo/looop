#!/usr/bin/env python3
"""Operator commands: inspect status, onboard planning projects, submit bounded planning tasks."""
import argparse,datetime,importlib.util,json,pathlib,re,subprocess,sys,uuid
from board import Board,ROOT

def status():
 b=Board()
 for c in b.api('GET','/companies'):
  print('\n'+c['name'])
  for t in b.api('GET',f'/companies/{c["id"]}/issues'):
   print(t['identifier'],t['status'],t['title'])
 for name in ['codex','commandcode','magpie_chatgpt','magpie_deepseek','magpie_commandcode','magpie_flash_pool']:
  p=ROOT/'data'/('quota-'+name+'.json');print(name,'PAUSED '+p.read_text() if p.exists() else 'available; subscription remaining unknown')

def onboard(repo,name,lane):
 if not re.fullmatch('[a-z][a-z0-9-]{0,47}',lane):raise ValueError('lane must be a short slug')
 statepath=ROOT/'data/control.json';state=json.loads(statepath.read_text())
 if lane in state['projects']:raise ValueError('lane already exists')
 profile=lane+'-'+uuid.uuid4().hex[:8]+'.json';subprocess.run(['python3',str(ROOT/'bin/project-profile.py'),'inspect',repo,'--output',str(ROOT/'profiles'/profile)],check=True)
 b=Board();company=b.api('POST','/companies',{'name':name,'description':'Bounded planning enabled. Delivery requires explicit project-specific execution policy; no auto merge.'})
 p=b.api('POST',f'/companies/{company["id"]}/projects',{'name':name,'status':'planned','workspace':{'name':lane,'cwd':str(pathlib.Path(repo).resolve()),'isPrimary':True}})
 a=b.api('POST',f'/companies/{company["id"]}/agents',{'name':lane+' / product','role':'pm','adapterType':'process','adapterConfig':{'command':'/usr/bin/python3','args':[str(ROOT/'bin/bridge.py'),'heartbeat',lane,'product'],'cwd':str(ROOT),'timeoutSec':0},'runtimeConfig':{'heartbeat':{'enabled':True,'intervalSec':60,'wakeOnDemand':True,'maxConcurrentRuns':1}},'permissions':{'canCreateAgents':False,'canCreateSkills':False}})
 state['projects'][lane]={'id':p['id'],'company':company['id'],'repo':str(pathlib.Path(repo).resolve()),'profile':profile};state['agents'][lane+':product']=a['id'];statepath.write_text(json.dumps(state,indent=2));print('Planning project connected:',lane)

def reconcile():
 # Never replay an interrupted attempt automatically. Preserve uncertainty for an operator.
 import sqlite3
 p=ROOT/'data/bridge.sqlite'
 if p.exists():
  c=sqlite3.connect(p)
  for issue,rid in c.execute("SELECT issue,run_id FROM jobs WHERE state='running'").fetchall():
   print('Inspect interrupted/running job',issue,'run',rid,'before retry; no replay performed')
 for p in list((ROOT/'data/pipelines').glob('*/state.json'))+list((ROOT/'data/gtp-pilot').glob('*/state.json'))+list((ROOT/'data/deliveries').glob('*/state.json')):
  s=json.loads(p.read_text());print(p.parent.name,s.get('state'),s.get('pr_url',''))

if __name__=='__main__':
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
 sub.add_parser('status');sub.add_parser('reconcile');sub.add_parser('sync-usage')
 a=sub.add_parser('add-project');a.add_argument('--repo',required=True);a.add_argument('--name',required=True);a.add_argument('--lane',required=True)
 a=sub.add_parser('plan');a.add_argument('--role',choices=['product','product-manager'],default='product');a.add_argument('lane');a.add_argument('--title',required=True);a.add_argument('--description',required=True)
 args=p.parse_args()
 if args.action=='status':status()
 elif args.action=='reconcile':reconcile()
 elif args.action=='sync-usage':
  from metrics import record
  b=Board()
  for kind,base in [('fixture','pipelines'),('gtp','gtp-pilot')]:
   p=ROOT/'data'/(kind+'-control.json')
   if not p.exists():continue
   cfg=json.loads(p.read_text())
   for folder in (ROOT/'data'/base).iterdir():
    if folder.is_dir() and (folder/'state.json').exists():record(b,folder,cfg['company'],cfg['agent'],folder.name,cfg['project'])
  for folder in (ROOT/'data/deliveries').glob('*'):
   binding=ROOT/'data/delivery-bindings'/(folder.name+'.json')
   if not binding.exists():continue
   d=json.loads(binding.read_text());s=json.loads((ROOT/'data/control.json').read_text());cfg=s['projects'][d['lane']]
   record(b,folder,cfg.get('company',s.get('company')),s['agents'][d['lane']+':delivery'],folder.name,cfg['id'])
  print('Measured tokens imported; costs unpriced, remaining unknown.')
 elif args.action=='add-project':onboard(args.repo,args.name,args.lane)
 else:
  from bridge import submit
  s=json.loads((ROOT/'data/control.json').read_text());key=args.lane+':'+args.role
  if key not in s['agents']:
   if args.lane not in s['projects']:raise ValueError('Unknown executable lane')
   cfg=s['projects'][args.lane];b=Board();company=cfg.get('company',s.get('company'))
   a=b.api('POST',f'/companies/{company}/agents',{'name':args.lane+' / '+args.role,'role':'pm','adapterType':'process','adapterConfig':{'command':'/usr/bin/python3','args':[str(ROOT/'bin/bridge.py'),'heartbeat',args.lane,args.role],'cwd':str(ROOT),'timeoutSec':0},'runtimeConfig':{'heartbeat':{'enabled':True,'intervalSec':60,'wakeOnDemand':True,'maxConcurrentRuns':1}},'permissions':{'canCreateAgents':False,'canCreateSkills':False}})
   s['agents'][key]=a['id'];(ROOT/'data/control.json').write_text(json.dumps(s,indent=2))
  submit(args.lane,args.title,args.description,args.role)
