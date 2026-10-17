import json,os,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import sandbox
from executor import command
class Runtime(unittest.TestCase):
 def test_checks_use_real_cwd_and_host_tools(self):
  with tempfile.TemporaryDirectory() as d:

   with patch.dict(os.environ,{'EXPECTED_CWD':d}):result=command(d,['python3','-c',"import os,shutil;assert os.getcwd()==os.environ['EXPECTED_CWD'];assert shutil.which('node');open('owned','w').write('ok')"],writable=True)
   self.assertEqual(result.returncode,0,result.stdout);self.assertEqual((pathlib.Path(d)/'owned').read_text(),'ok')
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
 def test_native_claude_only_subscription_auth(self):
  with tempfile.TemporaryDirectory() as d,patch.object(sandbox.shutil,'which',return_value='/cli'),patch.object(sandbox,'claude_subscription',return_value=True),patch.dict(os.environ,{'ANTHROPIC_API_KEY':'paid-api','ANTHROPIC_BASE_URL':'https://unapproved'}):
   argv,env,_=sandbox.invocation(d,pathlib.Path(d),{'harness':'claude','provider':'claude_subscription'})
   self.assertEqual(argv[0],'claude');self.assertIn('--no-session-persistence',argv);self.assertNotIn('ANTHROPIC_API_KEY',env);self.assertNotIn('ANTHROPIC_BASE_URL',env)
   with self.assertRaises(ValueError):sandbox.invocation(d,pathlib.Path(d),{'harness':'claude','provider':'commandcode'})
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
 def test_check_cannot_change_reviewed_source(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'source.py').write_text('original')
   with self.assertRaisesRegex(RuntimeError,'modified source'):command(root,['python3','-c',"open('source.py','w').write('changed')"])

 def test_actual_claude_auth_status_shape(self):
  for method,provider,expected in [('claude.ai','firstParty',True),('api_key','firstParty',False),('oauth_token','firstParty',True),('claude.ai','bedrock',False)]:
   with patch.object(sandbox.shutil,'which',return_value='/cli'),patch.object(sandbox.subprocess,'check_output',return_value=json.dumps({'loggedIn':True,'authMethod':method,'apiProvider':provider})):
    self.assertEqual(sandbox.claude_subscription(),expected)

 def test_browser_environment_shared_by_checks_and_harnesses(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);browser=root/'data/browsers/chromium-fixture/chrome-linux64/chrome';browser.parent.mkdir(parents=True);browser.write_text('fixture')
   with patch.object(sandbox,'ROOT',root),patch.dict(os.environ,{},clear=True):
    self.assertEqual(sandbox.execution_environment()['CHROMIUM_PATH'],str(browser))
    check=command(root,['/usr/bin/python3','-c',"import os;print(os.environ['CHROMIUM_PATH'])"])
    self.assertEqual(check.returncode,0,check.stdout);self.assertEqual(check.stdout.strip(),str(browser))
    with patch.object(sandbox,'claude_subscription',return_value=True),patch.object(sandbox.shutil,'which',return_value='/cli'):
     _,env,_=sandbox.invocation(root,root,{'harness':'claude','provider':'claude_subscription'})
     self.assertEqual(env['CHROMIUM_PATH'],str(browser))
   with patch.object(sandbox,'ROOT',root),patch.dict(os.environ,{'CHROMIUM_PATH':'/project/browser'}):self.assertEqual(sandbox.execution_environment()['CHROMIUM_PATH'],'/project/browser')
