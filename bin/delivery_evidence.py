"""Evidence navigation and source-preserving repair gates."""
import hashlib,json,pathlib
from repository import git
from gates import GateError,verdict as check_result
from output_protocol import delivery_schema

def saved_result(report,stage='build'):
 # Modern runs hand off through a file; legacy attempts retain their original transport.
 repaired=report.parent/'repaired-result.json'
 if repaired.is_file() and not repaired.is_symlink():return check_result(repaired.read_text())
 path=report.parent/'handoff.json'
 if path.exists() or path.is_symlink() or (report.parent/'handoff.schema.json').exists():
  from handoff import read
  schema=json.loads((report.parent/'handoff.schema.json').read_text())
  identity={'version':1,'run_id':report.parent.name,'nonce':schema['properties']['nonce']['enum'][0]}
  result=read(report.parent,delivery_schema(stage),identity)
  return check_result(json.dumps(result,ensure_ascii=False))
 return check_result(report.read_text())

def check_context(target,checks,receipt):
 # Successful output is evidence on disk, not repeated prompt context.
 return ('\nVerification Agent receipt: '+json.dumps({'target_sha':target,'receipt_path':str(receipt),'checks':[{'argv':c['argv'],'exit_code':c['exit_code']} for c in checks]},ensure_ascii=False)+
  '\nThese checks already ran on this exact target. Read the receipt for full output when needed. Run additional targeted checks for a specific suspected defect or project requirement; do not repeat the full suite solely for confirmation.\n')

def review_navigation(candidate,baseline,target,previous,folder):
 changed=git(candidate,'diff','--name-status',baseline,target).decode().strip()
 text='\nReview navigation (controller facts, not an approval):\nFull change: git diff '+baseline+' '+target+'\nChanged files:\n'+changed+'\n'
 if previous and previous.get('target_sha') and previous.get('run_id'):
  prior=previous['target_sha']
  git(candidate,'merge-base','--is-ancestor',prior,target)
  report=folder/previous['run_id']/'validated-result.json'
  text+='Previous independent review at '+prior+'; verdict '+previous['verdict']+'. Full findings: '+str(report)+'\n'
  text+='Prior findings (navigation only): '+json.dumps(previous.get('findings',[]),ensure_ascii=False)[:6000]+'\n'
  if prior!=target:text+='Repair delta: git diff '+prior+' '+target+'\n'
 text+=('Start with the diff and trace changed behavior into relevant callers and tests. For re-review, verify prior findings and repair regressions first, then independently assess the complete baseline-to-target change. Prior approval never approves a new SHA. '
  'Read focused ranges; expand only to resolve a concrete correctness question. Conclude when requirements, changed paths and relevant failure cases are covered; do not keep searching solely to produce more findings. No Builder conversation is supplied.\n')
 return text

def artifacts_digest(folder):
 root=folder/'artifacts';items={}
 if root.is_symlink():raise GateError('Symlink evidence refused')
 if root.exists():
  for p in sorted(root.rglob('*')):
   if p.is_symlink():raise GateError('Symlink evidence refused')
   if p.is_file():
    h=hashlib.sha256()
    with p.open('rb') as stream:
     for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
    items[str(p.relative_to(root))]=h.hexdigest()
 return hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest() if items else None

def evidence_repair(folder,old,tree):
 """Recover only a completed, source-identical Builder after the legacy no-change gate."""
 if old.get('error')!='No change inside Packet scope' or old.get('failed_stage')!='building' or old.get('round',0)<2:
  raise GateError('Not a stopped evidence-only repair')
 candidate=folder/'candidate';source=folder/('build-'+str(old['round']))
 if tree(source)!=tree(candidate) or not artifacts_digest(folder):raise GateError('Evidence repair source changed or evidence absent')
 prior=pathlib.Path(old.get('stage_receipt',''))
 if not prior.is_relative_to(folder) or not prior.is_file():raise GateError('Missing prior independent review receipt')
 receipt=json.loads(prior.read_text())
 if receipt.get('stage')!='review' or receipt.get('target_sha')!=old['target_sha'] or receipt.get('verdict')!='changes_requested':raise GateError('Evidence repair requires matching independent rejection')
 matches=[]
 for p in folder.glob('*/validated-result.json'):
  if not p.parent.name.startswith('builder-') or p.stat().st_mtime<=prior.stat().st_mtime:continue
  if p.stat().st_mtime>old['updated_at']:continue
  value=saved_result(p.parent/'result.md')
  if value==json.loads(p.read_text()) and value.get('verdict')=='approved':matches.append((p.parent.name,value))
 if len(matches)!=1:raise GateError('Evidence repair requires one verified completed Builder')
 return matches[0]
