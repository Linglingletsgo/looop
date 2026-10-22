import importlib.util,json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict
spec=importlib.util.spec_from_file_location('state_sync_recovery',pathlib.Path(__file__).resolve().parents[1]/'bin/state-sync.py')
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
class RecoveredStateSync(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  self.store=Store(self.root);self.store.ensure('demo')
  self.packet={'title':'Existing outcome','requirements':['Preserve behavior'],'acceptance':['Verified outcome'],'allowed_paths':['app.py'],'baseline_sha':'a'*40}
  self.store.bind('demo','task',self.packet)
  self.store.transition('demo','task','verifying',import_existing=True)
  p=self.root/'data/delivery-bindings';p.mkdir()
  self.binding=p/'task.json'
  self.data={'lane':'demo','packet':{**self.packet,'execution_notes':'Prior Builder draft','clarification_receipt':'/archived/product-receipt'}}
  self.binding.write_text(json.dumps(self.data))
  p=self.root/'data/deliveries/task';p.mkdir(parents=True)
  (p/'state.json').write_text(json.dumps({'state':'merged','mainline_verified':'b'*40,'target_sha':'c'*40}))
 def test_merged_recovered_task_completes_and_reconcile_is_idempotent(self):
  sync.reconcile(self.root,self.store)
  first=self.store.read('demo')
  self.assertEqual(first['tasks']['task']['phase'],'completed')
  self.assertEqual(first['tasks']['task']['packet'],self.packet)
  sync.reconcile(self.root,self.store)
  self.assertEqual(self.store.read('demo')['revision'],first['revision'])
 def test_recovery_metadata_cannot_hide_actual_contract_changes(self):
  self.data['packet']['allowed_paths']=['outside.py'];self.binding.write_text(json.dumps(self.data))
  with self.assertRaises(Conflict):sync.reconcile(self.root,self.store)
  self.assertEqual(self.store.read('demo')['tasks']['task']['phase'],'verifying')
 def test_first_binding_never_stores_recovery_metadata_in_contract(self):
  self.store.bind('demo','new',self.data['packet'])
  self.assertEqual(self.store.read('demo')['tasks']['new']['packet'],self.packet)
  self.store.bind('demo','new',{**self.packet,'execution_notes':'Updated transport note'})
