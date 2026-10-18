import json,os,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import sandbox,handoff
from output_protocol import OutputError,delivery_schema
class FileHandoff(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.work=self.root/'work';self.work.mkdir();(self.work/'source.txt').write_text('unchanged');self.schema=delivery_schema('build')
 def test_strict_file_identity_and_schema(self):
  scratch=self.root/'run';scratch.mkdir();identity=handoff.prepare(scratch,self.schema);path=scratch/'handoff.json';doc={**identity,'result':{'verdict':'approved','findings':[],'summary':'Ready for checks'}};path.write_text(json.dumps(doc));self.assertEqual(handoff.read(scratch,self.schema,identity),doc['result'])
  for bad in ({**doc,'nonce':'stale'},{**doc,'result':None},{**doc,'result':{**doc['result'],'verdict':'success'}},{**doc,'result':{**doc['result'],'findings':'none'}}):
   path.write_text(json.dumps(bad))
   with self.assertRaises(OutputError):handoff.read(scratch,self.schema,identity)
  path.unlink();path.symlink_to(self.work/'source.txt')
  with self.assertRaises(OutputError):handoff.read(scratch,self.schema,identity)
 def test_duplicate_keys_and_stale_files_rejected(self):
  scratch=self.root/'run';scratch.mkdir();identity=handoff.prepare(scratch,self.schema)
  (scratch/'handoff.json').write_text('{"result":null,"result":{}}')
  with self.assertRaises(OutputError):handoff.read(scratch,self.schema,identity)
  with self.assertRaises(OutputError):handoff.prepare(scratch,self.schema)
 def invoke(self,scratch,body):
  code='import sys,json,pathlib;sys.stdin.read();p=pathlib.Path(sys.argv[1]);d=json.loads(p.read_text());'+body
  command=['python3','-c',code,str(scratch/'handoff.json')]
  with patch.object(sandbox,'ROOT',self.root),patch.object(sandbox,'invocation',return_value=(command,os.environ.copy(),'fixture')):
   return sandbox.run(self.work,scratch,'Review the project',role='readonly',execution_route={'harness':'claude','provider':'claude_subscription'},handoff_schema=self.schema)
 def test_natural_dialogue_and_file_verdict_are_separate(self):
  scratch=self.root/'run';result=self.invoke(scratch,"d['result']={'verdict':'blocked','findings':['Missing prerequisite'],'summary':'Do not advance'};p.write_text(json.dumps(d));print(json.dumps({'type':'result','result':'Here is my detailed report. This is ordinary chat, not JSON.'}))")
  self.assertEqual(json.loads(result)['verdict'],'blocked');self.assertIn('ordinary chat',(scratch/'result.md').read_text());self.assertEqual((self.work/'source.txt').read_text(),'unchanged')
 def test_chat_approval_without_file_never_advances(self):
  with self.assertRaises(OutputError):self.invoke(self.root/'run',"print(json.dumps({'type':'result','result':'{\\\"verdict\\\":\\\"approved\\\",\\\"findings\\\":[]}'}))")
 def test_native_json_response_flag_not_used_for_file_handoff(self):
  class Stop(Exception):pass
  for harness,argv in (('codex',['codex','exec','-']),('claude',['claude','-p'])):
   with patch.object(sandbox,'ROOT',self.root),patch.object(sandbox,'invocation',return_value=(argv,os.environ.copy(),'fixture')),patch.object(sandbox.subprocess,'Popen',side_effect=Stop) as process:
    with self.assertRaises(Stop):sandbox.run(self.work,self.root/harness,'Fixture',execution_route={'harness':harness,'provider':'codex'},handoff_schema=self.schema)
   self.assertNotIn('--output-schema',process.call_args.args[0]);self.assertNotIn('--json-schema',process.call_args.args[0])
