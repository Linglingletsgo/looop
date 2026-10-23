import hashlib,http.client,importlib.util,json,os,pathlib,stat,subprocess,sys,tempfile,threading,time,unittest,urllib.parse
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];BIN=ROOT/'bin';sys.path.insert(0,str(BIN))
import console_auth
spec=importlib.util.spec_from_file_location('console_server',BIN/'console-server.py');server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
PASSWORD='correct horse battery'
NEW_PASSWORD='another correct battery'
STATUS_STUB='''import json,pathlib,sys
root=pathlib.Path(__file__).resolve().parents[1]
mode=(root/'data/stub-status-mode').read_text().strip() if (root/'data/stub-status-mode').exists() else ''
if mode=='fail':sys.exit(3)
if mode=='huge':sys.stdout.write('x'*(1024*1024+1));sys.exit(0)
if mode=='sleep':import time;time.sleep(5)
if mode=='endless':
 import os
 while True:os.write(1,b'x'*65536)
sys.stdout.write((root/'data/stub-status.json').read_text())
'''
ACTION_STUB='''import json,pathlib,sys
root=pathlib.Path(__file__).resolve().parents[1]
(root/'data/stub-action-started').write_text('yes')
mode=(root/'data/stub-action-mode').read_text().strip() if (root/'data/stub-action-mode').exists() else ''
if mode=='fail':sys.exit(3)
if mode=='huge':sys.stdout.write('x'*(1024*1024+1));sys.exit(0)
value=json.load(sys.stdin);value_out=json.loads((root/'data/stub-action.json').read_text())
if value_out.pop('echo',False):value_out['echo']=value
sys.stdout.write(json.dumps(value_out))
'''
class Clock:
 def __init__(self,now=1000000):self.now=now
 def __call__(self):return self.now

def make_root(directory):
 root=pathlib.Path(directory);(root/'bin').mkdir();(root/'ui').mkdir();(root/'data').mkdir()
 (root/'bin/console.py').write_text(STATUS_STUB);(root/'bin/console_actions.py').write_text(ACTION_STUB)
 (root/'ui/index.html').write_text('<!doctype html><title>fixture console</title><p>INDEX</p>')
 (root/'ui/app.js').write_text("console.log('app fixture')");(root/'ui/style.css').write_text('body{color:#fff}')
 console_auth.Auth(root).set_password(PASSWORD)
 return root

class Live(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=make_root(self.tmp.name)
  (self.root/'data/stub-status.json').write_text(json.dumps({'projects':[],'providers':[],'tracker':'local'}))
  (self.root/'data/stub-action.json').write_text(json.dumps({'ok':True,'result':42}))
  self.clock=Clock();self.http=server.make_server(self.root,port=0,clock=self.clock)
  self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
  self.port=self.http.server_address[1];self.base=f'http://127.0.0.1:{self.port}'
  self.addCleanup(self.stop)
 def stop(self):
  self.http.shutdown();self.http.server_close();self.thread.join(5)
 def call(self,method,path,body=None,headers=None,token=None,origin=True):
  headers=dict(headers or {})
  if origin:headers.setdefault('Origin',self.base)
  if token:headers['Cookie']=f'looop_session={token}'
  if body is not None:headers.setdefault('Content-Type','application/json')
  if isinstance(body,str):body=body.encode()
  connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
  connection.request(method,path,body=body,headers=headers);response=connection.getresponse()
  data=response.read();values={key.lower():value for key,value in response.getheaders()};connection.close()
  return response.status,values,data
 def login(self,password=PASSWORD,next_path='/looop',headers=None,origin=True):
  body=urllib.parse.urlencode({'password':password,'next':next_path})
  status,values,data=self.call('POST','/login',body,{'Content-Type':'application/x-www-form-urlencoded',**(headers or {})},origin=origin)
  cookie=values.get('set-cookie','');token=cookie.split(';',1)[0].split('=',1)[1] if cookie else None
  return status,values,token
 def mode(self,kind,value=None):
  path=self.root/'data'/('stub-'+kind+'-mode')
  if value is None:
   if path.exists():path.unlink()
  else:path.write_text(value)

class Routes(Live):
 def test_login_required_on_every_route(self):
  status,values,_=self.call('GET','/looop');self.assertEqual(status,302);self.assertEqual(values['location'],'/login?next=%2Flooop')
  for path in ('/looop-assets/app.js','/looop-assets/style.css','/api/looop/status'):
   status,_,data=self.call('GET',path);self.assertEqual(status,401);self.assertEqual(json.loads(data),{'error':'Sign in required','login':'/login?next=%2Flooop'})
  status,_,_=self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},origin=False);self.assertEqual(status,401)
  status,values,_=self.call('GET','/');self.assertEqual(status,302);self.assertEqual(values['location'],'/looop')

 def test_login_page_and_cookie(self):
  status,values,data=self.call('GET','/login');self.assertEqual(status,200);self.assertIn(b'<form',data);self.assertIn("style-src 'nonce-",values['content-security-policy']);self.assertNotIn('unsafe-inline',values['content-security-policy'])
  status,values,token=self.login();self.assertEqual(status,303);self.assertEqual(values['location'],'/looop');cookie=values['set-cookie']
  for part in ('HttpOnly','SameSite=Strict','Path=/'):
   self.assertIn(part,cookie)
  self.assertNotIn('Secure',cookie);self.assertIsNotNone(token)
  status,_,data=self.call('GET','/looop',token=token);self.assertEqual(status,200);self.assertIn(b'INDEX',data)
  status,_,data=self.call('GET','/api/looop/status',token=token);self.assertEqual(status,200);self.assertEqual(json.loads(data)['console'],'standalone')

 def test_forwarded_proto_does_not_imply_https(self):
  status,values,token=self.login(headers={'X-Forwarded-Proto':'https'})
  self.assertEqual(status,303);self.assertNotIn('Secure',values['set-cookie']);self.assertIsNotNone(token)

 def test_wrong_password_and_rate_limit(self):
  for _ in range(5):
   status,_,token=self.login(password='wrong password 123');self.assertEqual(status,401);self.assertIsNone(token)
  status,_,token=self.login();self.assertEqual(status,429);self.assertIsNone(token)
  self.clock.now+=15*60+1
  status,_,token=self.login();self.assertEqual(status,303);self.assertIsNotNone(token)

 def test_global_rate_limit(self):
  limiter=console_auth.RateLimiter(self.clock)
  for number in range(30):limiter.failed(f'10.0.0.{number}')
  self.assertTrue(limiter.blocked('192.0.2.1'))
  self.clock.now+=15*60+1;self.assertFalse(limiter.blocked('192.0.2.1'))

 def test_session_idle_and_absolute_expiry(self):
  auth=console_auth.Auth(self.root,self.clock);token=auth.create_session();self.clock.now+=12*60*60+1
  self.assertFalse(auth.validate(token));token=auth.create_session()
  for _ in range(14):
   self.clock.now+=12*60*60;self.assertTrue(auth.validate(token))
  self.clock.now+=1;self.assertFalse(auth.validate(token))

 def test_logout_invalidates_session(self):
  _,_,token=self.login();status,values,_=self.call('POST','/logout',token=token)
  self.assertEqual(status,303);self.assertEqual(values['location'],'/login');self.assertIn('Max-Age=0',values['set-cookie'])
  self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],401)

 def test_password_change_invalidates_sessions(self):
  _,_,token=self.login();before=json.loads((self.root/'data/console-auth.json').read_text())['generation']
  console_auth.Auth(self.root).set_password(NEW_PASSWORD);after=json.loads((self.root/'data/console-auth.json').read_text())['generation']
  self.assertNotEqual(before,after)
  self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],401)
  self.assertEqual(self.login(password=PASSWORD)[0],401)
  self.assertEqual(self.login(password=NEW_PASSWORD)[0],303)

 def test_origin_checks(self):
  self.assertEqual(self.call('POST','/logout',origin=False)[0],403)
  self.assertEqual(self.login(origin=False)[0],403)
  self.assertEqual(self.login(headers={'Origin':'https://outside.example'})[0],403)
  _,_,token=self.login()
  self.assertEqual(self.call('POST','/logout',token=token,origin=False)[0],403)
  self.assertEqual(self.call('POST','/logout',token=token,headers={'Origin':'https://outside.example'})[0],403)
  self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],200)
  self.assertEqual(self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},token=token,origin=False)[0],403)

 def test_action_content_type_size_and_json(self):
  _,_,token=self.login()
  self.assertEqual(self.call('POST','/api/looop/action',b'{}',{'Content-Type':'text/plain'},token=token)[0],415)
  big=json.dumps({'body':'a'*33000})
  self.assertEqual(self.call('POST','/api/looop/action',big,{'Content-Type':'application/json'},token=token)[0],413)
  self.assertEqual(self.call('POST','/api/looop/action',b'{',{'Content-Type':'application/json'},token=token)[0],400)

 def test_status_proxy_and_failures(self):
  _,_,token=self.login()
  status,_,data=self.call('GET','/api/looop/status',token=token);value=json.loads(data)
  self.assertEqual(status,200);self.assertEqual(value['tracker'],'local');self.assertEqual(value['console'],'standalone')
  self.mode('status','fail');status,_,data=self.call('GET','/api/looop/status',token=token)
  self.assertEqual(status,503);self.assertEqual(json.loads(data)['error'],server.STATUS_ERROR)
  self.mode('status','huge');self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],503)
  self.mode('status','sleep');old=server.TIMEOUT;server.TIMEOUT=0.2
  try:self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],503)
  finally:server.TIMEOUT=old;self.mode('status',None)
  self.mode('status','endless');old=server.TIMEOUT;server.TIMEOUT=5;started=time.monotonic()
  try:self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],503);self.assertLess(time.monotonic()-started,3)
  finally:server.TIMEOUT=old;self.mode('status',None)
  (self.root/'data/stub-status.json').write_text('not json')
  self.assertEqual(self.call('GET','/api/looop/status',token=token)[0],503)

 def test_action_proxy_statuses_and_failures(self):
  _,_,token=self.login()
  (self.root/'data/stub-action.json').write_text(json.dumps({'ok':True,'result':42,'echo':True}))
  status,_,data=self.call('POST','/api/looop/action',json.dumps({'action':'demo'}),{'Content-Type':'application/json'},token=token)
  self.assertEqual(status,200);self.assertEqual(json.loads(data)['echo'],{'action':'demo'})
  (self.root/'data/stub-action.json').write_text(json.dumps({'ok':False,'conflict':True,'error':'stale'}))
  self.assertEqual(self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},token=token)[0],409)
  (self.root/'data/stub-action.json').write_text(json.dumps({'ok':False,'error':'bad'}))
  self.assertEqual(self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},token=token)[0],422)
  self.mode('action','fail');status,_,data=self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},token=token)
  self.assertEqual(status,503);self.assertEqual(json.loads(data)['error'],server.ACTION_ERROR)
  self.mode('action','huge');self.assertEqual(self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},token=token)[0],503)
  self.mode('action',None);(self.root/'data/stub-action.json').write_text('not json')
  self.assertEqual(self.call('POST','/api/looop/action',b'{}',{'Content-Type':'application/json'},token=token)[0],503)

 def test_next_open_redirect_is_rejected(self):
  status,_,data=self.call('GET','/login?next=%2F%2Fevil.example');self.assertEqual(status,200);self.assertIn(b'value="/looop"',data);self.assertNotIn(b'evil.example',data)
  self.assertEqual(self.login(next_path='//evil.example')[1]['location'],'/looop')
  self.assertEqual(self.login(next_path='https://evil.example')[1]['location'],'/looop')
  self.assertEqual(self.login(next_path='/looop?tab=1')[1]['location'],'/looop?tab=1')

 def test_static_routes_and_404s(self):
  _,_,token=self.login()
  status,values,data=self.call('GET','/looop',token=token);self.assertEqual(status,200);self.assertIn('text/html',values['content-type']);self.assertIn(b'INDEX',data)
  status,values,_=self.call('GET','/looop-assets/app.js',token=token);self.assertEqual(status,200);self.assertIn('text/javascript',values['content-type'])
  status,values,_=self.call('GET','/looop-assets/style.css',token=token);self.assertEqual(status,200);self.assertIn('text/css',values['content-type'])
  for path in ('/looop-assets/missing','/etc/passwd','/looop/','/api/unknown'):
   self.assertEqual(self.call('GET',path,token=token)[0],404)
  self.assertEqual(self.call('POST','/looop',b'',token=token)[0],404)

 def test_security_headers_on_all_responses(self):
  responses=[self.call('GET','/login'),self.call('GET','/api/looop/status'),self.call('GET','/missing'),self.call('GET','/looop')]
  for status,values,_ in responses:
   self.assertEqual(values['cache-control'],'no-store');self.assertEqual(values['x-content-type-options'],'nosniff')
   self.assertEqual(values['referrer-policy'],'same-origin');self.assertEqual(values['x-frame-options'],'DENY');self.assertIn('content-security-policy',values)
  self.assertIn("script-src 'self'",self.call('GET','/looop')[1]['content-security-policy'])
  self.assertIn("style-src 'nonce-",self.call('GET','/login')[1]['content-security-policy'])

 def test_auth_files_are_private_and_contain_no_secrets(self):
  _,_,token=self.login();auth_path=self.root/'data/console-auth.json';sessions_path=self.root/'data/console-sessions.json'
  self.assertEqual(stat.S_IMODE(auth_path.stat().st_mode),0o600);self.assertEqual(stat.S_IMODE(sessions_path.stat().st_mode),0o600)
  auth_text=auth_path.read_text();sessions_text=sessions_path.read_text()
  self.assertNotIn(PASSWORD,auth_text);self.assertNotIn(token,sessions_text)
  value=json.loads(auth_text);self.assertEqual(value['scrypt']['n'],16384);self.assertEqual(value['scrypt']['r'],8);self.assertEqual(value['scrypt']['p'],1)
  self.assertIsInstance(value['generation'],str);self.assertGreater(len(value['generation']),8)
  sessions=json.loads(sessions_text)['sessions'];self.assertIn(hashlib.sha256(token.encode()).hexdigest(),sessions)
  self.assertIn('created',sessions[hashlib.sha256(token.encode()).hexdigest()]);self.assertIn('last_seen',sessions[hashlib.sha256(token.encode()).hexdigest()])
  env={**os.environ,'AGENT_RUNTIME_ROOT':str(self.root)}
  result=subprocess.run([sys.executable,str(BIN/'console-auth.py'),'status'],capture_output=True,text=True,env=env)
  self.assertEqual(result.returncode,0);self.assertIn('password set',result.stdout);self.assertNotIn(PASSWORD,result.stdout)

class RuntimeRoot(unittest.TestCase):
 def test_runtime_root_env_holds_auth_data_not_code_root(self):
  with tempfile.TemporaryDirectory() as code, tempfile.TemporaryDirectory() as data:
   root=make_root(code);runtime=pathlib.Path(data);(runtime/'data').mkdir();console_auth.Auth(runtime).set_password(PASSWORD)
   with patch.dict(os.environ,{'AGENT_RUNTIME_ROOT':str(runtime)}):
    instance=server.make_server(root,port=0)
    try:self.assertEqual(instance.auth.auth_path,(runtime/'data/console-auth.json').resolve());self.assertTrue(instance.auth.password_set())
    finally:instance.server_close()

class Startup(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=make_root(self.tmp.name);console_auth.Auth(self.root).set_password(PASSWORD);self.empty=pathlib.Path(self.tmp.name)/'empty';(self.empty/'data').mkdir(parents=True)
 def test_refusals_and_allowed_configurations(self):
  with self.assertRaises(ValueError):server.validate_startup(self.empty,'127.0.0.1',False)
  with self.assertRaises(ValueError):server.make_server(self.empty,port=0)
  server.validate_startup(self.empty,'127.0.0.1',True)
  with self.assertRaises(ValueError):server.validate_startup(self.empty,'0.0.0.0',True)
  with self.assertRaises(ValueError):server.validate_startup(self.empty,'0.0.0.0',False)
  server.validate_startup(self.root,'0.0.0.0',False)
  with self.assertRaises(ValueError):server.validate_startup(self.root,'0.0.0.0',True)
 def test_main_exits_two_for_refused_startup(self):
  self.assertEqual(server.main(['--root',str(self.empty),'--port','0']),2)
  self.assertEqual(server.main(['--root',str(self.root),'--host','0.0.0.0','--port','0','--insecure-local-dev']),2)

class DevMode(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name);(self.root/'bin').mkdir();(self.root/'ui').mkdir();(self.root/'data').mkdir()
  (self.root/'bin/console.py').write_text(STATUS_STUB);(self.root/'bin/console_actions.py').write_text(ACTION_STUB)
  (self.root/'ui/index.html').write_text('INDEX');(self.root/'ui/app.js').write_text('APP');(self.root/'ui/style.css').write_text('CSS')
  (self.root/'data/stub-status.json').write_text('{}');(self.root/'data/stub-action.json').write_text('{"ok":true}')
  self.http=server.make_server(self.root,port=0,insecure_local_dev=True);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
  self.port=self.http.server_address[1];self.base=f'http://127.0.0.1:{self.port}'
 def tearDown(self):
  self.http.shutdown();self.http.server_close();self.thread.join(5);self.tmp.cleanup()
 def call(self,method,path,body=None,headers=None):
  connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
  connection.request(method,path,body=body,headers=headers or {});response=connection.getresponse();data=response.read();values={key.lower():value for key,value in response.getheaders()};connection.close()
  return response.status,values,data
 def test_dev_mode_disables_login(self):
  self.assertEqual(self.call('GET','/looop')[0],200)
  self.assertEqual(self.call('GET','/api/looop/status')[0],200)
  self.assertEqual(self.call('GET','/login')[1]['location'],'/looop')
  status,values,_=self.call('POST','/login',body=b'x',headers={'Origin':self.base,'Content-Type':'application/x-www-form-urlencoded'})
  self.assertEqual(status,303);self.assertEqual(values['location'],'/looop')
  status,values,data=self.call('GET','/looop',headers={'Host':'evil.example'})
  self.assertEqual(status,421);self.assertEqual(data,b'');self.assertIn('cache-control',values)

if __name__=='__main__':unittest.main()
