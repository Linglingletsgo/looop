import json,os,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import execution_settings as settings,sandbox


def events(*values):
 return '\n'.join(json.dumps(value) for value in values)


class Invocation(unittest.TestCase):
 def test_command_environment_and_model_label(self):
  with tempfile.TemporaryDirectory() as d,patch.object(sandbox.shutil,'which',return_value='/cli/dsh'),patch.dict(os.environ,{'OPENAI_API_KEY':'paid','ANTHROPIC_API_KEY':'paid','OPENAI_BASE_URL':'https://unapproved','LOOOP_PROVIDER_KEY':'ambient'},clear=False):
   argv,env,model=sandbox.invocation(d,pathlib.Path(d),{'harness':'dsh','provider':'dsh_profile'})
  self.assertEqual(argv,['dsh','--profile','headless','--json','-'])
  self.assertEqual(model,'dsh:headless')
  self.assertNotIn('LOOOP_PROVIDER_KEY',env)
  for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','OPENAI_BASE_URL'):self.assertNotIn(key,env)

 def test_requires_dsh_binary(self):
  with tempfile.TemporaryDirectory() as d,patch.object(sandbox.shutil,'which',return_value=None):
   with self.assertRaisesRegex(RuntimeError,'not installed: dsh'):sandbox.invocation(d,pathlib.Path(d),{'harness':'dsh','provider':'dsh_profile'})

 def test_incompatible_pairs_are_rejected(self):
  pairs=[('dsh','codex'),('dsh','magpie_flash_pool'),('codex','dsh_profile'),('claude','dsh_profile'),('omp','dsh_profile')]
  with tempfile.TemporaryDirectory() as d,patch.object(sandbox.shutil,'which',return_value='/cli'):
   for harness,provider in pairs:
    with self.assertRaises(ValueError):sandbox.invocation(d,pathlib.Path(d),{'harness':harness,'provider':provider})


class FinalText(unittest.TestCase):
 def test_last_final_and_step_usage(self):
  text,usage=sandbox.final_text('dsh',events(
   {'type':'session','sessionId':'fixture'},
   {'type':'status','phase':'step_end','usage':{'inputTokens':10,'outputTokens':2,'totalTokens':12,'cacheReadTokens':3}},
   {'type':'text','text':'intermediate'},
   {'type':'status','phase':'step_end','usage':{'inputTokens':5,'outputTokens':4,'totalTokens':9,'cacheReadTokens':1}},
   {'type':'status','phase':'turn_end','reason':{'kind':'completed'}},
   {'type':'final','text':'first'},
   {'type':'final','text':'dsh answer'}))
  self.assertEqual(text,'dsh answer')
  self.assertEqual(usage,{'input_tokens':15,'cached_input_tokens':4,'output_tokens':6})

 def test_error_without_final_fails(self):
  with self.assertRaisesRegex(RuntimeError,'DeepSeek Harness failed'):
   sandbox.final_text('dsh',events({'type':'error','message':'boom'}))

 def test_non_completed_turn_without_final_fails(self):
  with self.assertRaisesRegex(RuntimeError,'DeepSeek Harness failed'):
   sandbox.final_text('dsh',events({'type':'status','phase':'turn_end','reason':{'kind':'error'}}))

 def test_final_wins_over_earlier_error(self):
  text,_=sandbox.final_text('dsh',events({'type':'error','message':'retry'},{'type':'final','text':'recovered'}))
  self.assertEqual(text,'recovered')


class Run(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.work=self.root/'work';self.work.mkdir();self.bin=self.root/'bin';self.bin.mkdir()
 def tearDown(self):self.tmp.cleanup()
 def fake(self,body):
  path=self.bin/'dsh';path.write_text('#!'+sys.executable+'\n'+body);path.chmod(0o755)
  self.addCleanup(path.unlink,missing_ok=True)
  return {'PATH':str(self.bin)}
 def test_success_failure_and_429_pause(self):
  env=self.fake("import json,sys\nsys.stdin.read()\nprint(json.dumps({'type':'session','sessionId':'fixture'}))\nprint(json.dumps({'type':'status','phase':'step_end','usage':{'inputTokens':7,'outputTokens':3,'totalTokens':10,'cacheReadTokens':2}}))\nprint(json.dumps({'type':'final','text':'dsh answer'}))\nprint(json.dumps({'type':'status','phase':'turn_end','reason':{'kind':'completed'}}))\n")
  with patch.object(sandbox,'ROOT',self.root),patch.object(sandbox,'execution_environment',return_value=env):
   self.assertEqual(sandbox.run(self.work,self.root/'success','task',execution_route={'harness':'dsh','provider':'dsh_profile'}),'dsh answer')
  usage=json.loads((self.root/'success/usage.json').read_text())
  self.assertEqual((usage['harness'],usage['provider'],usage['model']),('dsh','dsh_profile','dsh:headless'))
  self.assertEqual((usage['input_tokens'],usage['output_tokens'],usage['cached_input_tokens']),(7,3,2))
  self.fake("import json,sys\nsys.stdin.read()\nprint(json.dumps({'type':'error','message':'boom'}))\n")
  with patch.object(sandbox,'ROOT',self.root),patch.object(sandbox,'execution_environment',return_value=env):
   with self.assertRaisesRegex(RuntimeError,'DeepSeek Harness failed'):
    sandbox.run(self.work,self.root/'failure','task',execution_route={'harness':'dsh','provider':'dsh_profile'})
  # Real dsh shape (0.2.1): non-completed turn, empty final, provider error on stderr, exit 1.
  self.fake("import json,sys\nsys.stdin.read()\nprint(json.dumps({'type':'status','phase':'turn_end','reason':{'kind':'error','error':{'message':'429: {\\\\\"message\\\\\":\\\\\"quota exceeded\\\\\"}','code':'QUOTA'}}}))\nprint(json.dumps({'type':'final','text':''}))\nsys.stdout.flush()\nprint('dsh: QUOTA: 429: quota exceeded for this route',file=sys.stderr)\nsys.exit(1)\n")
  with patch.object(sandbox,'ROOT',self.root),patch.object(sandbox,'execution_environment',return_value=env):
   with self.assertRaisesRegex(RuntimeError,'quota: HTTP 429'):
    sandbox.run(self.work,self.root/'quota','task',execution_route={'harness':'dsh','provider':'dsh_profile'})
  self.assertEqual(json.loads((self.root/'data/quota-dsh_profile.json').read_text())['http_status'],429)


class Settings(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.home=self.root/'home';self.home.mkdir()
  # dsh_ready() prefers DSH_HOME; pin it to the fake home so the ambient value cannot leak in.
  env=patch.dict(os.environ,{'DSH_HOME':str(self.home/'.dsh')});env.start();self.addCleanup(env.stop)
 def tearDown(self):self.tmp.cleanup()
 def command(self,harness='dsh',provider='dsh_profile'):
  return {'harness':harness,'routes':{stage:provider for stage in settings.STAGES},'codex_model':None}
 def test_save_and_public_when_dsh_profile_exists(self):
  (self.home/'.dsh/profiles/headless').mkdir(parents=True)
  with patch.object(settings.pathlib.Path,'home',return_value=self.home),patch.object(settings.shutil,'which',side_effect=lambda name:'/cli/'+name),patch.object(settings,'claude_subscription',return_value=False):
   settings.save(self.root,self.command(),0,'dsh')
   saved=settings.read(self.root);self.assertEqual(saved['harness'],'dsh');self.assertEqual(settings.route(saved,'review'),{'harness':'dsh','provider':'dsh_profile','model':None})
   public=settings.public(self.root)
  self.assertEqual(public['plan_labels']['dsh_profile'],'DeepSeek Harness / dsh 配置（Magpie）')
  self.assertTrue(next(item for item in public['harnesses'] if item['id']=='dsh')['installed'])
  self.assertTrue(next(item for item in public['plans'] if item['id']=='dsh_profile')['configured'])
  self.assertEqual(public['compatibility']['dsh'],('dsh_profile',))

 def test_save_refuses_missing_binary_or_profile(self):
  with patch.object(settings.pathlib.Path,'home',return_value=self.home),patch.object(settings.shutil,'which',return_value=None):
   with self.assertRaisesRegex(ValueError,'dsh'):settings.save(self.root,self.command(),0,'no-binary')
  with patch.object(settings.pathlib.Path,'home',return_value=self.home),patch.object(settings.shutil,'which',side_effect=lambda name:'/cli/'+name),patch.object(settings,'claude_subscription',return_value=False):
   with self.assertRaisesRegex(ValueError,'profiles/headless'):settings.save(self.root,self.command(),0,'no-profile')
   public=settings.public(self.root)
  self.assertFalse(next(item for item in public['plans'] if item['id']=='dsh_profile')['configured'])

 def test_incompatible_pairs_and_harness_choices(self):
  with patch.object(settings.pathlib.Path,'home',return_value=self.home),patch.object(settings.shutil,'which',return_value='/cli'):
   with self.assertRaisesRegex(ValueError,'不兼容'):settings.save(self.root,self.command('dsh','codex'),0,'dsh-codex')
   command=self.command('codex','codex');command['routes']['review']='dsh_profile'
   with self.assertRaisesRegex(ValueError,'不兼容'):settings.save(self.root,command,0,'codex-dsh')
   with self.assertRaisesRegex(ValueError,'DeepSeek Harness'):settings.save(self.root,self.command('pi','codex'),0,'bad-harness')


class DshHermetic(unittest.TestCase):
 def test_install_check_uses_execution_path_and_permission_mode(self):
  with tempfile.TemporaryDirectory() as tmp:
   fake=pathlib.Path(tmp)/'dsh';fake.write_text('#!/bin/sh\n');fake.chmod(0o755)
   with patch.dict(os.environ,{'PATH':'/usr/bin:/bin'}),patch.object(sandbox,'execution_environment',return_value={'PATH':tmp,'OPENAI_API_KEY':'x'}):
    cmd,env,model=sandbox.invocation(pathlib.Path(tmp),pathlib.Path(tmp),{'harness':'dsh','provider':'dsh_profile'})
   self.assertEqual(cmd,['dsh','--profile','headless','--json','-'])
   self.assertEqual(env['DSH_PERMISSION_MODE'],'danger-full-access')
   self.assertNotIn('OPENAI_API_KEY',env)
   with patch.object(sandbox,'execution_environment',return_value={'PATH':'/nonexistent'}):
    with self.assertRaisesRegex(RuntimeError,'Harness not installed: dsh'):
     sandbox.invocation(pathlib.Path(tmp),pathlib.Path(tmp),{'harness':'dsh','provider':'dsh_profile'})
 def test_tool_output_mentioning_quota_does_not_pause(self):
  events='{"type":"tool_result","result":"dsh: QUOTA: 429: page text"}\n{"type":"final","text":"done"}\n'
  self.assertIsNone(sandbox.PROVIDER_STATUS.search(events))
  self.assertEqual(sandbox.final_text('dsh',events)[0],'done')
 def test_readiness_honours_dsh_home(self):
  import execution_settings
  with tempfile.TemporaryDirectory() as tmp:
   (pathlib.Path(tmp)/'profiles/headless').mkdir(parents=True)
   with patch.dict(os.environ,{'DSH_HOME':tmp}),patch.object(execution_settings.shutil,'which',return_value='/x/dsh'):
    self.assertTrue(execution_settings.dsh_ready())
   with patch.dict(os.environ,{'DSH_HOME':tmp+'/missing'}),patch.object(execution_settings.shutil,'which',return_value='/x/dsh'):
    self.assertFalse(execution_settings.dsh_ready())
