#!/usr/bin/env python3
"""Dispatch an explicit project check to its configured native Harness Agent."""
import argparse,json,pathlib,sys
from runtime import ROOT
from executor import command
from repository import snapshot,git
from lifecycle_io import save

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('lane');p.add_argument('--job',required=True);p.add_argument('argv',nargs=argparse.REMAINDER);a=p.parse_args()
 from project_state import valid_lane
 valid_lane(a.lane)
 import re
 if not re.fullmatch('[a-zA-Z0-9-]{1,80}',a.job):p.error('Invalid job')
 argv=a.argv[1:] if a.argv[:1]==['--'] else a.argv
 if not argv:p.error('Explicit command required')
 policy=json.loads((ROOT/'data/delivery-policies'/(a.lane+'.json')).read_text());repo=pathlib.Path(policy['repo']);sha=git(repo,'rev-parse','HEAD').decode().strip();folder=ROOT/'data/agent-checks'/a.lane/a.job
 if folder.exists():raise ValueError('Existing check retained; inspect evidence instead of replay')
 workspace=snapshot(repo,sha,folder/'workspace');save(folder/'state.json',{'state':'running','sha':sha,'lane':a.lane,'argv':argv})
 result=command(workspace,argv,dependencies=policy.get('dependencies'))
 receipt={'state':'validated' if result.returncode==0 else 'blocked','sha':sha,'lane':a.lane,'argv':argv,'exit_code':result.returncode,'output':result.stdout[-24000:],'executor':'native-agent'};save(folder/'state.json',receipt);print(json.dumps(receipt,ensure_ascii=False));return result.returncode
if __name__=='__main__':sys.exit(main())
