import json,pathlib,sys,tempfile,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import autonomy
from roles import resolve,fingerprints
class Autonomy(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.repo=self.root/'data/execution-repos/test';self.repo.mkdir(parents=True)
  subprocess.run(['git','init','-q',str(self.repo)],check=True)
  for k,v in [('user.name','Test'),('user.email','test@example.test')]:autonomy.git(self.repo,'config',k,v)
  (self.repo/'spec.py').write_text('Existing behavior returns stable known values.\n');(self.repo/'test.py').write_text('pass\n')
  autonomy.git(self.repo,'add','.');autonomy.git(self.repo,'commit','-qm','baseline');self.sha=autonomy.git(self.repo,'rev-parse','HEAD').decode().strip()
  self.mandate={'enabled':True,'allowed_paths':['test.py'],'evidence_paths':['spec.py'],'max_files':1,'max_proposals_per_day':2,'pm_role':'product-manager','product_role':'product'}
  self.value={'action':'task','value':'Regression verifies current deterministic behavior with a meaningful negative control.','evidence':[{'path':'spec.py','quote':'Existing behavior returns stable known values.'}],'packet':{'title':'Add regression','requirements':['Preserve behavior'],'acceptance':['Negative control catches wrong result'],'allowed_paths':['test.py']}}
  self.policy={'enabled':True,'repo':str(self.repo),'github_repo':'test/repo','max_rounds':2,'allowed_paths':['test.py'],'checks':[['python3','test.py']],'workflow':[{'stage':'plan','role':'product'},{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'},{'stage':'acceptance','role':'product'}],'role_registry':fingerprints(resolve(self.repo))}
 def tearDown(self):self.tmp.cleanup()
 def setup_tick(self):
  for folder in ('data/autonomy-policies','data/delivery-policies','data/locks'):(self.root/folder).mkdir(parents=True,exist_ok=True)
  (self.root/'data/autonomy-policies/test.json').write_text(json.dumps(self.mandate));(self.root/'data/delivery-policies/test.json').write_text(json.dumps(self.policy));(self.root/'data/control.json').write_text(json.dumps({'company':'company','projects':{'test':{'id':'project','repo':str(self.repo),'profile':'profile'}},'agents':{'test:delivery':'delivery'}}))
 def test_scope_source_evidence_and_duplicate_rejected(self):
  p,key=autonomy.checked_proposal(self.value,self.mandate,self.repo,self.sha,[]);self.assertEqual(p['baseline_sha'],self.sha)
  with self.assertRaisesRegex(ValueError,'Duplicate'):autonomy.checked_proposal(self.value,self.mandate,self.repo,self.sha,[key])
  self.value['packet']['allowed_paths']=['spec.py']
  with self.assertRaisesRegex(ValueError,'Outside'):autonomy.checked_proposal(self.value,self.mandate,self.repo,self.sha,[])
 def test_false_source_quote_refused(self):
  self.value['evidence'][0]['quote']='Fabricated source text that is not in the repository'
  with self.assertRaisesRegex(ValueError,'not found'):autonomy.checked_proposal(self.value,self.mandate,self.repo,self.sha,[])
 def test_pm_product_binding_cycle_and_no_same_baseline_repeat(self):
  self.setup_tick();calls=[];responses=[json.dumps(self.value),'{"verdict":"approved","findings":[],"reason":"Within authorized existing behavior"}']
  class Board:
   def api(self,method,path,data=None):
    calls.append((method,path,data))
    if path=='/auth/get-session':return {'user':{'id':'owner'}}
    if method=='POST':return {'id':'delivery-issue' if data['status']=='backlog' else 'pm-issue','identifier':'T-1'}
  def model(*a,**k):return responses.pop(0)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=model) as run:
   autonomy.tick('test');self.assertEqual(run.call_count,2)
   binding=json.loads((self.root/'data/delivery-bindings/delivery-issue.json').read_text());self.assertEqual(binding['authorization']['type'],'project_mandate')
   autonomy.tick('test');self.assertEqual(run.call_count,2)
   state=self.root/'data/deliveries/delivery-issue/state.json';state.parent.mkdir(parents=True);state.write_text('{"state":"merged","mainline_verified":"same"}')
   autonomy.tick('test');self.assertEqual(run.call_count,2)
 def test_no_work_creates_no_delivery(self):
  self.setup_tick();calls=[]
  class Board:
   def api(self,m,p,d=None):
    calls.append((m,p,d))
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    if m=='POST':return {'id':'pm','identifier':'T-1'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"No meaningful gap"}'):
   autonomy.tick('test')
  self.assertFalse((self.root/'data/delivery-bindings').exists())
 def test_blocked_or_unverified_delivery_prevents_new_pm_calls(self):
  p=self.root/'data/delivery-bindings/task.json';p.parent.mkdir(parents=True);p.write_text('{"lane":"test"}')
  self.assertIsNotNone(autonomy.slots(self.root,'test',self.mandate))
  p=self.root/'data/deliveries/task/state.json';p.parent.mkdir(parents=True);p.write_text('{"state":"blocked"}')
  self.assertIn('blocked',autonomy.slots(self.root,'test',self.mandate))
  p.write_text('{"state":"merged"}');self.assertIn('verification',autonomy.slots(self.root,'test',self.mandate))
 def test_only_connection_failure_retries_at_most_twice(self):
  binding=self.root/'data/delivery-bindings/task.json';binding.parent.mkdir(parents=True);binding.write_text('{"lane":"test"}')
  state=self.root/'data/deliveries/task/state.json';state.parent.mkdir(parents=True)
  state.write_text(json.dumps({'state':'blocked','failed_stage':'building','updated_at':0,'failure':{'retryable':True}}));calls=[]
  class Board:
   def api(self,m,p,d=None):
    if m=='GET':return {'status':'idle'}
    calls.append(d)
  with patch('recovery.prepare') as recovery:
   self.assertTrue(autonomy.retry_connection(self.root,'test',Board(),'agent',now=1000));self.assertEqual(recovery.call_count,1)
   data=json.loads(binding.read_text());data['connection_retries']=2;binding.write_text(json.dumps(data))
   self.assertFalse(autonomy.retry_connection(self.root,'test',Board(),'agent',now=1000));self.assertEqual(recovery.call_count,1)
   data['connection_retries']=0;binding.write_text(json.dumps(data));s=json.loads(state.read_text());s['failure']['retryable']=False;state.write_text(json.dumps(s))
   self.assertFalse(autonomy.retry_connection(self.root,'test',Board(),'agent',now=1000))
