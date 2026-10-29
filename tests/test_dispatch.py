import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import dispatch
from jobs import Jobs
from project_state import Store
from tracker import LocalTracker
class FlakyJobs(Jobs):
 """Lost assignment response: the update is applied, then the call raises."""
 fail=False
 def update(self,*args,**kwargs):
  value=super().update(*args,**kwargs)
  if self.fail:self.fail=False;raise ConnectionError('Assignment applied but response lost')
  return value
class Dispatch(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.path=self.root/'data/delivery-bindings/job-task.json';self.path.parent.mkdir(parents=True)
  self.path.write_text(json.dumps({'lane':'test','packet':{'title':'Authorized'},'policy':{},'owner':'owner','publish':False}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}},'agents':{'test:delivery':'worker'}}))
  self.jobs=FlakyJobs(self.root);self.jobs.create('test','delivery','Task','Authorized',status='backlog',job_id='job-task');self.tracker=LocalTracker(self.jobs,self.root)
 def tearDown(self):self.tmp.cleanup()
 def job_row(self):return self.jobs.get('job-task')
 def test_binding_is_redispatched_once_without_new_issue_or_model(self):
  self.assertEqual(dispatch.reconcile(self.root,self.tracker)[0]['state'],'dispatched');dispatch.reconcile(self.root,self.tracker)
  self.assertEqual((self.job_row()['status'],self.job_row()['assignee']),('todo','test:delivery'))
 def test_lost_response_is_reconciled_without_duplicate_patch(self):
  self.jobs.fail=True;self.assertEqual(dispatch.reconcile(self.root,self.tracker)[0]['state'],'deferred')
  self.assertEqual(self.job_row()['status'],'todo');self.assertEqual(dispatch.reconcile(self.root,self.tracker),[])
 def test_existing_or_partial_execution_never_replays(self):
  folder=self.root/'data/deliveries/job-task';folder.mkdir(parents=True)
  self.assertEqual(dispatch.reconcile(self.root,self.tracker),[]);self.assertEqual(self.job_row()['status'],'backlog')
 def test_manual_cancellation_block_or_other_assignment_preserved(self):
  for status in ('cancelled','blocked','done','in_review'):
   self.jobs.update('job-task',status=status);dispatch.reconcile(self.root,self.tracker)
  self.jobs.update('job-task',status='todo',assignee='someone-else');dispatch.reconcile(self.root,self.tracker);self.assertEqual(self.job_row()['assignee'],'someone-else')
 def test_lane_without_local_job_is_deferred_after_the_valid_one(self):
  self.jobs.create('other','delivery','Elsewhere',status='backlog',job_id='job-other')
  control=self.root/'data/control.json';value=json.loads(control.read_text());value['projects']['other']={};control.write_text(json.dumps(value))
  (self.path.parent/'other.json').write_text(json.dumps({**json.loads(self.path.read_text()),'lane':'other'}))
  result=dispatch.reconcile(self.root,self.tracker);self.assertEqual([(r['state']) for r in result],['dispatched','deferred'])
  self.assertIn("'other'",result[1]['reason']);self.assertEqual(self.job_row()['assignee'],'test:delivery')
 def test_shared_state_restored_and_hold_respected(self):
  s=Store(self.root);s.ensure('test');(self.root/'data/project-state/enabled').touch()
  dispatch.reconcile(self.root,self.tracker);self.assertEqual(s.read('test')['tasks']['job-task']['phase'],'queued')
  s.submit('test',{'type':'change','title':'Change','body':'Hold execution','human_confirmed':True,'target_task':'job-task'},s.read('test')['revision'],'hold','human')
  self.jobs.update('job-task',status='backlog',assignee=None);result=dispatch.reconcile(self.root,self.tracker)
  self.assertEqual(result[0]['state'],'deferred');self.assertIsNone(self.job_row()['assignee'])
 def test_one_bad_binding_does_not_block_next(self):
  self.jobs.create('other','delivery','Elsewhere',status='backlog',job_id='job-other')
  control=self.root/'data/control.json';value=json.loads(control.read_text());value['projects']['other']={};control.write_text(json.dumps(value))
  (self.path.parent/'aaa.json').write_text('{broken');(self.path.parent/'other.json').write_text(json.dumps({**json.loads(self.path.read_text()),'lane':'other'}))
  result=dispatch.reconcile(self.root,self.tracker);self.assertEqual([r['state'] for r in result],['deferred','dispatched','deferred'])
class Maintenance(unittest.TestCase):
 def test_dynamic_lanes_and_step_failure_isolation(self):
  path=pathlib.Path(__file__).resolve().parents[1]/'bin/maintenance.py';spec=importlib.util.spec_from_file_location('maintenance',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'data/autonomy-policies').mkdir(parents=True)
   (root/'data/autonomy-policies/alpha.json').write_text('{}')
   (root/'data/control.json').write_text(json.dumps({'projects':{'alpha':{'id':'a'},'ds1':{'execution_enabled':False}}}))
   commands=m.commands(root);self.assertEqual(commands[-1][-1],'alpha');self.assertFalse(any('gtp' in x for x in commands))
   with patch.object(m.subprocess,'run',side_effect=[OSError('Unavailable')]+[type('R',(),{'returncode':0})()]*(len(commands)-1)) as run:
    self.assertEqual(m.main(root),1);self.assertEqual(run.call_count,len(commands))
class PlannerDispatch(unittest.TestCase):
 setUp=Dispatch.setUp
 tearDown=Dispatch.tearDown
 job_row=Dispatch.job_row
 def test_assignment_response_failure_does_not_leave_planner_permanently_blocked(self):
  folder=self.root/'data/autonomy/test/attempt';folder.mkdir(parents=True);(folder/'state.json').write_text('{"state":"blocked","error":"assignment response lost"}')
  d=json.loads(self.path.read_text());d['authorization']={'proposal':str(folder)};self.path.write_text(json.dumps(d))
  self.jobs.fail=True;dispatch.reconcile(self.root,self.tracker);dispatch.reconcile(self.root,self.tracker)
  self.assertEqual(self.job_row()['status'],'todo');receipt=json.loads((folder/'state.json').read_text());self.assertEqual(receipt['state'],'queued');self.assertTrue(receipt['dispatch_reconciled'])
