"""P1d: import legacy bindings, deliveries and planning receipts into jobs."""
import contextlib,importlib.util,io,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bin'))
import binding_requests,dispatch,health,job_migration,launch_loops
from jobs import Jobs
from tracker import LocalTracker

def load(name):
 spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'bin'/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

worker=load('delivery-worker')
CLI=ROOT/'scripts/migrate-jobs.py'

class Base(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  self.write('data/control.json',{'projects':{'test':{'id':'project'}},'agents':{}})
 def tearDown(self):self.tmp.cleanup()
 def write(self,name,value):
  path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False));return path
 def delivery(self,job_id,title='Packet',lane='test'):
  return self.write('data/delivery-bindings/'+job_id+'.json',{'lane':lane,'packet':{'title':title}})
 def receipt(self,job_id,state):
  return self.write('data/deliveries/'+job_id+'/state.json',{'state':state})
 def rows(self,result):return {row['id']:row for row in result['jobs']}
 def files(self):return {str(path.relative_to(self.root)) for path in self.root.rglob('*') if path.is_file()}
 def migrate(self,apply=False):return job_migration.migrate(self.root,apply=apply)
 def store(self):return Jobs(self.root)
 def job(self,job_id):return Jobs(self.root).get(job_id)
 def cli_run(self,*args):return subprocess.run([sys.executable,str(CLI),'--root',str(self.root),*args],capture_output=True,text=True)
 def cli(self):
  spec=importlib.util.spec_from_file_location('migrate_jobs_cli',CLI)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class DM(Base):
 def test_delivery_states(self):
  states={'merged':'done','validated':'done','closed':'cancelled','waiting_for_merge':'in_review',
   'blocked':'blocked','planning':'in_progress','building':'in_progress','checking':'in_progress',
   'review_standard':'in_progress','acceptance':'in_progress','pr_ready':'in_progress','queued':'in_progress','none':'todo'}
  for job_id,state in states.items():
   self.delivery(job_id)
   if state!='todo':self.receipt(job_id,state)
  result=self.migrate(apply=True);store=self.store();rows=self.rows(result)
  for job_id,state in states.items():
   with self.subTest(state=state):
    expected=('done' if state in ('merged','validated') else 'cancelled' if state=='closed' else
     'in_review' if state=='waiting_for_merge' else 'blocked' if state=='blocked' else
     'todo' if state=='todo' else 'in_progress')
    assignee='test:delivery' if expected in ('todo','in_progress') else 'owner'
    job=store.get(job_id)
    self.assertEqual((job['kind'],job['lane'],job['title'],job['status'],job['assignee']),
     ('delivery','test','Packet',expected,assignee))
    self.assertTrue(rows[job_id]['source'].endswith('data/delivery-bindings/'+job_id+'.json'))
  self.assertEqual(result['counts']['jobs'],len(states))
 def test_orphan(self):
  self.receipt('orphan','merged')
  result=self.migrate()
  self.assertEqual(result['orphans'],['orphan']);self.assertNotIn('orphan',self.rows(result))

class PM(Base):
 STATES={'queued':'done','no_work':'done','cancelled':'cancelled','rejected':'done','blocked':'blocked',
  'proposing':'in_progress','product_scope_review':'in_progress','binding':'in_progress','discovering':'in_progress','unknown':'blocked'}
 def test_planning_states(self):
  for attempt,expected in self.STATES.items():
   self.write('data/autonomy/test/'+attempt+'/state.json',{'state':attempt,'issue':'issue-'+attempt})
  self.write('data/autonomy/test/test-status.json',{'state':'blocked'})
  self.write('data/autonomy/test/not-a-directory','x')
  self.migrate(apply=True);store=self.store()
  for attempt,expected in self.STATES.items():
   with self.subTest(state=expected):
    row=store.get('issue-'+attempt)
    self.assertEqual((row['kind'],row['lane'],row['title'],row['status'],row['assignee']),
     ('planning','test','PM / '+attempt,expected,'owner'))
  self.assertNotIn('test-status',[job['id'] for job in store.list()])

class SD(Base):
 def test_status_body(self):
  self.write('data/loop-dashboard/test.json',{'issue':'status-one','body':'状态正文'})
  self.write('data/loop-dashboard/empty.json',{'body':'no issue'})
  self.migrate(apply=True);row=self.job('status-one')
  self.assertEqual((row['kind'],row['lane'],row['title'],row['description'],row['status'],row['assignee']),
   ('status','test','自动队列 / 当前状态与阻塞原因','状态正文','in_progress','owner'))
 def test_duplicates(self):
  self.delivery('shared');self.receipt('shared','merged')
  self.write('data/autonomy/test/reused/state.json',{'state':'queued','issue':'shared'})
  self.write('data/loop-dashboard/test.json',{'issue':'shared','body':'status'})
  result=self.migrate()
  self.assertEqual(len(result['jobs']),1);row=result['jobs'][0]
  self.assertEqual((row['id'],row['kind'],row['status']),('shared','delivery','done'))
  self.assertEqual(result['duplicates'],['shared'])

class DR(Base):
 def test_dry_run(self):
  self.delivery('dry');self.write('data/loop-dashboard/test.json',{'issue':'status','body':'body'})
  before=sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file())
  result=self.migrate()
  after=sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file())
  self.assertEqual((result['mode'],result['counts']['planned']),('dry-run',2))
  self.assertEqual({row['result'] for row in result['jobs']},{'planned'})
  self.assertEqual(before,after);self.assertFalse((self.root/'data/jobs.sqlite').exists())
  self.assertFalse((self.root/'data/jobs.sqlite-wal').exists());self.assertFalse((self.root/'data/locks').exists())
 def test_cli_dry_run(self):
  self.delivery('cli')
  run=self.cli_run()
  self.assertEqual(run.returncode,0,run.stderr)
  self.assertEqual(json.loads(run.stdout)['mode'],'dry-run')
  self.assertFalse((self.root/'data/jobs.sqlite').exists())

class AP(Base):
 def test_apply_idempotent(self):
  self.delivery('task-one','First');self.receipt('task-one','merged')
  self.write('data/autonomy/test/attempt/state.json',{'state':'queued','issue':'pm-one'})
  self.write('data/loop-dashboard/test.json',{'issue':'status-one','body':'状态正文'})
  first=self.migrate(apply=True)
  self.assertEqual(first['mode'],'apply');self.assertEqual(first['counts']['created'],3)
  self.assertEqual(first['conflicts'],[]);self.assertEqual(first['errors'],[])
  store=self.store()
  self.assertEqual(store.get('task-one')['status'],'done')
  self.assertEqual((store.get('pm-one')['kind'],store.get('pm-one')['status']),('planning','done'))
  self.assertEqual((store.get('status-one')['description'],store.get('status-one')['status']),('状态正文','in_progress'))
  created=store.events('task-one')
  self.assertEqual([event['kind'] for event in created],['created','comment'])
  self.assertTrue(created[-1]['body'].startswith('migrated from '))
  self.assertTrue(created[-1]['body'].endswith('data/delivery-bindings/task-one.json'))
  before={job['id']:store.get(job['id']) for job in first['jobs']}
  second=self.migrate(apply=True)
  self.assertEqual(second['counts']['existing'],3);self.assertEqual(second['counts']['created'],0);self.assertEqual(second['conflicts'],[])
  self.assertEqual({row['result'] for row in second['jobs']},{'existing'})
  self.assertFalse(any('differs' in row for row in second['jobs']))
  self.assertEqual({job['id']:store.get(job['id']) for job in second['jobs']},before)
  self.assertEqual([event['kind'] for event in store.events('task-one')],['created','comment'])
 def test_changed_source(self):
  self.delivery('task-one','Original')
  self.assertEqual(self.migrate(apply=True)['counts']['created'],1)
  store=self.store();store.update('task-one',status='blocked',assignee='owner',description='old')
  before=store.get('task-one');self.delivery('task-one','Changed')
  changed=self.migrate(apply=True);row=self.rows(changed)['task-one']
  self.assertEqual(row['result'],'existing')
  self.assertEqual(set(row['differs']),{'status','title','assignee','description'})
  self.assertEqual(changed['conflicts'],[]);self.assertEqual(store.get('task-one'),before)
  run=self.cli_run('--apply')
  self.assertEqual(run.returncode,0,run.stderr)
  self.assertEqual(json.loads(run.stdout)['conflicts'],[])
 def test_conflicts(self):
  self.delivery('kind-conflict');self.delivery('lane-conflict')
  store=self.store()
  store.create('test','planning','Existing','',status='done',assignee='owner',job_id='kind-conflict')
  store.create('other','delivery','Existing','',status='todo',assignee='owner',job_id='lane-conflict')
  result=self.migrate(apply=True)
  self.assertEqual(set(result['conflicts']),{'kind-conflict','lane-conflict'})
  self.assertEqual({self.rows(result)[job_id]['result'] for job_id in result['conflicts']},{'conflict'})
  self.assertEqual(result['errors'],[]);self.assertEqual(result['counts']['created'],0)
  run=self.cli_run('--apply')
  self.assertEqual(run.returncode,1,run.stderr)
  self.assertEqual(set(json.loads(run.stdout)['conflicts']),{'kind-conflict','lane-conflict'})
 def test_apply_paths(self):
  self.delivery('only')
  before=self.files()
  self.migrate(apply=True)
  new=self.files()-before
  allowed={'data/jobs.sqlite','data/jobs.sqlite-wal','data/jobs.sqlite-shm','data/locks/migrate-jobs','data/.jobs.lock'}
  self.assertLessEqual(new,allowed)
  self.assertIn('data/jobs.sqlite',new);self.assertIn('data/locks/migrate-jobs',new)
 def test_missing_control(self):
  (self.root/'data/control.json').unlink()
  with self.assertRaisesRegex(ValueError,'control.json'):self.migrate(apply=True)
  self.assertFalse((self.root/'data/jobs.sqlite').exists())
 def test_cli_has_no_board_overlay_and_runs_offline(self):
  self.delivery('offline')
  module=self.cli();out=io.StringIO()
  with contextlib.redirect_stdout(out):
   with self.assertRaises(SystemExit) as raised:module.main(['--root',str(self.root),'--board'])
  self.assertEqual(raised.exception.code,2)
  self.assertFalse((self.root/'data/jobs.sqlite').exists())
  with contextlib.redirect_stdout(io.StringIO()):
   code=module.main(['--root',str(self.root),'--apply'])
  self.assertEqual(code,0)
  self.assertEqual(self.job('offline')['status'],'todo')

class SI(Base):
 def test_source_errors(self):
  self.delivery('good');self.delivery('bad-receipt');self.write('data/deliveries/bad-receipt/state.json','{')
  cases=[('data/delivery-bindings/broken.json','{'),('data/delivery-bindings/non-object.json','[]'),
   ('data/delivery-bindings/bad-lane.json',{'lane':'Bad Lane'}),
   ('data/autonomy/test/no-issue/state.json',{'state':'queued'}),
   ('data/autonomy/test/numeric/state.json',{'state':'queued','issue':7}),
   ('data/autonomy/Bad Lane/x/state.json',{'state':'queued','issue':'x'}),
   ('data/loop-dashboard/broken.json','{'),('data/loop-dashboard/no-issue.json',{'body':'x'}),
   ('data/loop-dashboard/numeric.json',{'issue':7})]
  for path,value in cases:self.write(path,value)
  result=self.migrate()
  self.assertEqual([row['id'] for row in result['jobs']],['good'])
  self.assertEqual(result['counts']['errors'],10);self.assertEqual(len(result['errors']),10)
  for entry in result['errors']:
   self.assertEqual(set(entry),{'source','error'})
   self.assertTrue(isinstance(entry['source'],str) and entry['source'])
   self.assertTrue(isinstance(entry['error'],str) and entry['error'])
  names={pathlib.PurePath(entry['source']).name for entry in result['errors']}
  self.assertTrue({'broken.json','non-object.json','state.json'}<=names)
  applied=self.migrate(apply=True)
  self.assertEqual(self.rows(applied)['good']['result'],'created')
  self.assertEqual((applied['counts']['created'],applied['counts']['errors']),(1,10))
  self.assertEqual(self.job('good')['status'],'todo')
  run=self.cli_run('--apply')
  self.assertEqual(run.returncode,1,run.stderr)
  self.assertEqual(json.loads(run.stdout)['counts']['errors'],10)

class CE(Base):
 def test_create_error(self):
  self.write('data/loop-dashboard/test.json',{'issue':'bad-body','body':5})
  result=self.migrate(apply=True);row=self.rows(result)['bad-body']
  self.assertEqual(row['result'],'error');self.assertIn('strings',row['error'])
  self.assertEqual(result['conflicts'],[]);self.assertEqual(result['counts']['errors'],1)
  self.assertIsNone(self.job('bad-body'))
  self.write('data/loop-dashboard/test.json',{'issue':'bad-body','body':'fixed'})
  again=self.migrate(apply=True)
  self.assertEqual(self.rows(again)['bad-body']['result'],'created')
  self.assertEqual(self.job('bad-body')['description'],'fixed')

class IN(Base):
 def setUp(self):
  super().setUp()
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
  self.repo=self.root/'repo';self.repo.mkdir()
  subprocess.run(['git','init','-q',str(self.repo)],check=True)
  self.policy={'repo':str(self.repo)}
  self.binding={'lane':'test','packet':{'title':'Bound packet'},'policy':self.policy,'owner':'owner','publish':False}
  self.write('data/delivery-bindings/task-todo.json',self.binding)
  self.write('data/delivery-bindings/task-done.json',{**self.binding,'packet':{'title':'Done packet'}})
  self.receipt('task-done','merged')
  self.write('data/autonomy/test/pm-one/state.json',{'state':'queued','issue':'pm-one'})
  self.write('data/loop-dashboard/test.json',{'issue':'status-one','body':'status'})
  self.result=self.migrate(apply=True)
  self.jobs=Jobs(self.root);self.tracker=LocalTracker(self.jobs,self.root)
 def test_integration(self):
  self.assertEqual(self.result['counts']['created'],4)
  self.assertEqual(dispatch.reconcile(self.root,self.tracker),[])
  self.assertEqual(health.reconcile(self.root,self.tracker),0)
  self.assertEqual(self.jobs.get('task-done')['status'],'done')
  journal=self.write('data/operator-requests/job/binding-request.json',
   {'state':'binding','binding':self.binding,'issue':{'id':'task-todo'}})
  self.assertEqual(binding_requests.reconcile(self.root,self.tracker),[{'job':'task-todo','state':'bound'}])
  self.assertEqual(json.loads(journal.read_text())['state'],'bound')
  with patch.object(worker,'ROOT',self.root),patch.object(worker,'execute',return_value={'state':'validated'}) as execute:
   worker.heartbeat('test')
   worker.heartbeat('test')
  execute.assert_called_once()
  self.assertEqual((self.jobs.get('task-todo')['status'],self.jobs.get('task-todo')['assignee']),('done','owner'))
