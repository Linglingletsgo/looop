import json,os
from board import Board,ROOT
from pipeline import execute_fixture
b=Board();control=json.loads((ROOT/'data/fixture-control.json').read_text())
if os.environ.get('PAPERCLIP_AGENT_ID')!=control['agent']:raise ValueError('Identity mismatch')
issue=os.environ.get('PAPERCLIP_TASK_ID')
if not issue:
 tasks=b.api('GET',f'/companies/{control["company"]}/issues?assigneeAgentId={control["agent"]}&status=todo,in_progress')
 tasks=[t for t in tasks if t.get('projectId')==control['project'] and t['status'] in ['todo','in_progress']]
 if not tasks:print('No issue; no call.');raise SystemExit()
 issue=tasks[0]['id']
task=b.api('GET','/issues/'+issue)
if task.get('projectId')!=control['project'] or task.get('assigneeAgentId')!=control['agent']:raise ValueError('Task mismatch')
if task['status'] not in ['todo','in_progress']:print('Not runnable');raise SystemExit()
b.api('PATCH','/issues/'+issue,{'status':'in_progress'})
def emit(stage):
 print(stage,flush=True)
 b.api('POST','/issues/'+issue+'/comments',{'body':'Pipeline: '+stage})
try:
 result=execute_fixture(json.loads((ROOT/'data/fixture-packet.json').read_text()),issue,emit,publish=True)
 b.api('PATCH','/issues/'+issue,{'status':'in_review','comment':'合成仓库端到端完成，等待人工合并：'+result.get('pr_url','')+'\nEvidence: '+str(ROOT/'data/pipelines'/issue)})
except Exception as e:
 b.api('PATCH','/issues/'+issue,{'status':'blocked','comment':'Pipeline stopped: '+str(e)})
 raise
