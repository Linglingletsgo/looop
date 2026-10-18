import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from merging import eligibility,merge
from gates import GateError
class ProductMerge(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);(self.root/'product-run').mkdir();(self.root/'product-run/result.md').write_text('{"verdict":"approved"}')
  (self.root/'checks-1.json').write_text('[{"argv":["node","test"],"exit_code":0}]')
  self.state={'risk':'low','round':1,'target_sha':'head','builder_run':'builder','pr_url':'https://github.com/test/repo/pull/1','reviews':{'standard':{'target_sha':'head','mode':'standard','verdict':'approved','run_id':'reviewer'}},'acceptance':{'target_sha':'head','verdict':'approved','run_id':'product-run'}}
  self.binding={'publish':True,'packet':{'baseline_sha':'base'},'policy':{'github_repo':'test/repo','checks':[['node','test']],'workflow':[{'stage':'acceptance','role':'product'}]}}
  self.policy={'mode':'product_approved','github_repo':'test/repo','acceptance_role':'product'}
  self.pr={'state':'OPEN','isDraft':False,'url':self.state['pr_url'],'headRefOid':'head','baseRefOid':'base','baseRefName':'main','mergeable':'MERGEABLE','mergeStateStatus':'CLEAN','statusCheckRollup':[]}
 def tearDown(self):self.tmp.cleanup()
 def check(self):return eligibility(self.root,self.state,self.binding,self.policy,self.pr)
 def test_approved_same_head_merges_without_admin_override(self):
  self.assertTrue(self.check())
  with patch('merging.subprocess.run') as cmd,patch('merging.subprocess.check_output',return_value=b'{"state":"MERGED"}'):
   self.assertEqual(merge(self.root,self.state,self.binding,self.policy,self.pr)['state'],'MERGED')
   argv=cmd.call_args.args[0];self.assertIn('--match-head-commit',argv);self.assertNotIn('--admin',argv)
 def test_changed_head_base_conflict_or_pending_checks_refused(self):
  for key,value in [('headRefOid','new'),('baseRefOid','new'),('mergeable','CONFLICTING'),('mergeStateStatus','BLOCKED'),('isDraft',True),('statusCheckRollup',[{'__typename':'CheckRun','status':'IN_PROGRESS'}])]:
   old=copy.deepcopy(self.pr);self.pr[key]=value
   with self.subTest(key=key),self.assertRaises(GateError):self.check()
   self.pr=old
 def test_stale_review_acceptance_or_wrong_role_refused(self):
  self.state['reviews']['standard']['target_sha']='old'
  with self.assertRaises(GateError):self.check()
  self.state['reviews']['standard']['target_sha']='head';self.binding['policy']['workflow'][-1]['role']='builder'
  with self.assertRaises(GateError):self.check()
 def test_failed_checks_or_unapproved_report_refused(self):
  (self.root/'checks-1.json').write_text('[{"argv":["node","test"],"exit_code":1}]')
  with self.assertRaises(GateError):self.check()
  (self.root/'checks-1.json').write_text('[{"argv":["node","test"],"exit_code":0}]');(self.root/'product-run/result.md').write_text('{"verdict":"changes_requested"}')
  with self.assertRaises(GateError):self.check()

 def modern_report(self,stage='review'):
  from handoff import prepare
  from output_protocol import delivery_schema
  if stage=='review':
   self.binding['policy']['workflow']=[{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'}]
   self.policy={'mode':'review_approved','github_repo':'test/repo','review_role':'reviewer'}
   run=self.root/'reviewer';run.mkdir()
  else:run=self.root/'product-run'
  identity=prepare(run,delivery_schema(stage))
  result={'verdict':'approved','findings':[]}
  if stage=='acceptance':result['evidence']=['verified']
  (run/'handoff.json').write_text(json.dumps({**identity,'result':result}))
  (run/'result.md').write_text('Review completed. See the structured handoff file.')
  return run
 def test_modern_review_and_acceptance_ignore_dialogue(self):
  for stage in ('acceptance','review'):
   with self.subTest(stage=stage):
    self.modern_report(stage)
    self.assertTrue(self.check())
 def test_modern_identity_or_missing_file_cannot_fall_back_to_chat(self):
  run=self.modern_report()
  (run/'result.md').write_text('{"verdict":"approved"}')
  doc=json.loads((run/'handoff.json').read_text());doc['run_id']='different-run'
  (run/'handoff.json').write_text(json.dumps(doc))
  with self.assertRaises(ValueError):self.check()
  (run/'handoff.json').unlink()
  with self.assertRaises(ValueError):self.check()
 def test_modern_nonapproval_overrides_chat(self):
  run=self.modern_report()
  doc=json.loads((run/'handoff.json').read_text());doc['result']['verdict']='changes_requested'
  (run/'handoff.json').write_text(json.dumps(doc))
  (run/'result.md').write_text('{"verdict":"approved"}')
  with self.assertRaises(GateError):self.check()
