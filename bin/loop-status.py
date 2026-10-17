"""One quiet board status issue; update description only when meaningful state changes."""
import json
from board import ROOT,Board
from lifecycle import save
from health import progress

def report(lane):
 s=json.loads((ROOT/'data/control.json').read_text());cfg=s['projects'][lane];b=Board();rows=['# 自动队列状态','范围：既有行为的合成回归；PM定义契约 → Builder → 检查 → Reviewer → 按项目配置的发布/合并 → 主线复验。Acceptance仅在项目workflow显式配置时执行。','不按总时长终止；15分钟无事件只提示。']
 from project_state import configured_store
 store=configured_store(ROOT)
 if store:
  doc=store.read(lane)
  with store.connection(lane) as c:pending=c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',(lane,)).fetchone()[0]
  rows+=['共享项目状态：revision '+str(doc['revision'])+' / '+doc['phase'],'下一步：'+doc['next_action'],'看板同步待处理事件：'+str(pending),'外部Product会话通过 project-state.py 同步已确认需求；完整聊天不进入执行上下文。']
  for i in doc['intents'].values():
   if i['status']=='waiting_decision':rows.append('需求待处理：'+i['title']+'；'+i.get('planning_reason','待人工裁定'))
 policy=ROOT/'data/autonomy-policies'/(lane+'.json')
 if policy.exists():
  m=json.loads(policy.read_text());rows+=['队列启用：'+str(m['enabled']),'允许文件：'+', '.join(m['allowed_paths']),'自主发现每天最多 '+str(m['max_proposals_per_day'])+' 次；已确认需求按 urgent/high/normal/low 优先，不占发现额度。仍串行交付并保留范围、额度与审核门禁。']
 from provider_state import paused
 for provider in ('codex','commandcode'):
  pause=paused(ROOT,provider)
  rows.append(provider+('：自动等待服务端冷却结束；到期重试原路线' if pause is not None and pause.get('resume_at') else '：需要人工处理认证/额度；无可信恢复时间' if pause is not None else '：可用；剩余额度 unknown'))
 head=ROOT/'data/mainline-verification'/(lane+'.json')
 if head.exists():
  v=json.loads(head.read_text());rows.append('最近主线验证：'+v['status']+' / '+v['sha'])
 queue=ROOT/'data/autonomy'/(lane+'-status.json')
 if queue.exists():
  v=json.loads(queue.read_text());reason=v.get('reason','');rows.append('调度：'+v['state']+' / '+reason)
  rows.append('处理方式：'+('需要人工恢复项目开关' if v['state']=='paused' else '需要人工判断；系统不重放未知失败' if v['state'] in ('blocked','waiting_decision') or 'Unresolved' in reason or reason=='Existing delivery blocked' or ('Provider paused:' in reason and not (paused(ROOT,reason.rsplit(' ',1)[-1]) or {}).get('resume_at')) else '系统自动等待下一调度周期；无需手工派发'))
 for f in sorted((ROOT/'data/autonomy'/lane).glob('*/state.json'))[-6:]:
  v=json.loads(f.read_text())
  for recovery in f.parent.glob('*-recovery.json'):
   r=json.loads(recovery.read_text())
   if r.get('automatic_retry'):rows.append('规划自动接续：'+str(r['attempts'])+' 次尝试；短暂故障等待中')
  rows.append('规划：'+v['state']+'；issue '+v.get('issue','')+'；'+v.get('reason',v.get('error','')))
 for f in (ROOT/'data/deliveries').glob('*/state.json'):
  bind=ROOT/'data/delivery-bindings'/(f.parent.name+'.json')
  if not bind.exists() or json.loads(bind.read_text())['lane']!=lane:continue
  v=json.loads(f.read_text());p=progress(f.parent);rows.append('交付：'+v['state']+'；'+v.get('pr_url',f.parent.name)+('；15分钟无新事件，请查看日志' if p['needs_attention'] else '')+'；'+v.get('mainline_wait_reason',v.get('error','')))
 restart=ROOT/'data/restart-recovery-status.json'
 if restart.exists():
  for r in json.loads(restart.read_text()).get('results',[]):
   binding=ROOT/'data/delivery-bindings'/(r['job']+'.json')
   if binding.exists() and json.loads(binding.read_text())['lane']==lane:rows.append('中断恢复：'+r['state']+'；'+r['job']+'；'+r.get('reason','已保留证据并重新排队'))
 for filename in ('planning-recovery-status.json','publication-recovery-status.json','binding-recovery-status.json'):
  path=ROOT/'data'/filename
  if path.exists():
   for r in json.loads(path.read_text()).get('results',[]):
    binding=ROOT/'data/delivery-bindings'/(r['job']+'.json')
    is_lane=(ROOT/'data/autonomy'/lane/r['job']).exists() or binding.exists() and json.loads(binding.read_text())['lane']==lane
    if is_lane:rows.append('规划/发布恢复：'+r['state']+'；'+r['job']+'；'+r.get('reason',r.get('pr_url','等待下次调度')))
 body='\n\n'.join(rows);path=ROOT/'data/loop-dashboard'/(lane+'.json');old=json.loads(path.read_text()) if path.exists() else {}
 if old.get('body')==body:return
 if not old.get('issue'):
  owner=b.api('GET','/auth/get-session')['user']['id'];t=b.api('POST',f'/companies/{cfg.get("company",s.get("company"))}/issues',{'projectId':cfg['id'],'title':'自动队列 / 当前状态与阻塞原因','status':'in_progress','assigneeUserId':owner,'description':body});old['issue']=t['id']
 else:b.api('PATCH','/issues/'+old['issue'],{'description':body})
 old['body']=body;save(path,old)
if __name__=='__main__':
 import sys
 report(sys.argv[1])
