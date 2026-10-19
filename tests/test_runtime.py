import json,os,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import sandbox
from executor import command
class Runtime(unittest.TestCase):
 def test_project_checks_are_dispatched_not_executed_by_scheduler(self):
  import executor
  with tempfile.TemporaryDirectory() as d,patch.object(executor,'ROOT',pathlib.Path(d)),patch('sandbox.run',return_value=json.dumps({'argv':['python3','test.py'],'exit_code':0,'output':'agent observed pass','evidence_path':'artifact.log'})) as run:
   result=command(d,['python3','test.py'])
   self.assertEqual(result.returncode,0);self.assertEqual(run.call_count,1);self.assertIn('Execute the requested project check',run.call_args.args[2]);self.assertEqual(run.call_args.kwargs['role'],'readonly')

 def test_native_argv_no_gateway_no_key_in_argv_exact_flash(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'secrets').mkdir();(root/'secrets/commandcode.key').write_text('fixture-secret')
   for harness in ('codex','omp'):
    scratch=root/harness;scratch.mkdir()
    with patch.object(sandbox,'ROOT',root),patch.object(sandbox.shutil,'which',return_value='/cli'):
     argv,env,model=sandbox.invocation(root,scratch,{'harness':harness,'provider':'commandcode','model':'not-allowed'})
    self.assertEqual(argv[0],harness);self.assertNotIn('fixture-secret',' '.join(argv));self.assertEqual(env['LOOOP_PROVIDER_KEY'],'fixture-secret');self.assertEqual(model,sandbox.FLASH);self.assertNotIn('bwrap',argv)
    if harness=='omp':
     for flag in ('--smol','--slow','--plan'):self.assertEqual(argv[argv.index(flag)+1],'commandcode/'+sandbox.FLASH)
 def test_native_claude_subscription_auth_is_separate(self):
  with tempfile.TemporaryDirectory() as d,patch.object(sandbox.shutil,'which',return_value='/cli'),patch.object(sandbox,'claude_subscription',return_value=True),patch.dict(os.environ,{'ANTHROPIC_API_KEY':'paid-api','ANTHROPIC_BASE_URL':'https://unapproved'}):
   argv,env,_=sandbox.invocation(d,pathlib.Path(d),{'harness':'claude','provider':'claude_subscription'})
   self.assertEqual(argv[0],'claude');self.assertIn('--no-session-persistence',argv);self.assertNotIn('ANTHROPIC_API_KEY',env);self.assertNotIn('ANTHROPIC_BASE_URL',env)
   with self.assertRaises(ValueError):sandbox.invocation(d,pathlib.Path(d),{'harness':'claude','provider':'codex'})
 def test_final_outputs_and_usage(self):
  text,usage=sandbox.final_text('omp',json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'{}'}],'usage':{'input':12,'output':4}}}))
  self.assertEqual(text,'{}');self.assertEqual(usage['input_tokens'],12)
  text,_=sandbox.final_text('claude',json.dumps({'type':'result','result':'{}'}));self.assertEqual(text,'{}')
  with self.assertRaises(RuntimeError):sandbox.final_text('claude',json.dumps({'type':'result','is_error':True,'result':'failure'}))
 def test_temporary_dependencies_and_independent_git_metadata(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);repo=root/'repo';repo.mkdir();work=root/'work';work.mkdir();deps=root/'deps';deps.mkdir()
   subprocess.run(['git','init','-q',str(repo)],check=True)
   with sandbox.workspace_environment(work,deps,repo/'.git'):
    self.assertTrue((work/'node_modules').is_symlink());self.assertTrue((work/'.git').is_dir());self.assertFalse((work/'.git').is_symlink())
    subprocess.run(['git','config','custom.fixture','worker'],cwd=work,check=True)
   self.assertFalse((work/'node_modules').exists());self.assertFalse((work/'.git').exists());self.assertNotIn('worker',(repo/'.git/config').read_text())
 def test_real_process_output_readonly_and_quota_stop(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);work=root/'work';work.mkdir();scratch=root/'scratch'
   def invoke(work,scratch,route):return ['python3','-c',"import sys;sys.stdin.read();print('HTTP status 429');sys.exit(1)"],os.environ.copy(),'test'
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox,'invocation',side_effect=invoke) as called:
    with self.assertRaisesRegex(RuntimeError,'quota'):sandbox.run(work,scratch,'test',execution_route={'harness':'omp','provider':'commandcode'})
    with self.assertRaisesRegex(RuntimeError,'paused'):sandbox.run(work,root/'retry','test',execution_route={'harness':'omp','provider':'commandcode'})
    self.assertEqual(called.call_count,1)
   def modify(work,scratch,route):return ['python3','-c',"import sys;sys.stdin.read();open('source.py','w').write('bad');print('{}')"],os.environ.copy(),'test'
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox,'invocation',side_effect=modify):
    with self.assertRaisesRegex(RuntimeError,'modified source'):sandbox.run(work,root/'readonly','test')

 def test_output_is_bounded_without_total_timeout(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);work=root/'work';work.mkdir();scratch=root/'scratch'
   code="import sys,json;sys.stdin.read();print('x'*5000000);print(json.dumps({'type':'result','result':'{}'}))"
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox,'invocation',return_value=(['python3','-c',code],os.environ.copy(),'test')):
    result=sandbox.run(work,scratch,'test',execution_route={'harness':'claude','provider':'claude_subscription'})
   self.assertEqual(result,'{}');self.assertLessEqual((scratch/'events.jsonl').stat().st_size,4*1024*1024)
 def test_check_agent_cannot_change_reviewed_source(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'source.py').write_text('original')
   # Source immutability is a native Harness dispatch invariant.
   code="import pathlib,sys;sys.stdin.read();pathlib.Path('source.py').write_text('changed');print('{}')"
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox,'invocation',return_value=(['python3','-c',code],os.environ.copy(),'fixture')):
    with self.assertRaisesRegex(RuntimeError,'modified source'):sandbox.run(root,root/'run','check',execution_route={'harness':'claude','provider':'claude_subscription'})

 def test_actual_claude_auth_status_shape(self):
  for method,provider,expected in [('claude.ai','firstParty',True),('api_key','firstParty',False),('oauth_token','firstParty',True),('claude.ai','bedrock',False)]:
   with patch.object(sandbox.shutil,'which',return_value='/cli'),patch.object(sandbox.subprocess,'check_output',return_value=json.dumps({'loggedIn':True,'authMethod':method,'apiProvider':provider})):
    self.assertEqual(sandbox.claude_subscription(),expected)

 def test_browser_environment_shared_by_checks_and_harnesses(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);browser=root/'data/browsers/chromium-fixture/chrome-linux64/chrome';browser.parent.mkdir(parents=True);browser.write_text('fixture')
   with patch.object(sandbox,'ROOT',root),patch.dict(os.environ,{},clear=True):
    self.assertEqual(sandbox.execution_environment()['CHROMIUM_PATH'],str(browser))
    with patch.object(sandbox,'claude_subscription',return_value=True),patch.object(sandbox.shutil,'which',return_value='/cli'):
     _,env,_=sandbox.invocation(root,root,{'harness':'claude','provider':'claude_subscription'})
     self.assertEqual(env['CHROMIUM_PATH'],str(browser))
   with patch.object(sandbox,'ROOT',root),patch.dict(os.environ,{'CHROMIUM_PATH':'/project/browser'}):self.assertEqual(sandbox.execution_environment()['CHROMIUM_PATH'],'/project/browser')

 def test_nested_archive_cannot_discover_controller_git(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);subprocess.run(['git','init','-q',str(root)],check=True)
   subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.test','commit','--allow-empty','-qm','controller'],cwd=root,check=True)
   work=root/'data/workspace';work.mkdir(parents=True)
   code="import sys,subprocess,json;sys.stdin.read();p=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True);print(json.dumps({'type':'result','result':json.dumps({'exit':p.returncode,'head':p.stdout.strip()})}))"
   def invoke(*args):return ['python3','-c',code],{**os.environ,'GIT_DIR':str(root/'.git')},'fixture'
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox,'invocation',side_effect=invoke):
    missing=json.loads(sandbox.run(work,root/'missing','fixture',execution_route={'harness':'claude','provider':'claude_subscription'}))
    own=json.loads(sandbox.run(work,root/'own','fixture',git_metadata=root/'.git',execution_route={'harness':'claude','provider':'claude_subscription'}))
   self.assertNotEqual(missing['exit'],0);self.assertEqual(missing['head'],'')
   self.assertEqual(own['exit'],0);self.assertEqual(own['head'],subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip())
   self.assertFalse((work/'.git').exists())

 def test_schema_flags_and_claude_structured_output(self):
  from output_protocol import delivery_schema
  schema=delivery_schema('review')
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);work=root/'work';work.mkdir()
   # Mock only process creation after argument construction.
   class Stop(Exception):pass
   for harness,flag in [('codex','--output-schema'),('claude','--json-schema')]:
    argv=['codex','exec','-'] if harness=='codex' else ['claude','-p']
    with patch.object(sandbox,'ROOT',root),patch.object(sandbox,'invocation',return_value=(argv,os.environ.copy(),'fixture')),patch.object(sandbox.subprocess,'Popen',side_effect=Stop) as process:
     with self.assertRaises(Stop):sandbox.run(work,root/harness,'Fixture',execution_route={'harness':harness,'provider':'codex'},output_schema=schema)
    self.assertIn(flag,process.call_args.args[0])
   text,_=sandbox.final_text('claude',json.dumps({'type':'result','result':'ignored prose','structured_output':{'verdict':'blocked','findings':['Missing evidence']}}))
   self.assertEqual(json.loads(text)['verdict'],'blocked')

 def test_claude_commandcode_uses_private_bridge_and_fixed_model(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);folder=root/'data/commandcode-claude';folder.mkdir(parents=True);(folder/'client.key').write_text('PRIVATE-BRIDGE-KEY')
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox.shutil,'which',return_value='/cli'),patch.dict(os.environ,{'ANTHROPIC_API_KEY':'unwanted','ANTHROPIC_AUTH_TOKEN':'unwanted','CLAUDE_CODE_OAUTH_TOKEN':'unwanted','ANTHROPIC_BASE_URL':'https://unwanted'}),patch.object(sandbox,'claude_subscription',side_effect=AssertionError('Subscription must not be consulted')):
    argv,env,model=sandbox.invocation(root,root,{'harness':'claude','provider':'commandcode','model':'unwanted-model'})
   self.assertEqual(model,sandbox.FLASH)
   self.assertIn(sandbox.FLASH,argv)
   self.assertEqual(env['ANTHROPIC_BASE_URL'],'http://127.0.0.1:8318')
   self.assertEqual(env['ANTHROPIC_API_KEY'],'PRIVATE-BRIDGE-KEY')
   self.assertNotIn('ANTHROPIC_AUTH_TOKEN',env);self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN',env)
   for name in ('HAIKU','SONNET','OPUS'):self.assertEqual(env['ANTHROPIC_DEFAULT_'+name+'_MODEL'],sandbox.FLASH)
