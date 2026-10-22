import json,pathlib,sys,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import test_delivery,test_merging,delivery,runtime
from project_state import Store,Held
from merging import merge
class StatefulDelivery(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 harness=test_delivery.Delivery.harness
 execute=test_delivery.Delivery.execute
 def prepare(self):
  self.store=Store(self.root);self.store.ensure('test');(self.root/'data/project-state/enabled').touch()
  self.store.bind('test','task-one',self.packet)
  folder=self.root/'data/delivery-bindings';folder.mkdir();(folder/'task-one.json').write_text(json.dumps({'lane':'test','packet':self.packet}))
 def test_delivery_updates_durable_state_through_acceptance(self):
  self.prepare();self.assertEqual(self.execute()['state'],'validated')
  self.assertEqual(self.store.read('test')['tasks']['task-one']['phase'],'completed')
 def test_change_during_build_prevents_review_and_publication(self):
  self.prepare()
  def model(workspace,scratch,prompt,**kw):
   result=self.harness(workspace,scratch,prompt,**kw)
   if kw['role']=='builder':
    self.store.submit('test',{'type':'change','title':'Revise','body':'Change requirement','target_task':'task-one','human_confirmed':True},self.store.read('test')['revision'],'change','human:test')
   return result
  with self.assertRaises(Held):self.execute(harness=model)
  doc=self.store.read('test');self.assertEqual(doc['phase'],'waiting_decision');self.assertTrue(doc['tasks']['task-one']['holds'])
 def test_recovery_metadata_does_not_rebind_task_but_scope_changes_still_fail(self):
  from project_state import record_phase,Conflict
  self.prepare()
  p=self.root/'data/delivery-bindings/task-one.json';binding=json.loads(p.read_text())
  binding['packet'].update(execution_notes='Preserved draft',clarification_receipt='/archive/receipt')
  p.write_text(json.dumps(binding))
  record_phase(self.root,'task-one','queued',{'recovery_reason':'Product clarified fixture'})
  self.assertEqual(self.store.read('test')['tasks']['task-one']['packet'],self.packet)
  binding['packet']['allowed_paths']=['unrelated.py'];p.write_text(json.dumps(binding))
  with self.assertRaises(Conflict):record_phase(self.root,'task-one','queued',{})


class StatefulMerge(unittest.TestCase):
 setUp=test_merging.ProductMerge.setUp
 tearDown=test_merging.ProductMerge.tearDown
 def test_real_merge_entry_cannot_bypass_hold(self):
  store=Store(self.root);store.ensure('test');(self.root/'data/project-state/enabled').touch();self.binding['lane']='test';job=self.root.name
  store.bind('test',job,self.binding['packet']);store.transition('test',job,'waiting_merge',import_existing=True)
  store.submit('test',{'type':'change','title':'Revise','body':'Change requirement','target_task':job,'human_confirmed':True},store.read('test')['revision'],'change','human:test')
  with patch.object(runtime,'ROOT',self.root),patch('merging.subprocess.run') as cmd:
   with self.assertRaises(Held):merge(self.root,self.state,self.binding,self.policy,self.pr)
   cmd.assert_not_called()
