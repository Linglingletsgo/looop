import hashlib,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import preview
class Preview(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  self.repo=self.root/'data/execution-repos/demo';self.repo.mkdir(parents=True)
  subprocess.run(['git','init','-q',str(self.repo)],check=True)
  for k,v in [('user.name','Test'),('user.email','test@example.test')]:preview.git(self.repo,'config',k,v)
  (self.repo/'schema.sql').write_text('approved schema')
  preview.git(self.repo,'add','.');preview.git(self.repo,'commit','-qm','mainline')
  self.sha=preview.git(self.repo,'rev-parse','HEAD').decode().strip()
  p=self.root/'data/mainline-verification';p.mkdir();self.receipt=p/'demo.json'
  self.receipt.write_text(json.dumps({'status':'passed','sha':self.sha,'merge_commit':self.sha}))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'repo':str(self.repo)}}}))
  self.old=self.root/'original';self.old.mkdir();(self.old/'draft').write_text('keep')
  self.cfg={'enabled':True,'fallback_repo':str(self.old),'reviewed_files':{'schema.sql':hashlib.sha256(b'approved schema').hexdigest()},'install_dirs':['.'],'services':[{'session':'demo','port':1234,'argv':['app'],'url':'http://127.0.0.1:1234'}]}
 def test_only_passed_verified_mainline_and_reviewed_schema_can_be_served(self):
  self.assertEqual(preview.checked_target(self.root,'demo',self.cfg)[1],self.sha)
  self.cfg['reviewed_files']['schema.sql']='wrong'
  with self.assertRaisesRegex(ValueError,'compatibility review'):preview.checked_target(self.root,'demo',self.cfg)
  self.receipt.write_text(json.dumps({'status':'failed','sha':self.sha}))
  with self.assertRaisesRegex(ValueError,'passed mainline'):preview.checked_target(self.root,'demo',self.cfg)
 def test_success_switches_preview_once_and_preserves_original(self):
  with patch('preview.checked_target',return_value=(self.repo,self.sha)),patch('preview.snapshot',side_effect=lambda r,s,p:p.mkdir()),patch('preview.subprocess.run',return_value=subprocess.CompletedProcess([],0)),patch('preview.stop'),patch('preview.start') as start,patch('preview.healthy',return_value=True):
   preview.update(self.root,'demo',self.cfg);preview.update(self.root,'demo',self.cfg)
  base=self.root/'data/previews/demo'
  self.assertEqual(start.call_count,1)
  self.assertEqual((base/'current').resolve(),base/'releases'/self.sha)
  self.assertEqual(json.loads((base/'state.json').read_text())['sha'],self.sha)
  self.assertEqual((self.old/'draft').read_text(),'keep')
 def test_readiness_failure_restarts_previous_version_without_publishing_new_sha(self):
  with patch('preview.checked_target',return_value=(self.repo,self.sha)),patch('preview.snapshot',side_effect=lambda r,s,p:p.mkdir()),patch('preview.subprocess.run',return_value=subprocess.CompletedProcess([],0)),patch('preview.stop'),patch('preview.start',side_effect=[ValueError('unhealthy'),None]) as start:
   with self.assertRaisesRegex(ValueError,'unhealthy'):preview.update(self.root,'demo',self.cfg)
  self.assertEqual(start.call_args.args[2],self.old)
  self.assertFalse((self.root/'data/previews/demo/current').exists())
 def test_install_failure_does_not_stop_running_preview(self):
  with patch('preview.checked_target',return_value=(self.repo,self.sha)),patch('preview.snapshot',side_effect=lambda r,s,p:p.mkdir()),patch('preview.subprocess.run',return_value=subprocess.CompletedProcess([],1)),patch('preview.stop') as stop:
   with self.assertRaisesRegex(ValueError,'installation failed'):preview.update(self.root,'demo',self.cfg)
  stop.assert_not_called()
 def test_service_configuration_change_restarts_same_verified_sha(self):
  with patch('preview.checked_target',return_value=(self.repo,self.sha)),patch('preview.snapshot',side_effect=lambda r,s,p:p.mkdir()),patch('preview.subprocess.run',return_value=subprocess.CompletedProcess([],0)),patch('preview.stop'),patch('preview.start') as start,patch('preview.healthy',return_value=True):
   preview.update(self.root,'demo',self.cfg)
   self.cfg['services'][0]['env']={'CHROMIUM_PATH':'/installed/browser'}
   preview.update(self.root,'demo',self.cfg)
  self.assertEqual(start.call_count,2)
  state=json.loads((self.root/'data/previews/demo/state.json').read_text())
  self.assertEqual(state['previous_path'],str(self.old))
 def test_pr_sync_reconciles_opt_in_previews_after_mainline_processing(self):
  import importlib.util
  path=pathlib.Path(preview.__file__).parent/'delivery-control.py'
  spec=importlib.util.spec_from_file_location('preview_test_control',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with patch.object(module,'ROOT',self.root),patch('preview.sync') as sync:
   module.sync_prs()
  sync.assert_called_once_with(self.root)
