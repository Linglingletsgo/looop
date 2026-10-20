"""Task-source identity and explicit recovery of unbound PM proposals."""
import json,re
from project_adapter import safe_file

def source_intents(value,shared,selected,current_goal):
 """Bind only executable requirements; decision references remain context."""
 ids=value.get('intent_ids',[])
 if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Invalid source intent_ids')
 intents=(shared or {}).get('intents',{})
 for i in ids:
  if i not in intents:raise ValueError('PM cited unknown intent')
 decisions=[i for i in ids if intents[i]['kind']=='decision' and intents[i]['status']=='ready']
 executable=[i for i in ids if i not in decisions]
 expected=current_goal.get('intent_ids',[]) if current_goal else [selected['id']] if selected else []
 if executable!=expected:raise ValueError('Task must implement exactly the controller-selected requirement; decisions are context, autonomous intent_ids must be []')
 for i in expected:
  item=intents.get(i,{})
  if item.get('kind') not in ('requirement','propose') or item.get('status') not in (('ready','scheduled') if current_goal else ('ready',)):raise ValueError('PM cited unconfirmed requirement')
 return expected,decisions


def saved_proposal(root,lane,pending,sha,revision,current_goal,selected_id,fresh,validate):
 for prior in reversed(pending):
  job=prior.get('reuse_saved_proposal')
  if not job or prior.get('baseline_sha')!=sha or prior.get('planning_revision')!=revision or prior.get('goal_id')!=(current_goal or {}).get('id') or prior.get('selected_intent')!=selected_id:continue
  if not re.fullmatch('[a-zA-Z0-9-]{1,80}',job):raise ValueError('Invalid saved planning identity')
  path=safe_file(root/'data/autonomy'/lane/job,'proposal.json')
  value=json.loads(path.read_text())
  if value.get('action')!='task':raise ValueError('Saved proposal is not an implementation task')
  fresh();validate(value)
  return value,str(path)
 return None,None
