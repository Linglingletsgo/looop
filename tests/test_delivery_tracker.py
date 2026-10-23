"""P1c: delivery path through the tracker seam; Paperclip requests stay unchanged."""
import importlib.util,json,os,pathlib,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import process_owner
import test_delivery
import test_autonomy
from jobs import Jobs
from tracker import LocalTracker

BINDING_COMMENT='没有操作员绑定的执行 Packet。看板任务描述不作为执行授权；请通过 delivery-control.py submit 绑定。'

def load(name):
 path=pathlib.Path(__file__).resolve().parents[1]/'bin'/(name+'.py')
 spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

worker=load('delivery-worker');dispatch=load('dispatch');restart=load('restart-recovery')
control=load('delivery-control');health=load('health');launcher=load('launch_loops')

class Recording:
 """Fake Paperclip board with the routes the delivery path uses."""
 def __init__(self,issues=None):
  self.calls=[];self.issues=issues or {};self.counter=0
 def api(self,method,path,data=None):
  self.calls.append((method,path,data))
  if path=='/auth/get-session':return {'user':{'id':'owner'}}
  if method=='GET' and path.startswith('/companies/'):return [dict(v) for v in self.issues.values()]
  if method=='GET' and path.startswith('/issues/'):return dict(self.issues[path.split('/')[-1]])
  if method=='GET' and path.startswith('/agents/'):return {'id':path.split('/')[-1],'status':'idle'}
  if method=='POST':
   self.counter+=1;job='issue-'+str(self.counter)
   self.issues[job]={'id':job,'identifier':'T-'+str(self.counter),**data};return dict(self.issues[job])
  if method=='PATCH':
   job=path.split('/')[-1];self.issues[job].update(data);return dict(self.issues[job])
  raise AssertionError((method,path,data))

class PaperclipWorker(unittest.TestCase):
 """The worker's requests must equal HEAD's for the same board state."""
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def prepare(self,status='todo',binding=True,state=None):
  (self.root/'data').mkdir(exist_ok=True)
  (self.root/'data/control.json').write_text(json.dumps({'company':'company','projects':{'test':{'id':'project','company':'company','repo':str(self.repo),'profile':'profile'}},'agents':{'test:delivery':'agent'}}))
  job='task-one'
  if binding:
   path=self.root/'data/delivery-bindings'/(job+'.json');path.parent.mkdir(parents=True,exist_ok=True)
   path.write_text(json.dumps({'lane':'test','packet':self.packet,'policy':self.policy,'owner':'owner','publish':False}))
  if state:
   path=self.root/'data/deliveries'/job/'state.json';path.parent.mkdir(parents=True)
   path.write_text(json.dumps(state))
  return Recording({job:{'id':job,'identifier':'T-1','projectId':'project','status':status,'assigneeAgentId':'agent'}}),job
 def run_worker(self,board,agent='agent'):
  with patch.object(worker,'ROOT',self.root),patch.object(worker,'Board',lambda:board),patch.dict(os.environ,{'PAPERCLIP_AGENT_ID':agent}):
   worker.heartbeat('test')
 def test_happy_path_matches_head_requests(self):
  board,job=self.prepare()
  with patch.object(worker,'execute',return_value={'state':'validated'}),patch('metrics.record') as record:
   self.run_worker(board)
  self.assertEqual(board.calls,[('GET','/companies/company/issues?assigneeAgentId=agent&status=todo,in_progress',None),
   ('PATCH','/issues/'+job,{'status':'in_progress'}),
   ('PATCH','/issues/'+job,{'status':'done','assigneeAgentId':None,'assigneeUserId':'owner','comment':'Delivery validated\n\nEvidence: '+str(self.root/'data/deliveries'/job)})])
  record.assert_not_called()  # no usage folder exists yet in this synthetic run
 def test_usage_folder_still_imports_cost_events(self):
  board,job=self.prepare()
  usage=self.root/'data/deliveries'/job/'build-1'/'usage.json';usage.parent.mkdir(parents=True)
  usage.write_text(json.dumps({'provider':'codex','model':'m','input_tokens':1,'cached_input_tokens':0,'output_tokens':1}))
  with patch.object(worker,'execute',return_value={'state':'validated'}),patch('metrics.record') as record:
   self.run_worker(board)
  record.assert_called_once_with(board,self.root/'data/deliveries'/job,'company','agent',job,'project')
 def test_blocked_without_binding_clears_only_agent(self):
  board,job=self.prepare(binding=False)
  self.run_worker(board)
  self.assertEqual(board.calls,[('GET','/companies/company/issues?assigneeAgentId=agent&status=todo,in_progress',None),
   ('PATCH','/issues/'+job,{'status':'blocked','assigneeAgentId':None,'comment':BINDING_COMMENT})])
 def test_terminal_receipt_is_preserved_without_execute(self):
  board,job=self.prepare(state={'state':'merged'})
  with patch.object(worker,'execute') as execute:
   self.run_worker(board);execute.assert_not_called()
  self.assertEqual(board.calls[-1],('PATCH','/issues/'+job,{'status':'done','assigneeAgentId':None,'assigneeUserId':'owner','comment':'Preserved terminal delivery receipt; no replay.'}))
 def test_execute_failure_blocks_with_failure_receipt_and_reraises(self):
  board,job=self.prepare()
  with patch.object(worker,'execute',side_effect=ValueError('Provider quota exceeded')):
   with self.assertRaisesRegex(ValueError,'quota'):self.run_worker(board)
  method,path,data=board.calls[-1];self.assertEqual((method,path),('PATCH','/issues/'+job));self.assertEqual(data['status'],'blocked')
  self.assertIsNone(data['assigneeAgentId']);self.assertEqual(data['assigneeUserId'],'owner')
  self.assertTrue(data['comment'].startswith('执行暂停，未自动重放：Provider quota exceeded\n'));self.assertIn('provider_paused',data['comment'])
 def test_identity_mismatch_fails_before_any_request(self):
  board,job=self.prepare()
  with self.assertRaisesRegex(ValueError,'identity mismatch'):self.run_worker(board,agent='other')
  self.assertEqual(board.calls,[])
 def test_status_and_project_filtering_still_skips_foreign_rows(self):
  board,job=self.prepare()
  board.issues['foreign']={'id':'foreign','projectId':'other','status':'todo','assigneeAgentId':'agent'}
  with patch.object(worker,'execute',return_value={'state':'validated'}) as execute:
   self.run_worker(board);execute.assert_called_once()
  self.assertFalse(any('/issues/foreign' in c[1] for c in board.calls))
  self.assertEqual([c[1] for c in board.calls if c[0]=='GET'],['/companies/company/issues?assigneeAgentId=agent&status=todo,in_progress'])

class LocalWorker(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def prepare(self,status='todo',binding=True):
  (self.root/'data').mkdir(exist_ok=True)
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':'project'}},'agents':{}}))
  jobs=Jobs(self.root);job=jobs.create('test','delivery','Task',status=status,assignee='test:delivery')
  if binding:
   path=self.root/'data/delivery-bindings'/(job['id']+'.json');path.parent.mkdir(parents=True,exist_ok=True)
   path.write_text(json.dumps({'lane':'test','packet':self.packet,'policy':self.policy,'owner':'owner','publish':False}))
  return jobs,job
 def run_worker(self):
  with patch.object(worker,'ROOT',self.root),patch.object(worker,'Board',side_effect=AssertionError('Local mode must not build a Board')):
   worker.heartbeat('test')
 def test_claim_release_and_terminal_status(self):
  jobs,job=self.prepare()
  with patch.object(worker,'execute',return_value={'state':'validated'}) as execute:
   self.run_worker();execute.assert_called_once()
  final=jobs.get(job['id']);self.assertEqual((final['status'],final['assignee']),('done','owner'))
  self.assertIsNone(jobs.holder(job['id']))
 def test_release_and_block_on_failure(self):
  jobs,job=self.prepare()
  with patch.object(worker,'execute',side_effect=ValueError('Provider unavailable')):
   with self.assertRaisesRegex(ValueError,'Provider'):self.run_worker()
  self.assertEqual(jobs.get(job['id'])['status'],'blocked');self.assertIsNone(jobs.holder(job['id']))
  self.assertIn('provider_paused',jobs.events(job['id'])[-1]['body'])
 def test_job_leased_by_another_live_identity_is_skipped(self):
  jobs,job=self.prepare();other={**process_owner.identity(),'boot_id':'other-boot','pid':1}
  with jobs.connection() as c:c.execute('UPDATE jobs SET lease_owner=?,lease_until=? WHERE id=?',(json.dumps(other),time.time()+600,job['id']))
  with patch('process_owner.alive',return_value=True),patch.object(worker,'execute') as execute:
   self.run_worker();execute.assert_not_called()
  self.assertEqual(jobs.get(job['id'])['status'],'todo')
 def test_local_mode_needs_no_agent_environment_or_binding(self):
  jobs,job=self.prepare(binding=False)
  with patch.dict(os.environ,{},clear=True):
   self.run_worker()
  self.assertEqual(jobs.get(job['id'])['status'],'blocked');self.assertEqual(jobs.events(job['id'])[-1]['body'],BINDING_COMMENT)
  self.assertIsNone(jobs.holder(job['id']))

class Launch(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  (self.root/'data').mkdir();(self.root/'logs').mkdir()
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':'project'}}}))
  (self.root/'data/delivery-policies').mkdir();(self.root/'data/delivery-policies/test.json').write_text('{}')
  self.jobs=Jobs(self.root)
 def settings(self,value):(self.root/'data/local-settings.json').write_text(json.dumps(value))
 def launches(self,run):
  return [call.args[0] for call in run.call_args_list if call.args[0][:2]==['tmux','new-session']]
 def test_local_mode_starts_exactly_one_delivery_session(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  self.assertTrue((self.root/'data/jobs.sqlite').exists())
  created=set()
  def run(argv,*a,**kw):
   if argv[:2]==['tmux','has-session']:return type('R',(),{'returncode':0 if argv[3] in created else 1})()
   created.add(argv[4]);return type('R',(),{'returncode':0})()
  with patch('subprocess.run',side_effect=run) as mock:
   launcher.launch(self.root);launcher.launch(self.root)
  sessions=self.launches(mock);self.assertEqual(len(sessions),1)
  argv=sessions[0];self.assertEqual(argv[4],'looop-delivery-test');self.assertIn('/bin/delivery-worker.py',argv[7]);self.assertIn('logs/delivery-test.log',argv[7])
 def test_no_session_without_pending_job(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='done',assignee='test:delivery')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_unleased_in_progress_job_is_resumed_but_live_lease_is_not(self):
  self.settings({'tracker':'local'});job=self.jobs.create('test','delivery','Task',status='in_progress',assignee='test:delivery')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(len(self.launches(run)),1)
  self.assertTrue(self.jobs.claim(job['id'],process_owner.identity(),60))
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_no_session_without_delivery_policy(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  (self.root/'data/delivery-policies/test.json').unlink()
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_existing_session_or_live_lease_suppresses_launch(self):
  self.settings({'tracker':'local'});job=self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':0})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
  self.jobs.claim(job['id'],process_owner.identity(),600)
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
 def test_paperclip_mode_never_creates_delivery_sessions(self):
  self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  (self.root/'data/autonomy-policies').mkdir();(self.root/'data/autonomy-policies/test.json').write_text('{}')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root)
  self.assertFalse(any('delivery' in c[4] for c in self.launches(run)))
 def test_no_job_table_creates_no_session_and_no_database(self):
  self.settings({'tracker':'local'});self.jobs.path.unlink();self.assertFalse((self.root/'data/jobs.sqlite').exists())
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root);self.assertEqual(self.launches(run),[])
  self.assertFalse((self.root/'data/jobs.sqlite').exists())
 def test_delivery_continues_while_planning_is_paused(self):
  self.settings({'tracker':'local'});self.jobs.create('test','delivery','Task',status='todo',assignee='test:delivery')
  (self.root/'data/autonomy-policies').mkdir();(self.root/'data/autonomy-policies/test.json').write_text('{}')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root)
  self.assertEqual([c[4] for c in self.launches(run)],['looop-delivery-test'])

class Decisions(unittest.TestCase):
 """dispatch/restart/health reach the same decision in both tracker modes."""
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def state(self,local,status='backlog'):
  board=Recording({'task-one':{'id':'task-one','identifier':'T-1','projectId':'project','status':status,'assigneeAgentId':None}})
  jobs=Jobs(self.root);jobs.create('test','delivery','Task',status=status,job_id='task-one')
  settings=self.root/'data/local-settings.json'
  if local:settings.write_text('{"tracker":"local"}')
  elif settings.exists():settings.unlink()
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':'project'}},'agents':{'test:delivery':'agent'}}))
  return (LocalTracker(jobs,self.root) if local else board),jobs
 def binding(self):
  path=self.root/'data/delivery-bindings/task-one.json';path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps({'lane':'test','packet':self.packet,'policy':self.policy,'publish':False,'owner':'owner'}))
 def test_dispatch_assigns_once_in_both_modes(self):
  for local in (False,True):
   with self.subTest(local=local):
    tracker,jobs=self.state(local);self.binding()
    self.assertEqual([r['state'] for r in dispatch.reconcile(self.root,tracker)],['dispatched'])
    self.assertEqual(dispatch.reconcile(self.root,tracker),[])
    status=jobs.get('task-one')['status'] if local else tracker.issues['task-one']['status']
    self.assertEqual(status,'todo')
 def test_restart_recovery_requeues_dead_worker_in_both_modes(self):
  for local in (False,True):
   with self.subTest(local=local):
    tracker,jobs=self.state(local,'in_progress');self.binding()
    if local:jobs.update('task-one',status='in_progress',assignee='test:delivery')
    else:tracker.issues['task-one'].update(status='in_progress',assigneeAgentId='agent')
    receipt=self.root/'data/deliveries/task-one/state.json';receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps({'state':'building','owner':{**process_owner.identity(),'boot_id':'prior-boot'}}))
    with patch.object(restart,'prepare') as prepare:
     result=restart.reconcile(self.root,tracker)
    self.assertEqual(result[0]['state'],'requeued');prepare.assert_called_once()
    status=jobs.get('task-one')['status'] if local else tracker.issues['task-one']['status']
    self.assertEqual(status,'todo')
 def test_health_terminal_reconciliation_in_both_modes(self):
  for local in (False,True):
   with self.subTest(local=local):
    tracker,jobs=self.state(local,'in_progress');self.binding()
    if local:jobs.update('task-one',status='in_progress',assignee='test:delivery')
    else:tracker.issues['task-one'].update(status='in_progress',assigneeAgentId='agent')
    receipt=self.root/'data/deliveries/task-one/state.json';receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps({'state':'merged'}))
    self.assertEqual(health.reconcile(self.root,tracker),1)
    if local:self.assertEqual((jobs.get('task-one')['status'],jobs.get('task-one')['assignee']),('done',None))
    else:
     self.assertEqual(tracker.issues['task-one']['status'],'done');self.assertIsNone(tracker.issues['task-one']['assigneeAgentId'])

class Control(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def test_configure_local_mode_creates_no_agent(self):
  (self.root/'data').mkdir(exist_ok=True);(self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  policy=self.root/'policy.json';policy.write_text(json.dumps(self.policy))
  config={'company':'company','projects':{'test':{'id':'project','repo':str(self.repo),'profile':'profile'}},'agents':{}}
  registry={'roles':{name:{} for name in ('product','builder','reviewer','acceptance')},'workflow':None,'project_roles':{}}
  with patch.object(control,'ROOT',self.root),patch.object(control,'config',return_value=config),patch.object(control,'validate_profile'),patch.object(control,'Board',side_effect=AssertionError('Local mode must not build a Board')),patch.object(control,'resolve',return_value=registry),patch.object(control,'fingerprints',return_value={}):
   control.configure('test',str(policy))
  saved=json.loads((self.root/'data/control.json').read_text())
  self.assertNotIn('test:delivery',saved.get('agents',{}))
  self.assertTrue((self.root/'data/delivery-policies/test.json').exists())

class EndToEnd(unittest.TestCase):
 """planning tick -> binding -> dispatch -> worker -> job done, no Paperclip board."""
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_local_loop_runs_without_paperclip(self):
  import autonomy,test_autonomy
  self.mandate['scope_approval']='pm'
  self.setup_tick()
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  def no_board():raise AssertionError('Local mode must not build a Paperclip Board')
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',no_board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)) as model:
   autonomy.tick('test')
  self.assertEqual(model.call_count,1)
  jobs=Jobs(self.root);delivery=jobs.list(lane='test',kind='delivery')
  self.assertEqual(len(delivery),1);self.assertEqual((delivery[0]['status'],delivery[0]['assignee']),('todo','test:delivery'))
  tracker=LocalTracker(jobs,self.root)
  self.assertEqual(dispatch.reconcile(self.root,tracker),[])
  with patch.object(worker,'ROOT',self.root),patch.object(worker,'Board',no_board),patch.object(worker,'execute',return_value={'state':'validated'}) as execute:
   worker.heartbeat('test')
  execute.assert_called_once()
  self.assertEqual((jobs.get(delivery[0]['id'])['status'],jobs.get(delivery[0]['id'])['assignee']),('done','owner'))
  receipts=[json.loads(p.read_text()) for p in (self.root/'data/autonomy/test').glob('*/state.json')]
  receipt=next(r for r in receipts if r.get('delivery_issue'))
  self.assertEqual((receipt['state'],receipt['delivery_issue']),('queued',delivery[0]['id']))
