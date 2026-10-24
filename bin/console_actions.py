"""Owner console commands. Revision checked; fixed operations only, never shell input."""
import fcntl,importlib.util,json,pathlib,sys,re
from runtime import ROOT
from project_state import Store,Conflict,valid_lane
from loop_control import switch,set_limits,set_settings,view

def retry(root,lane,task,reason,expected):
 if not isinstance(task,str) or not re.fullmatch('[a-zA-Z0-9-]{1,80}',task):raise ValueError('Invalid task id')
 store=Store(root);doc=store.read(lane)
 if doc['revision']!=expected:raise Conflict('项目状态已更新，请刷新后重新判断。')
 item=doc['tasks'].get(task)
 if not item or item['phase']!='blocked':raise ValueError('只能重试当前项目的受阻任务。')
 details=evidence(root,lane,task)
 if not details['intervention']['retry_allowed']:raise ValueError(details['intervention']['unavailable_reason'])
 binding=json.loads((root/'data/delivery-bindings'/(task+'.json')).read_text())
 if binding['lane']!=lane:raise ValueError('Task/project mismatch')
 if len(reason.strip())<4:raise ValueError('请简要说明已处理什么，以及为什么可以重试。')
 spec=importlib.util.spec_from_file_location('delivery_control',root/'bin/delivery-control.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 # Existing recovery checks worker/repository ownership, baseline, holds and publication.
 mod.retry(task,reason[:2000])
 return {'queued':True,'message':'已重新排队；历史证据保留，检查与独立审核将重新执行。'}

def evidence(root,lane,task):
 if not isinstance(task,str) or not re.fullmatch('[a-zA-Z0-9-]{1,80}',task):raise ValueError('Invalid task id')
 doc=Store(root).read(lane);item=doc['tasks'].get(task)
 if not item:raise ValueError('Unknown project task')
 state_path=root/'data/deliveries'/task/'state.json';state=json.loads(state_path.read_text()) if state_path.exists() else {}
 research=item.get('evidence',{}).get('research') or {}
 brief={k:research[k] for k in ('status','question','finding','counterevidence','recommendation','skill_usage','loaded_skills','sources','source_gap') if k in research}
 from intervention import describe
 help=describe(root,lane,item,state,doc)
 # No raw logs/check output/environment dumps are exposed.
 return {'revision':doc['revision'],'intervention':help,'research':brief,'goal_id':item.get('goal_id'),'title':item.get('packet',{}).get('title',task),'phase':item['phase'],'requirements':item.get('packet',{}).get('requirements',[]),'acceptance':item.get('packet',{}).get('acceptance',[]),'allowed_paths':item.get('packet',{}).get('allowed_paths',[]),'holds':item.get('holds',[]),'evidence':{k:v for k,v in item.get('evidence',{}).items() if k in ('target_sha','pr_url','mainline_verified','error','merge_wait_reason','mainline_wait_reason')},'failed_stage':state.get('failed_stage'),'failure':{k:v for k,v in state.get('failure',{}).items() if k in ('category','retryable','next_action')},'retry_possible':help['retry_allowed']}

def execute(value,root=ROOT):
 root=pathlib.Path(root);action=value.get('action')
 if action=='execution_settings':
  from execution_settings import save
  return save(root,value,value.get('revision'),value.get('request_id'))
 if action in ('preview','connect'):
  from onboarding import preview,connect
  if action=='connect':return connect(root,value['repo'],value['fingerprint'])
  return preview(value['repo'],root=root)
 lane=valid_lane(value.get('lane'));store=Store(root)
 if lane not in json.loads((root/'data/control.json').read_text())['projects']:raise ValueError('Unknown project')
 if action=='activation_preview':
  from activation import preview
  return preview(root,lane)
 if action=='evidence':return evidence(root,lane,value['task'])
 revision=value.get('revision');request=value.get('request_id')
 if not isinstance(revision,int) or isinstance(revision,bool) or not isinstance(request,str):raise ValueError('Revision and stable request id required')
 if action=='enable_execution':
  from activation import enable
  return enable(root,lane,revision,request,value.get('fingerprint'))
 if action=='loop':
  result=switch(root,lane,value['mode'],revision,request)
  from launch_loops import launch
  if value['mode']!='paused':launch(root,lane)
  return result
 if action in ('limits','settings'):
  result=set_settings(root,lane,value.get('daily_limit'),value.get('selection_mode'),revision,request) if action=='settings' else set_limits(root,lane,value.get('daily_limit'),revision,request)
  from launch_loops import launch
  if view(root,lane)['mode']!='paused':launch(root,lane)
  return result
 if action=='intent':
  kind=value.get('kind','requirement')
  if kind not in ('requirement','decision'):raise ValueError('Invalid product input kind')
  return store.submit(lane,{'type':kind,'title':value.get('title'),'body':value.get('body'),'priority':value.get('priority','normal'),'human_confirmed':True},revision,request,'looop-console')
 if action=='decision':
  intent=store.read(lane)['intents'].get(value.get('intent_id'))
  if not intent:raise ValueError('决定不存在，请刷新。')
  if value.get('resolution') in ('keep_original','follow_up'):command={'type':'resolve_change','intent_id':intent['id'],'resolution':value['resolution'],'human_confirmed':True}
  else:
   if value.get('resolution')!='retry_planning':raise ValueError('Unknown decision resolution')
   command={'type':'priority','intent_id':intent['id'],'priority':intent['priority'],'human_confirmed':True}
  return store.submit(lane,command,revision,request,'looop-console')
 if action=='retry_planning_attempt':
  from planning_intervention import retry as retry_pm
  from board import Board
  from tracker import open_tracker
  result=retry_pm(root,lane,value.get('job'),value.get('reason',''),revision,open_tracker(root,Board))
  from launch_loops import launch
  launch(root,lane)
  return result
 if action=='retry':
  folder=root/'data/locks';folder.mkdir(exist_ok=True,parents=True)
  with (folder/('console-retry-'+lane)).open('w') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   return retry(root,lane,value['task'],value.get('reason',''),revision)
 raise ValueError('Unsupported console operation')

if __name__=='__main__':
 try:
  value=json.load(sys.stdin)
  if len(json.dumps(value))>32000:raise ValueError('Request too large')
  # Legacy retry prints status; keep the wire response JSON-only.
  import contextlib,io
  with contextlib.redirect_stdout(io.StringIO()):result=execute(value)
  print(json.dumps({'ok':True,'result':result},ensure_ascii=False))
 except (ValueError,KeyError,OSError,RuntimeError) as exc:
  print(json.dumps({'ok':False,'error':str(exc)[:2000],'conflict':isinstance(exc,Conflict)},ensure_ascii=False))
