#!/usr/bin/env python3
"""Harness-neutral interface for external Product conversations. No execution permissions."""
import argparse,json,sys
from runtime import ROOT
from project_state import Store,Conflict

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['init','context','read','history','submit']);p.add_argument('lane');p.add_argument('--file',default='-');p.add_argument('--expected-revision',type=int);p.add_argument('--request-id');p.add_argument('--source');a=p.parse_args();store=Store(ROOT)
 try:
  if a.action=='init':
   config=json.loads((ROOT/'data/control.json').read_text())
   if a.lane not in config['projects']:raise ValueError('Register an executable project first; DS1 is excluded')
   cfg=config['projects'][a.lane];path=ROOT/'data/delivery-policies'/(a.lane+'.json');policy=json.loads(path.read_text()) if path.exists() else {}
   result=store.ensure(a.lane,{'repository':cfg['repo'],'allowed_paths':policy.get('allowed_paths',[]),'scope_source':str(path)})
  elif a.action=='read':result=store.read(a.lane)
  elif a.action=='context':result=store.context(a.lane)
  elif a.action=='history':result=store.events(a.lane)
  else:
   if not a.request_id or not a.source:p.error('submit requires --request-id and --source')
   with (sys.stdin if a.file=='-' else open(a.file)) as f:value=json.load(f)
   result=store.submit(a.lane,value,a.expected_revision,a.request_id,a.source)
  print(json.dumps(result,ensure_ascii=False,indent=2))
 except (ValueError,KeyError) as e:
  print(json.dumps({'error':str(e),'conflict':isinstance(e,Conflict)},ensure_ascii=False),file=sys.stderr);return 2
 return 0
if __name__=='__main__':sys.exit(main())
