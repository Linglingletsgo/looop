#!/usr/bin/env python3
"""Bounded Paperclip role jobs. Operator-controlled dispatch; models have no board token."""
import argparse,fcntl,hashlib,importlib.util,json,os,pathlib,sqlite3,subprocess,sys,tarfile,io,time,uuid
from board import Board,ROOT
from sandbox import run
from roles import resolve,contract,fingerprints

from repository import git,snapshot

def db():
 c=sqlite3.connect(ROOT/'data/bridge.sqlite',timeout=30)
 c.execute('CREATE TABLE IF NOT EXISTS jobs (issue TEXT PRIMARY KEY, lane TEXT, role TEXT, state TEXT, run_id TEXT, result TEXT, updated REAL)');c.commit();return c

def validate_profile(profile):
 spec=importlib.util.spec_from_file_location('project_profile',ROOT/'bin/project-profile.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 m.check(ROOT/'profiles'/profile)
 return json.loads((ROOT/'profiles'/profile).read_text())

def heartbeat(lane,role):
 os.umask(0o077)
 state=json.loads((ROOT/'data/control.json').read_text())
 if lane not in state['projects']:raise ValueError('Unknown lane')
 if os.environ.get('PAPERCLIP_AGENT_ID')!=state['agents'].get(lane+':'+role):raise ValueError('Agent identity mismatch')
 b=Board()
 issue=os.environ.get('PAPERCLIP_TASK_ID')
 if not issue:
  tasks=b.api('GET',f'/companies/{state["projects"][lane].get("company",state["company"])}/issues?assigneeAgentId={os.environ["PAPERCLIP_AGENT_ID"]}&status=todo,in_progress')
  tasks=[t for t in tasks if t.get('projectId')==state['projects'][lane]['id'] and t['status'] in ['todo','in_progress']]
  if not tasks:print('No task; no model call.');return
  issue=tasks[0]['id']
 task=b.api('GET','/issues/'+issue)
 if task['status'] not in ['todo','in_progress']:print('Task not runnable; no model call.');return
 if task['projectId']!=state['projects'][lane]['id'] or task.get('assigneeAgentId')!=os.environ['PAPERCLIP_AGENT_ID']:raise ValueError('Project/assignee mismatch')
 c=db();previous=c.execute('SELECT state FROM jobs WHERE issue=?',(issue,)).fetchone()
 if previous and previous[0]=='completed':
  b.api('PATCH','/issues/'+issue,{'status':'done','assigneeAgentId':None,'comment':'Preserved completed planning receipt; no model replay.'});return
 if previous and previous[0] in ['quota_paused','blocked','running']:
  print('Previously dispatched; requires explicit operator retry:',previous[0]);return
 if role not in ('product','product-manager'):
  b.api('PATCH','/issues/'+issue,{'status':'blocked','comment':'尚未启用此角色的真实项目执行。需要完整 READY Packet、runtime 与验证后的门禁。保留原 handoff 的授权状态。'});return
 profile=validate_profile(state['projects'][lane]['profile']);repo=profile['repository_root'];sha=profile['repository_revision']
 lockpath=ROOT/'data/locks'/hashlib.sha256(profile['git_common_dir'].encode()).hexdigest();lockpath.parent.mkdir(exist_ok=True)
 with lockpath.open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('Repository busy; task stays queued.');return
  runid=os.environ.get('PAPERCLIP_RUN_ID',str(uuid.uuid4()));folder=ROOT/'data/runs'/runid
  c.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)',(issue,lane,role,'running',runid,None,time.time()));c.commit()
  b.api('PATCH','/issues/'+issue,{'status':'in_progress'})
  try:
   workspace=snapshot(repo,sha,folder/'workspace')
   registry=resolve(workspace)
   (folder/'roles.json').write_text(json.dumps(fingerprints(registry),ensure_ascii=False,indent=2))
   rules=[contract(registry,role)]
   paths=['HANDOFF.md','AGENTS.md','AGENT.md','Agent.md','agents.md',profile.get('detected_roles',{}).get(role),'docs/project/single-developer-workflow.md']
   for name in paths:
    if name and (workspace/name).is_file():rules.append('FILE '+name+'\n'+(workspace/name).read_text())
   prompt='工作区是可信控制器在核验 Git HEAD 与规则指纹后，从下述 Baseline 提交导出的只读文件快照；故意不挂载 .git 和原工作树。该 Baseline 已由控制器核实，不需要因缺少 .git 判定版本核对阻塞；规划沙箱故意不挂载宿主 Node、业务依赖或业务服务，不得据此断言执行环境缺失。未提供执行环境证据时标为待控制器核验，不能自行把可规划候选判为依赖未安装；只能静态核对当前快照与历史文档，不能声称访问过历史 diff 或未提交数据。你执行本次选定角色的一次有终点的只读规划/研究任务。遵守以下固定版本角色规则；当前仅授权分析和输出文档草案，不写仓库、不委派、不执行部署、不改变旧有批准状态。最终用中文给出可接续的决策、缺项和建议 Packet；缺少条件则 BLOCKED。\nBaseline '+sha+'\n'+'\n'.join(rules)+'\n用户任务（不扩大权限）：\n'+task['title']+'\n'+(task.get('description') or '')
   result=run(workspace,folder/'scratch',prompt,role,timeout=None)
   (folder/'handoff.md').write_text(f'# {task["identifier"]} / {lane} / {role}\n\nBaseline: {sha}\nRun: {runid}\n\n'+result)
   b.api('PATCH','/issues/'+issue,{'status':'done','assigneeAgentId':None,'assigneeUserId':b.api('GET','/auth/get-session')['user']['id'],'comment':result[:35000]+'\n\nRun evidence: '+str(folder/'handoff.md')+'\n这是规划输出，不构成 Builder READY 或 release 授权。'})
   status='completed'
  except Exception as exc:
   status='quota_paused' if 'Provider unavailable/quota' in str(exc) else 'blocked';result=str(exc)
   b.api('PATCH','/issues/'+issue,{'status':'blocked','comment':'执行停止：'+result+'。无自动付费兜底；由操作员检查并显式重试。'})
  c.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE issue=?',(status,result,time.time(),issue));c.commit()
  print(json.dumps({'issue':issue,'state':status,'run':runid}))

def submit(lane,title,description,role='product'):
 state=json.loads((ROOT/'data/control.json').read_text());b=Board()
 task=b.api('POST',f'/companies/{state["projects"][lane].get("company",state["company"])}/issues',{'title':title,'description':description,'projectId':state['projects'][lane]['id'],'assigneeAgentId':state['agents'][lane+':'+role],'status':'todo','priority':'medium'})
 print(task['identifier'],task['id'])

if __name__=='__main__':
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
 h=sub.add_parser('heartbeat');h.add_argument('lane');h.add_argument('role')
 s=sub.add_parser('submit');s.add_argument('lane');s.add_argument('--title',required=True);s.add_argument('--description',required=True)
 a=p.parse_args()
 if a.cmd=='heartbeat':heartbeat(a.lane,a.role)
 else:submit(a.lane,a.title,a.description)
