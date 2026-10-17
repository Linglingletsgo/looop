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
 return {**value,'configured':bool(policy),'allowed':bool(policy) and lane not in ('mainline','ds1')}

def switch(root,lane,mode,expected,request_id):
 if mode not in ('paused','once','continuous'):raise ValueError('Unknown loop mode')
 root=pathlib.Path(root);store=Store(root)
 if mode!='paused':
  cfg=read(root/'data/control.json',{});policy=read(root/'data/delivery-policies'/(lane+'.json'),{})
  if not view(root,lane)['allowed'] or not policy.get('enabled') or not cfg.get('agents',{}).get(lane+':delivery'):raise ValueError('项目尚未配置可执行授权；接入或发现角色不会自动获得开发权限。')
  from bridge import validate_profile
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
  value={k:v for k,v in value.items() if k not in ('configured','allowed')};value.update(attempt=job,status='running',reason='本次只选择一个任务；交付或无工作结果后停止。');doc['loop_control']=value;return value
 return store.mutate(lane,'loop-claim-'+job,{'type':'loop_claim','job':job},apply)

def settle(root,lane):
 root=pathlib.Path(root);store=Store(root);value=view(root,lane)
 if value['mode']!='once' or not value.get('attempt'):return value
 receipt=read(root/'data/autonomy'/lane/value['attempt']/'state.json',{})
 reason=None
 if receipt.get('state') in ('no_work','rejected','blocked','cancelled'):reason='单次选题已结束：'+receipt.get('reason',receipt.get('error',receipt['state']))
 elif receipt.get('delivery_issue'):
  state=read(root/'data/deliveries'/receipt['delivery_issue']/'state.json',{})
  if state.get('state') in ('validated','closed','blocked') or state.get('mainline_verified'):reason='单次交付已结束：'+state.get('state','completed')
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
  current.update(mode='paused',status='finished',reason=reason);return current
 return store.mutate(lane,'loop-finish-'+value['run_id'],{'type':'loop_finished','reason':reason},apply)
