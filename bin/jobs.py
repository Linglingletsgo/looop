"""Local job table with bounded events and process-owner leases."""
import contextlib,fcntl,json,pathlib,sqlite3,time,uuid
import process_owner
from project_state import valid_lane

STATUSES=('backlog','todo','in_progress','in_review','blocked','done','cancelled')
KINDS=('planning','delivery','status')
COLUMNS=('id','lane','kind','title','description','status','assignee','created','updated')
MAX_EVENTS=50
MAX_BODY=35000
_UNSET=object()
_SCHEMA="""CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,lane TEXT NOT NULL,kind TEXT NOT NULL,
title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,assignee TEXT,
created REAL NOT NULL,updated REAL NOT NULL,lease_owner TEXT,lease_until REAL);
CREATE TABLE IF NOT EXISTS job_events(job TEXT NOT NULL,at REAL NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_lane_status ON jobs(lane,status);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job,at);"""

def _status(value):
 if value not in STATUSES:raise ValueError('Invalid job status: '+repr(value))
 return value

def _kind(value):
 if value not in KINDS:raise ValueError('Invalid job kind: '+repr(value))
 return value

def _owner(text):
 if not text:return None
 try:value=json.loads(text)
 except ValueError:return None
 return value if isinstance(value,dict) else None

def _dump(owner):
 return json.dumps(owner,sort_keys=True,ensure_ascii=False,separators=(',',':'))

def _record(row):
 job={name:row[name] for name in COLUMNS}
 job['identifier']=row['lane'].upper()+'-'+row['id'][:8]
 return job

def _event(c,job,kind,body,at):
 c.execute('INSERT INTO job_events(job,at,kind,body) VALUES (?,?,?,?)',(job,at,kind,body))
 c.execute('DELETE FROM job_events WHERE job=? AND rowid NOT IN '
  '(SELECT rowid FROM job_events WHERE job=? ORDER BY rowid DESC LIMIT ?)',(job,job,MAX_EVENTS))

class Jobs:
 def __init__(self,root):
  self.root=pathlib.Path(root);directory=self.root/'data'
  directory.mkdir(parents=True,exist_ok=True,mode=0o700);self.path=directory/'jobs.sqlite'
  with self.connection():pass

 @contextlib.contextmanager
 def connection(self):
  self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  with (self.path.parent/'.jobs.lock').open('a') as handle:
   fcntl.flock(handle,fcntl.LOCK_EX)
   c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
   c.execute('PRAGMA journal_mode=WAL');c.executescript(_SCHEMA)
   self.path.chmod(0o600)
   try:
    yield c;c.commit()
   except BaseException:
    c.rollback();raise
   finally:c.close()

 def create(self,lane,kind,title,description='',status='backlog',assignee=None,job_id=None):
  valid_lane(lane);_kind(kind);_status(status)
  if not isinstance(title,str) or not isinstance(description or '',str) or not isinstance(assignee,(str,type(None))):
   raise TypeError('title, description and assignee must be strings')
  jid=job_id or uuid.uuid4().hex;now=time.time()
  payload=(lane,kind,title,description or '',status,assignee)
  with self.connection() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT lane,kind,title,description,status,assignee FROM jobs WHERE id=?',(jid,)).fetchone()
   if row:
    existing=tuple(row[name] for name in ('lane','kind','title','description','status','assignee'))
    if existing!=payload:raise ValueError('Job id already used for a different payload: '+jid)
    return _record(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
   c.execute('INSERT INTO jobs(id,lane,kind,title,description,status,assignee,created,updated) '
    'VALUES (?,?,?,?,?,?,?,?,?)',(jid,*payload,now,now))
   _event(c,jid,'created','',now)
   return _record(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())

 def get(self,id):
  with self.connection() as c:row=c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone()
  return _record(row) if row else None

 def update(self,id,status=None,assignee=_UNSET,comment=None,description=None):
  now=time.time();changes={};events=[]
  with self.connection() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone()
   if not row:raise KeyError(id)
   if status is not None:
    _status(status)
    if status!=row['status']:changes['status']=status;events.append(('status',row['status']+'->'+status))
   if assignee is not _UNSET:changes['assignee']=assignee
   if description is not None:changes['description']=description
   if comment is not None:events.append(('comment',str(comment)[:MAX_BODY]))
   changes['updated']=now
   c.execute('UPDATE jobs SET '+','.join(name+'=?' for name in changes)+' WHERE id=?',(*changes.values(),id))
   for kind,body in events:_event(c,id,kind,body,now)
   return _record(c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone())

 def list(self,lane=None,status=None,assignee=None,kind=None):
  clauses=[];params=[]
  if lane is not None:clauses.append('lane=?');params.append(valid_lane(lane))
  if status is not None:
   statuses=[status] if isinstance(status,str) else list(status)
   for value in statuses:_status(value)
   if not statuses:return []
   clauses.append('status IN ('+','.join('?' for _ in statuses)+')');params.extend(statuses)
  if assignee is not None:clauses.append('assignee=?');params.append(assignee)
  if kind is not None:clauses.append('kind=?');params.append(_kind(kind))
  query='SELECT * FROM jobs'+((' WHERE '+(' AND '.join(clauses))) if clauses else '')+' ORDER BY created,rowid'
  with self.connection() as c:rows=c.execute(query,params).fetchall()
  return [_record(row) for row in rows]

 def events(self,id,limit=50):
  with self.connection() as c:
   if not c.execute('SELECT 1 FROM jobs WHERE id=?',(id,)).fetchone():raise KeyError(id)
   rows=c.execute('SELECT at,kind,body FROM job_events WHERE job=? ORDER BY rowid DESC LIMIT ?',
    (id,max(0,int(limit)))).fetchall()
  return [dict(row) for row in reversed(rows)]

 def claim(self,id,owner,ttl):
  if not isinstance(owner,dict):raise TypeError('lease owner must be a process_owner identity')
  now=time.time()
  with self.connection() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT lease_owner,lease_until FROM jobs WHERE id=?',(id,)).fetchone()
   if not row:raise KeyError(id)
   previous=_owner(row['lease_owner']);until=row['lease_until'] or 0
   if previous and previous!=owner and now<until and process_owner.alive(previous) is not False:return False
   c.execute('UPDATE jobs SET lease_owner=?,lease_until=? WHERE id=?',(_dump(owner),now+float(ttl),id))
   return True

 def release(self,id,owner):
  with self.connection() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT lease_owner FROM jobs WHERE id=?',(id,)).fetchone()
   if not row:raise KeyError(id)
   if _owner(row['lease_owner'])!=owner:return False
   c.execute('UPDATE jobs SET lease_owner=NULL,lease_until=NULL WHERE id=?',(id,))
   return True

 def holder(self,id):
  now=time.time()
  with self.connection() as c:row=c.execute('SELECT lease_owner,lease_until FROM jobs WHERE id=?',(id,)).fetchone()
  if not row:raise KeyError(id)
  previous=_owner(row['lease_owner'])
  if not previous or now>=(row['lease_until'] or 0):return None
  return previous if process_owner.alive(previous) is not False else None

 def owner(self):
  return 'owner'
