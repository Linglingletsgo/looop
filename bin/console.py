#!/usr/bin/env python3
"""Bounded, read-only project projections for the owner dashboard."""
import json,pathlib,time
from runtime import ROOT
from project_state import Store
from loop_control import view

LABELS={'idle':'等待有价值的工作','ready':'需求已就绪','waiting':'等待','discovering':'PM 选题中','queued':'排队中','defining':'定义任务','building':'开发中','checking':'检查中','reviewing':'审查中','acceptance':'项目验收','pr_ready':'PR 已就绪','waiting_merge':'等待合并','verifying':'主线复验','completed':'已完成','blocked':'执行受阻','waiting_decision':'等待决定','external_work':'独立开发中','cancelled':'已取消'}
def read(path,default):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return default

def status(root=ROOT,companies=()):
 prefixes={c["id"]:c["issuePrefix"] for c in companies}
 root=pathlib.Path(root);config=read(root/'data/control.json',{});store=Store(root);projects=[]
 for lane,cfg in config.get('projects',{}).items():
  policy=read(root/'data/autonomy-policies'/(lane+'.json'),None)
  doc=store.context(lane);phase=doc['phase'];tasks=list(doc['tasks'].values());active=[t for t in tasks if t['phase'] not in ('completed','cancelled')]
  intents=list(doc['intents'].values());attention=[]
  for item in intents:
   if item['status']=='waiting_decision':attention.append({'title':item['title'],'reason':item.get('planning_reason','需求变更需要决定'),'body':item['body'][:4000],'kind':'decision','intent_id':item['id'],'intent_kind':item['kind']})
  for task in active:
   if task['phase']=='blocked' or task.get('holds'):attention.append({'title':task.get('packet',{}).get('title',task['id']),'reason':task.get('evidence',{}).get('error','任务受阻，请查看证据'),'kind':'task','task_id':task['id']})
  loop=view(root,lane,doc)
  if doc.get('selection',{} ) and doc['selection']['phase']=='blocked' and not any(a['kind']=='task' for a in attention):attention.append({'title':'PM 选题受阻','reason':doc['selection']['detail'],'kind':'planning'})
  test=lane.startswith('validate-');mode='validation' if test else 'automatic' if loop['mode']=='continuous' else 'once' if loop['mode']=='once' else 'paused' if policy else 'manual'
  execution=read(root/'data/delivery-policies'/(lane+'.json'),{});workflow=[{'stage':'pm','role':'product-manager'}]+[{'stage':s['stage'],'role':s['role']} for s in execution.get('workflow',[])]
  recent=[]
  for task in tasks[-6:]:
   evidence=task.get('evidence',{});recent.append({'id':task['id'],'title':task.get('packet',{}).get('title',task['id']),'phase':task['phase'],'label':LABELS.get(task['phase'],task['phase']),'sha':evidence.get('target_sha'),'pr_url':evidence.get('pr_url'),'holds':len(task.get('holds',[]))})
  works=[{'id':w['id'],'status':w['status'],'summary':w['summary'],'updated_at':w.get('updated_at'),'verification':'self_reported'} for w in list(doc.get('external_work',{}).values())[-3:]]
  # Return a narrow projection, never configs, role prompts, raw logs or credentials.
  projects.append({'id':lane,'name':{'gtp':'Goal to People','mainline':'WOS 主线'}.get(lane,cfg.get('name',lane)),'company':cfg.get('company',config.get('company')),'paperclip_id':cfg.get('id'),'company_prefix':prefixes.get(cfg.get('company',config.get('company'))),'mode':mode,'loop':loop,'test':test,'phase':phase,'label':LABELS.get(phase,phase),'next_action':doc['next_action'],'revision':doc['revision'],'updated_at':doc.get('updated_at'),'workflow':workflow,'tasks':recent,'active_count':len(active),'attention':attention[:10],'independent_work':works,'intents':[{'id':i['id'],'kind':i['kind'],'title':i['title'],'body':i['body'][:4000],'status':i['status'],'priority':i['priority']} for i in intents[-5:]]})
 from execution_settings import read as read_settings
 selected=set(read_settings(root).get('routes',{}).values())
 providers=[]
 for name in ('codex','commandcode','claude_subscription'):
  if name=='claude_subscription' and name not in selected and not (root/'data'/('quota-'+name+'.json')).exists():continue
  p=read(root/'data'/('quota-'+name+'.json'),None)
  providers.append({'name':name,'state':'cooldown' if p and p.get('resume_at') else 'needs_action' if p else 'available','resume_at':p.get('resume_at') if p else None,'remaining':'unknown'})
 from execution_settings import public
 return {'execution_settings':public(root),'generated_at':time.time(),'projects':projects,'providers':providers}

if __name__=='__main__':
 from board import Board
 print(json.dumps(status(companies=Board().api("GET","/companies")),ensure_ascii=False))
