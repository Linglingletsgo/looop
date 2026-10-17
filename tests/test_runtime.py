import json,pathlib,socket,sys,tempfile,types,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import sandbox
from executor import command
class Runtime(unittest.TestCase):
 def test_readonly_secret_network(self):
  with tempfile.TemporaryDirectory() as d:
   p=command(d,['python3','-c',"import os,socket;assert not os.path.exists('/home/agentdev/.codex/auth.json');assert not os.path.exists('/run/docker.sock');s=socket.socket();assert s.connect_ex(('127.0.0.1',54321))!=0\ntry:open('/workspace/no','w');raise AssertionError('writable')\nexcept OSError:pass\nprint('boundary-pass')"])
   self.assertEqual(p.returncode,0,p.stdout);self.assertIn('boundary-pass',p.stdout)
 def test_write_scope(self):
  with tempfile.TemporaryDirectory() as d:
   p=command(d,['python3','-c',"open('/workspace/owned','w').write('ok')"],writable=True);self.assertEqual(p.returncode,0,p.stdout);self.assertEqual((pathlib.Path(d)/'owned').read_text(),'ok')
 def test_quota_stops_without_fallback(self):
  # Test the real Unix gateway, fake only upstream and harness: no live inference.
  with tempfile.TemporaryDirectory(prefix='pcq-') as d:
   root=pathlib.Path(d);(root/'secrets').mkdir();(root/'secrets/commandcode.key').write_text('test-only')
   scratch=root/'scratch';work=root/'work';work.mkdir()
   upstream_calls=[]
   class Response:
    status=429
    def getheader(self,key,default=None):return '60' if key=='Retry-After' else default
    def read1(self,n):return b''
   class Upstream:
    def __init__(self,*a,**k):upstream_calls.append(a)
    def request(self,*a,**k):pass
    def getresponse(self):return Response()
    def close(self):pass
   def fake_harness(cmd,**kwargs):
    sock=next((root/'data/gateways').glob('*/model.sock'))
    raw=json.dumps({'model':'deepseek/deepseek-v4.1-flash'}).encode()
    s=socket.socket(socket.AF_UNIX);s.connect(str(sock));s.sendall(b'POST /v1/responses HTTP/1.1\r\nHost: local\r\nContent-Length: '+str(len(raw)).encode()+b'\r\n\r\n'+raw)
    data=b''
    while block:=s.recv(4096):data+=block
    s.close();self.assertIn(b'429',data)
    (scratch/'result.md').write_text('not a successful model call')
    return types.SimpleNamespace(returncode=1)
   with patch.object(sandbox,'ROOT',root),patch.object(sandbox.http.client,'HTTPSConnection',Upstream),patch.object(sandbox.subprocess,'run',fake_harness):
    with self.assertRaisesRegex(RuntimeError,'quota'):sandbox.run(work,scratch,'test',provider_id='commandcode')
    self.assertTrue((root/'data/quota-commandcode.json').exists())
    with self.assertRaisesRegex(RuntimeError,'paused'):sandbox.run(work,root/'scratch2','test',provider_id='commandcode')
    self.assertEqual(len(upstream_calls),1)
