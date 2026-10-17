#!/usr/bin/env python3
"""Operator switch for new autonomous planning; never kills active work or resets evidence."""
import argparse,json
from board import ROOT
from lifecycle import save
p=argparse.ArgumentParser();p.add_argument('action',choices=['status','pause','resume']);p.add_argument('lane');args=p.parse_args()
if not args.lane.replace('-','').isalnum():raise ValueError('Invalid lane')
path=ROOT/'data/autonomy-policies'/(args.lane+'.json');policy=json.loads(path.read_text())
if args.action!='status':
 policy['enabled']=args.action=='resume';save(path,policy)
 print('New autonomous planning '+('enabled' if policy['enabled'] else 'paused')+'; active/bound tasks and historical evidence unchanged.')
print(json.dumps(policy,ensure_ascii=False,indent=2))
