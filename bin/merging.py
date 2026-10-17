"""Controller-owned Product-approved merge policy; model sandboxes cannot merge."""
import json,pathlib,subprocess
from gates import GateError,require_pr

def eligibility(folder,state,binding,policy,pr):
 if policy.get('mode') not in ('product_approved','acceptance_approved','review_approved'):raise GateError('Product merge policy disabled')
 if not binding.get('publish') or binding['policy'].get('github_repo')!=policy.get('github_repo'):raise GateError('Publication repository mismatch')
 require_pr(state,binding['policy'])
 steps=binding['policy']['workflow']
 if policy['mode']=='review_approved':
  if any(s['stage']=='acceptance' for s in steps):raise GateError('Review-only merge requires a workflow without acceptance')
  if steps[-1]['stage']!='review' or steps[-1]['role']!=policy.get('review_role'):raise GateError('Configured reviewer mismatch')
  for step in steps:
   if step['stage']!='review':continue
   mode=step.get('mode','standard');evidence=state['reviews'].get(mode,{})
   if evidence.get('verdict')!='approved' or evidence.get('target_sha')!=state['target_sha']:raise GateError('Review missing or stale')
   from gates import verdict
   report=pathlib.Path(folder)/evidence['run_id']/'result.md'
   if verdict(report.read_text()).get('verdict')!='approved':raise GateError('Reviewer report not approved')
 else:
  if not state.get('acceptance',{}).get('run_id'):raise GateError('Acceptance run missing')
  if steps[-1]['stage']!='acceptance' or steps[-1]['role']!=policy.get('acceptance_role'):raise GateError('Final acceptance is not the configured Product role')
  run=pathlib.Path(folder)/state['acceptance']['run_id']
  result=json.loads((run/'result.md').read_text())
  if result.get('verdict')!='approved':raise GateError('Product report is not approved')
 checks=json.loads((pathlib.Path(folder)/('checks-'+str(state['round'])+'.json')).read_text())
 if [c['argv'] for c in checks]!=binding['policy']['checks'] or any(c['exit_code'] for c in checks):raise GateError('Checks missing or failed')
 if pr.get('state')!='OPEN' or pr.get('isDraft'):raise GateError('PR not open/ready')
 if pr.get('url')!=state['pr_url'] or not pr['url'].startswith('https://github.com/'+policy['github_repo']+'/pull/'):raise GateError('PR repository mismatch')
 if pr.get('headRefOid')!=state['target_sha']:raise GateError('PR head changed; fresh review required')
 if pr.get('baseRefName')!=binding['policy'].get('base_branch','main') or pr.get('baseRefOid')!=binding['packet']['baseline_sha']:raise GateError('Base moved; refresh baseline and rerun gates')
 if pr.get('mergeable')!='MERGEABLE' or pr.get('mergeStateStatus')!='CLEAN':raise GateError('GitHub merge state not clean')
 for check in pr.get('statusCheckRollup',[]):
  if check.get('__typename')=='CheckRun':
   if check.get('status')!='COMPLETED' or check.get('conclusion') not in ('SUCCESS','NEUTRAL','SKIPPED'):raise GateError('GitHub checks pending/failed')
  elif check.get('state')!='SUCCESS':raise GateError('GitHub status pending/failed')
 return True

def merge(folder,state,binding,policy,pr):
 eligibility(folder,state,binding,policy,pr)
 gh=str(pathlib.Path.home()/'.local/bin/gh')
 def perform():
  subprocess.run([gh,'pr','merge',state['pr_url'],'--merge','--match-head-commit',state['target_sha']],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  return json.loads(subprocess.check_output([gh,'pr','view',state['pr_url'],'--json','state,mergedAt,mergeCommit']))
 from project_state import configured_store
 from runtime import ROOT
 store=configured_store(ROOT) if binding.get('lane') else None
 if store:return store.merge_gate(binding['lane'],pathlib.Path(folder).name,state['target_sha'],perform)
 return perform()
