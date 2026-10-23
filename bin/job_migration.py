"""Import existing runtime records into the local job table under legacy ids."""
import fcntl,json,pathlib,re
from jobs import Jobs,STATUSES
from lifecycle import terminal
from project_state import valid_lane
from tracker import PaperclipTracker

def _expired(exc):
 return getattr(exc,'code',None)==401 or re.search(r'(?:^|:\s*)401(?:\D|$)',str(exc).strip()) is not None

class ReadOnlyBoard:
 """Board proxy for migration: only GET is allowed and a 401 never signs in."""
 def __init__(self,board):
  self.board=board
 def api(self,method,path,data=None,retry=True):
  if method!='GET':raise RuntimeError('migration board access is read-only: '+str(method))
  try:return self.board.api(method,path,data,retry=False)
  except Exception as exc:
   if _expired(exc):raise RuntimeError('Paperclip session expired; sign in through the console and rerun') from None
   raise

class _TitleTracker(PaperclipTracker):
 def _issue(self,value,lane=None):
  value=value if isinstance(value,dict) else {}
  issue=super()._issue(value,lane);issue['title']=value.get('title');return issue

def _assignee(kind,lane,status):
 return lane+':delivery' if kind=='delivery' and status in ('todo','in_progress') else 'owner'

def _load(path,errors):
 try:value=json.loads(path.read_text())
 except (OSError,ValueError) as exc:
  errors.append({'source':str(path),'error':str(exc)});return None
 if not isinstance(value,dict):
  errors.append({'source':str(path),'error':'expected a JSON object'});return None
 return value

def _lane(value,path,errors):
 try:return valid_lane(value)
 except ValueError as exc:
  errors.append({'source':str(path),'error':str(exc)});return None

def _issue(value,path,errors):
 if not isinstance(value,str) or not value:
  errors.append({'source':str(path),'error':'missing or invalid issue id'});return None
 return value

def _delivery(root,errors):
 jobs=[];bindings=root/'data/delivery-bindings';folder=root/'data/deliveries';bound=set()
 for path in sorted(bindings.glob('*.json')) if bindings.is_dir() else []:
  binding=_load(path,errors)
  if binding is None:continue
  lane=_lane(binding.get('lane'),path,errors)
  if lane is None:continue
  # A binding the worker could not execute is an error, not a job; its receipt then shows as an orphan.
  job_id=path.stem;packet=binding.get('packet')
  if not isinstance(packet,dict) or not packet:
   errors.append({'source':str(path),'error':'packet must be a non-empty JSON object'});continue
  bound.add(job_id)
  title=packet.get('title') if isinstance(packet.get('title'),str) else job_id
  receipt=folder/job_id/'state.json';status='todo'
  if receipt.is_file():
   document=_load(receipt,errors)
   if document is None:continue
   state=document.get('state')
   status=(terminal(state) if isinstance(state,str) else None) or ('blocked' if state=='blocked' else 'in_progress')
  jobs.append({'id':job_id,'kind':'delivery','lane':lane,'title':title,
   'description':'','status':status,'assignee':_assignee('delivery',lane,status),
   'source':str(path)})
 orphans=[p.name for p in sorted(folder.iterdir()) if p.is_dir() and (p/'state.json').is_file() and p.name not in bound] if folder.is_dir() else []
 return jobs,orphans

STATUS={'queued':'done','no_work':'done','cancelled':'cancelled','rejected':'done','blocked':'blocked',
 'proposing':'in_progress','product_scope_review':'in_progress','binding':'in_progress','discovering':'in_progress'}

def _planning(root,errors):
 jobs=[];base=root/'data/autonomy'
 if not base.is_dir():return jobs
 for lane_dir in sorted(base.iterdir()):
  if not lane_dir.is_dir():continue
  for attempt in sorted(lane_dir.iterdir()):
   path=attempt/'state.json'
   if not attempt.is_dir() or attempt.name.endswith('-status.json') or not path.is_file():continue
   receipt=_load(path,errors)
   if receipt is None:continue
   lane=_lane(lane_dir.name,path,errors)
   if lane is None:continue
   issue=_issue(receipt.get('issue'),path,errors)
   if issue is None:continue
   state=receipt.get('state');status=STATUS.get(state,'blocked') if isinstance(state,str) else 'blocked'
   jobs.append({'id':issue,'kind':'planning','lane':lane,'title':'PM / '+attempt.name,
    'description':'','status':status,'assignee':_assignee('planning',lane,status),
    'source':str(path)})
 return jobs

def _status(root,errors):
 jobs=[];base=root/'data/loop-dashboard'
 if not base.is_dir():return jobs
 for path in sorted(base.glob('*.json')):
  board=_load(path,errors)
  if board is None:continue
  lane=_lane(path.stem,path,errors)
  if lane is None:continue
  issue=_issue(board.get('issue'),path,errors)
  if issue is None:continue
  jobs.append({'id':issue,'kind':'status','lane':lane,'title':'自动队列 / 当前状态与阻塞原因',
   'description':board.get('body') or '','status':'in_progress',
   'assignee':_assignee('status',lane,'in_progress'),'source':str(path)})
 return jobs

def collect(root):
 jobs=[];duplicates=[];errors=[];seen=set();delivery,orphans=_delivery(root,errors)
 for job in delivery+_planning(root,errors)+_status(root,errors):
  if job['id'] in seen:
   if job['id'] not in duplicates:duplicates.append(job['id'])
   continue
  seen.add(job['id']);jobs.append(job)
 return jobs,orphans,duplicates,errors

def overlay(root,jobs,board):
 """Apply a read-only Paperclip overlay; errors stay local to one issue."""
 report={}
 if board is None:return report
 tracker=_TitleTracker(ReadOnlyBoard(board),root)
 for job in jobs:
  try:
   issue=tracker.get(job['id'])
   lane=issue.get('lane');status=issue.get('status');title=issue.get('title')
   if lane!=job['lane']:
    report[job['id']]={'result':'lane_mismatch','lane_mismatch':True,'lane':lane,'status':status,'title':title};continue
   if status not in STATUSES:raise ValueError('Unsupported board status: '+repr(status))
   if not isinstance(title,str):title=job['title']
   differs=status!=job['status'] or title!=job['title']
   job['status']=status;job['title']=title
   job['assignee']=_assignee(job['kind'],job['lane'],status)
   report[job['id']]={'result':'board_differs' if differs else 'same','differs':differs,'lane_mismatch':False,'lane':lane,'status':status,'title':title}
  except Exception as exc:report[job['id']]={'result':'error','error':str(exc)}
 return report

def _board_failure(report,job_id):
 entry=report.get(job_id) or {}
 if entry.get('result')!='error':return None
 return entry.get('error') or 'board overlay failed'

def _row(job,result,**extra):
 return {name:job[name] for name in ('id','kind','lane','status','assignee','source')}|{'result':result}|extra

def _counts(rows,orphans,duplicates,conflicts,errors):
 result={'jobs':len(rows),'total':len(rows),'orphans':len(orphans),'duplicates':len(duplicates),
  'conflicts':len(conflicts),'errors':len(errors)}
 result.update({name:sum(row['result']==name for row in rows) for name in
  ('planned','created','existing','board_error','conflict','error')})
 return result

def migrate(root,apply=False,board=None):
 root=pathlib.Path(root).expanduser().resolve()
 if not (root/'data/control.json').is_file():raise ValueError('Not a runtime root (no data/control.json): '+str(root))
 jobs,orphans,duplicates,errors=collect(root);report=overlay(root,jobs,board)
 if not apply:
  rows=[]
  for job in jobs:
   failed=_board_failure(report,job['id'])
   rows.append(_row(job,'board_error',error=failed) if failed else _row(job,'planned'))
  return {'mode':'dry-run','counts':_counts(rows,orphans,duplicates,[],errors),'jobs':rows,
   'orphans':orphans,'duplicates':duplicates,'errors':errors,'conflicts':[],'board':report}
 lock=root/'data/locks/migrate-jobs';lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX)
  store=Jobs(root);rows=[];conflicts=[];errors=list(errors)
  for job in jobs:
   failed=_board_failure(report,job['id'])
   if failed is not None:
    rows.append(_row(job,'board_error',error=failed));continue
   existing=store.get(job['id'])
   if existing:
    if existing['lane']!=job['lane'] or existing['kind']!=job['kind']:
     conflicts.append(job['id']);rows.append(_row(job,'conflict'));continue
    differs=[name for name in ('status','title','assignee','description') if existing[name]!=job[name]]
    row=_row(job,'existing')
    if differs:row['differs']=differs
    rows.append(row);continue
   try:
    store.create(job['lane'],job['kind'],job['title'],job['description'],job['status'],job['assignee'],job_id=job['id'])
    store.update(job['id'],comment='migrated from '+job['source']);rows.append(_row(job,'created'))
   except (TypeError,ValueError) as exc:
    errors.append({'source':job['source'],'error':str(exc)})
    rows.append(_row(job,'error',error=str(exc)))
  return {'mode':'apply','counts':_counts(rows,orphans,duplicates,conflicts,errors),'jobs':rows,
   'orphans':orphans,'duplicates':duplicates,'errors':errors,'conflicts':conflicts,'board':report}

def plan(root,board=None):
 return migrate(root,apply=False,board=board)

def apply(root,board=None):
 return migrate(root,apply=True,board=board)
