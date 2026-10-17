import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from planning_runtime import invoke
from provider_state import pause,paused
class PlanningRecovery(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.scratch=self.root/'pm'
 def tearDown(self):self.tmp.cleanup()
 def test_connection_recovers_in_fresh_attempt(self):
  run=Mock(side_effect=[RuntimeError('Model connection failed'),'{"action":"no_work"}']);fresh=Mock()
  with patch('planning_runtime.time.sleep'):self.assertEqual(invoke(run,self.root,self.scratch,'prompt',fresh)['action'],'no_work')
  self.assertEqual(fresh.call_count,2);self.assertNotEqual(run.call_args_list[0].args[1],run.call_args_list[1].args[1])
 def test_invalid_json_retry_is_bounded(self):
  run=Mock(return_value='not json')
  with patch('planning_runtime.time.sleep'),self.assertRaises(json.JSONDecodeError):invoke(run,self.root,self.scratch,'prompt',Mock())
  self.assertEqual(run.call_count,3)
 def test_changed_decision_stops_retry_before_model(self):
  run=Mock(side_effect=RuntimeError('Model connection failed'));fresh=Mock(side_effect=[None,ValueError('Decision changed')])
  with patch('planning_runtime.time.sleep'),self.assertRaisesRegex(ValueError,'Decision changed'):invoke(run,self.root,self.scratch,'prompt',fresh)
  self.assertEqual(run.call_count,1)
 def test_no_work_or_business_verdict_never_retried(self):
  for text in ('{"action":"no_work"}','{"verdict":"blocked"}'):
   run=Mock(return_value=text);invoke(run,self.root,self.scratch,'prompt',Mock());self.assertEqual(run.call_count,1)
  for message in ('Outside scope','Provider unavailable/quota','Harness failed'):
   run=Mock(side_effect=RuntimeError(message))
   with self.assertRaises(RuntimeError):invoke(run,self.root,self.scratch,'prompt',Mock())
   self.assertEqual(run.call_count,1)
class ProviderRecovery(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_explicit_429_cooldown_expires_without_calling_provider(self):
  pause(self.root,'codex',429,'120',now=100)
  self.assertIsNotNone(paused(self.root,'codex',now=219));self.assertIsNone(paused(self.root,'codex',now=220));self.assertIsNone(paused(self.root,'codex',now=221))
  self.assertEqual(len(list((self.root/'data/provider-recovery').glob('*.json'))),1)
 def test_auth_billing_unknown_or_bad_retry_after_stay_paused(self):
  for status,header in ((401,'120'),(402,'120'),(403,'120'),(429,None),(429,'nonsense'),(429,'-1'),(429,'90000')):
   pause(self.root,'commandcode',status,header,now=100);self.assertIsNotNone(paused(self.root,'commandcode',now=1000000))
 def test_old_pause_without_timestamp_does_not_auto_clear(self):
  p=self.root/'data/quota-codex.json';p.parent.mkdir();p.write_text('{"http_status":429,"retry_after":"120"}')
  self.assertIsNotNone(paused(self.root,'codex',now=100000))
 def test_http_date_and_minimum_delay(self):
  v=pause(self.root,'codex',429,'Thu, 01 Jan 1970 00:03:20 GMT',now=100);self.assertEqual(v['resume_at'],200)
  v=pause(self.root,'codex',429,'1',now=100);self.assertEqual(v['resume_at'],160)
class IntegratedPlanning(unittest.TestCase):
 def test_transient_pm_failure_still_creates_exactly_one_binding(self):
  import test_state_autonomy,autonomy
  fixture=test_state_autonomy.SharedPlanning();fixture.setUp()
  try:
   fixture.setup_shared()
   with patch.object(autonomy,'ROOT',fixture.root),patch.object(autonomy,'Board',fixture.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':fixture.sha}),patch.object(autonomy,'run',side_effect=[RuntimeError('Model connection failed'),json.dumps(fixture.value)]) as run,patch('planning_runtime.time.sleep'):
    autonomy.tick('test');autonomy.tick('test');self.assertEqual(run.call_count,2)
   self.assertEqual(len(list((fixture.root/'data/delivery-bindings').glob('*.json'))),1)
   self.assertEqual(fixture.store.read('test')['intents'][fixture.intent]['status'],'scheduled')
  finally:fixture.tearDown()
