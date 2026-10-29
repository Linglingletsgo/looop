"""Local jobs are the only tracker: no deleted Paperclip module is imported anywhere."""
import importlib.util,json,os,pathlib,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
BIN=pathlib.Path(__file__).resolve().parents[1]/'bin'
sys.path.insert(0,str(BIN))
from jobs import Jobs
from project_state import Held,Store
from tracker import LocalTracker,open_tracker

def module(name,symbol=None):
 path=BIN/(name+'.py');spec=importlib.util.spec_from_file_location(symbol or name.replace('-','_'),path)
 value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def local_root(tmp):
 root=pathlib.Path(tmp);(root/'data').mkdir(parents=True)
 (root/'data/local-settings.json').write_text(json.dumps({'tracker':'local'}))
 return root

class StateSyncLocal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{}}}))
  self.store=Store(self.root);self.store.ensure('demo');self.sync=module('state-sync','state_sync_local')

 def test_reconcile_and_outbox_delivery_are_local_idempotent(self):
  packet={'title':'Existing outcome','requirements':['Preserve behavior'],'acceptance':['Verified outcome'],'allowed_paths':['app.py'],'baseline_sha':'a'*40}
  bindings=self.root/'data/delivery-bindings';bindings.mkdir();(bindings/'task.json').write_text(json.dumps({'lane':'demo','packet':packet,'intent_ids':[],'authorization':{}}))
  receipt=self.root/'data/deliveries/task';receipt.mkdir(parents=True);(receipt/'state.json').write_text(json.dumps({'state':'merged','mainline_verified':'b'*40}))
  self.store.submit('demo',{'type':'requirement','title':'Intent','body':'Body','human_confirmed':True},0,'intent','test')
  self.assertTrue(self.sync.sync(self.root))
  first=self.store.read('demo');self.assertEqual(first['tasks']['task']['phase'],'completed')
  with self.store.connection('demo') as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',('demo',)).fetchone()[0],0)
  self.assertTrue(self.sync.sync(self.root))
  self.assertEqual(self.store.read('demo')['revision'],first['revision'])

 def test_5000_rows_are_acknowledged_before_held_can_stick(self):
  self.store.ensure('big');doc=self.store.read('big')
  with self.store.connection('big') as c:
   c.executemany('INSERT INTO outbox(lane,revision) VALUES (?,?)',[('big',i) for i in range(1,5001)])
   doc['revision']=5000;c.execute('UPDATE projects SET doc=? WHERE lane=?',(json.dumps(doc),'big'))
  command={'type':'requirement','title':'Next','body':'Body','human_confirmed':True}
  with self.assertRaises(Held):self.store.submit('big',command,5000,'blocked','test')
  self.assertTrue(self.sync.sync(self.root))
  with self.store.connection('big') as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE lane=? AND delivered=0',('big',)).fetchone()[0],0)
  self.assertEqual(self.store.submit('big',command,5000,'after-sync','test')['revision'],5001)

class PlanningRetryUnmigratedJob(unittest.TestCase):
 """Local retry of a PM attempt whose issue was never migrated fails clearly and changes nothing."""
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  self.lane='demo';self.jobs=Jobs(self.root);self.tracker=LocalTracker(self.jobs,self.root)
  self.pm=module('planning_intervention','planning_retry_local')
  # An unrelated row proves only the PM issue is missing from the local table.
  self.jobs.create(self.lane,'delivery','Delivery for PM','unrelated',job_id='delivery-1')
  self.path=self.root/'data/autonomy'/self.lane/'pm-one'/'state.json';self.path.parent.mkdir(parents=True)
  self.path.write_text(json.dumps({'state':'blocked','owner':{'pid':0},'issue':'pm-issue','error':'Completion protocol failed'}))
  self.revision=Store(self.root).ensure(self.lane)['revision']
  (self.root/'data/control.json').write_text(json.dumps({'projects':{self.lane:{}},'agents':{}}))

 def rows(self):
  with self.jobs.connection() as c:return c.execute('SELECT * FROM jobs ORDER BY id').fetchall()

 def run_retry(self):
  with patch.object(self.pm,'alive',return_value=False):
   with self.assertRaisesRegex(ValueError,'该 PM 任务不在本地任务表中（可能未迁移）；请先运行迁移或在维护对话中核对。') as raised:
    self.pm.retry(self.root,self.lane,'pm-one','证据已核验',self.revision,self.tracker)
  self.assertNotIsInstance(raised.exception,KeyError);return raised.exception

 def test_missing_job_raises_value_error_without_any_state_change(self):
  # Project state, PM receipt and job table are unchanged after the refused retry.
  files=[p for p in (self.root/'data').rglob('*') if p.suffix in ('.json','.current.json')];before={p:p.read_bytes() for p in files};rows=self.rows()
  self.run_retry()
  self.assertIsNone(self.jobs.get('pm-issue'));self.assertEqual(json.loads(self.path.read_text())['state'],'blocked')
  self.assertEqual(Store(self.root).read(self.lane)['revision'],self.revision)
  self.assertEqual({p:p.read_bytes() for p in files},before);self.assertEqual(self.rows(),rows)

 def test_console_retry_planning_attempt_reports_the_same_error(self):
  actions=module('console_actions','console_actions_local')
  with patch.object(self.pm,'alive',return_value=False),patch.object(actions,'ROOT',self.root):
   with self.assertRaisesRegex(ValueError,'该 PM 任务不在本地任务表中') as raised:
    actions.execute({'action':'retry_planning_attempt','lane':self.lane,'job':'pm-one','reason':'证据已核验','revision':self.revision,'request_id':'r1'},root=self.root)
  self.assertNotIsInstance(raised.exception,KeyError)

class OnboardingLocal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=pathlib.Path(self.tmp.name)
  self.home=base/'home';self.repo=self.home/'projects'/'demo';self.repo.mkdir(parents=True)
  self.root=local_root(base/'root');(self.root/'data/control.json').write_text(json.dumps({'projects':{},'agents':{}}))
  (self.root/'bin').mkdir()
  for name in ('project-session.py','project_state.py','state_revisions.py','product_goals.py','lifecycle_io.py'):shutil.copy2(BIN/name,self.root/'bin'/name)
  subprocess.run(['git','-C',str(self.repo),'init','-q','-b','main'],check=True)
  subprocess.run(['git','-C',str(self.repo),'-c','user.email=t@t','-c','user.name=t','commit','--allow-empty','-qm','init'],check=True)
  env=patch.dict(os.environ,{'HOME':str(self.home)});env.start();self.addCleanup(env.stop)
  self.onboarding=module('onboarding','onboarding_local');self.value=self.onboarding.preview(self.repo,root=self.root)

 def test_preview_uses_local_wording(self):
  self.assertFalse(any('Paperclip' in item for item in self.value['planned_changes']))
  self.assertTrue(any('本地任务队列' in item for item in self.value['planned_changes']))

 def test_connect_creates_a_local_entry_and_local_consumers_work(self):
  result=self.onboarding.connect(self.root,self.repo,self.value['fingerprint'])
  self.assertTrue(result['connected']);entry=json.loads((self.root/'data/control.json').read_text())['projects']['demo']
  self.assertFalse({'id','company'}&set(entry));self.assertEqual((entry['repo'],entry['integration'],entry['name']),(str(self.repo),'observe','demo'))
  receipt=json.loads((self.repo/'.agent/local/onboarding.json').read_text())
  self.assertEqual((receipt['phase'],receipt['company'],receipt['project'],receipt['tracker']),('connected',None,None,'local'))
  dispatch=module('dispatch','dispatch_local');health=module('health','health_local');launch=module('launch_loops','launch_local');console=module('console','console_local')
  tracker=open_tracker(self.root)
  self.assertEqual(dispatch.reconcile(self.root,tracker),[]);self.assertEqual(health.reconcile(self.root,tracker),0);launch.launch(self.root)
  value=console.status(self.root);self.assertEqual(value['tracker'],'local');self.assertIn('demo',[p['id'] for p in value['projects']])

class MaintenanceLocal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'repo':str(self.root)}},'agents':{}}))
  (self.root/'data/autonomy-policies').mkdir();(self.root/'data/autonomy-policies/demo.json').write_text('{}')
  (self.root/'data/delivery-bindings').mkdir();(self.root/'data/project-state').mkdir();(self.root/'data/project-state/enabled').touch()
  Store(self.root).ensure('demo');self.jobs=Jobs(self.root)

 def test_every_maintenance_step_runs_locally(self):
  names=('retention','binding_requests','planning-recovery','publication-recovery','restart-recovery','dispatch','state-sync','delivery-control','health','loop-status','maintenance')
  mods={name:module(name,'maint_'+name.replace('-','_')) for name in names};tracker=LocalTracker(self.jobs,self.root)
  with patch.object(mods['delivery-control'],'ROOT',self.root):
   self.assertIsInstance(mods['retention'].maintain(self.root),dict)
   self.assertEqual(mods['binding_requests'].reconcile(self.root,tracker),[])
   self.assertEqual(mods['planning-recovery'].reconcile(self.root,tracker),[])
   self.assertEqual(mods['publication-recovery'].reconcile(self.root),[])
   self.assertEqual(mods['restart-recovery'].reconcile(self.root,tracker),[])
   self.assertEqual(mods['dispatch'].reconcile(self.root,tracker),[])
   self.assertTrue(mods['state-sync'].sync(self.root))
   self.assertIsNone(mods['delivery-control'].sync_prs())
   self.assertEqual(mods['health'].reconcile(self.root,tracker),0)
   self.assertIn(['python3','bin/loop-status.py','demo'],mods['maintenance'].commands(self.root))
   with patch.object(mods['loop-status'],'ROOT',self.root):mods['loop-status'].report('demo')


class PaperclipFreeBin(unittest.TestCase):
 """No module under bin/ imports the retired Paperclip client, references PAPERCLIP_ or its API paths."""
 RETIRED={'board','bridge','metrics','supervise','provision','provision_gtp','setup_fixture','fixture_worker','gtp_worker','gtp_resume','control','install-ui'}
 PATTERNS=('PAPERCLIP_','/companies/','/auth/get-session','/issues/','paperclipai')
 def files(self):
  return [p for p in BIN.iterdir() if p.suffix in ('.py','.mjs') and p.name!='tracker.py']
 def test_no_module_imports_or_references_paperclip(self):
  for path in self.files():
   with self.subTest(module=path.name):
    text=path.read_text()
    for name in self.RETIRED:
     self.assertNotRegex(text,r'(?m)^\s*(?:from|import)\s+'+name+r'\b',path.name)
    for pattern in self.PATTERNS:self.assertNotIn(pattern,text,path.name)
 def test_only_the_tracker_names_the_retired_product(self):
  # tracker.py keeps one message: an old install gets a clear error and the tag to migrate on.
  occurrences={p.name for p in BIN.iterdir() if p.suffix in ('.py','.mjs') and 'Paperclip' in p.read_text()}
  self.assertEqual(occurrences,{'tracker.py'})
 def test_retired_entry_points_are_gone(self):
  for name in sorted(self.RETIRED):
   self.assertFalse((BIN/name).exists(),name);self.assertFalse((BIN/(name+'.py')).exists(),name)
  for name in ('paperclip','run-paperclip','show-login','change-password.py','patch-login-email.py','bootstrap-owner.py','repair-stale-queue.mjs','product-chat'):
   self.assertFalse((BIN/name).exists(),name)
  self.assertFalse((BIN.parent/'ui/server.mjs').exists())

class PaperclipFreeTree(unittest.TestCase):
 """Outside bin/, shipped code, units, skills and top-level docs no longer mention the retired product."""
 ROOTS=('ui','scripts','skills','deployment','templates','pm-skills','spec')
 FILES=('README.md','AGENTS.md','setup.py')
 def test_no_paperclip_outside_history_docs_and_tests(self):
  root=BIN.parent;paths=[root/name for name in self.FILES if (root/name).exists()]
  for folder in self.ROOTS:
   if (root/folder).exists():paths+=[p for p in (root/folder).rglob('*') if p.is_file() and not p.is_symlink()]
  self.assertTrue(paths)
  for path in paths:
   try:text=path.read_text()
   except (UnicodeDecodeError,OSError):continue
   with self.subTest(path=str(path.relative_to(root))):
    self.assertNotIn('paperclip',text.lower())

class Setup(unittest.TestCase):
 def test_setup_never_installs_or_references_the_retired_product(self):
  text=(BIN/'setup.py').read_text()
  for token in ('Paperclip','paperclip','board_url','install-ui','@paperclipai','npm'):self.assertNotIn(token,text)
  source=text.split('def main',1)[1]
  self.assertIn("'tracker':'local'",source)
  self.assertNotIn("'tracker':'paperclip'",source)

class OldControl(unittest.TestCase):
 """Maintenance, launcher and console tolerate a control.json that still carries retired fields."""
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=local_root(self.tmp.name)
  (self.root/'data/control.json').write_text(json.dumps({'company':'legacy-company','projects':{'demo':{'id':'legacy-project-id','company':'legacy-company','agents':{},'repo':str(self.root)}},'agents':{'demo:delivery':'legacy-agent-id'}}))
  for folder in ('autonomy-policies','delivery-policies','delivery-bindings','logs'):(self.root/'data'/folder).mkdir()
  (self.root/'data/autonomy-policies/demo.json').write_text('{}');(self.root/'data/delivery-policies/demo.json').write_text('{}')
  Store(self.root).ensure('demo');self.jobs=Jobs(self.root)

 def test_files_are_not_rewritten(self):
  before={p:p.read_bytes() for p in (self.root/'data').rglob('*.json')}
  maintenance=module('maintenance','maint_old_control');launch=module('launch_loops','launch_old_control');console=module('console','console_old_control')
  launch.launch(self.root)
  self.assertEqual(console.status(self.root)['tracker'],'local')
  maintenance.commands(self.root)
  self.assertEqual({p:p.read_bytes() for p in (self.root/'data').rglob('*.json')},before)

 def test_maintenance_and_console_work_on_the_old_control(self):
  maintenance=module('maintenance','maint_old_control2');console=module('console','console_old_control2');launch=module('launch_loops','launch_old_control2')
  steps=maintenance.commands(self.root);self.assertIn(['python3','bin/loop-status.py','demo'],steps)
  value=console.status(self.root);self.assertEqual([p['id'] for p in value['projects']],['demo'])
  self.assertFalse({'company','paperclip_id','company_prefix'}&set(value['projects'][0]))
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launch.launch(self.root)
  self.assertEqual([c.args[0][4] for c in run.call_args_list if c.args[0][:2]==['tmux','new-session']],[])

 def test_unsupported_tracker_setting_stops_console_maintenance_and_launcher(self):
  (self.root/'data/local-settings.json').write_text(json.dumps({'tracker':'paperclip'}))
  console=module('console','console_old_control3');maintenance=module('maintenance','maint_old_control3');launch=module('launch_loops','launch_old_control3')
  for call in (lambda:console.status(self.root),lambda:maintenance.commands(self.root),lambda:launch.launch(self.root)):
   with self.assertRaisesRegex(ValueError,'Unsupported tracker'):call()


class Units(unittest.TestCase):
 """Only looop-named user units ship; the board unit and old names are gone."""
 def test_unit_templates(self):
  units=BIN.parent/'deployment/systemd'
  names=sorted(path.name for path in units.iterdir())
  self.assertEqual(names,['looop-console.service','looop-loops.service','looop-loops.timer','looop-maintenance.service','looop-maintenance.timer'])
  timer=(units/'looop-loops.timer').read_text();self.assertIn('Unit=looop-loops.service',timer)
  self.assertIn('Unit=looop-maintenance.service',(units/'looop-maintenance.timer').read_text())
  for path in units.iterdir():self.assertNotIn('paperclip',path.read_text(),path.name)
  console=(units/'looop-console.service').read_text()
  self.assertIn('bin/console-server.py',console);self.assertIn('--host <tailscale IP>',console)
  self.assertNotIn('--host 0.0.0.0',console)
  self.assertIn('ExecStart=@ROOT@/bin/start-autonomy',(units/'looop-loops.service').read_text())

if __name__=='__main__':unittest.main()
