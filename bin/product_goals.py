"""One current product outcome; execution slices never complete it implicitly."""
import copy,hashlib,json

def active(doc):
 goal=(doc or {}).get('product_goal')
 return goal if goal and goal.get('status')!='completed' else None

def text(value,name,limit):
 if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('Product goal requires concise '+name)
 return value.strip()

def strings(value,name,limit=12):
 if not isinstance(value,list) or not 1<=len(value)<=limit:raise ValueError('Product goal requires '+name)
 return [text(v,name,1000) for v in value]

def proposal(value,current=None):
 if not isinstance(value,dict):raise ValueError('Product goal required; a technical task alone is not a product requirement')
 result={'title':text(value.get('title'),'user-facing title',160),'user_value':text(value.get('user_value'),'user value',1600),'success_criteria':strings(value.get('success_criteria'),'observable success criteria'),'remaining':strings(value.get('remaining'),'remaining outcomes'),'progress':text(value.get('progress'),'current progress',1600),'slice_value':text(value.get('slice_value'),'slice contribution',1200)}
 if current:
  for field in ('title','user_value','success_criteria'):
   if result[field]!=current[field]:raise ValueError('Active product goal contract cannot change during slicing')
  result['id']=current['id']
 else:result['id']='goal-'+hashlib.sha256(json.dumps({k:result[k] for k in ('title','user_value','success_criteria')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
 return result

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
 return {k:goal.get(k) for k in ('id','title','user_value','success_criteria','remaining','progress','slice_value','status','current_task','completed_slices','completion_reason','progress_verification')} if goal else None

INSTRUCTIONS='''Work on a product outcome, not an arbitrary quota of tiny tasks. Define a user-facing title, concrete user benefit, observable end-to-end success criteria and the remaining outcomes. A large requirement may span many development/review cycles and PRs. Propose only the next coherent implementation slice; explain how it advances the same outcome. Do not repeatedly invent isolated regression tests. Keep the active goal title, value and success criteria unchanged. Completion of one slice does not mean completion of the requirement. To finish an active goal, return action goal_complete with goal_id, a concise reason, and current source evidence proving EVERY success criterion; merged/test counts alone are not product evidence. If scope or evidence is insufficient return no_work with the real blocker, never substitute unrelated small work. All work stays within the current mandate; research cannot expand it.'''
