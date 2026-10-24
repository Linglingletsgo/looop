#!/usr/bin/env python3
"""Replayable state -> Paperclip mirror. Controller state is authoritative."""
import fcntl,json
from board import ROOT,Board
from project_state import Store,phase_of
from tracker import local_mode

def reconcile(root,store):
 for path in (root/'data/delivery-bindings').glob('*.json'):
  binding=json.loads(path.read_text());lane=binding['lane']
  receipt_path=root/'data/deliveries'/path.stem/'state.json'
  if receipt_path.exists() and json.loads(receipt_path.read_text()).get('state_compacted'):continue
  try:store.read(lane)
  except ValueError:continue
  store.bind(lane,path.stem,binding['packet'],binding.get('intent_ids',[]),binding.get('authorization',{}))
  receipt=root/'data/deliveries'/path.stem/'state.json'
  if receipt.exists():
   r=json.loads(receipt.read_text());doc=store.read(lane);task=doc['tasks'][path.stem];phase=phase_of(r)
   # Runtime receipts are execution evidence, never permission to clear intent holds.
   if task['phase'] in ('completed','cancelled') and phase!=task['phase']:continue
   if task['phase']=='verifying' and phase not in ('verifying','completed'):continue
   store.transition(lane,path.stem,phase,{k:r[k] for k in ('pr_url','error','mainline_verified','target_sha','merge_wait_reason','mainline_wait_reason') if k in r},import_existing=True)

_UNSET=object()
def _payload(b,payload,session):
 # Paperclip rejects an in_progress issue without an assignee. Resolve the session user once.
 if payload.get('status')!='in_progress':return payload
 if session[0] is _UNSET:session[0]=b.api('GET','/auth/get-session')['user']['id']
 return {**payload,'assigneeUserId':session[0]}

def sync(root=ROOT,board=None):
 store=Store(root);reconcile(root,store);local=local_mode(root)
 config=None if local else json.loads((root/'data/control.json').read_text());b=None if local else board or Board()
 lock=root/'data/project-state/sync.lock'
 with lock.open('w') as h:
  fcntl.flock(h,fcntl.LOCK_EX)
  lanes=store.lanes()
  if local:
   # No mirror in local mode: acknowledge the snapshot so the 5000-row Held limit cannot stall writes.
   for lane in lanes:
    try:doc=store.read(lane)
    except ValueError:continue
    with store.connection(lane) as c:c.execute('UPDATE outbox SET delivered=1 WHERE lane=? AND revision<=?',(lane,doc['revision']))
   return True
  session=[_UNSET]
  for lane in lanes:
   with store.connection(lane) as c:pending=c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',(lane,)).fetchone()[0]
   if not pending:continue
   cfg=config['projects'].get(lane)
   if not cfg or not cfg.get('id'):continue
   doc=store.read(lane);company=cfg.get('company',config.get('company'))
   # Scan for the durable marker too: handles crash after POST, before local link save.
   issues=b.api('GET',f'/companies/{company}/issues?projectId={cfg["id"]}')
   for item in doc['intents'].values():
    marker='<!-- project-state:'+lane+':'+item['id']+' -->'
    with store.connection(lane) as c:row=c.execute('SELECT issue FROM links WHERE lane=? AND item=?',(lane,item['id'])).fetchone()
    issue=row[0] if row else next((i['id'] for i in issues if marker in (i.get('description') or '')),None)
    status={'completed':'done','withdrawn':'cancelled','superseded':'cancelled','blocked':'blocked','waiting_decision':'blocked'}.get(item['status'],'backlog')
    body=marker+'\n\n结构化产品输入；状态：'+item['status']+'；类型：'+item['kind']+'；优先级：'+item['priority']+'\n\n'+item['body']+('\n\nPM待处理原因：'+item['planning_reason'] if item.get('planning_reason') else '')+'\n\n来源：'+item['source']+'\n\n此条是需求记录，不是可执行 Packet。项目授权边界仍有效。'
    payload=_payload(b,{'title':'Product / '+item['title'],'description':body,'status':status},session)
    if issue:b.api('PATCH','/issues/'+issue,payload)
    else:
     issue=b.api('POST',f'/companies/{company}/issues',{**payload,'projectId':cfg['id']})['id']
    with store.connection(lane) as c:c.execute('INSERT OR REPLACE INTO links VALUES (?,?,?)',(lane,item['id'],issue))
   for item in doc.get('external_work',{}).values():
    marker='<!-- project-external-work:'+lane+':'+item['id']+' -->'
    key='external:'+item['id']
    with store.connection(lane) as c:row=c.execute('SELECT issue FROM links WHERE lane=? AND item=?',(lane,key)).fetchone()
    issue=row[0] if row else next((i['id'] for i in issues if marker in (i.get('description') or '')),None)
    payload=_payload(b,{'title':'Independent work / '+item['summary'][:100],'description':marker+'\n\n独立项目对话进度（自述，未替代调度器审核）：'+item['status']+'\n\n'+item['summary']+'\n\n来源：'+item['source'],'status':{'active':'in_progress','completed':'done','cancelled':'cancelled'}[item['status']]},session)
    if issue:b.api('PATCH','/issues/'+issue,payload)
    else:issue=b.api('POST',f'/companies/{company}/issues',{**payload,'projectId':cfg['id']})['id']
    with store.connection(lane) as c:c.execute('INSERT OR REPLACE INTO links VALUES (?,?,?)',(lane,key,issue))
   # Only acknowledge the snapshot we actually mirrored; concurrent events remain pending.
   with store.connection(lane) as c:c.execute('UPDATE outbox SET delivered=1 WHERE lane=? AND revision<=?',(lane,doc['revision']))
 return True
if __name__=='__main__':sync()
