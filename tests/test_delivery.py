import copy,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import delivery
from gates import GateError

class Delivery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
  subprocess.run(['git','init','-q',str(self.repo)],check=True)
  for k,v in [('user.name','Synthetic'),('user.email','synthetic@example.test')]:delivery.git(self.repo,'config',k,v)
  (self.repo/'app.py').write_text('value = 0\n');(self.repo/'other.py').write_text('untouched = True\n');(self.repo/'AGENTS.md').write_text('Only synthetic data.\n')
  delivery.git(self.repo,'add','.');delivery.git(self.repo,'commit','-qm','baseline')
  sha=delivery.git(self.repo,'rev-parse','HEAD').decode().strip()
  self.packet={'title':'Implement count','requirements':['value = 1'],'acceptance':['Count matches'],'baseline_sha':sha,'allowed_paths':['app.py']}
  self.policy={'enabled':True,'repo':str(self.repo),'max_rounds':2,'risk':'low','allowed_paths':['app.py'],'checks':[['python3','-m','unittest']],'workflow':[{'role':'product','stage':'plan'},{'role':'builder','stage':'build','provider':'commandcode'},{'role':'reviewer','stage':'review'},{'role':'acceptance','stage':'acceptance'}]}
 def tearDown(self):self.tmp.cleanup()
 def harness(self,workspace,scratch,prompt,**kwargs):
  if kwargs['role']=='builder':(pathlib.Path(workspace)/'app.py').write_text('value = 1\n')
  return json.dumps({'verdict':'approved','findings':[],'evidence':['Synthetic check']})
 def execute(self,job='task-one',harness=None,check=None):
  with patch.object(delivery,'ROOT',self.root),patch.object(delivery,'run',side_effect=harness or self.harness),patch.object(delivery,'command',side_effect=check or (lambda *a,**kw:subprocess.CompletedProcess([],0,'passed'))):
   return delivery.execute(self.packet,self.policy,job,emit=lambda *_:None,publish=False)
 def test_two_distinct_packets_and_no_replay(self):
  first=self.execute();self.assertEqual(first['state'],'validated')
  self.packet['title']='Another bounded task';second=self.execute('task-two');self.assertEqual(second['state'],'validated')
  def forbidden(*a,**kw):raise AssertionError('duplicate model execution')
  self.assertEqual(self.execute('task-one',harness=forbidden)['target_sha'],first['target_sha'])
  self.assertEqual((self.repo/'app.py').read_text(),'value = 0\n')
 def test_scope_violation_stops_before_checks(self):
  def bad(workspace,*a,**kw):
   if kw['role']=='builder':(pathlib.Path(workspace)/'other.py').write_text('changed')
   return '{"verdict":"approved","findings":[]}'
  with self.assertRaisesRegex(GateError,'scope'):self.execute(harness=bad)
  s=json.loads((self.root/'data/deliveries/task-one/state.json').read_text());self.assertEqual(s['state'],'blocked');self.assertNotIn('pr_url',s)
 def test_failing_checks_are_bounded(self):
  count=[0]
  def build(workspace,*a,**kw):
   if kw['role']=='builder':count[0]+=1;(pathlib.Path(workspace)/'app.py').write_text('value = '+str(count[0])+'\n')
   return '{"verdict":"approved","findings":[]}'
  with self.assertRaisesRegex(GateError,'Round limit'):self.execute(harness=build,check=lambda *a,**kw:subprocess.CompletedProcess([],1,'failure'))
  self.assertEqual(count[0],2)
 def test_extra_role_is_executed_not_discarded(self):
  self.policy['workflow'].insert(1,{'stage':'advisory','role':'ux-designer'})
  self.assertEqual(self.execute()['state'],'validated')
  r=json.loads((self.root/'data/deliveries/task-one/roles.json').read_text());self.assertIn('ux-designer',r)
 def test_traversal_and_rule_writes_rejected(self):
  for name in ['../escape','AGENTS.md','.paperclip/roles.json','.env','/tmp/escape']:
   self.packet['allowed_paths']=[name];self.policy['allowed_paths']=[name]
   with self.assertRaises(GateError):delivery.validate(self.packet,self.policy)
 def test_project_workflow_not_silently_replaced(self):
  (self.repo/'.paperclip').mkdir();(self.repo/'.paperclip/roles.json').write_text(json.dumps({'version':1,'roles':{},'workflow':[{'stage':'advisory','role':'qa'}]}))
  delivery.git(self.repo,'add','.');delivery.git(self.repo,'commit','-qm','custom workflow');self.packet['baseline_sha']=delivery.git(self.repo,'rev-parse','HEAD').decode().strip()
  with self.assertRaisesRegex(GateError,'workflow differs'):self.execute()
 def test_high_risk_needs_adversarial(self):
  self.policy['risk']='high'
  with self.assertRaisesRegex(GateError,'adversarial'):delivery.validate(self.packet,self.policy)
 def test_moved_baseline_refused(self):
  (self.repo/'other.py').write_text('moved');delivery.git(self.repo,'add','.');delivery.git(self.repo,'commit','-qm','moved')
  with self.assertRaisesRegex(GateError,'Baseline moved'):self.execute()
 def test_role_contract_cannot_be_mutated_by_packet(self):
  (self.repo/'personas').mkdir();(self.repo/'personas/builder.md').write_text('Project builder contract')
  (self.repo/'.paperclip').mkdir();(self.repo/'.paperclip/roles.json').write_text(json.dumps({'version':1,'roles':{'builder':'personas/builder.md'}}))
  delivery.git(self.repo,'add','.');delivery.git(self.repo,'commit','-qm','custom builder');self.packet['baseline_sha']=delivery.git(self.repo,'rev-parse','HEAD').decode().strip()
  self.packet['allowed_paths']=['personas/builder.md'];self.policy['allowed_paths']=['personas/builder.md']
  with self.assertRaisesRegex(GateError,'Role definitions'):self.execute()
 def test_custom_build_role_gets_write_but_review_never_does(self):
  self.policy['workflow'][1]['role']='qa'
  seen=[]
  def model(workspace,scratch,prompt,**kwargs):
   seen.append(kwargs['role'])
   if kwargs['role']=='builder':(pathlib.Path(workspace)/'app.py').write_text('value = 1\n')
   return '{"verdict":"approved","findings":[]}'
  self.assertEqual(self.execute(harness=model)['state'],'validated')
  self.assertEqual(seen,['readonly','builder','readonly','readonly'])
 def test_acceptance_rejection_returns_to_builder_with_fresh_reviews(self):
  counts={'build':0,'review':0,'acceptance':0}
  def model(workspace,scratch,prompt,**kwargs):
   if kwargs['role']=='builder':
    counts['build']+=1;(pathlib.Path(workspace)/'app.py').write_text('value = '+str(counts['build'])+'\n')
   if 'Independently review full' in prompt:counts['review']+=1
   if 'Independently verify acceptance' in prompt:
    counts['acceptance']+=1
    if counts['acceptance']==1:return '{"verdict":"changes_requested","findings":["Synthetic missing case"]}'
   return '{"verdict":"approved","findings":[]}'
  result=self.execute(harness=model)
  self.assertEqual(result['state'],'validated');self.assertEqual(counts,{'build':2,'review':2,'acceptance':2})
  self.assertEqual(result['reviews']['standard']['target_sha'],result['target_sha'])
 def test_publish_is_once_and_never_merges(self):
  self.policy['github_repo']='synthetic/validation'
  original_git=delivery.git;original_output=subprocess.check_output;calls=[]
  def git(repo,*args):
   if args[0]=='push':calls.append('push');return b''
   return original_git(repo,*args)
  def output(argv,*args,**kwargs):
   if argv[0].endswith('/gh'):
    calls.append(argv[1:3])
    if argv[1:3]==['pr','list']:return b'[]'
    if argv[1:3]==['pr','create']:return 'https://github.com/synthetic/validation/pull/1\n'
    raise AssertionError('Unexpected GitHub action')
   return original_output(argv,*args,**kwargs)
  with patch.object(delivery,'ROOT',self.root),patch.object(delivery,'run',side_effect=self.harness),patch.object(delivery,'command',return_value=subprocess.CompletedProcess([],0,'passed')),patch.object(delivery,'git',side_effect=git),patch.object(delivery.subprocess,'check_output',side_effect=output):
   first=delivery.execute(self.packet,self.policy,'publish-one',emit=lambda *_:None,publish=True)
   second=delivery.execute(self.packet,self.policy,'publish-one',emit=lambda *_:None,publish=True)
  self.assertEqual(first['pr_url'],second['pr_url']);self.assertEqual(calls.count('push'),1);self.assertEqual(calls.count(['pr','create']),1)
 def test_unsupported_stage_does_not_silently_skip(self):
  self.policy['workflow'].insert(1,{'stage':'deploy','role':'qa'})
  with self.assertRaisesRegex(GateError,'Explicit workflow'):delivery.validate(self.packet,self.policy)
 def test_project_workflow_evidence_must_match_and_remain_readonly(self):
  (self.repo/'workflow.md').write_text('PO validates; Builder only implements.')
  delivery.git(self.repo,'add','.');delivery.git(self.repo,'commit','-qm','workflow')
  self.packet['baseline_sha']=delivery.git(self.repo,'rev-parse','HEAD').decode().strip()
  self.policy['workflow_evidence']={'workflow.md':'0'*64}
  with self.assertRaisesRegex(GateError,'Workflow evidence changed'):self.execute('wrong-workflow')
  import hashlib
  self.policy['workflow_evidence']={'workflow.md':hashlib.sha256((self.repo/'workflow.md').read_bytes()).hexdigest()}
  self.packet['allowed_paths']=['workflow.md'];self.policy['allowed_paths']=['workflow.md']
  with self.assertRaisesRegex(GateError,'Role definitions'):self.execute('write-workflow')
 def test_unlimited_runtime_and_explicit_commands_in_prompts(self):
  seen=[]
  def model(workspace,scratch,prompt,**kwargs):
   self.assertIsNone(kwargs['timeout']);self.assertIn('exact configured checks',prompt);self.assertIn('Controller checks:',prompt);seen.append(kwargs['role'])
   return self.harness(workspace,scratch,prompt,**kwargs)
  def check(*a,**kw):self.assertIsNone(kw['timeout']);return subprocess.CompletedProcess([],0,'passed')
  self.assertEqual(self.execute(harness=model,check=check)['state'],'validated');self.assertEqual(len(seen),4)
 def test_recovery_preserves_evidence_draft_and_never_publishes(self):
  from recovery import prepare
  def bad(workspace,scratch,prompt,**kwargs):
   if kwargs['role']=='builder':
    (pathlib.Path(workspace)/'app.py').write_text('value = 123\n');raise RuntimeError('Synthetic disconnect')
   return '{"verdict":"approved","findings":[]}'
  with self.assertRaisesRegex(RuntimeError,'disconnect'):self.execute(harness=bad)
  bindings=self.root/'data/delivery-bindings';bindings.mkdir();path=bindings/'task-one.json'
  path.write_text(json.dumps({'packet':self.packet,'policy':self.policy,'lane':'test','publish':True}))
  archive=prepare(self.root,'task-one','Connection restored')
  self.assertTrue((archive/'state.json').exists());self.assertFalse((self.root/'data/deliveries/task-one').exists())
  d=json.loads(path.read_text());self.assertIn('+value = 123',d['packet']['execution_notes']);self.assertTrue(d['publish'])
  # Recovery cannot bypass fresh review/checks; restarting without recovery notes is not implied.
  self.assertEqual(self.execute()['state'],'validated')
  with self.assertRaisesRegex(ValueError,'unpublished blocked'):prepare(self.root,'task-one','must refuse success')
 def test_builder_blocker_is_preserved_without_checks_or_repair(self):
  def blocked(workspace,scratch,prompt,**kwargs):
   if kwargs['role']=='builder':
    (pathlib.Path(workspace)/'app.py').write_text('failing proof\n');return '{"verdict":"blocked","findings":["Production bug outside authorized scope"]}'
   return '{"verdict":"approved","findings":[]}'
  def forbidden(*a,**kw):raise AssertionError('No checks or repairs after explicit blocker')
  with self.assertRaisesRegex(GateError,'Builder blocked'):self.execute(harness=blocked,check=forbidden)
  self.assertEqual((self.root/'data/deliveries/task-one/build-1/app.py').read_text(),'failing proof\n')
 def test_test_only_check_failure_stops_instead_of_repairing_assertions(self):
  self.policy['on_check_failure']='stop'
  with self.assertRaisesRegex(GateError,'Product disposition'):self.execute(check=lambda *a,**kw:subprocess.CompletedProcess([],1,'exposed regression'))
  state=json.loads((self.root/'data/deliveries/task-one/state.json').read_text());self.assertEqual(state['round'],1);self.assertEqual(state['failure']['category'],'product_disposition')
