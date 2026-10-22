"""Research plan validation and compatibility recovery; no product conclusions inferred."""
import json,pathlib
from handoff import read
from lifecycle import save
from research_evidence import KINDS

def normalize(plan,repo,available,public_required=False):
 from product_research import load_skills
 if not isinstance(plan,dict):raise ValueError('Research plan must be a JSON object')
 plan={k:v for k,v in plan.items() if k in ('kind','question','stop_condition','skills','skill_reason','fallback_reason')}
 for key in ('skill_reason','fallback_reason'):
  if plan.get(key) is None:plan.pop(key,None)
  elif not isinstance(plan[key],str):raise ValueError('Research plan '+key+' must be a string or null; omit it when inapplicable')
  elif len(plan[key])>2000:raise ValueError('Research plan '+key+' exceeds 2000 characters')
 for key in ('question','stop_condition'):
  if not isinstance(plan.get(key),str) or not plan[key].strip() or len(plan[key])>2000:raise ValueError('Research needs a bounded discovery question and stopping condition')
 plan.setdefault('kind','new_requirement' if public_required else 'backlog_validation')
 if plan['kind'] not in KINDS:raise ValueError('Invalid research kind')
 if public_required and plan['kind']=='backlog_validation':raise ValueError('No selected backlog or requirement; choose new_requirement or existing_defect')
 load_skills(repo,plan,available)
 return plan

def restore(checkpoint,folder,repo,available,public_required,fresh):
 if not checkpoint:return None
 source=pathlib.Path(checkpoint)
 statefile=source/'state.json'
 if statefile.is_symlink() or not statefile.is_file():return None
 state=json.loads(statefile.read_text())
 if state.get('error') not in ('Research plan explanation must be concise','Experiment runtime must be python, node or node_ts'):return None
 # Only these compatibility failures are replayed; callers already bind checkpoints to
 # the same baseline, planning revision and selected requirement.
 for name in ('research-plan-retry-2','research-plan-retry-1','research-plan'):
  run=source/name
  if not (run/'handoff.json').is_file():continue
  fresh()
  try:
   schema=json.loads((run/'handoff.schema.json').read_text())
   identity={k:schema['properties'][k]['enum'][0] for k in ('version','run_id','nonce')}
   if identity['run_id']!=name:raise ValueError('Saved research plan identity mismatch')
   original=read(run,schema['properties']['result'],identity)
   result=normalize(original,repo,available,public_required)
  except (ValueError,OSError,KeyError):return None
  fresh()
  save(folder/'research-plan-reused.json',{'source_run':str(run),'plan':result,'model_calls':0})
  return result
 return None

def prior_report(checkpoint,fresh):
 """Preserve the failed report as unverified context, never as a product verdict."""
 if not checkpoint:return None
 source=pathlib.Path(checkpoint)
 state=json.loads((source/'state.json').read_text())
 if state.get('error')!='Experiment runtime must be python, node or node_ts':return None
 for name in ('research-retry-2','research-retry-1','research'):
  run=source/name
  if not (run/'handoff.json').is_file():continue
  fresh()
  try:
   schema=json.loads((run/'handoff.schema.json').read_text())
   identity={k:schema['properties'][k]['enum'][0] for k in ('version','run_id','nonce')}
   if identity['run_id']!=name:raise ValueError('Saved research identity mismatch')
   return read(run,schema['properties']['result'],identity)
  except (ValueError,OSError,KeyError):return None
 return None
