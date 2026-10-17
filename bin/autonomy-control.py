#!/usr/bin/env python3
"""Operator interface to the same project-owned loop control used by the console."""
import argparse,json,uuid
from runtime import ROOT
from project_state import Store
from loop_control import view,switch
p=argparse.ArgumentParser();p.add_argument('action',choices=['status','pause','resume','once']);p.add_argument('lane');a=p.parse_args()
if a.action!='status':
 store=Store(ROOT);switch(ROOT,a.lane,{'pause':'paused','resume':'continuous','once':'once'}[a.action],store.read(a.lane)['revision'],'cli-'+uuid.uuid4().hex)
print(json.dumps(view(ROOT,a.lane),ensure_ascii=False,indent=2))
