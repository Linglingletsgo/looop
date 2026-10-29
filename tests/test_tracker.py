import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import process_owner
from jobs import Jobs
from tracker import LocalTracker,TrackerConfigError,open_tracker,resolve_tracker
import binding_requests
import test_autonomy


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
 def test_open_tracker_always_returns_the_local_tracker(self):
  for value in (None,{},{'tracker':'local'},{'tracker':'local','board_url':'http://127.0.0.1:3101'}):
   with self.subTest(value=value):
    settings=self.root/'data/local-settings.json'
    if settings.exists():settings.unlink()
    if value is not None:self.settings(value)
    tracker=open_tracker(self.root)
    self.assertIsInstance(tracker,LocalTracker);self.assertEqual(tracker.name,'local')
 def test_unsupported_tracker_setting_is_a_clear_startup_error(self):
  for value in ({'tracker':'paperclip'},{'tracker':''},{'tracker':'remote'}):
   with self.subTest(value=value):
    self.settings(value)
    with self.assertRaisesRegex(TrackerConfigError,'Unsupported tracker') as raised:open_tracker(self.root)
    self.assertEqual(raised.exception.path,self.root/'data/local-settings.json')
    self.assertIn('paperclip-last',str(raised.exception))
 def test_non_object_settings_file_is_a_clear_startup_error(self):
  for value in ([],None,5):
   with self.subTest(value=value):
    self.settings(value)
    with self.assertRaisesRegex(TrackerConfigError,'JSON object'):resolve_tracker(self.root)
  (self.root/'data/local-settings.json').write_text('{bad')
  with self.assertRaisesRegex(TrackerConfigError,'not valid JSON'):resolve_tracker(self.root)
 def test_settings_are_not_rewritten(self):
  self.settings({'tracker':'local','pm_skills':{'noncommercial':True}})
  before=(self.root/'data/local-settings.json').read_text()
  open_tracker(self.root);resolve_tracker(self.root)
  self.assertEqual((self.root/'data/local-settings.json').read_text(),before)

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
  self.assertEqual(result[0]['state'],'deferred');self.assertIn('predates the local job table',result[0]['reason'])
