"""Read-only progress observation and terminal-state reconciliation; never kills workers."""
import json,pathlib,sqlite3,time
from lifecycle import save,terminal
from tracker import CLEAR_AGENT,as_tracker

def progress(folder,now=None):
 folder=pathlib.Path(folder);now=time.time() if now is None else now
 files=list(folder.glob('*/events.jsonl'));latest=max((p.stat().st_mtime for p in files),default=(folder/'state.json').stat().st_mtime)
 state=json.loads((folder/'state.json').read_text());age=max(0,now-latest)
 repeated=False
 if files:
  events=max(files,key=lambda p:p.stat().st_mtime).read_text().splitlines()[-80:];commands=[]
  for line in events:
   try:event=json.loads(line)
   except ValueError:continue
   if event.get('type')=='item.completed' and event.get('item',{}).get('type')=='command_execution':commands.append(event['item'].get('command',''))
  repeated=len(commands)>=6 and len(set(commands[-6:]))==1
 active=state['state'] in ('planning','building','checking','acceptance','proposing','product_scope_review','binding') or state['state'].startswith('review_')
 return {'stage':state['state'],'last_event_at':latest,'silent_seconds':round(age),'needs_attention':active and (age>900 or repeated),'repeated_command':repeated,'note':'超过15分钟无新事件，仅提示，不按时长终止任务' if active and age>900 else '观察日志进展，不按总时长终止'}

def observe(folder,tracker,issue):
 p=progress(folder);path=folder/'progress.json';old=json.loads(path.read_text()) if path.exists() else {}
 if p['needs_attention'] and not old.get('needs_attention'):
  tracker.update(issue,comment='执行观察：'+p['stage']+'，'+('连续六次执行相同命令' if p['repeated_command'] else '已有15分钟无新事件')+'。未终止任务；请查看日志是否等待工具、连接或重复操作。')
 save(path,p)

def reconcile(root,tracker):
 root=pathlib.Path(root);tracker=as_tracker(tracker,root);count=0
 database=root/'data/bridge.sqlite'
 if database.exists():
  with sqlite3.connect(database) as db:
   for issue,run_id,result in db.execute("SELECT issue,run_id,result FROM jobs WHERE state='completed'"):
    if not (root/'data/runs'/run_id/'handoff.md').is_file():continue
    try:t=tracker.get(issue)
    except KeyError:
     # Local jobs are the only truth; a legacy bridge row without one has no board state.
     if tracker.name=='local':continue
     raise
    # Preserve an explicit human cancellation. Repair drift only with durable completion proof.
    if t['status']=='cancelled':continue
    if t['status']!='done' or tracker.agent_assigned(t):
     tracker.update(issue,status='done',assignee=CLEAR_AGENT,comment='完成证据对账：规划已完成，解除旧Agent分配，保留原报告；没有重新执行模型。');count+=1
 for folder in (root/'data/deliveries').glob('*'):
  f=folder/'state.json'
  if not f.exists():continue
  state=json.loads(f.read_text());binding=root/'data/delivery-bindings'/(folder.name+'.json')
  if not binding.exists():continue
  status=terminal(state['state'])
  try:t=tracker.get(folder.name)
  except KeyError:
   # Local jobs are the only truth: a receipt without a job row has no projection to repair.
   if tracker.name=='local':continue
   raise
  if status and t['status']!='cancelled' and (t['status']!=status or tracker.agent_assigned(t)):
   tracker.update(folder.name,status=status,assignee=CLEAR_AGENT,comment='交付终态对账：'+state['state']+'；未重复执行。');count+=1
  observe(folder,tracker,folder.name)
 for folder in (root/'data/autonomy').glob('*/*'):
  if not (folder/'state.json').exists():continue
  state=json.loads((folder/'state.json').read_text())
  if state.get('issue'):
   try:observe(folder,tracker,state['issue'])
   except KeyError:
    # e.g. a Paperclip-era planning attempt after switching to local jobs.
    if tracker.name!='local':raise
    continue
   if tracker.name=='paperclip':
    try:
     from metrics import record
     config=json.loads((root/'data/control.json').read_text());lane=folder.parent.name;cfg=config['projects'][lane]
     record(tracker.board,folder,cfg.get('company',config.get('company')),config['agents'][lane+':product'],state['issue'],cfg['id'])
    except Exception:print('Planning usage import pending:',folder.name)
 return count

if __name__=='__main__':
 from board import ROOT,Board
 from tracker import open_tracker
 print('Reconciled:',reconcile(ROOT,open_tracker(ROOT,Board)))
