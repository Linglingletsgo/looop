import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from jobs import Jobs
spec=importlib.util.spec_from_file_location('delivery_control',pathlib.Path(__file__).resolve().parents[1]/'bin/delivery-control.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Control(unittest.TestCase):
 def test_existing_issue_binding_clears_owner_without_duplicate_issue(self):
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);(root/'data/delivery-policies').mkdir(parents=True)
   (root/'data/delivery-policies/test.json').write_text(json.dumps({'github_repo':'test/repo','repo':str(root),'enabled':True,'checks':[['python3','-c','pass']],'workflow':[{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'}],'allowed_paths':['test.py']}))
   packet=root/'packet.json';packet.write_text(json.dumps({'title':'Bound task','requirements':['Preserve behavior'],'acceptance':['Observable result'],'allowed_paths':['test.py'],'baseline_sha':'a'*40}))
   s={'projects':{'test':{'repo':str(root),'profile':'profile'}},'agents':{'test:delivery':'agent'}}
   jobs=Jobs(root);jobs.create('test','delivery','Existing',status='backlog',job_id='issue')
   spec=importlib.util.spec_from_file_location('delivery_control_bind',module.__file__);control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
   with patch.object(control,'ROOT',root),patch.object(control,'config',return_value=s),patch.object(control,'validate_profile'),patch('subprocess.check_output',return_value='a'*40):
    control.submit('test',str(packet),True,'issue')
    job=jobs.get('issue');self.assertEqual((job['status'],job['assignee']),('todo','test:delivery'))
    bindings=list((root/'data/delivery-bindings').glob('*.json'));self.assertEqual([path.stem for path in bindings],['issue'])
    with self.assertRaisesRegex(ValueError,'backlog'):control.submit('test',str(packet),False,issue='issue')
    self.assertEqual(len([job for job in jobs.list(lane='test') if job['kind']=='delivery']),1)
 def test_sync_prs_never_merges_and_preserves_open_tasks(self):
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);p=root/'data/deliveries/task';p.mkdir(parents=True);state=p/'state.json';state.write_text('{"state":"waiting_for_merge","pr_url":"https://example.test/1"}')
   jobs=Jobs(root);jobs.create('test','delivery','Task','Test',status='in_review',assignee='owner',job_id='task')
   with patch.object(module,'ROOT',root),patch('subprocess.check_output',return_value=b'{"state":"OPEN"}') as gh:
    module.sync_prs();self.assertEqual(jobs.get('task')['status'],'in_review');self.assertEqual(gh.call_args.args[0][1:3],['pr','view'])
   with patch.object(module,'ROOT',root),patch('subprocess.check_output',return_value=b'{"state":"MERGED","mergeCommit":{"oid":"human-sha"},"mergedAt":"now"}'):
    module.sync_prs();self.assertEqual(json.loads(state.read_text())['state'],'merged');self.assertEqual(jobs.get('task')['status'],'done')
