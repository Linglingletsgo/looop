#!/usr/bin/env python3
"""Operator interface to the same project-owned loop control used by the console."""
import argparse,json,uuid
from runtime import ROOT
from project_state import Store
from loop_control import view,switch,set_settings
p=argparse.ArgumentParser();p.add_argument('action',choices=['status','pause','resume','once','select']);p.add_argument('lane');p.add_argument('--selection-mode',choices=['backlog_only','backlog_and_research']);a=p.parse_args()
if a.action=='select':
 if not a.selection_mode:p.error('select requires --selection-mode')
 store=Store(ROOT);set_settings(ROOT,a.lane,view(ROOT,a.lane)['limits']['max_proposals_per_day'],a.selection_mode,store.read(a.lane)['revision'],'cli-'+uuid.uuid4().hex)
elif a.action!='status':
 store=Store(ROOT);switch(ROOT,a.lane,{'pause':'paused','resume':'continuous','once':'once'}[a.action],store.read(a.lane)['revision'],'cli-'+uuid.uuid4().hex)
print(json.dumps(view(ROOT,a.lane),ensure_ascii=False,indent=2))
