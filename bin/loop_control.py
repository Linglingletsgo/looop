"""Project-owned loop switches. Pause drains work; one-shot claims exactly one PM attempt."""
import json,pathlib
from project_state import Store,Conflict

def read(path,default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def view(root,lane,doc=None):
 root=pathlib.Path(root)
 if doc is None:
  try:doc=Store(root).read(lane)
  except ValueError:doc={}
 policy=read(root/'data/autonomy-policies'/(lane+'.json'),{})
 value=doc.get('loop_control',{'mode':'continuous' if policy.get('enabled') else 'paused','status':'legacy','reason':''})
 return {**value,'configured':bool(policy),'allowed':bool(policy) and lane!='ds1','limits':doc.get('loop_limits',{'max_proposals_per_day':None}),'selection_mode':doc.get('task_selection',{}).get('mode','backlog_only')}

def switch(root,lane,mode,expected,request_id):
 if mode not in ('paused','once','continuous'):raise ValueError('Unknown loop mode')
 root=pathlib.Path(root);store=Store(root)
 if mode!='paused':
  cfg=read(root/'data/control.json',{});policy=read(root/'data/delivery-policies'/(lane+'.json'),{})
  if not view(root,lane)['allowed'] or not policy.get('enabled'):raise ValueError('项目尚未配置可执行授权；接入或发现角色不会自动获得开发权限。')
  from project_adapter import validate_profile
  validate_profile(cfg['projects'][lane]['profile'])
  store.project_guard(lane)
 command={'type':'loop_control','mode':mode}
 def apply(doc):
  old=view(root,lane,doc)
  active=any(t['phase'] not in ('completed','cancelled') for t in doc['tasks'].values())
  if mode=='once' and (active or old['mode']!='paused' or doc.get('phase')=='discovering' or any(read(f,{}).get('state') not in ('queued','no_work','rejected','cancelled') for f in (root/'data/autonomy'/lane).glob('*/state.json'))):raise Conflict('请先暂停并等待当前任务结束，再启动单次执行。')
  if old['mode']=='once' and old.get('attempt') and old.get('status')=='running' and mode!='paused':raise Conflict('单次执行正在进行，请等待结束。')
  doc['loop_control']={'mode':mode,'run_id':request_id,'status':'paused' if mode=='paused' else 'requested','reason':'已暂停新选题；已启动的任务继续完成。' if mode=='paused' else '等待调度器检查门禁并选择任务。'}
  return doc['loop_control']
 return store.mutate(lane,request_id,command,apply,expected,'looop-console')

def claim(root,lane,job):
 store=Store(root);store.ensure(lane)
 def apply(doc):
  value=view(root,lane,doc)
  if value['mode']=='paused':raise Conflict('新选题已暂停。')
  if value['mode']!='once':return None
  if value.get('attempt'):raise Conflict('本次单次执行已领取规划任务。')
  value={k:v for k,v in value.items() if k not in ('configured','allowed','limits','selection_mode')};value.update(attempt=job,status='running',reason='本次推进一个产品目标；可连续交付多个切片，目标完成或受阻后停止。');doc['loop_control']=value;return value
 return store.mutate(lane,'loop-claim-'+job,{'type':'loop_claim','job':job},apply)

def settle(root,lane):
 root=pathlib.Path(root);store=Store(root);value=view(root,lane)
 if value['mode']!='once' or not value.get('attempt'):return value
 receipt=read(root/'data/autonomy'/lane/value['attempt']/'state.json',{})
 reason=None;state={}
 if receipt.get('state') in ('no_work','rejected','blocked','cancelled'):reason='单次选题已结束：'+receipt.get('reason',receipt.get('error',receipt['state']))
 elif receipt.get('delivery_issue'):
  state=read(root/'data/deliveries'/receipt['delivery_issue']/'state.json',{})
  if state.get('state') in ('validated','closed','blocked') or state.get('mainline_verified'):reason='单次交付已结束：'+state.get('state','completed')
 if reason and receipt.get('delivery_issue') and (state.get('state')=='validated' or state.get('mainline_verified')):
  from product_goals import active
  goal=active(store.read(lane))
  if goal and goal.get('status')=='active':
   def continue_goal(doc):
    current=doc.get('loop_control',{})
    if current.get('mode')!='once' or current.get('attempt')!=value.get('attempt'):return None
    current.pop('attempt',None);current.update(status='requested',reason='当前切片已交付，继续同一产品目标；不选择无关新需求。');return current
   store.mutate(lane,'loop-continue-'+value['attempt'],{'type':'loop_continue_goal','goal_id':goal['id']},continue_goal)
   return view(root,lane)
 if reason:
  def apply(doc):
   current=doc.get('loop_control',{})
   if current.get('run_id')!=value.get('run_id') or current.get('mode')!='once':return None
   current.update(mode='paused',status='finished',reason=reason[:2000]);return current
  store.mutate(lane,'loop-finish-'+value['run_id'],{'type':'loop_finished','run_id':value['run_id']},apply)
 return view(root,lane)


def finish_without_attempt(root,lane,reason):
 store=Store(root);value=view(root,lane)
 if value['mode']!='once' or value.get('attempt'):return
 def apply(doc):
  current=doc.get('loop_control',{})
  if current.get('run_id')!=value.get('run_id') or current.get('mode')!='once' or current.get('attempt'):return None
  current.update(mode='paused',status='finished',reason=reason)
  doc['selection']={'phase':'no_work','detail':reason}
  return current
 return store.mutate(lane,'loop-finish-'+value['run_id'],{'type':'loop_finished','reason':reason},apply)


def set_limits(root,lane,daily_limit,expected,request_id):
 if daily_limit is not None and (isinstance(daily_limit,bool) or not isinstance(daily_limit,int) or not 1<=daily_limit<=9007199254740991):raise ValueError('每日次数须为正整数，或留空表示不限。')
 store=Store(root)
 def apply(doc):
  doc['loop_limits']={'max_proposals_per_day':daily_limit}
  if doc.get('selection',{} ) and doc['selection'].get('detail')=='Daily autonomous discovery budget reached':doc['selection']=None
  return doc['loop_limits']
 return store.mutate(lane,request_id,{'type':'loop_limits','max_proposals_per_day':daily_limit},apply,expected,'looop-console')


def set_settings(root,lane,daily_limit,selection_mode,expected,request_id):
 if selection_mode not in ('backlog_only','backlog_and_research'):raise ValueError('未知选题模式。')
 if daily_limit is not None and (isinstance(daily_limit,bool) or not isinstance(daily_limit,int) or not 1<=daily_limit<=9007199254740991):raise ValueError('每日次数须为正整数，或留空表示不限。')
 store=Store(root)
 def apply(doc):
  changed=view(root,lane,doc)['selection_mode']!=selection_mode
  doc['task_selection']={'mode':selection_mode}
  doc['loop_limits']={'max_proposals_per_day':daily_limit}
  if changed:
   doc['planning_revision']+=1
   doc['selection']=None
  elif doc.get('selection',{} ) and doc['selection'].get('detail')=='Daily autonomous discovery budget reached':doc['selection']=None
  return {'task_selection':doc['task_selection'],'loop_limits':doc['loop_limits']}
 return store.mutate(lane,request_id,{'type':'execution_settings','selection_mode':selection_mode,'max_proposals_per_day':daily_limit},apply,expected,'looop-console')
