import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from source_evidence import quote,SourceEvidenceError
from planning_runtime import invoke
import product_research as research
from looop_support import setUpModule  # noqa: F401

class Quotes(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.repo=pathlib.Path(self.temp.name);self.text='不可靠表格/金额关联星号保留原句待核。';(self.repo/'spec.md').write_text(self.text)
 def test_exact_short_cjk_quote_is_valid_in_all_research(self):
  self.assertEqual(len(self.text),19);quote(self.repo,'spec.md',self.text)
  report={'status':'supported','question':'Contract?','finding':'Source confirms it','counterevidence':'No runtime claim','recommendation':'Use the contract','sources':[{'kind':'repository','path':'spec.md','quote':self.text}]}
  self.assertEqual(research.verify(report,self.repo)['status'],'supported')
 def test_malformed_and_missing_quotes_have_specific_errors(self):
  for value,message in [('', 'nonempty'),('   ','nonempty'),(None,'nonempty'),('x'*2001,'2000'),('invented','not found: spec.md')]:
   with self.assertRaisesRegex(SourceEvidenceError,message):quote(self.repo,'spec.md',value)
 def test_source_correction_can_reread_without_repeating_research(self):
  run=Mock(side_effect=[json.dumps({'quote':'Invented'}),json.dumps({'quote':self.text})])
  result=invoke(run,self.repo,self.repo/'pm','Prepare same Packet',Mock(),validate=lambda v:quote(self.repo,'spec.md',v['quote']))
  self.assertEqual(result['quote'],self.text);self.assertEqual(run.call_count,2);self.assertIn('Read only the named source',run.call_args.args[2]);self.assertNotIn('Do not perform additional work to repair formatting',run.call_args.args[2]);self.assertEqual(json.loads((self.repo/'pm-recovery.json').read_text())['state'],'recovered')
 def test_persistent_mismatch_remains_blocked(self):
  run=Mock(return_value=json.dumps({'quote':'Invented'}))
  with self.assertRaises(SourceEvidenceError):invoke(run,self.repo,self.repo/'pm','Packet',Mock(),validate=lambda v:quote(self.repo,'spec.md',v['quote']))
  self.assertEqual(run.call_count,3);self.assertFalse(json.loads((self.repo/'pm-recovery.json').read_text())['automatic_retry'])

 def completion(self,path,**extra):
  return {'criterion':'Executed outcome','path':path,'quote':'51 tests passed',**extra}
 def test_runtime_proof_namespaces_and_legacy_current_run_report(self):
  from source_evidence import verify_completion
  artifacts=self.repo/'data/autonomy/demo/run/pm';artifacts.mkdir(parents=True)
  (artifacts/'report.md').write_text('Baseline '+ 'a'*40 + ': 51 tests passed')
  goal={'success_criteria':['Executed outcome']}
  for path in ['report.md',str(artifacts/'report.md'),'data/autonomy/demo/run/pm/report.md']:
   evidence=[self.completion(path,kind='runtime_check',target_sha='a'*40)]
   self.assertEqual(verify_completion(self.repo,artifacts,goal,evidence,'a'*40,artifact_base=self.repo),evidence)
  evidence=[self.completion('data/autonomy/demo/run/pm/report.md')]
  verify_completion(self.repo,artifacts,goal,evidence,'a'*40,artifact_base=self.repo)
  with self.assertRaisesRegex(SourceEvidenceError,'target SHA'):
   verify_completion(self.repo,artifacts,goal,evidence,'b'*40,artifact_base=self.repo)
 def test_runtime_proof_cannot_borrow_other_run_escape_or_invent_quote(self):
  from source_evidence import verify_completion
  artifacts=self.repo/'data/autonomy/demo/run/pm';artifacts.mkdir(parents=True)
  (artifacts/'report.md').write_text('51 tests passed')
  other=self.repo/'other';other.mkdir();(other/'report.md').write_text('51 tests passed')
  (artifacts/'link.md').symlink_to(other/'report.md')
  goal={'success_criteria':['Executed outcome']}
  for path in ['../report.md',str(other/'report.md'),'data/autonomy/demo/other/pm/report.md','link.md']:
   with self.subTest(path=path),self.assertRaises(SourceEvidenceError):
    verify_completion(self.repo,artifacts,goal,[self.completion(path,kind='runtime_check',target_sha='a'*40)],'a'*40,artifact_base=self.repo)
  for sha in [None,'b'*40]:
   with self.assertRaisesRegex(SourceEvidenceError,'another revision'):
    verify_completion(self.repo,artifacts,goal,[self.completion('report.md',kind='runtime_check',target_sha=sha)],'a'*40)
  with self.assertRaisesRegex(SourceEvidenceError,'not found'):
   verify_completion(self.repo,artifacts,goal,[{**self.completion('report.md',kind='runtime_check',target_sha='a'*40),'quote':'Invented pass'}],'a'*40)
 def test_source_completion_checks_quote_instead_of_only_existence(self):
  from source_evidence import verify_completion
  goal={'success_criteria':['Executed outcome']}
  with self.assertRaisesRegex(SourceEvidenceError,'not found'):
   verify_completion(self.repo,self.repo/'run',goal,[self.completion('spec.md')],'a'*40)
