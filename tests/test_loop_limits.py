import datetime,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import test_loop_controls
from project_state import Conflict,Store
from loop_control import view,set_limits
from autonomy import slots

class Limits(unittest.TestCase):
 setUp=test_loop_controls.LoopControls.setUp
 tearDown=test_loop_controls.LoopControls.tearDown
 write=test_loop_controls.LoopControls.write
 def test_default_is_unlimited_despite_legacy_policy(self):
  self.write('data/autonomy-policies/demo.json',{'enabled':False,'max_proposals_per_day':2})
  self.assertIsNone(view(self.root,'demo')['limits']['max_proposals_per_day'])
 def test_custom_limit_persists_without_changing_mode(self):
  set_limits(self.root,'demo',3,0,'limit');self.assertEqual(view(self.root,'demo')['limits']['max_proposals_per_day'],3);self.assertEqual(view(self.root,'demo')['mode'],'paused')
  set_limits(self.root,'demo',None,1,'unlimited');self.assertIsNone(Store(self.root).context('demo')['loop_limits']['max_proposals_per_day'])
 def test_limits_are_revision_checked_and_idempotent(self):
  set_limits(self.root,'demo',5,0,'limit');self.assertTrue(set_limits(self.root,'demo',5,0,'limit')['replayed'])
  with self.assertRaises(Conflict):set_limits(self.root,'demo',None,0,'stale')
 def test_invalid_values_rejected(self):
  for v in (0,-1,True,1.5,'2',9007199254740992):
   with self.subTest(value=v),self.assertRaises(ValueError):set_limits(self.root,'demo',v,0,'bad')
 def test_budget_unlimited_custom_and_human_requirement(self):
  day=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
  for i in range(3):self.write('data/autonomy/demo/job'+str(i)+'/state.json',{'state':'no_work','day':day})
  self.assertIsNone(slots(self.root,'demo',{}));self.assertIn('budget',slots(self.root,'demo',{'max_proposals_per_day':2}));self.assertIsNone(slots(self.root,'demo',{'max_proposals_per_day':2},human=True))
 def test_removing_daily_limit_keeps_provider_and_existing_work_gates(self):
  self.write('data/quota-codex.json',{'status':'paused','http_status':401})
  self.assertIn('Provider paused',slots(self.root,'demo',{}))
  (self.root/'data/quota-codex.json').unlink();self.write('data/delivery-bindings/task.json',{'lane':'demo'});self.assertIn('Bound task',slots(self.root,'demo',{}))
 def test_limit_update_clears_stale_budget_reason(self):
  self.store.selection('demo','waiting','Daily autonomous discovery budget reached');set_limits(self.root,'demo',None,1,'unlimited');self.assertNotIn('budget',Store(self.root).read('demo')['next_action'])
