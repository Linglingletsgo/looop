"""Issue tracker seam: Paperclip HTTP board or the local job table."""
import json,pathlib
from jobs import Jobs,KINDS
UNSET=object()

def _config(root):
 try:value=json.loads((pathlib.Path(root)/'data/control.json').read_text())
 except (OSError,ValueError):return {}
 return value if isinstance(value,dict) else {}

class PaperclipTracker:
 idempotent_create=False
 def __init__(self,board,root):
  self.board=board;self.root=pathlib.Path(root);cfg=_config(root);self.session=None
  projects=cfg.get('projects') or {}
  self.projects={k:v['id'] for k,v in projects.items() if (v or {}).get('id')}
  self.agents=cfg.get('agents') or {}
  self.companies={k:(v or {}).get('company') or cfg.get('company') for k,v in projects.items()}
  self.lanes={v:k for k,v in self.projects.items()}
 def _role(self,agent):
  return None if not agent else next((key for key,value in self.agents.items() if value==agent),agent)
 def _agent(self,key):
  # 'lane:role' keys must be configured; anything else is a legacy raw agent id.
  if ':' in key and key not in self.agents:raise KeyError('No agent configured for role '+key)
  return self.agents.get(key,key)
 def _issue(self,value,lane=None):
  value=value or {};project=value.get('projectId')
  return {'id':value.get('id'),'identifier':value.get('identifier'),
   'lane':self.lanes.get(project) if project else None,'status':value.get('status'),
   'assignee':'owner' if value.get('assigneeUserId') else self._role(value.get('assigneeAgentId')),
   'description':value.get('description') or ''}
 def owner(self):
  if self.session is None:self.session=self.board.api('GET','/auth/get-session')['user']['id']
  return self.session
 def get(self,id):
  return self._issue(self.board.api('GET','/issues/'+id))
 def create(self,lane,kind,title,status,description='',assignee=None,job_id=None,company=None):
  payload={'projectId':self.projects[lane],'title':title,'status':status,'description':description}
  if assignee=='owner':payload['assigneeUserId']=self.owner()
  elif assignee:payload.update(assigneeAgentId=self._agent(assignee),assigneeUserId=None)
  response=self.board.api('POST',f'/companies/{company or self.companies[lane]}/issues',payload) or {}
  return self._issue({**payload,**response})
 def update(self,id,status=None,assignee=UNSET,comment=None,description=None,unblockDescriptor=None):
  payload={}
  if status is not None:payload['status']=status
  if assignee is not UNSET:
   payload.update(assigneeAgentId=None if assignee in (None,'owner') else self._agent(assignee),
    assigneeUserId=self.owner() if assignee=='owner' else None)
  if comment is not None:payload['comment']=comment
  if description is not None:payload['description']=description
  if unblockDescriptor is not None:payload['unblockDescriptor']=unblockDescriptor
  response=self.board.api('PATCH','/issues/'+id,payload)
  return self._issue(response) if response else None
 def find(self,lane,marker,company=None,project=None):
  # Recovery queries where the journal says the POST went, not current config.
  path=f'/companies/{company or self.companies[lane]}/issues?projectId={project or self.projects[lane]}'
  return [self._issue(row) for row in self.board.api('GET',path) or [] if marker in (row.get('description') or '')]
 def role_running(self,key):
  return self.board.api('GET','/agents/'+self._agent(key))['status']=='running'
 def require_role(self,key):
  self._agent(key)

class LocalTracker:
 idempotent_create=True
 def __init__(self,jobs,root):
  self.jobs=jobs;self.root=pathlib.Path(root)
 def owner(self):
  return 'owner'
 def get(self,id):
  job=self.jobs.get(id)
  if not job:raise KeyError(id)
  return job
 def create(self,lane,kind,title,status,description='',assignee=None,job_id=None,company=None):
  return self.jobs.create(lane,kind,title,description=description,status=status,assignee=assignee,job_id=job_id)
 def update(self,id,status=None,assignee=UNSET,comment=None,description=None,unblockDescriptor=None):
  changes={}
  if status is not None:changes['status']=status
  if assignee is not UNSET:changes['assignee']=assignee
  if comment is not None:changes['comment']=comment
  if unblockDescriptor is not None:
   changes['comment']=(changes.get('comment') or '')+'\nunblock: '+json.dumps(unblockDescriptor,ensure_ascii=False)
  if description is not None:changes['description']=description
  return self.jobs.update(id,**changes)
 def find(self,lane,marker,company=None,project=None):
  return [job for job in self.jobs.list(lane=lane) if marker in (job.get('description') or '')]
 def require_role(self,key):
  lane,_,kind=key.partition(':')
  if not lane or kind not in KINDS:raise KeyError('Unknown role '+key)
 def role_running(self,key):
  lane,_,kind=key.partition(':')
  if not lane or kind not in KINDS:return False
  return any(self.jobs.holder(job['id']) is not None for job in self.jobs.list(lane=lane,kind=kind,status='in_progress'))

def as_tracker(tracker,root):
 return PaperclipTracker(tracker,root) if hasattr(tracker,'api') else tracker

def open_tracker(root,board_factory):
 try:value=json.loads((pathlib.Path(root)/'data/local-settings.json').read_text())
 except (OSError,ValueError):value=None
 if isinstance(value,dict) and value.get('tracker')=='local':return LocalTracker(Jobs(root),root)
 return PaperclipTracker(board_factory(),root)
