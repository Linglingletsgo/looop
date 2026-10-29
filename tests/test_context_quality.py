"""Stage inputs exclude unrelated state while retaining current authority and evidence."""
import copy,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import autonomy,product_research
import test_state_autonomy,test_autonomy,test_delivery

class PlanningInputs(unittest.TestCase):
 setUp=test_state_autonomy.SharedPlanning.setUp
 tearDown=test_state_autonomy.SharedPlanning.tearDown
 setup_tick=test_state_autonomy.SharedPlanning.setup_tick
 setup_shared=test_state_autonomy.SharedPlanning.setup_shared
 board=test_state_autonomy.SharedPlanning.job_ids
 def test_selected_context_contains_effective_decision_once_without_drafts_or_audit(self):
  self.setup_shared()
  for kind,body,confirmed in [('decision','Keep offline support',True),('propose','UNCONFIRMED-NOISE',False),('requirement','UNSELECTED-LOW-PRIORITY',True)]:
   self.store.submit('test',{'type':kind,'title':kind,'body':body,'human_confirmed':confirmed,'priority':'low'},self.store.read('test')['revision'],kind,'human:test')
  report=self.research_mock.return_value
  report.update(loaded_skills=[{'sha256':'AUDIT-ONLY-HASH'}],plan={'skill_reason':'AUDIT-ONLY-PLAN'})
  report['sources'][0].update(sha256='SOURCE-AUDIT-HASH',retrieved_at='AUDIT-TIMESTAMP')
  prompts=[]
  def model(*a,**k):prompts.append(a[2]);return json.dumps(self.value)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=model):autonomy.tick('test')
  prompt=prompts[0]
  self.assertEqual(prompt.count('Test current stable behavior'),1)
  self.assertEqual(prompt.count('Keep offline support'),1)
  for noise in ('UNCONFIRMED-NOISE','UNSELECTED-LOW-PRIORITY','AUDIT-ONLY','SOURCE-AUDIT-HASH','AUDIT-TIMESTAMP','max_proposals_per_day'):self.assertNotIn(noise,prompt)
  self.assertIn('Existing behavior returns stable known values.',prompt)
  self.assertIn('missing test alone',prompt)
 def test_no_material_gain_sleeps_without_dispatch(self):
  self.setup_shared();self.value['value_assessment']['material']=False;self.value['reason']='Only an absent test; no evidenced risk or meaningful contribution'
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)) as run:
   autonomy.tick('test');autonomy.tick('test');self.assertEqual(run.call_count,1)
  self.assertEqual(self.store.read('test')['tasks'],{})
  self.assertFalse((self.root/'data/delivery-bindings').exists())
 def test_missing_value_contract_corrects_before_dispatch(self):
  self.setup_shared();bad=copy.deepcopy(self.value);bad.pop('value_assessment')
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=[json.dumps(bad),json.dumps(self.value)]) as run:
   autonomy.tick('test');self.assertEqual(run.call_count,2)
  self.assertEqual(len(list((self.root/'data/delivery-bindings').glob('*.json'))),1)

class DeliveryInputs(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 harness=test_delivery.Delivery.harness
 execute=test_delivery.Delivery.execute
 def test_review_receipt_matches_target_and_keeps_builder_history_private(self):
  prompts=[]
  def harness(workspace,scratch,prompt,**kwargs):
   prompts.append((scratch.name,prompt))
   result=self.harness(workspace,scratch,prompt,**kwargs)
   if kwargs['role']=='builder':return json.dumps({'verdict':'approved','findings':[],'summary':'BUILDER-PRIVATE-THOUGHT'})
   return result
  result=self.execute(harness=harness)
  for name,prompt in prompts:
   if name.startswith(('reviewer-','acceptance-')):
    self.assertIn('Verification Agent receipt',prompt);self.assertIn(result['target_sha'],prompt)
    self.assertNotIn('output_tail',prompt);self.assertIn('receipt_path',prompt);self.assertNotIn('BUILDER-PRIVATE-THOUGHT',prompt)
    receipt=self.root/'data/deliveries/task-one/checks-1.json'
    self.assertIn(str(receipt),prompt);self.assertEqual(json.loads(receipt.read_text())[0]['output'],'passed')

class ResearchProjection(unittest.TestCase):
 def test_brief_retains_counterevidence_and_exact_sources_only(self):
  report={'status':'supported','question':'Q','finding':'F','counterevidence':'C','recommendation':'R','plan':{'skills':['irrelevant-next-stage']},'loaded_skills':[{'license':'audit'}],'sources':[{'kind':'repository','path':'a.py','quote':'exact evidence','sha256':'audit','retrieved_at':'audit'}]}
  value=product_research.brief(report)
  self.assertEqual(value['counterevidence'],'C');self.assertEqual(value['sources'],[{'kind':'repository','path':'a.py','quote':'exact evidence'}]);self.assertNotIn('plan',value)
