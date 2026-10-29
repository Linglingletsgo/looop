import importlib.util,json,pathlib,shutil,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Held,Conflict
spec=importlib.util.spec_from_file_location('session',pathlib.Path(__file__).resolve().parents[1]/'bin/project-session.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ExternalWork(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.t.name);self.store=Store(self.root);self.store.ensure('demo')
 def tearDown(self):self.t.cleanup()
 def test_manual_blocks_dispatch_and_preserves_task_gates(self):
  s=self.store;s.external_work('demo',{'action':'start','id':'one','summary':'Implement manual task'},0,'start','chat')
  self.assertEqual(s.read('demo')['phase'],'external_work')
  with self.assertRaises(Held):s.project_guard('demo')
  with self.assertRaises(Held):s.bind('demo','job',{'title':'task'})
  s.external_work('demo',{'action':'finish','id':'one','summary':'Changed code; tests not run'},1,'finish','chat')
  self.assertEqual(s.read('demo')['external_work']['one']['verification'],'self_reported');s.project_guard('demo');self.assertEqual(s.read('demo')['tasks'],{})
 def test_active_task_rejects_manual_start(self):
  self.store.bind('demo','job',{'title':'existing'})
  with self.assertRaises(Held):self.store.external_work('demo',{'action':'start','id':'one','summary':'manual'},1,'start','chat')
 def test_source_revision_and_idempotence(self):
  c={'action':'start','id':'one','summary':'manual'};s=self.store;s.external_work('demo',c,0,'same','chat');self.assertTrue(s.external_work('demo',c,0,'same','chat')['replayed'])
  with self.assertRaises(Conflict):s.external_work('demo',{'action':'finish','id':'one','summary':'done'},1,'other','different')
  with self.assertRaises(Conflict):s.external_work('demo',{'action':'progress','id':'one','summary':'progress'},0,'stale','chat')
 def test_standalone_without_paperclip(self):
  repo=self.root/'repo';repo.mkdir();m.operate(repo,'init');m.operate(repo,'start','one','manual');r=m.operate(repo,'finish','one','Finished, self-reported')
  self.assertEqual(r['pending_events'],0);self.assertEqual(m.operate(repo,'context',history=True)['project_state']['external_work']['one']['status'],'completed')
 def test_offline_records_survive_and_sync(self):
  repo=self.root/'repo';repo.mkdir();remote=self.root/'remote';Store(remote).ensure('demo');m.operate(repo,'init',runtime=str(remote),lane='demo')
  moved=self.root/'unavailable';remote.rename(moved);r=m.operate(repo,'start','one','offline work');self.assertEqual(r['pending_events'],1);self.assertEqual(m.operate(repo,'context')['local_pending_work']['one']['status'],'active')
  moved.rename(remote);r=m.operate(repo,'sync');self.assertEqual(len(r['accepted']),1);self.assertEqual(m.operate(repo,'context')['project_state']['phase'],'external_work')

 def test_sync_records_external_work_and_acknowledges_the_outbox(self):
  spec=importlib.util.spec_from_file_location('state_sync',pathlib.Path(__file__).resolve().parents[1]/'bin/state-sync.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  (self.root/'data/delivery-bindings').mkdir();(self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'id':None}}}))
  s=self.store;s.external_work('demo',{'action':'start','id':'one','summary':'manual'},0,'start','chat');self.assertTrue(module.sync(self.root))
  self.assertEqual(s.read('demo')['phase'],'external_work')
  s.external_work('demo',{'action':'finish','id':'one','summary':'finished'},1,'finish','chat');self.assertTrue(module.sync(self.root))
  with s.connection('demo') as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',('demo',)).fetchone()[0],0)
  self.assertEqual(s.read('demo')['tasks'],{})

 def test_standalone_connect_imports_progress_without_duplicate(self):
  repo=self.root/'repo';repo.mkdir();m.operate(repo,'init');m.operate(repo,'start','one','Started locally');m.operate(repo,'finish','one','Finished locally')
  r=m.operate(repo,'connect',runtime=str(self.root),lane='demo');self.assertEqual(len(r['accepted']),2)
  self.assertEqual(self.store.read('demo')['external_work']['one']['status'],'completed');self.assertEqual(m.operate(repo,'sync')['accepted'],[])

 def receipt(self,sha,**changes):
  value={'version':1,'task_id':'one','role':'builder','stage':'build','baseline_sha':sha,'target_sha':sha,'verdict':'approved','summary':'Implemented; review pending','findings':[],'checks':[],'artifacts':[],'unverified':['Independent review pending'],'cleanup':[]}
  return {**value,**changes}
 def git_repo(self):
  repo=self.root/'repo';repo.mkdir();subprocess.run(['git','init','-q',str(repo)],check=True)
  for key,value in [('user.name','Test'),('user.email','test@example.test')]:subprocess.run(['git','-C',str(repo),'config',key,value],check=True)
  (repo/'.gitignore').write_text('.agent/local/\n')
  subprocess.run(['git','-C',str(repo),'add','.'],check=True);subprocess.run(['git','-C',str(repo),'commit','-qm','baseline'],check=True)
  return repo,subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
 def test_structured_result_is_a_stage_claim_not_completion(self):
  repo,sha=self.git_repo();m.operate(repo,'init');m.operate(repo,'start','one','Implement')
  file=repo/'.agent/local/result.json';file.write_text(json.dumps(self.receipt(sha)))
  result=m.operate(repo,'result','one',result_file=file);self.assertEqual(result['pending_events'],0)
  doc=m.operate(repo,'context')['project_state'];work=doc['external_work']['one']
  self.assertEqual(work['status'],'active');self.assertEqual(work['verification'],'self_reported')
  self.assertEqual(work['results']['builder:build']['target_sha'],sha);self.assertEqual(doc['tasks'],{})
  m.operate(repo,'finish','one','Session finished; independent review pending')
  self.assertIn('one',m.operate(repo,'context')['project_state']['external_work'])
  m.operate(repo,'connect',runtime=str(self.root),lane='demo')
  imported=self.store.read('demo')['external_work']['one']
  self.assertEqual(imported['results'],work['results']);self.assertEqual(imported['status'],'completed')
 def test_bad_result_or_dirty_checkout_does_not_queue_claim(self):
  repo,sha=self.git_repo();m.operate(repo,'init');m.operate(repo,'start','one','Implement')
  file=repo/'.agent/local/result.json';file.write_text(json.dumps(self.receipt(sha,task_id='another')))
  with self.assertRaisesRegex(ValueError,'differs'):m.operate(repo,'result','one',result_file=file)
  file.write_text(json.dumps(self.receipt(sha)));(repo/'uncommitted.py').write_text('value=1')
  with self.assertRaisesRegex(ValueError,'clean checkout'):m.operate(repo,'result','one',result_file=file)
  self.assertEqual(m.operate(repo,'context')['pending_events'],0)
 def test_context_omits_completed_history_without_losing_it(self):
  s=self.store
  for n in range(5):
   work='work-'+str(n)
   s.external_work('demo',{'action':'start','id':work,'summary':'old work'},s.read('demo')['revision'],'start-'+work,'chat')
   s.external_work('demo',{'action':'finish','id':work,'summary':'old completed summary'},s.read('demo')['revision'],'finish-'+work,'chat')
  self.assertEqual(s.context('demo')['external_work'],{})
  self.assertEqual(len(s.context('demo',history=True)['external_work']),5)
  self.assertEqual(s.context('demo')['history_work_count'],5)
  for n in range(5):
   s.bind('demo','task-'+str(n),{'title':'Finished task'});s.transition('demo','task-'+str(n),'completed',import_existing=True)
  self.assertEqual(s.context('demo')['tasks'],{})
  self.assertEqual(len(s.context('demo',history=True)['tasks']),5)
 def test_structured_results_survive_offline_sync_and_revision_conflict(self):
  repo,sha=self.git_repo();remote=self.root/'remote';Store(remote).ensure('demo')
  m.operate(repo,'init',runtime=remote,lane='demo');m.operate(repo,'start','one','Implement')
  file=repo/'.agent/local/result.json';file.write_text(json.dumps(self.receipt(sha)))
  moved=self.root/'unavailable';remote.rename(moved)
  self.assertEqual(m.operate(repo,'result','one',result_file=file)['pending_events'],1)
  moved.rename(remote);store=Store(remote)
  store.external_work('demo',{'action':'progress','id':'one','summary':'Concurrent progress'},1,'concurrent','project-session:'+str(repo))
  with self.assertRaises(Conflict):m.operate(repo,'sync')
  self.assertEqual(m.operate(repo,'context')['pending_events'],1)
  self.assertNotIn('results',store.read('demo')['external_work']['one'])
 def test_exported_tools_run_without_scheduler_imports(self):
  repo,sha=self.git_repo();tools=repo/'.agent/tools';tools.mkdir(parents=True)
  source=pathlib.Path(__file__).resolve().parents[1]/'bin'
  for name in ('project-session.py','project_state.py','state_revisions.py','product_goals.py','lifecycle_io.py'):shutil.copy2(source/name,tools/name)
  def command(*args):
   return json.loads(subprocess.check_output([sys.executable,str(tools/'project-session.py'),*args,'--repo',str(repo)],text=True,cwd=self.root))
  command('init');command('start','--id','one','--summary','Independent work')
  # Tools are portable tracked files; commit them before a commit-backed receipt.
  subprocess.run(['git','-C',str(repo),'add','.agent/tools'],check=True);subprocess.run(['git','-C',str(repo),'commit','-qm','tools'],check=True)
  target=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
  file=repo/'.agent/local/result.json';file.write_text(json.dumps(self.receipt(sha,target_sha=target)))
  self.assertEqual(command('result','--id','one','--result-file',str(file))['pending_events'],0)
  self.assertEqual(command('context')['project_state']['external_work']['one']['results']['builder:build']['target_sha'],target)

 def test_outstanding_resources_survive_retention_and_can_be_resolved(self):
  from retention import compact_state
  from unittest.mock import patch
  s=self.store;sha='a'*40
  s.external_work('demo',{'action':'start','id':'one','summary':'Work'},0,'start','chat')
  receipt=self.receipt(sha,unverified=[],cleanup=['Builder: remove owned temporary worktree after preserving changes'])
  s.external_work('demo',{'action':'result','id':'one','summary':receipt['summary'],'receipt':receipt},1,'result','chat')
  s.external_work('demo',{'action':'finish','id':'one','summary':'Session ended; resource cleanup pending'},2,'finish','chat')
  # More recent completions must not evict unresolved current obligations.
  s.external_work('demo',{'action':'start','id':'two','summary':'Other work'},3,'other-start','chat')
  s.external_work('demo',{'action':'finish','id':'two','summary':'Other done'},4,'other-finish','chat')
  with patch('retention.POLICY',{'completed_work_limit':1}):compact_state(s,'demo')
  self.assertIn('one',s.context('demo')['external_work'])
  clean={**receipt,'cleanup':[],'summary':'Owned resources removed; no outstanding work'}
  s.external_work('demo',{'action':'result','id':'one','summary':clean['summary'],'receipt':clean},s.read('demo')['revision'],'resolved','chat')
  self.assertNotIn('one',s.context('demo')['external_work'])
  self.assertEqual(s.read('demo')['external_work']['one']['status'],'completed')

 def test_connect_imports_late_receipt_correction_after_finished_session(self):
  repo,sha=self.git_repo();m.operate(repo,'init');m.operate(repo,'start','one','Implement')
  file=repo/'.agent/local/result.json';file.write_text(json.dumps(self.receipt(sha)))
  m.operate(repo,'result','one',result_file=file);m.operate(repo,'finish','one','Session finished')
  file.write_text(json.dumps(self.receipt(sha,unverified=[],summary='Independent evidence updated')))
  m.operate(repo,'result','one',result_file=file)
  result=m.operate(repo,'connect',runtime=self.root,lane='demo')
  self.assertNotIn('error',result)
  work=self.store.read('demo')['external_work']['one']
  self.assertEqual(work['status'],'completed');self.assertEqual(work['results']['builder:build']['unverified'],[])
