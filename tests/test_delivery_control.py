import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
spec=importlib.util.spec_from_file_location('delivery_control',pathlib.Path(__file__).resolve().parents[1]/'bin/delivery-control.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Control(unittest.TestCase):
 def test_existing_issue_binding_clears_owner_without_duplicate_issue(self):
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);(root/'data/delivery-policies').mkdir(parents=True)
   (root/'data/delivery-policies/test.json').write_text('{"github_repo":"test/repo"}')
   packet=root/'packet.json';packet.write_text('{"title":"Bound task"}')
   s={'company':'company','projects':{'test':{'id':'project','profile':'profile'}},'agents':{'test:delivery':'agent'}};calls=[]
   class Board:
    def api(self,method,path,data=None):
     calls.append((method,path,data))
     if path=='/auth/get-session':return {'user':{'id':'owner'}}
     if method=='GET':return {'id':'issue','identifier':'T-1','projectId':'project','status':'backlog'}
   with patch.object(module,'ROOT',root),patch.object(module,'config',return_value=s),patch.object(module,'validate_profile'),patch.object(module,'validate'),patch.object(module,'Board',Board):
    module.submit('test',str(packet),True,'issue')
    self.assertFalse(any(c[0]=='POST' for c in calls));self.assertIsNone(calls[-1][2]['assigneeUserId'])
    self.assertTrue((root/'data/delivery-bindings/issue.json').exists())
    with self.assertRaisesRegex(ValueError,'already bound'):module.submit('test',str(packet),True,'issue')
 def test_sync_prs_never_merges_and_preserves_open_tasks(self):
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);p=root/'data/deliveries/task';p.mkdir(parents=True);state=p/'state.json';state.write_text('{"state":"waiting_for_merge","pr_url":"https://example.test/1"}');calls=[]
   class Board:
    def api(self,*args):calls.append(args)
   with patch.object(module,'ROOT',root),patch.object(module,'Board',Board),patch('subprocess.check_output',return_value=b'{"state":"OPEN"}') as gh:
    module.sync_prs();self.assertEqual(calls,[]);self.assertEqual(gh.call_args.args[0][1:3],['pr','view'])
   with patch.object(module,'ROOT',root),patch.object(module,'Board',Board),patch('subprocess.check_output',return_value=b'{"state":"MERGED","mergeCommit":{"oid":"human-sha"},"mergedAt":"now"}'):
    module.sync_prs();self.assertEqual(json.loads(state.read_text())['state'],'merged');self.assertEqual(calls[0][2]['status'],'done')
