import pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict
from autonomy import planning_state
class DecisionSupersession(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.store.ensure('demo')
  self.old=self.store.submit('demo',{'type':'decision','title':'Pause and keep scope','body':'Pause selection; no production changes.','human_confirmed':True},0,'old','human')['event']['data']['id']
 def tearDown(self):self.temp.cleanup()
 def command(self):return {'type':'supersede_decision','intent_id':self.old,'title':'Keep product scope','body':'Existing direction only; no production changes. Scheduling follows loop_control.','human_confirmed':True}
 def test_supersession_preserves_audit_and_removes_stale_constraint_from_context(self):
  result=self.store.submit('demo',self.command(),1,'replace','human');new=result['event']['data']['id'];doc=self.store.read('demo')
  self.assertEqual(doc['intents'][self.old]['status'],'superseded');self.assertEqual(doc['intents'][self.old]['superseded_by'],new);self.assertEqual(doc['intents'][new]['supersedes'],self.old);self.assertEqual(doc['planning_revision'],2)
  self.assertNotIn(self.old,self.store.context('demo')['intents']);self.assertIn(new,self.store.context('demo')['intents']);self.assertEqual(len(self.store.events('demo')),2)
  self.assertTrue(self.store.submit('demo',self.command(),1,'replace','human')['replayed'])
 def test_requires_human_confirmation_and_fresh_revision(self):
  cmd=self.command();cmd['human_confirmed']=False
  with self.assertRaises(ValueError):self.store.submit('demo',cmd,1,'bad','human')
  with self.assertRaises(Conflict):self.store.submit('demo',self.command(),0,'stale','human')
  self.assertEqual(self.store.read('demo')['intents'][self.old]['status'],'ready')
 def test_loop_activation_does_not_remove_effective_product_constraints(self):
  context=planning_state(self.store.context('demo'),{'mode':'once','run_id':'explicit-request'})
  self.assertEqual(context['execution_control']['mode'],'once');self.assertIn('no production changes',context['intents'][self.old]['body']);self.assertNotIn('tasks',context)
 def test_replacement_is_not_an_executable_requirement(self):
  from autonomy import next_intent
  self.store.submit('demo',self.command(),1,'replace','human');self.assertIsNone(next_intent(self.store.context('demo')))
