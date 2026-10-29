"""P1c: delivery path through the local job tracker."""
import importlib.util,json,os,pathlib,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import process_owner
import test_delivery
import test_autonomy
from jobs import Jobs
from tracker import LocalTracker

BINDING_COMMENT='没有操作员绑定的执行 Packet。任务描述不作为执行授权；请通过 delivery-control.py submit 绑定。'

def load(name):
 path=pathlib.Path(__file__).resolve().parents[1]/'bin'/(name+'.py')
 spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

worker=load('delivery-worker');control=load('delivery-control');launcher=load('launch_loops')

class LocalWorker(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def prepare(self,status='todo',binding=True):
  (self.root/'data').mkdir(exist_ok=True)
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':'project'}},'agents':{}}))
  jobs=Jobs(self.root);job=jobs.create('test','delivery','Task',status=status,assignee='test:delivery')
  if binding:
   path=self.root/'data/delivery-bindings'/(job['id']+'.json');path.parent.mkdir(parents=True,exist_ok=True)
   path.write_text(json.dumps({'lane':'test','packet':self.packet,'policy':self.policy,'owner':'owner','publish':False}))
  return jobs,job
 def run_worker(self):
  with patch.object(worker,'ROOT',self.root):worker.heartbeat('test')
 def test_claim_release_and_terminal_status(self):
  jobs,job=self.prepare()
  with patch.object(worker,'execute',return_value={'state':'validated'}) as execute:
   self.run_worker();execute.assert_called_once()
  final=jobs.get(job['id']);self.assertEqual((final['status'],final['assignee']),('done','owner'))
  self.assertIsNone(jobs.holder(job['id']))
 def test_release_and_block_on_failure(self):
  jobs,job=self.prepare()
  with patch.object(worker,'execute',side_effect=ValueError('Provider unavailable')):
   with self.assertRaisesRegex(ValueError,'Provider'):self.run_worker()
  self.assertEqual(jobs.get(job['id'])['status'],'blocked');self.assertIsNone(jobs.holder(job['id']))
  self.assertIn('provider_paused',jobs.events(job['id'])[-1]['body'])
 def test_job_leased_by_another_live_identity_is_skipped(self):
  jobs,job=self.prepare();other={**process_owner.identity(),'boot_id':'other-boot','pid':1}
  with jobs.connection() as c:c.execute('UPDATE jobs SET lease_owner=?,lease_until=? WHERE id=?',(json.dumps(other),time.time()+600,job['id']))
  with patch('process_owner.alive',return_value=True),patch.object(worker,'execute') as execute:
   self.run_worker();execute.assert_not_called()
  self.assertEqual(jobs.get(job['id'])['status'],'todo')
 def test_local_mode_needs_no_agent_environment_or_binding(self):
  jobs,job=self.prepare(binding=False)
  with patch.dict(os.environ,{},clear=True):
   self.run_worker()
  self.assertEqual(jobs.get(job['id'])['status'],'blocked');self.assertEqual(jobs.events(job['id'])[-1]['body'],BINDING_COMMENT)
  self.assertIsNone(jobs.holder(job['id']))

class Launch(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  (self.root/'data').mkdir();(self.root/'logs').mkdir()
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':'project'}}}))
  (self.root/'data/delivery-policies').mkdir();(self.root/'data/delivery-policies/test.json').write_text('{}')
  self.jobs=Jobs(self.root)
 def settings(self,value):(self.root/'data/local-settings.json').write_text(json.dumps(value))
 def launches(self,run):
  return [call.args[0] for call in run.call_args_list if call.args[0][:2]==['tmux','new-session']]
 def test_local_mode_starts_exactly_one_delivery_session(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  self.assertTrue((self.root/'data/jobs.sqlite').exists())
  created=set()
  def run(argv,*a,**kw):
   if argv[:2]==['tmux','has-session']:return type('R',(),{'returncode':0 if argv[3] in created else 1})()
   created.add(argv[4]);return type('R',(),{'returncode':0})()
  with patch('subprocess.run',side_effect=run) as mock:
   launcher.launch(self.root);launcher.launch(self.root)
  sessions=self.launches(mock);self.assertEqual(len(sessions),1)
  argv=sessions[0];self.assertEqual(argv[4],'looop-delivery-test');self.assertIn('/bin/delivery-worker.py',argv[7]);self.assertIn('logs/delivery-test.log',argv[7])
 def test_no_session_without_pending_job(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='done',assignee='test:delivery')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_unleased_in_progress_job_is_resumed_but_live_lease_is_not(self):
  self.settings({'tracker':'local'});job=self.jobs.create('test','delivery','Task',status='in_progress',assignee='test:delivery')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(len(self.launches(run)),1)
  self.assertTrue(self.jobs.claim(job['id'],process_owner.identity(),60))
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_no_session_without_delivery_policy(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  (self.root/'data/delivery-policies/test.json').unlink()
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_existing_session_or_live_lease_suppresses_launch(self):
  self.settings({'tracker':'local'});job=self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':0})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
  self.jobs.claim(job['id'],process_owner.identity(),600)
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_no_job_table_creates_no_session_and_no_database(self):
  self.settings({'tracker':'local'});self.jobs.path.unlink();self.assertFalse((self.root/'data/jobs.sqlite').exists())
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
  self.assertFalse((self.root/'data/jobs.sqlite').exists())
 def test_delivery_continues_while_planning_is_paused(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  (self.root/'data/autonomy-policies').mkdir();(self.root/'data/autonomy-policies/test.json').write_text('{}')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root)
  self.assertEqual([c[4] for c in self.launches(run)],['looop-delivery-test'])

class Control(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def test_configure_local_mode_creates_no_agent(self):
  (self.root/'data').mkdir(exist_ok=True);(self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  policy=self.root/'policy.json';policy.write_text(json.dumps(self.policy))
  config={'projects':{'test':{'repo':str(self.repo),'profile':'profile'}},'agents':{}}
  registry={'roles':{name:{} for name in ('product','builder','reviewer','acceptance')},'workflow':None,'project_roles':{}}
  with patch.object(control,'ROOT',self.root),patch.object(control,'config',return_value=config),patch.object(control,'validate_profile'),patch.object(control,'resolve',return_value=registry),patch.object(control,'fingerprints',return_value={}):
   control.configure('test',str(policy))
  saved=json.loads((self.root/'data/control.json').read_text())
  self.assertNotIn('test:delivery',saved.get('agents',{}))
  self.assertTrue((self.root/'data/delivery-policies/test.json').exists())

class EndToEnd(unittest.TestCase):
 """planning tick -> binding -> dispatch -> worker -> job done, all local."""
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_local_loop_runs_end_to_end(self):
  import autonomy,test_autonomy,dispatch
  self.mandate['scope_approval']='pm'
  self.setup_tick()
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)) as model:
   autonomy.tick('test')
  self.assertEqual(model.call_count,1)
  jobs=Jobs(self.root);delivery=jobs.list(lane='test',kind='delivery')
  self.assertEqual(len(delivery),1);self.assertEqual((delivery[0]['status'],delivery[0]['assignee']),('todo','test:delivery'))
  tracker=LocalTracker(jobs,self.root)
  self.assertEqual(dispatch.reconcile(self.root,tracker),[])
  with patch.object(worker,'ROOT',self.root),patch.object(worker,'execute',return_value={'state':'validated'}) as execute:
   worker.heartbeat('test')
  execute.assert_called_once()
  self.assertEqual((jobs.get(delivery[0]['id'])['status'],jobs.get(delivery[0]['id'])['assignee']),('done','owner'))
  receipts=[json.loads(p.read_text()) for p in (self.root/'data/autonomy/test').glob('*/state.json')]
  receipt=next(r for r in receipts if r.get('delivery_issue'))
  self.assertEqual((receipt['state'],receipt['delivery_issue']),('queued',delivery[0]['id']))
