"""Local job tracker: the local job table is the only tracker."""
import json,pathlib
from jobs import Jobs,KINDS
UNSET=object()
# Sentinel for update(): clear the agent assignment, leave the human owner alone.
CLEAR_AGENT=object()

class TrackerConfigError(ValueError):
 """A local settings value cannot be honoured; fail at startup instead of guessing."""
 def __init__(self,path,message):self.path=path;super().__init__(message)

def _settings(root):
 path=pathlib.Path(root)/'data/local-settings.json'
 try:text=path.read_text()
 except FileNotFoundError:return path,None
 except OSError as exc:raise TrackerConfigError(path,'Cannot read '+str(path)+': '+str(exc))
 try:value=json.loads(text)
 except ValueError:raise TrackerConfigError(path,'local-settings.json is not valid JSON; fix or remove '+str(path))
 if not isinstance(value,dict):raise TrackerConfigError(path,'local-settings.json must contain a JSON object; fix or remove '+str(path))
 return path,value

def resolve_tracker(root):
 """Return 'local'. The retired tracker setting is accepted only as "local" or absent."""
 path,value=_settings(root)
 if value is not None and not isinstance(value,dict):
  raise TrackerConfigError(path,'local-settings.json must contain a JSON object; fix or remove '+str(path))
 setting=value.get('tracker') if value is not None else None
 if setting not in (None,'local'):
  raise TrackerConfigError(path,'Unsupported tracker '+json.dumps(setting)+' in '+str(path)+'; only "local" is supported. '
   'Paperclip installs must migrate on tag paperclip-last before upgrading; see docs/cutover.md.')
 return 'local'

class LocalTracker:
 name='local'
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
 def update(self,id,status=None,assignee=UNSET,comment=None,description=None,unblockDescriptor=None,owner_id=None):
  changes={}
  if status is not None:changes['status']=status
  if assignee is CLEAR_AGENT:changes['assignee']=None
  elif assignee is not UNSET:changes['assignee']=assignee
  if comment is not None:changes['comment']=comment
  if unblockDescriptor is not None:
   changes['comment']=(changes.get('comment') or '')+'\nunblock: '+json.dumps(unblockDescriptor,ensure_ascii=False)
  if description is not None:changes['description']=description
  return self.jobs.update(id,**changes)
 def assigned(self,lane,role,statuses):
  statuses=(statuses,) if isinstance(statuses,str) else tuple(statuses)
  return self.jobs.list(lane=lane,status=statuses,assignee=role)
 def agent_of(self,issue):
  value=(issue or {}).get('assignee')
  return None if value in (None,'owner') else value
 def assignee_is(self,issue,role):
  return self.agent_of(issue)==role
 def agent_assigned(self,issue):
  return self.agent_of(issue) is not None
 def find(self,lane,marker,company=None,project=None):
  return [job for job in self.jobs.list(lane=lane) if marker in (job.get('description') or '')]
 def require_role(self,key):
  lane,_,kind=key.partition(':')
  if not lane or kind not in KINDS:raise KeyError('Unknown role '+key)
 def role_running(self,key):
  lane,_,kind=key.partition(':')
  if not lane or kind not in KINDS:return False
  return any(self.jobs.holder(job['id']) is not None for job in self.jobs.list(lane=lane,kind=kind,status=('todo','in_progress')))

def as_tracker(tracker,root):
 return tracker if tracker is not None else LocalTracker(Jobs(root),root)

def open_tracker(root):
 resolve_tracker(root)
 return LocalTracker(Jobs(root),root)
