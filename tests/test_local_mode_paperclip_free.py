"""Local mode must never construct Board or send a Paperclip request."""
import importlib.util,json,os,pathlib,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
BIN=pathlib.Path(__file__).resolve().parents[1]/'bin'
sys.path.insert(0,str(BIN))
import board
from jobs import Jobs
from project_state import Held,Store
from tracker import LocalTracker,open_tracker

def module(name,symbol=None):
 path=BIN/(name+'.py');spec=importlib.util.spec_from_file_location(symbol or name.replace('-','_'),path)
 value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

class NoBoard:
 def __init__(self):raise AssertionError('Board must not be constructed in local mode')

def local_root(tmp):
 root=pathlib.Path(tmp);(root/'data').mkdir(parents=True)
 (root/'data/local-settings.json').write_text(json.dumps({'tracker':'local'}))
 return root

class StateSyncLocal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'id':None,'company':None}}}))
  self.store=Store(self.root);self.store.ensure('demo');self.sync=module('state-sync','state_sync_local')

 def test_reconcile_and_outbox_delivery_are_local_idempotent(self):
  packet={'title':'Existing outcome','requirements':['Preserve behavior'],'acceptance':['Verified outcome'],'allowed_paths':['app.py'],'baseline_sha':'a'*40}
  bindings=self.root/'data/delivery-bindings';bindings.mkdir();(bindings/'task.json').write_text(json.dumps({'lane':'demo','packet':packet,'intent_ids':[],'authorization':{}}))
  receipt=self.root/'data/deliveries/task';receipt.mkdir(parents=True);(receipt/'state.json').write_text(json.dumps({'state':'merged','mainline_verified':'b'*40}))
  self.store.submit('demo',{'type':'requirement','title':'Intent','body':'Body','human_confirmed':True},0,'intent','test')
  with patch.object(self.sync,'Board',NoBoard):self.assertTrue(self.sync.sync(self.root))
  first=self.store.read('demo');self.assertEqual(first['tasks']['task']['phase'],'completed')
  with self.store.connection('demo') as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',('demo',)).fetchone()[0],0)
  with patch.object(self.sync,'Board',NoBoard):self.assertTrue(self.sync.sync(self.root))
  self.assertEqual(self.store.read('demo')['revision'],first['revision'])

 def test_5000_rows_are_acknowledged_before_held_can_stick(self):
  self.store.ensure('big');doc=self.store.read('big')
  with self.store.connection('big') as c:
   c.executemany('INSERT INTO outbox(lane,revision) VALUES (?,?)',[('big',i) for i in range(1,5001)])
   doc['revision']=5000;c.execute('UPDATE projects SET doc=? WHERE lane=?',(json.dumps(doc),'big'))
  command={'type':'requirement','title':'Next','body':'Body','human_confirmed':True}
  with self.assertRaises(Held):self.store.submit('big',command,5000,'blocked','test')
  with patch.object(self.sync,'Board',NoBoard):self.assertTrue(self.sync.sync(self.root))
  with self.store.connection('big') as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',('big',)).fetchone()[0],0)
  self.assertEqual(self.store.submit('big',command,5000,'after-sync','test')['revision'],5001)

class FakeBoard:
 def __init__(self):self.calls=[];self.issues=[]
 def api(self,method,path,data=None):
  self.calls.append((method,path,data))
  if path=='/auth/get-session':return {'user':{'id':'human'}}
  if method=='GET':return list(self.issues)
  if data and data.get('status')=='in_progress' and not data.get('assigneeUserId'):raise RuntimeError('Paperclip 422: in_progress issues require an assignee')
  if method=='POST':return {'id':'issue-'+str(len(self.calls))}
  return {'id':path.rsplit('/',1)[-1]}

class StateSyncPaperclip(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name);(self.root/'data').mkdir()
  (self.root/'data/control.json').write_text(json.dumps({'company':'fallback','projects':{'demo':{'id':'project-demo','company':'company-demo'}}}))
  self.store=Store(self.root);self.store.ensure('demo');self.sync=module('state-sync','state_sync_paperclip')

 def test_intent_request_sequence_is_unchanged_and_needs_no_session(self):
  self.store.submit('demo',{'type':'requirement','title':'Intent','body':'Body','human_confirmed':True},0,'intent','src')
  b=FakeBoard();self.assertTrue(self.sync.sync(self.root,b))
  self.assertEqual([(m,p) for m,p,_ in b.calls],[('GET','/companies/company-demo/issues?projectId=project-demo'),('POST','/companies/company-demo/issues')])
  payload=b.calls[1][2];self.assertEqual(set(payload),{'title','description','status','projectId'})
  self.assertEqual((payload['title'],payload['status'],payload['projectId']),('Product / Intent','backlog','project-demo'))
  self.assertNotIn('/auth/get-session',[p for _,p,_ in b.calls])

 def test_in_progress_post_and_patch_carry_one_session_assignee(self):
  self.store.external_work('demo',{'action':'start','id':'work-1','summary':'Started'},0,'start','src')
  b=FakeBoard();self.assertTrue(self.sync.sync(self.root,b))
  self.assertEqual([(m,p) for m,p,_ in b.calls],[('GET','/companies/company-demo/issues?projectId=project-demo'),('GET','/auth/get-session'),('POST','/companies/company-demo/issues')])
  post=b.calls[-1][2];self.assertEqual((post['status'],post['assigneeUserId'],post['projectId']),('in_progress','human','project-demo'))
  self.assertIn('<!-- project-external-work:demo:work-1 -->',post['description'])
  self.store.external_work('demo',{'action':'progress','id':'work-1','summary':'More'},1,'progress','src')
  self.assertTrue(self.sync.sync(self.root,b))
  self.assertEqual([(m,p) for m,p,_ in b.calls][3:],[('GET','/companies/company-demo/issues?projectId=project-demo'),('GET','/auth/get-session'),('PATCH','/issues/issue-3')])
  patch_payload=b.calls[-1][2];self.assertEqual((patch_payload['status'],patch_payload['assigneeUserId']),('in_progress','human'))
  self.assertEqual(len([1 for m,p,_ in b.calls if p=='/auth/get-session']),2)

class BrokenSessionBoard(FakeBoard):
 def __init__(self,response):super().__init__();self.response=response
 def api(self,method,path,data=None):
  self.calls.append((method,path,data))
  if path=='/auth/get-session':
   if isinstance(self.response,Exception):raise self.response
   return self.response
  if method=='GET':return list(self.issues)
  if method=='POST':self.issues.append({'id':'issue-'+str(len(self.calls)),'projectId':'project-demo','status':data.get('status'),'description':data.get('description')});return {'id':self.issues[-1]['id']}
  return {'id':path.rsplit('/',1)[-1]}

class StateSyncSessionFailure(StateSyncPaperclip):
 """A failed session lookup must stop before the in_progress request, as the old 422 did."""
 def prepare(self):
  # One backlog intent is mirrored first; the in_progress external work then needs the session.
  self.store.submit('demo',{'type':'requirement','title':'Intent','body':'Body','human_confirmed':True},0,'intent','src')
  self.store.external_work('demo',{'action':'start','id':'work-1','summary':'Started'},1,'start','src')
  # Both lanes carry a mirror database, so the missing local setting reads as Paperclip mode.
  Store(self.root).ensure('other');Store(self.root).submit('other',{'type':'requirement','title':'Elsewhere','body':'Body','human_confirmed':True},0,'intent','src')
  return {'demo':Store(self.root).read('demo')['revision'],'other':Store(self.root).read('other')['revision']}

 def pending(self):
  with Store(self.root).connection('demo') as c:return [r[0] for r in c.execute('SELECT revision FROM outbox WHERE lane=? AND delivered=0 ORDER BY revision',('demo',))]
 def check_failure(self,board,Expected):
  revisions=self.prepare();before=json.loads((self.store.document('demo')).read_text())
  with self.assertRaises(Expected):self.sync.sync(self.root,board)
  # The intent already mirrored stays linked; the failing lane keeps every revision pending for retry.
  with Store(self.root).connection('demo') as c:self.assertEqual(c.execute('SELECT count(*) FROM links WHERE lane=?',('demo',)).fetchone()[0],1)
  # Nothing was acknowledged: both the mirrored intent and the external work stay pending for retry.
  self.assertEqual(self.pending(),[1,revisions['demo']])
  self.assertEqual(Store(self.root).read('other')['revision'],revisions['other'])
  self.assertEqual(json.loads((self.store.document('demo')).read_text()),before)
  # The failed session GET is the last request; the in_progress POST never happens.
  self.assertEqual([(m,p) for m,p,_ in board.calls][-1:],[('GET','/auth/get-session')])
  self.assertEqual([p for _,p,_ in board.calls].count('/companies/company-demo/issues'),1)
  self.assertEqual(board.issues[0]['status'],'backlog')
  # A later run with a working session retries the same lane and delivers the pending snapshot.
  good=FakeBoard();self.assertTrue(self.sync.sync(self.root,good))
  self.assertEqual(self.pending(),[])
  # No duplicate intent: a fresh board scan still finds it by its durable marker and PATCHes it.
  self.assertEqual([(m,p) for m,p,_ in good.calls],[('GET','/companies/company-demo/issues?projectId=project-demo'),('PATCH','/issues/issue-2'),('GET','/auth/get-session'),('POST','/companies/company-demo/issues')])
  self.assertEqual(good.calls[-1][2]['assigneeUserId'],'human')

 def test_failed_session_lookup_stops_at_the_in_progress_request(self):
  self.check_failure(BrokenSessionBoard(RuntimeError('Paperclip 503: session unavailable')),RuntimeError)

 def test_unexpected_session_shape_stops_before_any_in_progress_request(self):
  self.check_failure(BrokenSessionBoard({'user':None}),(TypeError,KeyError))

class PlanningRetryUnmigratedJob(unittest.TestCase):
 """Local retry of a PM attempt whose issue was never migrated fails clearly and changes nothing."""
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  self.lane='demo';self.jobs=Jobs(self.root);self.tracker=LocalTracker(self.jobs,self.root)
  self.pm=module('planning_intervention','planning_retry_local')
  # An unrelated row proves only the PM issue is missing from the local table.
  self.jobs.create(self.lane,'delivery','Delivery for PM','unrelated',job_id='delivery-1')
  self.path=self.root/'data/autonomy'/self.lane/'pm-one'/'state.json';self.path.parent.mkdir(parents=True)
  self.path.write_text(json.dumps({'state':'blocked','owner':{'pid':0},'issue':'pm-issue','error':'Completion protocol failed'}))
  self.revision=Store(self.root).ensure(self.lane)['revision']
  (self.root/'data/control.json').write_text(json.dumps({'projects':{self.lane:{'id':None,'company':None}},'agents':{}}))

 def rows(self):
  with self.jobs.connection() as c:return c.execute('SELECT * FROM jobs ORDER BY id').fetchall()

 def run_retry(self):
  with patch.object(self.pm,'alive',return_value=False),patch.object(board,'Board',NoBoard):
   with self.assertRaisesRegex(ValueError,'该 PM 任务不在本地任务表中（可能未迁移）；请先运行迁移或在维护对话中核对。') as raised:
    self.pm.retry(self.root,self.lane,'pm-one','证据已核验',self.revision,self.tracker)
  self.assertNotIsInstance(raised.exception,KeyError);return raised.exception

 def test_missing_job_raises_value_error_without_any_state_change(self):
  # Project state, PM receipt and job table are unchanged after the refused retry.
  files=[p for p in (self.root/'data').rglob('*') if p.suffix in ('.json','.current.json')];before={p:p.read_bytes() for p in files};rows=self.rows()
  self.run_retry()
  self.assertIsNone(self.jobs.get('pm-issue'));self.assertEqual(json.loads(self.path.read_text())['state'],'blocked')
  self.assertEqual(Store(self.root).read(self.lane)['revision'],self.revision)
  self.assertEqual({p:p.read_bytes() for p in files},before);self.assertEqual(self.rows(),rows)

 def test_console_retry_planning_attempt_reports_the_same_error(self):
  actions=module('console_actions','console_actions_local')
  with patch.object(self.pm,'alive',return_value=False),patch.object(board,'Board',NoBoard),patch.object(actions,'ROOT',self.root):
   with self.assertRaisesRegex(ValueError,'该 PM 任务不在本地任务表中') as raised:
    actions.execute({'action':'retry_planning_attempt','lane':self.lane,'job':'pm-one','reason':'证据已核验','revision':self.revision,'request_id':'r1'},root=self.root)
  self.assertNotIsInstance(raised.exception,KeyError)

class OnboardingLocal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=pathlib.Path(self.tmp.name)
  self.home=base/'home';self.repo=self.home/'projects'/'demo';self.repo.mkdir(parents=True)
  self.root=local_root(base/'root');(self.root/'data/control.json').write_text(json.dumps({'projects':{},'agents':{}}))
  (self.root/'bin').mkdir()
  for name in ('project-session.py','project_state.py','state_revisions.py','product_goals.py','lifecycle_io.py'):shutil.copy2(BIN/name,self.root/'bin'/name)
  subprocess.run(['git','-C',str(self.repo),'init','-q','-b','main'],check=True)
  subprocess.run(['git','-C',str(self.repo),'-c','user.email=t@t','-c','user.name=t','commit','--allow-empty','-qm','init'],check=True)
  env=patch.dict(os.environ,{'HOME':str(self.home)});env.start();self.addCleanup(env.stop)
  self.onboarding=module('onboarding','onboarding_local');self.value=self.onboarding.preview(self.repo,root=self.root)

 def test_preview_uses_local_wording(self):
  self.assertFalse(any('Paperclip' in item for item in self.value['planned_changes']))
  self.assertTrue(any('本地任务队列' in item for item in self.value['planned_changes']))

 def test_connect_creates_no_board_and_local_consumers_work(self):
  with patch.object(board,'Board',NoBoard):result=self.onboarding.connect(self.root,self.repo,self.value['fingerprint'])
  self.assertTrue(result['connected']);entry=json.loads((self.root/'data/control.json').read_text())['projects']['demo']
  self.assertEqual((entry['id'],entry['company']),(None,None));self.assertEqual((entry['repo'],entry['integration'],entry['name']),(str(self.repo),'observe','demo'))
  receipt=json.loads((self.repo/'.agent/local/onboarding.json').read_text())
  self.assertEqual((receipt['phase'],receipt['company'],receipt['project'],receipt['tracker']),('connected',None,None,'local'))
  dispatch=module('dispatch','dispatch_local');health=module('health','health_local');launch=module('launch_loops','launch_local');console=module('console','console_local')
  with patch.object(board,'Board',NoBoard):
   tracker=open_tracker(self.root,board.Board)
   self.assertEqual(dispatch.reconcile(self.root,tracker),[]);self.assertEqual(health.reconcile(self.root,tracker),0);launch.launch(self.root)
   self.assertIn('demo',[p['id'] for p in console.status(self.root)['projects']])

class MaintenanceLocal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'id':None,'company':None,'repo':str(self.root)}},'agents':{}}))
  (self.root/'data/autonomy-policies').mkdir();(self.root/'data/autonomy-policies/demo.json').write_text('{}')
  (self.root/'data/delivery-bindings').mkdir();(self.root/'data/project-state').mkdir();(self.root/'data/project-state/enabled').touch()
  Store(self.root).ensure('demo');self.jobs=Jobs(self.root)

 def test_every_maintenance_step_avoids_board(self):
  names=('retention','binding_requests','planning-recovery','publication-recovery','restart-recovery','dispatch','state-sync','delivery-control','health','loop-status','maintenance')
  mods={name:module(name,'maint_'+name.replace('-','_')) for name in names};tracker=LocalTracker(self.jobs,self.root)
  with patch.object(board,'Board',NoBoard),patch.object(mods['state-sync'],'Board',NoBoard),patch.object(mods['delivery-control'],'Board',NoBoard),patch.object(mods['loop-status'],'Board',NoBoard),patch.object(mods['delivery-control'],'ROOT',self.root):
   self.assertIsInstance(mods['retention'].maintain(self.root),dict)
   self.assertEqual(mods['binding_requests'].reconcile(self.root,tracker),[])
   self.assertEqual(mods['planning-recovery'].reconcile(self.root,tracker),[])
   self.assertEqual(mods['publication-recovery'].reconcile(self.root,None),[])
   self.assertEqual(mods['restart-recovery'].reconcile(self.root,tracker),[])
   self.assertEqual(mods['dispatch'].reconcile(self.root,tracker),[])
   self.assertTrue(mods['state-sync'].sync(self.root))
   self.assertIsNone(mods['delivery-control'].sync_prs())
   self.assertEqual(mods['health'].reconcile(self.root,tracker),0)
   self.assertIn(['python3','bin/loop-status.py','demo'],mods['maintenance'].commands(self.root))
   with patch.object(mods['loop-status'],'ROOT',self.root):mods['loop-status'].report('demo')

if __name__=='__main__':unittest.main()
