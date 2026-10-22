import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import process_owner
from jobs import Jobs
from tracker import LocalTracker,PaperclipTracker,as_tracker,open_tracker
import binding_requests
import test_autonomy

CONFIG={'company':'fallback','projects':{'demo':{'id':'project-demo','company':'company-demo'},'other':{'id':'project-other'}},'agents':{'demo:delivery':'agent-demo','demo:planning':'agent-pm'}}

class FakeBoard:
 def __init__(self,issues=None):
  self.calls=[];self.issues=issues or {}
 def api(self,method,path,data=None):
  self.calls.append((method,path,data))
  if path=='/auth/get-session':return {'user':{'id':'human'}}
  if method=='POST':return {'id':'created','identifier':'DEMO-created'}
  if method=='GET' and path.startswith('/companies/'):return list(self.issues.values())
  if method=='GET' and path.startswith('/issues/'):
   issue=self.issues.get(path.split('/')[-1])
   if issue is None:raise KeyError(path)
   return issue
  if method=='GET' and path.startswith('/agents/'):return {'id':path.split('/')[-1],'status':'running'}
  return None

class Paperclip(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  (self.root/'data').mkdir();(self.root/'data/control.json').write_text(json.dumps(CONFIG))
  self.issues={'issue':{'id':'issue','identifier':'DEMO-1','projectId':'project-demo','status':'backlog','assigneeAgentId':'agent-demo','description':'has marker'}}
  self.board=FakeBoard(self.issues);self.tracker=PaperclipTracker(self.board,self.root)
 def test_create_maps_lane_role_and_owner_to_board_payload(self):
  self.tracker.create('demo','delivery','Title','todo','Body',assignee='demo:delivery')
  self.assertEqual(self.board.calls[-1],('POST','/companies/company-demo/issues',{'projectId':'project-demo','title':'Title','status':'todo','description':'Body','assigneeAgentId':'agent-demo','assigneeUserId':None}))
  issue=self.tracker.create('other','status','Status','in_progress','Body',assignee='owner')
  self.assertEqual(self.board.calls[-1][1],'/companies/fallback/issues')
  self.assertEqual(self.board.calls[-1][2],{'projectId':'project-other','title':'Status','status':'in_progress','description':'Body','assigneeUserId':'human'})
  self.assertEqual(issue['lane'],'other');self.assertEqual(issue['assignee'],'owner')
 def test_get_normalizes_lane_role_and_owner(self):
  issue=self.tracker.get('issue')
  self.assertEqual(issue,{'id':'issue','identifier':'DEMO-1','lane':'demo','status':'backlog','assignee':'demo:delivery','description':'has marker'})
  self.issues['issue'].update(projectId='unknown',assigneeAgentId=None,assigneeUserId='human')
  self.assertEqual(self.tracker.get('issue')['lane'],None);self.assertEqual(self.tracker.get('issue')['assignee'],'owner')
 def test_update_and_find_and_running_use_same_routes(self):
  self.tracker.update('issue',status='cancelled',assignee='demo:planning',comment='why')
  self.assertEqual(self.board.calls[-1],('PATCH','/issues/issue',{'status':'cancelled','assigneeAgentId':'agent-pm','assigneeUserId':None,'comment':'why'}))
  self.tracker.update('issue',description='new',assignee=None)
  self.assertEqual(self.board.calls[-1][2],{'assigneeAgentId':None,'assigneeUserId':None,'description':'new'})
  self.tracker.update('issue',**{'status':'blocked','comment':'x','unblockDescriptor':{'owner':'board'}})
  self.assertEqual(self.board.calls[-1][2],{'status':'blocked','comment':'x','unblockDescriptor':{'owner':'board'}})
  self.assertEqual([i['id'] for i in self.tracker.find('demo','marker')],['issue'])
  self.assertEqual(self.board.calls[-1],('GET','/companies/company-demo/issues?projectId=project-demo',None))
  self.assertEqual(self.tracker.find('demo','absent'),[])
  self.assertTrue(self.tracker.role_running('demo:delivery'))
  self.assertEqual(self.tracker.owner(),'human');self.assertEqual(self.board.calls[-1],('GET','/auth/get-session',None))
  self.assertEqual(self.tracker.owner(),'human');self.assertEqual(len([c for c in self.board.calls if c[1]=='/auth/get-session']),1)
  self.assertFalse(self.tracker.idempotent_create)
 def test_recovery_queries_journal_scope_and_fails_closed(self):
  self.tracker.find('demo','marker','company-old','project-old')
  self.assertEqual(self.board.calls[-1],('GET','/companies/company-old/issues?projectId=project-old',None))
  self.tracker.create('demo','delivery','T','backlog','B',company='company-old')
  self.assertEqual(self.board.calls[-1][1],'/companies/company-old/issues')
  del self.issues['issue']['projectId']
  self.assertIsNone(self.tracker.find('demo','marker')[0]['lane'])
 def test_unconfigured_role_key_fails_before_any_call(self):
  calls=len(self.board.calls)
  for action in (lambda:self.tracker.role_running('other:delivery'),lambda:self.tracker.update('issue',status='todo',assignee='other:delivery')):
   with self.assertRaises(KeyError):action()
  self.assertEqual(len(self.board.calls),calls)
  self.tracker.role_running('agent-raw');self.assertEqual(self.board.calls[-1][1],'/agents/agent-raw')
  with self.assertRaises(KeyError):self.tracker.require_role('other:delivery')
  self.tracker.require_role('demo:delivery');self.assertEqual(len(self.board.calls),calls+1)
 def test_raw_board_wraps_into_paperclip_tracker(self):
  wrapped=as_tracker(FakeBoard(),self.root)
  self.assertIsInstance(wrapped,PaperclipTracker);self.assertIs(as_tracker(wrapped,self.root),wrapped)

class Local(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  self.jobs=Jobs(self.root);self.tracker=LocalTracker(self.jobs,self.root)
 def test_create_get_update_and_missing(self):
  job=self.tracker.create('demo','delivery','Title','todo','Body',assignee='demo:delivery')
  self.assertEqual(self.tracker.get(job['id'])['status'],'todo')
  with self.assertRaises(KeyError):self.tracker.get('missing')
  updated=self.tracker.update(job['id'],status='in_progress',comment='note',unblockDescriptor={'owner':'board'})
  self.assertEqual(updated['status'],'in_progress');self.assertEqual(updated['assignee'],'demo:delivery')
  self.assertEqual([e['kind'] for e in self.jobs.events(job['id'])],['created','status','comment'])
  self.assertEqual(self.tracker.update(job['id'],assignee=None)['assignee'],None)
  with self.assertRaises(KeyError):self.tracker.update('missing',status='done')
 def test_unblock_descriptor_is_kept_in_comment(self):
  job=self.tracker.create('demo','planning','T','in_progress')
  self.tracker.update(job['id'],status='blocked',comment='why',unblockDescriptor={'owner':'board'})
  self.assertIn('"owner": "board"',self.jobs.events(job['id'])[-1]['body'])
 def test_create_is_idempotent_for_preallocated_job_id(self):
  first=self.tracker.create('demo','delivery','Title','backlog','Body',job_id='legacy')
  again=self.tracker.create('demo','delivery','Title','backlog','Body',job_id='legacy')
  self.assertEqual(first,again);self.assertEqual(len(self.jobs.list()),1)
  with self.assertRaises(ValueError):self.tracker.create('demo','delivery','Other','backlog','Body',job_id='legacy')
  self.assertTrue(self.tracker.idempotent_create)
 def test_find_and_role_running_track_live_lease(self):
  job=self.tracker.create('demo','delivery','Title','in_progress','marker body')
  self.assertEqual([i['id'] for i in self.tracker.find('demo','absent')],[])
  self.assertEqual([i['id'] for i in self.tracker.find('demo','marker')],[job['id']])
  self.assertFalse(self.tracker.role_running('demo:delivery'))
  self.jobs.claim(job['id'],process_owner.identity(),60)
  self.assertTrue(self.tracker.role_running('demo:delivery'))
  self.assertFalse(self.tracker.role_running('demo:planning'))
  self.assertFalse(self.tracker.role_running('unknown'))
  self.jobs.release(job['id'],process_owner.identity())
  self.assertFalse(self.tracker.role_running('demo:delivery'))
  self.assertEqual(self.tracker.owner(),'owner')

class Selection(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name);(self.root/'data').mkdir()
 def settings(self,value):
  (self.root/'data/local-settings.json').write_text(value if isinstance(value,str) else json.dumps(value))
 def test_missing_or_invalid_settings_stay_on_paperclip(self):
  for value in (None,'{not json',{}, {'tracker':'paperclip'},{'tracker':''},[]):
   with self.subTest(value=value):
    settings=self.root/'data/local-settings.json'
    if settings.exists():settings.unlink()
    if value is not None:self.settings(value)
    calls=[]
    tracker=open_tracker(self.root,lambda:calls.append(1) or FakeBoard())
    self.assertIsInstance(tracker,PaperclipTracker);self.assertEqual(calls,[1])
 def test_local_selection_never_builds_a_board(self):
  self.settings({'tracker':'local'});calls=[]
  tracker=open_tracker(self.root,lambda:calls.append(1) or FakeBoard())
  self.assertIsInstance(tracker,LocalTracker);self.assertEqual(calls,[])

class LocalBinding(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 def prepare(self):
  self.tracker=LocalTracker(Jobs(self.root),self.root)
  for folder in ('data/delivery-policies','data/locks'):(self.root/folder).mkdir(parents=True,exist_ok=True)
  (self.root/'data/delivery-policies/test.json').write_text(json.dumps(self.policy))
  self.binding={'lane':'test','intent_ids':[],'packet':{**self.value['packet'],'baseline_sha':self.sha},'policy':self.policy,'publish':False,'owner':'owner'}
  self.folder=self.root/'data/autonomy/test/attempt'
 def payload(self):return {'projectId':'project','title':'Task','status':'backlog','description':'bound by PM'}
 def begin(self):return binding_requests.create(self.root,self.tracker,self.folder,self.binding,'company',self.payload(),1)
 def test_create_binds_one_job_with_preallocated_id(self):
  self.prepare();issue=self.begin()
  journal=json.loads((self.folder/'binding-request.json').read_text())
  self.assertEqual(journal['state'],'bound');self.assertEqual(journal['issue']['id'],journal['job_id'])
  self.assertEqual(self.tracker.get(journal['job_id'])['lane'],'test')
  self.assertIsNone(issue['assignee'])
  self.assertTrue((self.root/'data/delivery-bindings'/(journal['job_id']+'.json')).exists())
  self.assertEqual(binding_requests.reconcile(self.root,self.tracker),[])
 def test_journal_without_create_rebinds_once(self):
  self.prepare();journal=self.folder/'binding-request.json'
  with patch.object(self.tracker,'create',side_effect=ConnectionError('process died after journal')):
   with self.assertRaises(ConnectionError):self.begin()
  record=json.loads(journal.read_text());self.assertEqual(record['state'],'posting');job_id=record['job_id']
  self.assertEqual(self.tracker.jobs.list(),[])
  self.assertEqual(binding_requests.reconcile(self.root,self.tracker),[{'job':job_id,'state':'bound'}])
  self.assertEqual([j['id'] for j in self.tracker.jobs.list()],[job_id])
  self.assertEqual(json.loads(journal.read_text())['state'],'bound')
  self.assertEqual(binding_requests.reconcile(self.root,self.tracker),[])
  self.assertEqual(len(self.tracker.jobs.list()),1)
 def test_create_succeeded_before_journal_update_reuses_same_job(self):
  self.prepare();journal=self.folder/'binding-request.json';original=binding_requests.save
  def save(path,value):
   if path==journal and value.get('state')=='binding':raise OSError('journal update lost')
   return original(path,value)
  with patch.object(binding_requests,'save',side_effect=save),self.assertRaises(OSError):self.begin()
  record=json.loads(journal.read_text());self.assertEqual(record['state'],'posting')
  self.assertEqual(binding_requests.reconcile(self.root,self.tracker),[{'job':record['job_id'],'state':'bound'}])
  self.assertEqual([j['id'] for j in self.tracker.jobs.list()],[record['job_id']])
 def test_changed_job_state_is_preserved_not_rebound(self):
  self.prepare();journal=self.folder/'binding-request.json'
  with patch.object(self.tracker,'create',side_effect=ConnectionError('lost')):
   with self.assertRaises(ConnectionError):self.begin()
  record=json.loads(journal.read_text())
  self.tracker.jobs.create('test','delivery','Task',description=record['payload']['description'],job_id=record['job_id'])
  self.tracker.update(record['job_id'],status='in_progress')
  results=binding_requests.reconcile(self.root,self.tracker)
  self.assertEqual(results[0]['state'],'deferred');self.assertIn('Remote issue changed',results[0]['reason'])
  self.assertFalse((self.root/'data/delivery-bindings'/(record['job_id']+'.json')).exists())
 def test_legacy_journal_without_job_id_is_reported(self):
  self.prepare();self.folder.mkdir(parents=True)
  (self.folder/'binding-request.json').write_text(json.dumps({'state':'posting','marker':'<!-- m -->','binding':self.binding,'company':'company','payload':self.payload()}))
  result=binding_requests.reconcile(self.root,self.tracker)
  self.assertEqual(result[0]['state'],'deferred');self.assertIn('predates the local tracker',result[0]['reason'])

class UnconfiguredDelivery(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_tick_fails_before_any_side_effect(self):
  self.setup_tick();control=self.root/'data/control.json'
  value=json.loads(control.read_text());value['agents']={};control.write_text(json.dumps(value))
  calls=[]
  class Board:
   def api(self,method,path,data=None):calls.append((method,path));return {'user':{'id':'owner'}}
  with patch.object(test_autonomy.autonomy,'ROOT',self.root),patch.object(test_autonomy.autonomy,'Board',Board),patch.object(test_autonomy.autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(test_autonomy.autonomy,'run') as run:
   with self.assertRaises(KeyError):test_autonomy.autonomy.tick('test')
  self.assertEqual(calls,[]);run.assert_not_called()
  self.assertFalse((self.root/'data/autonomy/test').exists())
  self.assertFalse((self.root/'data/delivery-bindings').exists())
