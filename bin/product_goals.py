"""One current product outcome; execution slices never complete it implicitly."""
import copy,hashlib,json,re

def active(doc):
 goal=(doc or {}).get('product_goal')
 return goal if goal and goal.get('status')!='completed' else None

def text(value,name,limit):
 if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('Product goal requires concise '+name)
 return value.strip()

def strings(value,name,limit=12):
 if not isinstance(value,list) or not 1<=len(value)<=limit:raise ValueError('Product goal requires '+name)
 return [text(v,name,1000) for v in value]

class ContractChanged(ValueError):
 def __init__(self,current,fields):
  super().__init__('Active product goal contract cannot change during slicing: '+', '.join(fields))
  self.recovery_instruction='ACTIVE GOAL CORRECTION: These supplied contract fields differ from current state: '+', '.join(fields)+'. Preserve the Packet and source evidence; move slice-specific descriptions into progress, slice_value and packet. Omit immutable fields to inherit them, or copy these exact current values: '+json.dumps({k:current.get(k) for k in fields},ensure_ascii=False)+'. Do not change the goal or relax success criteria. Update handoff.json only.'

def planning_context(current):
 return ('\nContinue this active goal; do not select a new requirement or unrelated backlog item: '+json.dumps(summary({'product_goal':current}),ensure_ascii=False)+
 '\nACTIVE GOAL OUTPUT: product_goal needs only remaining, progress and slice_value. title, user_value, success_criteria and experience are controller-owned: omit them to inherit current values, or copy them exactly. The generic new-goal example does not override this rule. Put the next slice journey, before/after and implementation details in packet, not experience.\n')


def proposal(value,current=None):
 if not isinstance(value,dict):raise ValueError('Product goal required; a technical task alone is not a product requirement')
 if current:
  locked=('title','user_value','success_criteria','experience')
  changed=[k for k in locked if k in value and value[k]!=current.get(k)]
  if changed:raise ContractChanged(current,changed)
  value={**{k:copy.deepcopy(current[k]) for k in locked if k in current},**value}
 result={'title':text(value.get('title'),'user-facing title',160),'user_value':text(value.get('user_value'),'user value',1600),'success_criteria':strings(value.get('success_criteria'),'observable success criteria'),'remaining':strings(value.get('remaining'),'remaining outcomes'),'progress':text(value.get('progress'),'current progress',1600),'slice_value':text(value.get('slice_value'),'slice contribution',1200)}
 experience=value.get('experience',(current or {}).get('experience'))
 if current and current.get('experience') and experience is None:raise ValueError('Active experience contract cannot change during slicing')
 if experience is not None:
  if not isinstance(experience,dict) or set(experience)!={'journey','before','after','criterion'}:raise ValueError('Experience requires journey, before, after and criterion')
  result['experience']={k:text(experience.get(k),'experience '+k,1000) for k in ('journey','before','after','criterion')}
  if result['experience']['criterion'] not in result['success_criteria']:raise ValueError('Experience criterion must be an exact success criterion')
  if current and result['experience']!=current.get('experience'):raise ValueError('Active experience contract cannot change during slicing')
 if current:
  for field in ('title','user_value','success_criteria'):
   if result[field]!=current[field]:raise ValueError('Active product goal contract cannot change during slicing')
  result['id']=current['id']
 else:result['id']='goal-'+hashlib.sha256(json.dumps({k:result[k] for k in ('title','user_value','success_criteria')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
 return result

def completion_coverage(evidence,criteria,experience=None):
 # Multiple source proofs per criterion are valid; ordering is presentation only.
 if not isinstance(evidence,list) or not 1<=len(evidence)<=64 or any(not isinstance(e,dict) or not isinstance(e.get('criterion'),str) for e in evidence):raise ValueError('Completion evidence must list exact success criteria')
 if {e['criterion'] for e in evidence}!=set(criteria):raise ValueError('Provide evidence for every exact success criterion; do not add unknown criteria')
 if experience:
  proofs=[e for e in evidence if e['criterion']==experience['criterion'] and e.get('kind') in ('agent_walkthrough','user_test')]
  if not proofs:raise ValueError('Experience completion needs a walkthrough or user test, not source/test counts')
  for e in proofs:
   if not isinstance(e.get('target_sha'),str) or not re.fullmatch('[0-9a-f]{40}',e['target_sha']):raise ValueError('Experience proof needs target SHA')
 return evidence


def bind(doc,job,details,intent_ids):
 current=active(doc);goal=proposal(details,current)
 if not current:goal['id']='goal-'+hashlib.sha256((goal['id']+'\n'+job).encode()).hexdigest()[:16]
 if current and current.get('intent_ids',[])!=intent_ids:raise ValueError('Continue the active goal before selecting another requirement')
 saved={**copy.deepcopy(current or {}),**goal,'intent_ids':intent_ids,'status':'active','progress_verification':'pm_assessed','current_task':job,'completed_slices':(current or {}).get('completed_slices',0),'research':(current or details).get('research'),'backlog_item_key':(current or details).get('backlog_item_key')}
 doc['product_goal']=saved
 return saved

def transition(doc,task,phase,previous_phase=None):
 goal=active(doc)
 if not goal or task.get('goal_id')!=goal['id']:return False
 if phase=='completed' and previous_phase=='completed':return True
 goal['status']='blocked' if phase in ('blocked','cancelled') else 'active'
 if phase=='completed' and previous_phase!='completed':
  goal['completed_slices']=goal.get('completed_slices',0)+1;goal['progress']='当前切片已通过交付检查；PM 将结合最新代码核验目标并决定剩余工作。';goal['current_task']=None;goal['progress_verification']='delivery_verified'
 elif phase in ('blocked','cancelled'):goal['progress']='当前切片受阻，保留目标与剩余工作，等待恢复。'
 return True

def summary(doc):
 goal=doc.get('product_goal')
 return {k:goal.get(k) for k in ('id','title','user_value','success_criteria','remaining','progress','slice_value','status','current_task','completed_slices','completion_reason','progress_verification','experience')} if goal else None

INSTRUCTIONS='''Work on a product outcome, not an arbitrary quota of tiny tasks. Define a user-facing title, concrete user benefit, observable end-to-end success criteria and the remaining outcomes. A large requirement may span many development/review cycles and PRs. Coherent scope matters more than minimizing file count; do not turn each technical edge case into a separate product outcome. Propose only the next coherent implementation slice; explain how it advances the same outcome. Do not repeatedly invent isolated regression tests. Keep the active goal title, user_value, success criteria and experience unchanged. For active goals return only remaining, progress and slice_value; omitted contract fields inherit current state. Completion of one slice does not mean completion of the requirement. To finish an active goal, return action goal_complete with goal_id, a concise reason, and current source evidence proving EVERY success criterion; merged/test counts alone are not product evidence. If scope or evidence is insufficient return no_work with the real blocker, never substitute unrelated small work. All work stays within the current mandate; research cannot expand it.'''

EXPERIENCE_INSTRUCTIONS='For consumer-facing products, prioritize a complete user journey: starting intent, current friction, observable before/after benefit and next action. Consider input, waiting, understanding results and taking action, including relevant empty/loading/error/recovery/success states and accessibility. Technical fixes remain valid when their contribution is explicit; do not pick tasks merely because edge-case tests are easy. For a NEW consumer experience goal include experience {journey,before,after,criterion}; criterion must exactly match a success_criteria entry. Preserve active goal contracts without retrofitting. Seek UX/UI advice only when relevant and supported by the existing workflow; do not add mandatory roles or self-dispatch. Put necessary runtime validation in the Packet criteria. To complete an experience goal, exercise the running product and record journey, observed states, outcome, limitations and target SHA in a bounded artifact in the supplied experience proof artifact root. Provide completion_evidence for the experience criterion with kind agent_walkthrough or user_test, target_sha, path relative to that artifact root and an exact quote. Agent walkthrough is not real user research; user_test requires an actual authorized user session. Never invent users or results. Source, screenshots, PR counts and unit tests alone do not prove usability. Missing runtime access is a concrete verification gap, not completion. Do not impose a UI workflow on non-interactive projects.'
