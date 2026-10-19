import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from research_evidence import basis,proposal_supported,EvidenceGap
import product_research as research
import research_experiment as probes

class Evidence(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir();(self.repo/'spec.py').write_text('VALUE=7 # Contract: preserve the original value when uncertain.\n')
  self.plan={'kind':'existing_defect','question':'Does output violate the current contract?','stop_condition':'Compare contract to controller observation','skills':['looop:investigation']}
  self.report={'status':'supported','question':self.plan['question'],'finding':'Output contradicts documented contract','counterevidence':'Synthetic reproduction only','recommendation':'Define a minimal fix','sources':[{'kind':'repository','path':'spec.py','quote':'Contract: preserve the original value when uncertain.'}],'skill_usage':[{'path':'looop:investigation','impact':'Compared source contract to observations'}],'defect_evidence':{'expected':'Preserve original value','observed':'The fixed input changed value','contract_source':'spec.py','experiment':0}}
  self.probe={'runtime':'python','purpose':'Observe actual code','script':'from spec import VALUE\nprint(VALUE)'}
 def perform(self,values,**kw):
  run=Mock(side_effect=[json.dumps(v) for v in values]);self.run=run
  return research.perform(run,self.repo,self.root/'run','PM','State',Mock(),{'provider':'codex','harness':'codex'},public_required=True,**kw)
 def test_label_without_runtime_cannot_bypass_public_research(self):
  with self.assertRaisesRegex(EvidenceGap,'successful controller experiment'):self.perform([self.plan,self.report,self.report,self.report])
  self.assertEqual(self.run.call_count,4)
 def test_new_requirement_cannot_use_defect_experiment_as_demand(self):
  e={'exit_code':0,'script_sha256':'x','source_fingerprint':'y','evidence_path':'probe'}
  with self.assertRaisesRegex(EvidenceGap,'public research'):basis({'sources':[{'kind':'repository','verified_source':'spec.py'}]},'new_requirement',True,[e])
 def test_current_checkpoint_recovers_into_supported_defect_without_reexecution(self):
  checkpoint=self.root/'prior';receipt=probes.execute(self.repo,checkpoint/'experiment-1',self.probe,None,Mock())
  result=self.perform([self.plan,self.report],checkpoint=checkpoint)
  self.assertTrue(proposal_supported(result));self.assertEqual(result['evidence_basis']['kind'],'existing_defect');self.assertEqual(self.run.call_count,2)
  self.assertEqual(result['experiments'][0]['script_sha256'],receipt['script_sha256']);self.assertIn('Controller-restored',self.run.call_args.args[2]);self.assertFalse((self.root/'run/experiment-1').exists())
 def test_changed_source_invalidates_checkpoint(self):
  checkpoint=self.root/'prior';probes.execute(self.repo,checkpoint/'experiment-1',self.probe,None,Mock());(self.repo/'spec.py').write_text('VALUE=8\n')
  self.assertEqual(probes.restored(self.repo,checkpoint),[])
 def test_tampered_probe_invalidates_checkpoint(self):
  checkpoint=self.root/'prior';probes.execute(self.repo,checkpoint/'experiment-1',self.probe,None,Mock());(checkpoint/'experiment-1/workspace/.looop-research-probe.py').write_text('print("forged")')
  self.assertEqual(probes.restored(self.repo,checkpoint),[])
 def test_failed_experiment_never_qualifies_defect(self):
  e={'exit_code':1,'script_sha256':'x','source_fingerprint':'y','evidence_path':'probe'}
  with self.assertRaises(EvidenceGap):basis({'sources':[{'kind':'repository','verified_source':'spec.py'}]},'existing_defect',True,[e],self.report['defect_evidence'])
 def test_unknown_contract_source_and_bad_receipt_index_rejected(self):
  e={'exit_code':0,'script_sha256':'x','source_fingerprint':'y','evidence_path':'probe'};report={'sources':[{'kind':'repository','path':'spec.py','verified_source':'spec.py'}]}
  for patch in ({'contract_source':'invented.md'},{'experiment':9},{'experiment':True}):
   with self.assertRaises(EvidenceGap):basis(report,'existing_defect',True,[e],{**self.report['defect_evidence'],**patch})
 def test_verified_public_evidence_uses_same_dispatch_rule(self):
  b=basis({'sources':[{'kind':'public','verified_source':'https://example.com'}]},'new_requirement',True,[])
  self.assertTrue(proposal_supported({'evidence_basis':b}));self.assertFalse(proposal_supported({'kind':'existing_defect','sources':[{'kind':'public'}]}))
 def test_observations_file_survives_verbose_stdout(self):
  script='import os,json\nfrom pathlib import Path\nPath(os.environ["LOOOP_EXPERIMENT_RESULT"]).write_text(json.dumps({"cases":10,"valid":10}))\nprint("noise"*10000)'
  r=probes.execute(self.repo,self.root/'probe',{**self.probe,'script':script},None,Mock())
  self.assertEqual(r['observations'],{'cases':10,'valid':10});self.assertLessEqual(len(r['output']),12000)
 def test_oversized_observations_rejected(self):
  script='import os\nfrom pathlib import Path\nPath(os.environ["LOOOP_EXPERIMENT_RESULT"]).write_text("x"*12001)'
  with self.assertRaisesRegex(ValueError,'12000 bytes'):probes.execute(self.repo,self.root/'probe',{**self.probe,'script':script},None,Mock())
