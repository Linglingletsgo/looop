import json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import test_autonomy
import autonomy
from project_state import Store
class SharedPlanning(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def setup_shared(self):
  self.mandate['scope_approval']='pm';self.setup_tick();self.store=Store(self.root);self.store.ensure('test');(self.root/'data/project-state/enabled').touch()
  result=self.store.submit('test',{'type':'requirement','title':'Regression','body':'Test current stable behavior','human_confirmed':True},0,'r','human:test');self.intent=result['event']['data']['id'];self.value['intent_ids']=[self.intent]
 def board(self):
  class Board:
   def api(self,m,p,d=None):
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    if m=='POST':return {'id':'delivery-issue' if d['status']=='backlog' else 'pm-issue','identifier':'T-1'}
  return Board
 def test_pm_defines_contract_without_redundant_product_run(self):
  self.setup_shared()
  def model(*args,**kwargs):
   self.assertIn('Test current stable behavior',args[2]);return json.dumps(self.value)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=model) as run:
   autonomy.tick('test');self.assertEqual(run.call_count,1)
  doc=self.store.read('test');self.assertEqual(doc['intents'][self.intent]['status'],'scheduled');self.assertEqual(doc['tasks']['delivery-issue']['phase'],'queued')
 def test_concurrent_decision_invalidates_model_result(self):
  self.setup_shared()
  def model(*args,**kwargs):
   self.store.submit('test',{'type':'decision','title':'New direction','body':'Prioritize differently','human_confirmed':True},self.store.read('test')['revision'],'r2','human:test');return json.dumps(self.value)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=model):
   with self.assertRaisesRegex(ValueError,'changed during planning'):autonomy.tick('test')
  self.assertEqual(self.store.read('test')['tasks'],{});self.assertFalse((self.root/'data/delivery-bindings').exists())
 def test_revision_wakes_same_baseline_after_no_work(self):
  self.setup_shared()
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"Outside current envelope"}') as run:
   autonomy.tick('test');autonomy.tick('test');self.assertEqual(run.call_count,1)
   self.store.submit('test',{'type':'priority','intent_id':self.intent,'priority':'high','human_confirmed':True},self.store.read('test')['revision'],'priority','human:test')
   autonomy.tick('test');self.assertEqual(run.call_count,2)
 def test_confirmed_requirement_bypasses_discovery_budget(self):
  self.setup_shared()
  for n in range(2):
   f=self.root/'data/autonomy/test'/str(n)/'state.json';f.parent.mkdir(parents=True);f.write_text(json.dumps({'state':'no_work','day':autonomy.datetime.datetime.now(autonomy.datetime.timezone.utc).strftime('%Y-%m-%d'),'baseline_sha':'old'}))
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)) as run:
   autonomy.tick('test');self.assertEqual(run.call_count,1)
  receipt=[json.loads(f.read_text()) for f in (self.root/'data/autonomy/test').glob('*/state.json') if json.loads(f.read_text()).get('selected_intent')]
  self.assertEqual(receipt[0]['origin'],'human_confirmed')
 def test_no_work_defers_only_selected_then_next_requirement_runs(self):
  self.setup_shared()
  second=self.store.submit('test',{'type':'requirement','title':'Second','body':'Other task','human_confirmed':True,'priority':'low'},self.store.read('test')['revision'],'second','human:test')['event']['data']['id']
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"Requires production scope"}') as run:
   autonomy.tick('test');self.assertEqual(autonomy.next_intent(self.store.context('test'))['id'],second)
   autonomy.tick('test');autonomy.tick('test');self.assertEqual(run.call_count,2)
   # Deferred demands wait for clarification; other ready demands still advance.
   autonomy.tick('test');self.assertEqual(run.call_count,2)
  self.assertEqual(self.store.read('test')['intents'][self.intent]['planning_reason'],'Requires production scope')
 def test_selected_requirement_cannot_be_replaced_by_lower_priority(self):
  self.setup_shared()
  high=self.store.submit('test',{'type':'requirement','title':'Urgent','body':'Urgent task','human_confirmed':True,'priority':'urgent'},self.store.read('test')['revision'],'urgent','human:test')['event']['data']['id']
  self.assertEqual(autonomy.next_intent(self.store.context('test'))['id'],high)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)):
   with self.assertRaisesRegex(ValueError,'controller-selected'):autonomy.tick('test')
 def test_human_budget_exception_keeps_provider_gate(self):
  self.setup_shared();(self.root/'data/quota-codex.json').write_text('{}')
  self.assertIn('Provider paused',autonomy.slots(self.root,'test',self.mandate,human=True))
 def test_decisions_and_drafts_are_context_not_executable_demands(self):
  self.setup_shared();self.store.defer_intent('test',self.intent,'Needs clarification',1)
  for kind in ('decision','propose'):
   self.store.submit('test',{'type':kind,'title':'Context','body':'Context only','human_confirmed':True},self.store.read('test')['revision'],kind,'human:test')
  self.assertIsNone(autonomy.next_intent(self.store.context('test')))
 def test_human_attempts_do_not_consume_discovery_budget(self):
  self.setup_shared()
  for n in range(3):
   f=self.root/'data/autonomy/test'/str(n)/'state.json';f.parent.mkdir(parents=True);f.write_text(json.dumps({'state':'no_work','origin':'human_confirmed','day':autonomy.datetime.datetime.now(autonomy.datetime.timezone.utc).strftime('%Y-%m-%d')}))
  self.assertIsNone(autonomy.slots(self.root,'test',self.mandate))
 def test_human_budget_exception_keeps_active_and_mainline_gates(self):
  self.setup_shared();p=self.root/'data/delivery-bindings/task.json';p.parent.mkdir(parents=True);p.write_text('{"lane":"test"}')
  self.assertIn('dispatch',autonomy.slots(self.root,'test',self.mandate,human=True))
  state=self.root/'data/deliveries/task/state.json';state.parent.mkdir(parents=True);state.write_text('{"state":"merged"}')
  self.assertIn('verification',autonomy.slots(self.root,'test',self.mandate,human=True))
 def test_confirmation_makes_draft_executable_and_clears_stale_budget(self):
  self.setup_shared();self.store.defer_intent('test',self.intent,'Needs scope',1)
  draft=self.store.submit('test',{'type':'propose','title':'Draft','body':'Candidate'},self.store.read('test')['revision'],'draft','human:test')['event']['data']['id']
  self.store.selection('test','waiting','Daily autonomous discovery budget reached')
  self.store.submit('test',{'type':'confirm','intent_id':draft,'human_confirmed':True},self.store.read('test')['revision'],'confirm-draft','human:test')
  self.assertEqual(autonomy.next_intent(self.store.context('test'))['id'],draft)
  self.assertEqual(self.store.read('test')['phase'],'ready')
