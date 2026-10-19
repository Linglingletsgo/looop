"""Dispatch project verification to a native Harness Agent; never execute project commands here."""
import json,pathlib,subprocess,uuid
from runtime import ROOT
from lifecycle_io import save


def command(workspace,argv,timeout=None,stdin=None,writable=False,dependencies=None):
 if not isinstance(argv,list) or not argv or not all(isinstance(x,str) for x in argv):raise ValueError('Check argv required')
 if writable:raise ValueError('Verification cannot modify project source; dispatch Builder instead')
 from sandbox import run
 from roles import resolve,contract
 from execution_settings import read,route
 from planning_runtime import invoke
 registry=resolve(workspace);role='qa' if 'qa' in registry['project_roles'] or 'reviewer' not in registry['project_roles'] else 'reviewer'
 folder=ROOT/'data/verification-agents'/uuid.uuid4().hex
 prompt=contract(registry,role)+'\nExecute the requested project check using real tools in this project snapshot. Do not implement or modify source. Do not install dependencies or access production data, external models or mail. Use only the documented isolated test environment when needed. Record the actual exit code, concise output, and evidence file path in handoff.json. Never infer a pass from source inspection. You may inspect project instructions to determine the correct environment. If a prerequisite is unavailable, use a nonzero exit code and explain. Requested argv: '+json.dumps(argv)+'\nStdin: '+json.dumps(stdin)+'\nWrite handoff.json result {"argv": [...exact requested argv...], "exit_code": integer, "output": "bounded actual execution summary", "evidence_path": "artifact path"}. The scheduler dispatches this job; it does not run or interpret the test.'
 def validate(value):
  if not isinstance(value,dict) or value.get('argv')!=argv:raise ValueError('Verification result belongs to another check')
  if type(value.get('exit_code')) is not int:raise ValueError('Verification exit_code must be an integer')
  for key in ('output','evidence_path'):
   if not isinstance(value.get(key),str) or len(value[key])>24000:raise ValueError('Verification requires bounded '+key)
 save(folder/'state.json',{'state':'running','executor':'native-agent','argv':argv})
 value=invoke(run,workspace,folder,prompt,lambda:None,validate=validate,role='readonly',timeout=None,dependencies=dependencies,execution_route=route(read(ROOT),'review','codex'))
 save(folder/'receipt.json',{'executor':'native-agent','role':role,**value})
 save(folder/'state.json',{'state':'validated','executor':'native-agent','argv':argv,'exit_code':value['exit_code']})
 return subprocess.CompletedProcess(argv,value['exit_code'],value['output']+'\nAgent evidence: '+value['evidence_path'])
