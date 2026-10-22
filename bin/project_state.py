"""Versioned project state. External intent commands and controller transitions are distinct."""
import contextlib,fcntl,hashlib,json,pathlib,re,sqlite3,time,uuid
from lifecycle_io import save as save_document,validate_receipt

class Conflict(ValueError):pass
class Held(ValueError):pass
PHASES={'queued','defining','building','checking','reviewing','acceptance','pr_ready','waiting_merge','verifying','completed','blocked','cancelled'}
NEXT={
 'queued':{'defining','building','blocked','cancelled'},'defining':{'building','blocked','cancelled'},
 'building':{'checking','blocked','cancelled'},'checking':{'building','reviewing','blocked','cancelled'},
 'reviewing':{'building','reviewing','acceptance','pr_ready','blocked','cancelled'},'acceptance':{'building','pr_ready','blocked','cancelled'},
 'pr_ready':{'waiting_merge','completed','blocked','cancelled'},'waiting_merge':{'verifying','blocked','cancelled'},
 'verifying':{'completed','blocked'},'blocked':{'queued'},'completed':set(),'cancelled':set()}
STAGES={'planning':'defining','building':'building','checking':'checking','acceptance':'acceptance','pr_ready':'pr_ready','waiting_for_merge':'waiting_merge','merged':'verifying','validated':'completed','closed':'cancelled','blocked':'blocked'}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def valid_lane(lane):
 if not isinstance(lane,str) or not re.fullmatch('[a-z][a-z0-9-]{0,47}',lane):raise ValueError('Invalid project lane')
 return lane

def unresolved_work(work):
 return any(r.get('cleanup') or r.get('unverified') or r.get('verdict')!='approved' for r in work.get('results',{}).values())

def initial(lane,config):
 return {'schema_version':1,'project':lane,'revision':0,'planning_revision':0,'phase':'idle','next_action':'PM selects meaningful work within mandate','config':config,'intents':{},'tasks':{},'selection':None}

class Store:
 def __init__(self,root):
  self.root=pathlib.Path(root);directory=self.root/'data/project-state';directory.mkdir(parents=True,exist_ok=True,mode=0o700);self.path=directory/'state.sqlite'
  self.locations=directory/'locations.json'
  with self.connection():pass
 def database(self,lane=None):
  if lane and self.locations.exists():
   mapping=json.loads(self.locations.read_text())
   if lane in mapping:return pathlib.Path(mapping[lane])
  return self.path
 def document(self,lane):
  return self.database(lane).parent/(valid_lane(lane)+'.current.json')
 @contextlib.contextmanager
 def connection(self,lane=None):
  path=self.database(lane);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  with (path.parent/'.state.lock').open('a') as handle:
   fcntl.flock(handle,fcntl.LOCK_EX)
   c=sqlite3.connect(path,timeout=30);c.row_factory=sqlite3.Row
   c.executescript("""CREATE TABLE IF NOT EXISTS projects(lane TEXT PRIMARY KEY,doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(lane TEXT,revision INTEGER,request_id TEXT,hash TEXT,event TEXT NOT NULL,created REAL,PRIMARY KEY(lane,revision),UNIQUE(lane,request_id));
CREATE TABLE IF NOT EXISTS outbox(lane TEXT,revision INTEGER,delivered INTEGER DEFAULT 0,PRIMARY KEY(lane,revision));
CREATE TABLE IF NOT EXISTS links(lane TEXT,item TEXT,issue TEXT NOT NULL,PRIMARY KEY(lane,item));""")
   path.chmod(0o600);pending=path.parent/'.state-pending.json'
   try:
    if pending.exists():
     marker=json.loads(pending.read_text());row=c.execute('SELECT doc FROM projects WHERE lane=?',(marker['lane'],)).fetchone()
     if row and json.loads(row['doc'])==marker['doc']:save_document(self.document(marker['lane']),marker['doc'])
     pending.unlink()
    if lane:
     docpath=self.document(lane)
     if docpath.exists():
      doc=json.loads(docpath.read_text())
      if doc.get('project')!=lane or doc.get('schema_version')!=1 or type(doc.get('revision')) is not int or len(json.dumps(doc).encode())>2097152:raise Conflict('Invalid project current-state document; preserve and repair it explicitly')
      for field,kind in (('tasks',dict),('intents',dict),('config',dict)):
       if not isinstance(doc.get(field),kind):raise Conflict('Invalid current-state field: '+field)
      cached=c.execute('SELECT doc FROM projects WHERE lane=?',(lane,)).fetchone()
      if cached:
       previous=json.loads(cached['doc'])
       if doc['revision']<previous['revision'] or doc['revision']==previous['revision'] and doc!=previous:raise Conflict('Current-state file revision conflicts with cached index; use revision-checked project tools')
       if doc['revision']>previous['revision']:
        event={'type':'file_state_update','source':'project-file','data':{'revision':doc['revision']}}
        c.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)',(lane,doc['revision'],'file-state-'+str(doc['revision']),digest(doc),json.dumps(event),time.time()))
        c.execute('INSERT OR IGNORE INTO outbox(lane,revision) VALUES (?,?)',(lane,doc['revision']))
      c.execute('INSERT OR REPLACE INTO projects VALUES (?,?)',(lane,json.dumps(doc,ensure_ascii=False)));c.commit()
    yield c
    if lane:
     row=c.execute('SELECT doc FROM projects WHERE lane=?',(lane,)).fetchone()
     if row:save_document(pending,{'lane':lane,'doc':json.loads(row['doc'])})
    c.commit()
    if lane and row:
     doc=json.loads(row['doc']);save_document(self.document(lane),doc)
     # Compatibility path is a read-only alias to the single authoritative document.
     alias=path.parent/'current.json'
     if not alias.is_symlink():
      if alias.exists():alias.replace(path.parent/'current.migrated.json')
      alias.symlink_to(self.document(lane).name)
     if pending.exists():pending.unlink()
   except BaseException:
    c.rollback();raise
   finally:c.close()

 def lanes(self):
  with self.connection() as c:lanes={r[0] for r in c.execute('SELECT lane FROM projects')}
  if self.locations.exists():lanes.update(json.loads(self.locations.read_text()))
  return sorted(lanes)
 def ensure(self,lane,config=None):
  valid_lane(lane)
  with self.connection(lane) as c:c.execute('INSERT OR IGNORE INTO projects VALUES (?,?)',(lane,json.dumps(initial(lane,config or {}),ensure_ascii=False)))
  return self.read(lane)
 def read(self,lane):
  valid_lane(lane)
  with self.connection(lane) as c:r=c.execute('SELECT doc FROM projects WHERE lane=?',(lane,)).fetchone()
  if not r:raise ValueError('Project state not initialized')
  return json.loads(r['doc'])
 def context(self,lane,history=False):
  doc=self.read(lane)
  # Conversations hydrate a bounded view; complete audit is available via read/history.
  tasks=doc['tasks'];active={k:v for k,v in tasks.items() if v['phase'] not in ('completed','cancelled')}
  recent=list(tasks.items()) if history else []
  selected=dict(recent);selected.update(active)
  intents={k:v for k,v in doc['intents'].items() if v['status'] not in ('completed','withdrawn','superseded')}
  works=doc.get('external_work',{})
  visible=works if history else {k:v for k,v in works.items() if v['status']=='active' or unresolved_work(v)}
  return {**doc,'tasks':selected,'intents':intents,'external_work':visible,'history_work_count':len(works),'history_task_count':len(tasks),'history_intent_count':len(doc['intents'])}
 def mutate(self,lane,request_id,command,apply,expected=None,source='controller'):
  valid_lane(lane)
  if not isinstance(request_id,str) or not re.fullmatch('[a-zA-Z0-9_.:-]{1,120}',request_id):raise ValueError('Stable request_id required')
  fingerprint=digest(command)
  with self.connection(lane) as c:
   c.execute('BEGIN IMMEDIATE')
   old=c.execute('SELECT hash,event,revision FROM events WHERE lane=? AND request_id=?',(lane,request_id)).fetchone()
   if old:
    if old['hash']!=fingerprint:raise Conflict('Idempotency key already used for a different command')
    return {'revision':old['revision'],'replayed':True,'event':json.loads(old['event'])}
   row=c.execute('SELECT doc FROM projects WHERE lane=?',(lane,)).fetchone()
   if not row:raise ValueError('Unknown initialized project')
   doc=json.loads(row['doc'])
   from state_revisions import check
   check(expected,doc['revision'],command,source)
   if c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',(lane,)).fetchone()[0]>=5000:raise Held('State sync backlog full; synchronize before new events')
   value=apply(doc)
   if value is None:return {'revision':doc['revision'],'unchanged':True}
   doc['revision']+=1;doc['updated_at']=time.time();recompute(doc)
   if len(json.dumps(doc,ensure_ascii=False).encode())>2097152:raise Held('Current state size limit reached; consolidate resolved state before continuing')
   event={'type':command['type'],'source':source,'data':value}
   c.execute('UPDATE projects SET doc=? WHERE lane=?',(json.dumps(doc,ensure_ascii=False),lane))
   c.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',(lane,doc['revision'],request_id,fingerprint,json.dumps(event,ensure_ascii=False),time.time()))
   c.execute('INSERT INTO outbox(lane,revision) VALUES (?,?)',(lane,doc['revision']))
   return {'revision':doc['revision'],'event':event}
 def submit(self,lane,command,expected,request_id,source):
  if not source or len(source)>300:raise ValueError('Source conversation identifier required')
  if expected is None:raise ValueError('expected_revision is required')
  if not isinstance(command,dict):raise ValueError('Command object required')
  if len(json.dumps(command,ensure_ascii=False))>32000:raise ValueError('Command too large; sync decisions, not transcript')
  kind=command.get('type')
  if kind not in ('propose','requirement','decision','priority','change','confirm','resolve_change','supersede_decision'):raise ValueError('External clients can submit intent, not execution transitions or policies')
  def apply(doc):
   confirmed=kind not in ('propose',)
   if confirmed and command.get('human_confirmed') is not True:raise ValueError('Explicit human confirmation is required for effective decisions')
   if kind in ('confirm','priority','resolve_change'):
    item=doc['intents'].get(command.get('intent_id'))
    if not item:raise ValueError('Unknown intent')
    if kind=='confirm':
     if item['status']!='proposed':raise ValueError('Only proposed intents can be confirmed')
     item['status']='ready' if item['kind']!='change' else 'waiting_decision'
    elif kind=='priority':
     if command.get('priority') not in ('urgent','high','normal','low'):raise ValueError('Invalid priority')
     item['priority']=command['priority']
     if item['status']=='waiting_decision' and item['kind']!='change':item['status']='ready';item.pop('planning_reason',None)
    else:
     if item['kind']!='change' or item['status']!='waiting_decision':raise ValueError('Not an unresolved change request')
     if command.get('resolution') not in ('keep_original','follow_up'):raise ValueError('Use keep_original or follow_up; replacing active scope requires controller cancellation and a new Packet')
     item['status']='withdrawn' if command['resolution']=='keep_original' else 'ready'
     if command['resolution']=='follow_up':item['kind']='requirement'
     task=doc['tasks'][item['target_task']];task['holds']=[i for i in task['holds'] if i!=item['id']]
    doc['selection']=None;doc['planning_revision']+=1;return item
   title=command.get('title');body=command.get('body')
   if not isinstance(title,str) or not 1<=len(title)<=200 or not isinstance(body,str) or not 1<=len(body)<=16000:raise ValueError('Title and concise body required')
   if command.get('priority','normal') not in ('urgent','high','normal','low'):raise ValueError('Invalid priority')
   item_id='intent-'+uuid.uuid4().hex[:16];item={'id':item_id,'kind':kind,'title':title,'body':body,'priority':command.get('priority','normal'),'source':source,'created_at':time.time(),'status':'proposed' if kind=='propose' else 'ready'}
   if kind=='supersede_decision':
    previous=doc['intents'].get(command.get('intent_id'))
    if not previous or previous['kind']!='decision' or previous['status']!='ready':raise ValueError('Only an effective product decision can be superseded')
    previous.update(status='superseded',superseded_by=item_id)
    item.update(kind='decision',supersedes=previous['id'])
   if kind=='change':
    task=doc['tasks'].get(command.get('target_task'))
    if not task or task['phase'] in ('completed','cancelled','verifying'):raise ValueError('Change must target an existing nonterminal task; otherwise submit a new requirement')
    item['target_task']=task['id'];item['status']='waiting_decision';task.setdefault('holds',[]).append(item_id)
   doc['intents'][item_id]=item
   if confirmed:doc['planning_revision']+=1;doc['selection']=None
   return item
  return self.mutate(lane,request_id,command,apply,expected,source)
 def bind(self,lane,job,packet,intent_ids=None,provenance=None,planning_revision=None):
  command={'type':'task_bound','job':job,'packet':{k:v for k,v in packet.items() if k!='execution_notes'},'intent_ids':intent_ids or []}
  def apply(doc):
   if job in doc['tasks']:
    if doc['tasks'][job]['contract_hash']!=digest({k:v for k,v in packet.items() if k!='execution_notes'}):raise Conflict('Cannot mutate a bound task contract')
    return None
   if planning_revision is not None and doc['planning_revision']!=planning_revision:raise Conflict('External decisions changed during planning; replan before dispatch')
   if any(t.get('holds') for t in doc['tasks'].values()):raise Held('Unresolved change holds dispatch')
   if any(w['status']=='active' for w in doc.get('external_work',{}).values()):raise Held('External development active; new dispatch paused')
   from product_goals import active,bind as bind_goal
   current=active(doc)
   for i in intent_ids or []:
    if i not in doc['intents'] or not (doc['intents'][i]['status']=='ready' or current and i in current.get('intent_ids',[]) and doc['intents'][i]['status']=='scheduled'):raise Conflict('Source intent is no longer ready')
   goal_contract=(provenance or {}).get('product_goal')
   if current and not goal_contract:raise Conflict('New tasks must continue the active product goal')
   goal=bind_goal(doc,job,goal_contract,intent_ids or []) if goal_contract else None
   doc['tasks'][job]={'id':job,'phase':'queued','packet':packet,'contract_hash':digest({k:v for k,v in packet.items() if k!='execution_notes'}),'intent_ids':intent_ids or [],'holds':[],'evidence':provenance or {}}
   if goal:doc['tasks'][job]['goal_id']=goal['id']
   for i in intent_ids or []:doc['intents'][i]['status']='scheduled'
   return doc['tasks'][job]
  return self.mutate(lane,'bind-'+job,command,apply)
 def transition(self,lane,job,phase,evidence=None,import_existing=False):
  if phase not in PHASES:raise ValueError('Unknown execution phase')
  evidence=evidence or {};command={'type':'task_transition','job':job,'phase':phase,'evidence':evidence,'import_existing':import_existing}
  def apply(doc):
   task=doc['tasks'].get(job)
   if not task:raise ValueError('Unknown bound task')
   if task['phase']==phase and all(task.get('evidence',{}).get(k)==v for k,v in evidence.items()):return None
   if phase!=task['phase'] and not import_existing and phase not in NEXT[task['phase']]:raise Conflict('Invalid transition '+task['phase']+' -> '+phase)
   if task['phase'] in ('completed','cancelled') and phase!=task['phase']:raise Conflict('Terminal task cannot be reopened')
   previous_phase=task['phase']
   task.update(phase=phase,evidence={**task.get('evidence',{}),**evidence})
   from product_goals import transition as goal_transition
   continuing=goal_transition(doc,task,phase,previous_phase)
   for i in task['intent_ids']:
    if phase=='completed':doc['intents'][i]['status']='scheduled' if continuing else 'completed'
    elif phase=='queued':doc['intents'][i]['status']='scheduled'
    elif phase=='blocked':doc['intents'][i]['status']='blocked'
   return task
  return self.mutate(lane,'phase-'+job+'-'+uuid.uuid4().hex,command,apply)
 def record_research(self,lane,report,planning_revision):
  if not isinstance(report,dict) or report.get('status') not in ('supported','rejected','insufficient_evidence'):raise ValueError('Invalid current research brief')
  if len(json.dumps(report,ensure_ascii=False).encode())>100000:raise ValueError('Research brief must remain bounded')
  def apply(doc):
   if doc['planning_revision']!=planning_revision:raise Conflict('External decisions changed during research')
   doc['research']=report
   return report
  return self.mutate(lane,'research-'+uuid.uuid4().hex,{'type':'research_updated'},apply)
 def finish_goal(self,lane,goal_id,reason,evidence,planning_revision):
  def apply(doc):
   from product_goals import active
   goal=active(doc)
   if doc['planning_revision']!=planning_revision:raise Conflict('External decisions changed during goal verification')
   if not goal or goal['id']!=goal_id:raise Conflict('Active goal changed')
   if any(t['phase'] not in ('completed','cancelled') for t in doc['tasks'].values()):raise Held('Deliveries must finish before goal completion')
   if not goal.get('completed_slices'):raise Held('Goal completion requires delivered work')
   if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ValueError('Concise goal completion reason required')
   from product_goals import completion_coverage
   completion_coverage(evidence,goal['success_criteria'],goal.get('experience'))
   goal.update(status='completed',progress_verification='pm_evidence_reviewed',remaining=[],progress=reason,completion_reason=reason,completion_evidence=evidence,current_task=None)
   for i in goal.get('intent_ids',[]):doc['intents'][i]['status']='completed'
   doc['planning_revision']+=1;doc['selection']=None
   return goal
  return self.mutate(lane,'goal-complete-'+goal_id,{'type':'goal_completed','goal_id':goal_id,'reason':reason,'evidence':evidence},apply)
 def wait_goal(self,lane,reason,planning_revision):
  def apply(doc):
   from product_goals import active
   goal=active(doc)
   if doc['planning_revision']!=planning_revision:raise Conflict('External decisions changed during planning')
   if not goal:raise Conflict('No active product goal')
   goal.update(status='waiting',progress=reason)
   return goal
  return self.mutate(lane,'goal-wait-'+uuid.uuid4().hex,{'type':'goal_wait','reason':reason},apply)
 def defer_intent(self,lane,intent,reason,planning_revision):
  def apply(doc):
   if doc['planning_revision']!=planning_revision:raise Conflict('External decisions changed during planning')
   item=doc['intents'][intent]
   if item['status']!='ready':raise Conflict('Source intent is no longer ready')
   item.update(status='waiting_decision',planning_reason=reason)
   return item
  return self.mutate(lane,'defer-'+uuid.uuid4().hex,{'type':'intent_deferred','intent_id':intent,'reason':reason},apply)
 def selection(self,lane,phase,detail):
  if phase not in ('discovering','no_work','blocked','queued','waiting'):raise ValueError('Unknown selection phase')
  def apply(doc):
   new={'phase':phase,'detail':detail}
   if doc.get('selection')==new:return None
   doc['selection']=new;return new
  return self.mutate(lane,'selection-'+uuid.uuid4().hex,{'type':'selection','phase':phase,'detail':detail},apply)
 def external_work(self,lane,command,expected,request_id,source):
  if expected is None or not source:raise ValueError('Revision and source required')
  action=command.get('action');work_id=command.get('id');summary=command.get('summary')
  if action not in ('start','progress','finish','cancel','result') or not isinstance(work_id,str) or not re.fullmatch('[a-zA-Z0-9-]{1,80}',work_id):raise ValueError('Invalid external work command')
  if not isinstance(summary,str) or not 1<=len(summary)<=8000:raise ValueError('Concise progress summary required')
  receipt=validate_receipt(command['receipt']) if action=='result' else None
  if receipt and receipt['task_id']!=work_id:raise ValueError('Receipt task differs from work ID')
  def apply(doc):
   works=doc.setdefault('external_work',{});item=works.get(work_id)
   if action=='start':
    if item:raise Conflict('Work ID already exists')
    if any(t['phase'] not in ('completed','cancelled') for t in doc['tasks'].values()):raise Held('Controller task active; pause/drain it before external development')
    if any(w['status']=='active' for w in works.values()):raise Held('Another external work session is active')
    item={'id':work_id,'source':source,'status':'active','started_at':time.time()};works[work_id]=item
   else:
    if not item or item['source']!=source or (item['status']!='active' and action!='result'):raise Conflict('No active work owned by this source')
    if action in ('finish','cancel'):item['status']='completed' if action=='finish' else 'cancelled'
   if receipt:
    results=item.setdefault('results',{});key=receipt['role']+':'+receipt['stage']
    if key not in results and len(results)>=16:raise ValueError('Too many role stages in one work session')
    results[key]=receipt
   item.update(summary=summary,updated_at=time.time(),verification='self_reported')
   from product_goals import active
   goal=active(doc)
   if goal and item['status']=='active':goal.update(progress=summary,progress_verification='self_reported')
   if action in ('start','finish','cancel'):doc['planning_revision']+=1;doc['selection']=None
   return item
  return self.mutate(lane,request_id,{'type':'external_work',**command},apply,expected,source)
 def merge_gate(self,lane,job,target,perform):
  # Same SQLite writer lock as external decisions: hold vs merge has a defined order.
  def apply(doc):
   task=doc['tasks'].get(job)
   if not task:raise Held('Merge requires a bound project task')
   if task.get('holds'):raise Held('Confirmed change request holds merge')
   if task['phase']!='waiting_merge':raise Held('Task is not waiting for merge')
   try:result=perform()
   except Exception as exc:result={'state':'UNKNOWN','error':str(exc)}
   # An uncertain network result may already have merged on GitHub: retain the gate.
   if result.get('state')!='MERGED':result={**result,'state':'UNKNOWN'}
   task.update(phase='verifying',evidence={**task.get('evidence',{}),'merge':result})
   return result
  result=self.mutate(lane,'merge-'+job+'-'+target,{'type':'merge','job':job,'target':target},apply)['event']['data']
  if result.get('state')!='MERGED':raise Held('Merge result uncertain; reconcile GitHub before recovery')
  return result
 def guard(self,lane,job):
  doc=self.read(lane);task=doc['tasks'].get(job)
  if task and task.get('holds'):raise Held('Confirmed change request requires disposition; task '+job+' held; immutable contract retained')
 def project_guard(self,lane):
  doc=self.read(lane)
  if any(t.get('holds') for t in doc['tasks'].values()):raise Held('Project has unresolved change requests; new dispatch paused')
  if any(w['status']=='active' for w in doc.get('external_work',{}).values()):raise Held('External development active; new dispatch paused')
 def events(self,lane,after=0):
  with self.connection(lane) as c:return [dict(r) for r in c.execute('SELECT revision,request_id,event,created FROM events WHERE lane=? AND revision>? ORDER BY revision',(lane,after))]

def recompute(doc):
 if any(w['status']=='active' for w in doc.get('external_work',{}).values()):
  doc.update(phase='external_work',next_action='Wait for independent development to finish; progress is self-reported');return
 active=[t for t in doc['tasks'].values() if t['phase'] not in ('completed','cancelled')]
 if any(t.get('holds') for t in active):doc.update(phase='waiting_decision',next_action='Resolve confirmed task change; old contract is immutable');return
 if active:
  task=next((t for t in active if t['phase']=='blocked'),active[-1]);doc.update(phase=task['phase'],next_action={'blocked':'Inspect failure evidence and decide recovery','waiting_merge':'Controller checks gates and merges','verifying':'Run post-merge mainline checks'}.get(task['phase'],'Controller advances current task after gate'));return
 selection=doc.get('selection')
 if selection and selection['phase'] in ('discovering','blocked'):doc.update(phase=selection['phase'],next_action='PM defines one task' if selection['phase']=='discovering' else 'Inspect PM evidence; no automatic replay');return
 if selection and selection['phase']=='waiting':
  doc.update(phase='waiting',next_action=selection['detail']);return
 from product_goals import active
 goal=active(doc)
 if goal:
  doc.update(phase='waiting' if goal['status']=='waiting' else 'ready',next_action=goal['progress'] if goal['status']=='waiting' else 'PM continues the active product goal');return
 ready=[i for i in doc['intents'].values() if i['status']=='ready' and i['kind'] in ('requirement','propose')]
 if not ready and any(i['status']=='waiting_decision' for i in doc['intents'].values()):
  doc.update(phase='waiting_decision',next_action='Review deferred requirement reasons; clarify scope or reprioritize to retry');return
 doc.update(phase='ready' if ready else 'idle',next_action='PM prioritizes confirmed intents' if ready else 'Wait for meaningful work or a confirmed external decision')

def phase_of(receipt):
 if receipt.get('mainline_verified'):return 'completed'
 state=receipt['state']
 return 'reviewing' if state.startswith('review_') else STAGES.get(state,'blocked')

def configured_store(root):
 return Store(root) if (pathlib.Path(root)/'data/project-state/enabled').exists() else None

def task_guard(root,job):
 store=configured_store(root)
 if not store:return
 binding=pathlib.Path(root)/'data/delivery-bindings'/(job+'.json')
 if binding.exists():store.guard(json.loads(binding.read_text())['lane'],job)

def record_phase(root,job,phase,evidence):
 store=configured_store(root)
 if not store:return
 binding=pathlib.Path(root)/'data/delivery-bindings'/(job+'.json')
 if not binding.exists():return
 from recovery import record_phase as record
 record(store,json.loads(binding.read_text()),job,phase,evidence)


