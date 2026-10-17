import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import dispatch
from project_state import Store
class Dispatch(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.path=self.root/'data/delivery-bindings/job.json';self.path.parent.mkdir(parents=True)
  self.path.write_text(json.dumps({'lane':'test','packet':{'title':'Authorized'},'policy':{},'owner':'owner','publish':False}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':'project'}},'agents':{'test:delivery':'worker'}}))
  self.issue={'id':'job','projectId':'project','status':'backlog','assigneeAgentId':None};self.calls=[];parent=self
  class Board:
   fail=False
   def api(self,m,p,d=None):
    if m=='GET':return dict(parent.issue)
    parent.calls.append(d);parent.issue.update(d)
    if self.fail:self.fail=False;raise ConnectionError('Assignment applied but response lost')
  self.board=Board()
 def tearDown(self):self.tmp.cleanup()
 def test_binding_is_redispatched_once_without_new_issue_or_model(self):
  self.assertEqual(dispatch.reconcile(self.root,self.board)[0]['state'],'dispatched');dispatch.reconcile(self.root,self.board)
  self.assertEqual(len(self.calls),1);self.assertIsNone(self.issue['assigneeUserId'])
 def test_lost_response_is_reconciled_without_duplicate_patch(self):
  self.board.fail=True;self.assertEqual(dispatch.reconcile(self.root,self.board)[0]['state'],'deferred')
  self.assertEqual(dispatch.reconcile(self.root,self.board),[]);self.assertEqual(len(self.calls),1)
 def test_existing_or_partial_execution_never_replays(self):
  folder=self.root/'data/deliveries/job';folder.mkdir(parents=True)
  self.assertEqual(dispatch.reconcile(self.root,self.board),[]);self.assertEqual(self.calls,[])
 def test_manual_cancellation_block_or_other_assignment_preserved(self):
  for status in ('cancelled','blocked','done','in_review'):
   self.issue['status']=status;dispatch.reconcile(self.root,self.board)
  self.issue.update(status='todo',assigneeAgentId='someone-else');dispatch.reconcile(self.root,self.board);self.assertEqual(self.calls,[])
 def test_project_mismatch_is_deferred(self):
  self.issue['projectId']='other';self.assertEqual(dispatch.reconcile(self.root,self.board)[0]['state'],'deferred');self.assertEqual(self.calls,[])
 def test_shared_state_restored_and_hold_respected(self):
  s=Store(self.root);s.ensure('test');(self.root/'data/project-state/enabled').touch()
  dispatch.reconcile(self.root,self.board);self.assertEqual(s.read('test')['tasks']['job']['phase'],'queued')
  s.submit('test',{'type':'change','title':'Change','body':'Hold execution','human_confirmed':True,'target_task':'job'},s.read('test')['revision'],'hold','human')
  self.issue.update(status='backlog',assigneeAgentId=None);self.calls.clear();result=dispatch.reconcile(self.root,self.board)
  self.assertEqual(result[0]['state'],'deferred');self.assertEqual(self.calls,[])
 def test_one_bad_binding_does_not_block_next(self):
  (self.path.parent/'aaa.json').write_text('{broken')
  result=dispatch.reconcile(self.root,self.board);self.assertEqual([r['state'] for r in result],['deferred','dispatched'])
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
 def test_assignment_response_failure_does_not_leave_planner_permanently_blocked(self):
  folder=self.root/'data/autonomy/test/attempt';folder.mkdir(parents=True);(folder/'state.json').write_text('{"state":"blocked","error":"assignment response lost"}')
  d=json.loads(self.path.read_text());d['authorization']={'proposal':str(folder)};self.path.write_text(json.dumps(d))
  self.board.fail=True;dispatch.reconcile(self.root,self.board);dispatch.reconcile(self.root,self.board)
  self.assertEqual(len(self.calls),1);receipt=json.loads((folder/'state.json').read_text());self.assertEqual(receipt['state'],'queued');self.assertTrue(receipt['dispatch_reconciled'])
