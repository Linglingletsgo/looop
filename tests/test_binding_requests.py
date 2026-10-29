import json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import test_state_autonomy
import binding_requests as requests
from jobs import Jobs
from tracker import LocalTracker
class Binding(unittest.TestCase):
 setUp=test_state_autonomy.SharedPlanning.setUp
 tearDown=test_state_autonomy.SharedPlanning.tearDown
 setup_tick=test_state_autonomy.SharedPlanning.setup_tick
 setup_shared=test_state_autonomy.SharedPlanning.setup_shared
 def setup_request(self):
  self.setup_shared();self.binding={'lane':'test','intent_ids':[self.intent],'packet':{**self.value['packet'],'baseline_sha':self.sha},'policy':self.policy,'publish':False,'owner':'owner'}
  self.folder=self.root/'data/autonomy/test/attempt';self.job_table=Jobs(self.root);self.tracker=LocalTracker(self.job_table,self.root);self.lose=True
  original=LocalTracker.create
  def create(__self,lane,kind,title,status,description='',assignee=None,job_id=None,company=None):
   job=original(__self,lane,kind,title,status,description,assignee,job_id)
   if self.lose:self.lose=False;raise ConnectionError('Response lost after job creation')
   return job
  self.create_patch=patch.object(LocalTracker,'create',autospec=True,side_effect=create);self.create_patch.start();self.addCleanup(self.create_patch.stop)
 def begin(self):return requests.create(self.root,self.tracker,self.folder,self.binding,None,{'status':'backlog','title':'Task'},1)
 def rows(self):return self.job_table.list(lane='test')
 def record(self):return json.loads((self.folder/'binding-request.json').read_text())
 def test_local_creation_succeeded_response_lost_reconciles_once(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  self.assertEqual(len(self.rows()),1)
  self.assertEqual(requests.reconcile(self.root,self.tracker)[0]['state'],'bound')
  self.assertEqual(requests.reconcile(self.root,self.tracker),[]);self.assertEqual(len(self.rows()),1)
  job=self.rows()[0];self.assertEqual(self.store.read('test')['intents'][self.intent]['status'],'scheduled')
  self.assertTrue((self.root/'data/delivery-bindings'/(job['id']+'.json')).exists())
 def test_changed_job_requires_disposition_and_is_never_rebound(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  job_id=self.record()['job_id'];self.job_table.update(job_id,status='in_progress')
  result=requests.reconcile(self.root,self.tracker)
  self.assertEqual(result[0]['state'],'deferred');self.assertIn('Remote issue changed',result[0]['reason'])
  self.assertFalse((self.root/'data/delivery-bindings'/(job_id+'.json')).exists())
 def test_manual_cancellation_and_changed_policy_preserved(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  job_id=self.record()['job_id'];self.job_table.update(job_id,status='cancelled')
  self.assertEqual(requests.reconcile(self.root,self.tracker)[0]['state'],'deferred')
  self.job_table.update(job_id,status='backlog');(self.root/'data/delivery-policies/test.json').write_text('{}')
  self.assertEqual(requests.reconcile(self.root,self.tracker)[0]['state'],'deferred');self.assertFalse((self.root/'data/delivery-bindings'/(job_id+'.json')).exists())
 def test_new_decision_rejects_stale_unbound_packet(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  self.store.submit('test',{'type':'decision','title':'Changed','body':'Changed intent','human_confirmed':True},self.store.read('test')['revision'],'changed','human')
  job_id=self.record()['job_id']
  self.assertEqual(requests.reconcile(self.root,self.tracker)[0]['state'],'deferred');self.assertFalse((self.root/'data/delivery-bindings'/(job_id+'.json')).exists())
 def test_shared_bind_saved_but_file_write_interrupted_can_finish(self):
  self.setup_request();self.lose=False
  original=requests.save
  def save(path,value):
   if path.parent.name=='delivery-bindings':raise OSError('Disk interrupted')
   return original(path,value)
  with patch.object(requests,'save',side_effect=save),self.assertRaises(OSError):self.begin()
  self.assertEqual(len(self.store.read('test')['tasks']),1);self.assertEqual(requests.reconcile(self.root,self.tracker)[0]['state'],'bound');self.assertEqual(len(self.rows()),1)
 def test_final_journal_write_lost_after_binding_does_not_rebind(self):
  self.setup_request();self.lose=False;original=requests.save
  def save(path,value):
   if path.name=='binding-request.json' and value['state']=='bound':raise OSError('Final journal update lost')
   return original(path,value)
  with patch.object(requests,'save',side_effect=save),self.assertRaises(OSError):self.begin()
  self.assertEqual(requests.reconcile(self.root,self.tracker)[0]['state'],'bound');self.assertEqual(len(self.rows()),1)
 def test_lost_create_response_full_planner_to_dispatch_cycle(self):
  import autonomy,dispatch
  self.setup_request();self.create_patch.stop();self.lose=False
  control=self.root/'data/control.json';value=json.loads(control.read_text());value['projects']['test']['repo']=str(self.repo);control.write_text(json.dumps(value))
  jobs=Jobs(self.root);self.create_patch.stop()
  def create(__self,lane,kind,title,status,description='',assignee=None,job_id=None,company=None):
   if kind=='delivery' and not getattr(self,'lost',False):self.lost=True;raise ConnectionError('Create response lost')
   return __self.jobs.create(lane,kind,title,description=description,status=status,assignee=assignee,job_id=job_id)
  tracker=LocalTracker(jobs,self.root)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'open_tracker',return_value=tracker),patch.object(LocalTracker,'create',autospec=True,side_effect=create),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)) as model:
   with self.assertRaises(ConnectionError):autonomy.tick('test')
   dispatched=requests.reconcile(self.root,tracker);self.assertEqual(dispatched,[{'job':dispatched[0]['job'],'state':'bound'}],dispatched)
   dispatch.reconcile(self.root,tracker)
   autonomy.tick('test');self.assertEqual(model.call_count,1)
  delivery=[job for job in jobs.list(lane='test') if job['kind']=='delivery'];self.assertEqual(len(delivery),1);self.assertEqual(delivery[0]['status'],'todo')
  self.assertEqual(len(list((self.root/'data/delivery-bindings').glob('*.json'))),1)
  state=json.loads(next((self.root/'data/autonomy/test').glob('*/state.json')).read_text());self.assertEqual(state['state'],'queued')
 def test_identical_operator_submission_uses_same_journal(self):
  import importlib.util
  self.setup_request();self.lose=False
  path=pathlib.Path(__file__).resolve().parents[1]/'bin/delivery-control.py';spec=importlib.util.spec_from_file_location('control_binding_test',path);control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
  cfg=json.loads((self.root/'data/control.json').read_text());packet=self.root/'operator-packet.json';packet.write_text(json.dumps(self.binding['packet']))
  with patch.object(control,'ROOT',self.root),patch.object(control,'config',return_value=cfg),patch.object(control,'validate_profile'):
   control.submit('test',str(packet),False);control.submit('test',str(packet),False)
  self.assertEqual(len(self.rows()),1)
