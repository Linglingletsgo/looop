import importlib.util,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from process_owner import identity

def module(name):
 spec=importlib.util.spec_from_file_location(name,pathlib.Path(__file__).resolve().parents[1]/'bin'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class Publication(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.folder=self.root/'data/deliveries/job';self.folder.mkdir(parents=True);(self.root/'data/locks').mkdir()
  b=self.root/'data/delivery-bindings/job.json';b.parent.mkdir();b.write_text(json.dumps({'publish':True,'policy':{'repo':'repo','github_repo':'owner/repo','checks':[['check']]}}))
  self.state={'state':'pr_ready','owner':{**identity(),'boot_id':'prior-boot'},'target_sha':'abc','risk':'low','round':1,'builder_run':'builder','reviews':{'standard':{'target_sha':'abc','mode':'standard','verdict':'approved','run_id':'review'}},'acceptance':{'target_sha':'abc','verdict':'approved','run_id':'acceptance'}}
  (self.folder/'checks-1.json').write_text('[{"argv":["check"],"exit_code":0}]');self.save();self.m=module('publication-recovery')
  self.pr={'url':'https://github.com/owner/repo/pull/1','state':'OPEN','headRefOid':'abc','headRefName':'agent/delivery-job','baseRefName':'main','isCrossRepository':False}
 def tearDown(self):self.tmp.cleanup()
 def save(self):(self.folder/'state.json').write_text(json.dumps(self.state))
 def reconcile(self,prs):
  with patch.object(self.m.subprocess,'check_output',side_effect=['/tmp/common',json.dumps(prs).encode()]) as gh:
   result=self.m.reconcile(self.root,None)
   self.assertFalse(any('create' in x.args[0] or 'push' in x.args[0] for x in gh.call_args_list));return result
 def test_existing_pr_restores_receipt_and_never_creates(self):
  self.assertEqual(self.reconcile([self.pr])[0]['state'],'reconciled');self.assertEqual(json.loads((self.folder/'state.json').read_text())['state'],'waiting_for_merge')
  with patch.object(self.m.subprocess,'check_output') as gh:self.m.reconcile(self.root,None);gh.assert_not_called()
 def test_missing_ambiguous_fork_or_changed_sha_requires_attention(self):
  for prs in ([],[self.pr,self.pr],[{**self.pr,'headRefOid':'other'}],[{**self.pr,'isCrossRepository':True}]):
   self.assertEqual(self.reconcile(prs)[0]['state'],'needs_attention');self.assertEqual(json.loads((self.folder/'state.json').read_text())['state'],'pr_ready')
 def test_alive_or_unknown_worker_not_touched(self):
  for owner in (identity(),None):
   self.state['owner']=owner;self.save()
   with patch.object(self.m.subprocess,'check_output') as gh:self.m.reconcile(self.root,None);gh.assert_not_called()
 def test_lost_response_exception_and_merged_pr_reconcile(self):
  self.state.update(state='blocked',failed_stage='pr_ready');self.save()
  self.assertEqual(self.reconcile([{**self.pr,'state':'MERGED','mergeCommit':{'oid':'merge-sha'}}])[0]['state'],'reconciled');self.assertEqual(json.loads((self.folder/'state.json').read_text())['merge_commit'],'merge-sha')
