import importlib.util,json,os,pathlib,signal,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import test_delivery
from jobs import Jobs
from tracker import LocalTracker
from process_owner import identity,alive
from recovery import prepare
spec=importlib.util.spec_from_file_location('restart_recovery',pathlib.Path(__file__).resolve().parents[1]/'bin/restart-recovery.py');restart=importlib.util.module_from_spec(spec);spec.loader.exec_module(restart)
class Restart(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 harness=test_delivery.Delivery.harness
 execute=test_delivery.Delivery.execute
 def tracker(self,status='in_progress'):
  jobs=Jobs(self.root);jobs.create('test','delivery','Task','Test',status=status,assignee='test:delivery',job_id='task-one');return LocalTracker(jobs,self.root)
 def binding(self):
  p=self.root/'data/delivery-bindings/task-one.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'lane':'test','packet':self.packet,'policy':self.policy,'publish':False,'owner':'owner'}));return p
 def test_real_killed_worker_recovers_and_rechecks_without_publication(self):
  binding=self.binding();script=self.root/'worker.py';binpath=pathlib.Path(__file__).resolve().parents[1]/'bin'
  script.write_text('import sys,json,pathlib,time\nsys.path.insert(0,'+repr(str(binpath))+')\nimport delivery\nfrom unittest.mock import patch\nroot=pathlib.Path('+repr(str(self.root))+')\nd=json.loads((root/"data/delivery-bindings/task-one.json").read_text())\ndef run(*a,**kw):\n if kw["role"]=="builder":\n  (root/"worker-ready").touch()\n  time.sleep(60)\n return json.dumps({"verdict":"approved","findings":[]})\nwith patch.object(delivery,"ROOT",root),patch.object(delivery,"run",side_effect=run):delivery.execute(d["packet"],d["policy"],"task-one",publish=False)\n')
  proc=subprocess.Popen([sys.executable,str(script)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   until=time.monotonic()+10
   while not (self.root/'worker-ready').exists() and time.monotonic()<until and proc.poll() is None:time.sleep(.05)
   self.assertTrue((self.root/'worker-ready').exists())
   receipt=self.root/'data/deliveries/task-one/state.json';owner=json.loads(receipt.read_text())['owner'];self.assertTrue(alive(owner))
   with self.assertRaisesRegex(ValueError,'still running'):prepare(self.root,'task-one','test',interrupted=True)
   proc.kill();proc.wait();self.assertFalse(alive(owner))
   archive=prepare(self.root,'task-one','test killed worker',interrupted=True)
   self.assertTrue((archive/'state.json').exists());self.assertEqual(json.loads(binding.read_text())['interruption_retries'],1)
   result=self.execute();self.assertEqual(result['state'],'validated');self.assertNotIn('pr_url',result)
   self.assertTrue(result['acceptance']);self.assertTrue(result['reviews'])
  finally:
   if proc.poll() is None:proc.kill();proc.wait()
 def test_unknown_identity_and_publication_boundary_never_restart(self):
  self.binding();p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True)
  p.write_text('{"state":"building"}')
  with self.assertRaisesRegex(ValueError,'identity unknown'):prepare(self.root,'task-one','test',interrupted=True)
  p.write_text(json.dumps({'state':'pr_ready','owner':identity()}))
  with self.assertRaisesRegex(ValueError,'Stage'):prepare(self.root,'task-one','test',interrupted=True)
 def test_pid_reuse_or_new_boot_is_not_same_worker(self):
  owner=identity();self.assertTrue(alive(owner));self.assertFalse(alive({**owner,'boot_id':'prior-boot'}));self.assertFalse(alive({**owner,'start_ticks':'0'}));self.assertIsNone(alive(None))
 def test_automatic_reconcile_respects_holds_and_manual_status(self):
  self.binding();p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'building','owner':{**identity(),'boot_id':'prior-boot'}}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}}}));tracker=self.tracker('cancelled')
  with patch.object(restart,'prepare') as prepare_mock:restart.reconcile(self.root,tracker);prepare_mock.assert_not_called()
 def test_restart_limit_is_durable(self):
  b=self.binding();d=json.loads(b.read_text());d['interruption_retries']=2;b.write_text(json.dumps(d))
  p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'building','owner':{**identity(),'boot_id':'old'}}))
  with self.assertRaisesRegex(ValueError,'budget'):prepare(self.root,'task-one','test',interrupted=True)
 def test_automatic_reconcile_requeues_dead_worker_after_new_boot(self):
  self.binding();p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'building','owner':{**identity(),'boot_id':'prior-boot'}}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}}}));tracker=self.tracker()
  result=restart.reconcile(self.root,tracker);self.assertEqual(result[0]['state'],'requeued');self.assertEqual(tracker.jobs.get('task-one')['status'],'todo');self.assertFalse(p.exists())
  self.assertEqual(restart.reconcile(self.root,tracker),[])
 def test_unresolved_change_hold_prevents_orphan_requeue(self):
  from project_state import Store
  self.binding();p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'building','owner':{**identity(),'boot_id':'prior-boot'}}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}}}))
  s=Store(self.root);s.ensure('test');(self.root/'data/project-state/enabled').touch();s.bind('test','task-one',self.packet);s.transition('test','task-one','building')
  s.submit('test',{'type':'change','title':'Change','body':'Hold','target_task':'task-one','human_confirmed':True},s.read('test')['revision'],'hold','human')
  with patch.object(restart,'prepare') as prepare_mock:
   r=restart.reconcile(self.root,self.tracker());self.assertEqual(r[0]['state'],'deferred');prepare_mock.assert_not_called()
 def test_pr_ready_requires_attention_without_publication_replay(self):
  self.binding();p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'pr_ready','owner':{**identity(),'boot_id':'prior-boot'}}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}}}))
  with patch.object(restart,'prepare') as prepare_mock:
   self.assertEqual(restart.reconcile(self.root,self.tracker())[0]['state'],'needs_attention');prepare_mock.assert_not_called()
 def test_heartbeat_does_not_turn_interrupted_run_into_manual_block(self):
  self.binding();p=self.root/'data/deliveries/task-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'building','owner':{**identity(),'boot_id':'prior-boot'}}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}}}));self.tracker()
  spec=importlib.util.spec_from_file_location('delivery_worker',pathlib.Path(__file__).resolve().parents[1]/'bin/delivery-worker.py');worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
  with patch.object(worker,'ROOT',self.root),patch.dict(os.environ,{}),patch.object(worker,'execute') as execute:
   worker.heartbeat('test');execute.assert_not_called()
