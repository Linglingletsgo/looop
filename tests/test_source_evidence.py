import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from source_evidence import quote,SourceEvidenceError
from planning_runtime import invoke
import product_research as research

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
