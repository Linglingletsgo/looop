import copy,json,pathlib,subprocess,sys,unittest,time,os
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import test_delivery,delivery
from gates import GateError
from delivery_clarification import apply,packet_hash,effective_packet
from delivery_evidence import artifacts_digest

class EvidenceRepair(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 execute=test_delivery.Delivery.execute
 def model(self):
  self.counts={'build':0,'review':0,'check':0}
  def run(workspace,scratch,prompt,**kw):
   value={'verdict':'approved','findings':[],'summary':'Completed'}
   if kw['role']=='builder':
    self.counts['build']+=1
    if self.counts['build']==1:(workspace/'app.py').write_text('value = 1\n')
    artifacts=scratch.parent/'artifacts';artifacts.mkdir(exist_ok=True)
    (artifacts/'proof.json').write_text(json.dumps({'run':self.counts['build']}))
   if 'Independently review full' in prompt:
    self.counts['review']+=1
    if self.counts['review']==1:value.update(verdict='changes_requested',findings=['Refresh proof at the frozen SHA'])
   scratch.mkdir(exist_ok=True,parents=True);(scratch/'result.md').write_text(json.dumps(value))
   return json.dumps(value)
  return run
 def test_evidence_only_repair_keeps_commit_and_reruns_all_gates(self):
  result=self.execute(harness=self.model())
  folder=self.root/'data/deliveries/task-one'
  self.assertEqual(result['state'],'validated');self.assertEqual(self.counts['build'],2);self.assertEqual(self.counts['review'],2)
  self.assertEqual(delivery.git(folder/'candidate','rev-list','--count',self.packet['baseline_sha']+'..HEAD').decode().strip(),'1')
  self.assertTrue((folder/'checks-2.json').exists())
  self.assertEqual(json.loads((folder/result['builder_run']/'stage-receipt.json').read_text())['target_sha'],result['target_sha'])
 def test_unchanged_source_and_evidence_still_stops(self):
  run=self.model()
  def no_progress(workspace,scratch,prompt,**kw):
   if kw['role']=='builder' and self.counts['build']==1:return '{"verdict":"approved","findings":[]}'
   return run(workspace,scratch,prompt,**kw)
  with self.assertRaisesRegex(GateError,'No repair progress'):self.execute(harness=no_progress)
  self.assertEqual(self.counts['review'],1)
 def test_first_round_artifacts_do_not_substitute_for_source_delivery(self):
  def no_source(workspace,scratch,prompt,**kw):
   if kw['role']=='builder':
    p=scratch.parent/'artifacts';p.mkdir();(p/'proof').write_text('not source')
   return '{"verdict":"approved","findings":[]}'
  with self.assertRaisesRegex(GateError,'No repair progress'):self.execute(harness=no_source)
 def test_symlink_evidence_refused(self):
  root=self.root/'evidence';(root/'artifacts').mkdir(parents=True)
  (root/'artifacts/link').symlink_to(self.repo/'app.py')
  with self.assertRaisesRegex(GateError,'Symlink evidence'):artifacts_digest(root)
 def test_legacy_resume_reuses_completed_builder_with_fresh_checks_and_review(self):
  result=self.execute(harness=self.model());folder=self.root/'data/deliveries/task-one'
  prior=next(p for p in folder.glob('reviewer-*/stage-receipt.json') if json.loads(p.read_text())['verdict']=='changes_requested')
  state={**result,'state':'blocked','error':'No change inside Packet scope','failed_stage':'building','stage_receipt':str(prior),'updated_at':time.time()+10}
  # Historical gate stopped before adopting round two; its completed Builder remains on disk.
  prior_time=time.time()-20;os.utime(prior,(prior_time,prior_time))
  state['builder_run']='older-builder'
  (folder/'state.json').write_text(json.dumps(state))
  calls=[];checks=[]
  def review(workspace,scratch,prompt,**kw):
   self.assertNotEqual(kw['role'],'builder');calls.append(prompt);return '{"verdict":"approved","findings":[]}'
  # Only the completed second Builder can follow the prior review in this fixture.
  builders=sorted(folder.glob('builder-*/validated-result.json'),key=lambda p:p.stat().st_mtime)
  os.utime(builders[0],(prior_time-1,prior_time-1))
  with patch.object(delivery,'ROOT',self.root),patch.object(delivery,'run',side_effect=review),patch.object(delivery,'command',side_effect=lambda *a,**kw:checks.append(a) or subprocess.CompletedProcess([],0,'pass')),patch('process_owner.alive',return_value=False):
   resumed=delivery.execute(self.packet,self.policy,'task-one',publish=False,resume_evidence=True,emit=lambda *_:None)
  self.assertEqual(resumed['target_sha'],result['target_sha']);self.assertEqual(resumed['state'],'validated')
  self.assertEqual(len(checks),1);self.assertEqual(len(calls),2)
  self.assertEqual(resumed['builder_run'],result['builder_run'])

 def test_product_clarification_recovers_format_and_binds_actual_handoff(self):
  from delivery_clarification import clarify,effective_packet
  from handoff import prepare
  result=self.execute(harness=self.model());folder=self.root/'data/deliveries/task-one'
  result.update(state='blocked');(folder/'state.json').write_text(json.dumps(result))
  bindings=self.root/'data/delivery-bindings';bindings.mkdir()
  (bindings/'task-one.json').write_text(json.dumps({'packet':self.packet,'policy':self.policy}))
  calls=[]
  def product(workspace,scratch,prompt,**kw):
   calls.append(1);scratch.mkdir(parents=True)
   identity=prepare(scratch,kw['handoff_schema'])
   clause=self.packet['requirements'][0]
   value={'verdict':'approved','summary':'Clarified wording, no scope expansion','changes':[{'section':'requirements','index':0,'before':'partial' if len(calls)==1 else clause,'after':clause+' exactly','reason':'Clarify exactness'}]}
   (scratch/'handoff.json').write_text(json.dumps({**identity,'result':value}))
   return json.dumps(value)
  with patch('sandbox.run',side_effect=product),patch('process_owner.alive',return_value=False):
   effective=clarify(self.root,'task-one')
   self.assertEqual(clarify(self.root,'task-one'),effective)
  self.assertEqual(len(calls),2)
  doc=json.loads((folder/'product-clarification.json').read_text())
  self.assertTrue(doc['run_id'].endswith('-retry-1'))
  self.assertEqual(effective_packet(folder,self.packet),effective)
  self.assertEqual(json.loads((folder/'packet.json').read_text()),self.packet)

class Clarification(unittest.TestCase):
 def setUp(self):
  self.packet={'requirements':['Keep all truthful unknowns'],'acceptance':['Deadline unknowns exclude N/A'],'allowed_paths':['app.py'],'baseline_sha':'a'*40}
  self.change={'section':'requirements','index':0,'before':self.packet['requirements'][0],'after':'Keep unrelated unknowns; exclude N/A only from deadline unknowns','reason':'Resolve contradictory wording'}
 def test_only_criteria_change_original_and_scope_preserved(self):
  original=copy.deepcopy(self.packet);value=apply(self.packet,{'verdict':'approved','changes':[self.change]})
  self.assertEqual(self.packet,original);self.assertEqual(value['allowed_paths'],original['allowed_paths'])
  self.assertEqual(value['baseline_sha'],original['baseline_sha']);self.assertNotEqual(value['requirements'],original['requirements'])
 def test_reject_stale_duplicate_scope_and_blocked_decisions(self):
  for change in [{**self.change,'before':'stale'},{**self.change,'index':True},{**self.change,'section':'allowed_paths'}]:
   with self.assertRaises(GateError):apply(self.packet,{'verdict':'approved','changes':[change]})
  with self.assertRaises(GateError):apply(self.packet,{'verdict':'approved','changes':[self.change,self.change]})
  with self.assertRaises(GateError):apply(self.packet,{'verdict':'blocked','changes':[self.change]})
 def test_clarification_is_bound_to_original_handoff(self):
  import tempfile
  from handoff import prepare
  with tempfile.TemporaryDirectory() as tmp:
   folder=pathlib.Path(tmp);run=folder/'product-clarification-test';run.mkdir()
   schema={'type':'object'};identity=prepare(run,schema)
   result={'verdict':'approved','changes':[self.change]}
   (run/'handoff.json').write_text(json.dumps({**identity,'result':result}))
   doc={'packet_hash':packet_hash(self.packet),'run_id':run.name,'result':result}
   (folder/'product-clarification.json').write_text(json.dumps(doc))
   self.assertEqual(effective_packet(folder,self.packet)['requirements'][0],self.change['after'])
   doc['result']={'verdict':'approved','changes':[]};(folder/'product-clarification.json').write_text(json.dumps(doc))
   with self.assertRaisesRegex(GateError,'differs'):effective_packet(folder,self.packet)
