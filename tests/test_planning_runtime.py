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
  with patch('planning_runtime.time.sleep'),self.assertRaises(ValueError):invoke(run,self.root,self.scratch,'prompt',Mock())
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
 def test_schema_correction_is_bounded_and_keeps_separate_receipts(self):
  def validate(value):
   if not isinstance(value,dict) or not value.get('question'):raise ValueError('question required')
  run=Mock(side_effect=['{"packet":{}}','{"question":"Verify export?"}'])
  value=invoke(run,self.root,self.scratch,'schema',Mock(),validate=validate)
  self.assertEqual(value['question'],'Verify export?')
  self.assertIn('OUTPUT CORRECTION',run.call_args.args[2]);self.assertNotEqual(run.call_args_list[0].args[1],run.call_args_list[1].args[1])
  self.assertEqual(json.loads((self.root/'pm-recovery.json').read_text())['state'],'recovered')
  run=Mock(return_value='[]')
  with self.assertRaisesRegex(ValueError,'JSON object'):invoke(run,self.root,self.scratch,'schema',Mock(),validate=validate)
  self.assertEqual(run.call_count,3);self.assertEqual(json.loads((self.root/'pm-recovery.json').read_text())['category'],'invalid_json')
 def test_format_correction_carries_prior_evidence(self):
  original={'status':'supported','question':'Original discovery','sources':[{'path':'spec.md:7','quote':'Previously read exact source evidence.'}]}
  def validate(value):
   if value['sources'][0]['path'].endswith(':7'):raise ValueError('Remove line-number suffix')
  corrected=json.loads(json.dumps(original));corrected['sources'][0]['path']='spec.md'
  run=Mock(side_effect=[json.dumps(original),json.dumps(corrected)])
  value=invoke(run,self.root,self.scratch,'Research phase',Mock(),validate=validate)
  prompt=run.call_args.args[2];self.assertIn('Previously read exact source evidence.',prompt);self.assertIn('spec.md:7',prompt);self.assertIn('Do not discard gathered evidence',prompt);self.assertEqual(value['status'],'supported')
 def test_scope_change_after_result_prevents_correction(self):
  run=Mock(return_value='{"packet":{}}');fresh=Mock(side_effect=[None,ValueError('Decision changed')]);validate=Mock(side_effect=ValueError('question required'))
  with self.assertRaisesRegex(ValueError,'Decision changed'):invoke(run,self.root,self.scratch,'schema',fresh,validate=validate)
  self.assertEqual(run.call_count,1);validate.assert_not_called()
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
 def test_workbuddy_explicit_reset_from_error_expires_without_model_call(self):
  import datetime
  from provider_state import pause_from_events
  reset=datetime.datetime(2026,10,20,14,10,46,tzinfo=datetime.timezone.utc).timestamp()
  message='API Error: Request rejected (429) · WorkBuddy: 您的使用量已超出频率限制，将在 2026-10-20 22:10:46 UTC+8 重置，您也可以切换其他模型继续使用。'
  events=json.dumps({'type':'result','is_error':True,'result':message},ensure_ascii=False)
  value=pause_from_events(self.root,'magpie_deepseek',429,events,now=reset-600)
  self.assertEqual(value['resume_at'],reset)
  self.assertIsNotNone(paused(self.root,'magpie_deepseek',now=reset-1))
  self.assertIsNone(paused(self.root,'magpie_deepseek',now=reset))
  for error,status in [(False,429),(True,401)]:
   value=pause_from_events(self.root,'magpie_deepseek',status,json.dumps({'type':'result','is_error':error,'result':message}),now=reset-600)
   self.assertNotIn('resume_at',value)

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
