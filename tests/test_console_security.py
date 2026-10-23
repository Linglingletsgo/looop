import http.client,json,os,pathlib,socket,sys,tempfile,threading,time,unittest,urllib.parse
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
TESTS=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(TESTS))
from test_console_server import Live,make_root,Clock,PASSWORD,NEW_PASSWORD,server,ROOT,console_auth

class Security(Live):
 def test_host_is_not_trusted_from_request(self):
  status,values,data=self.call('GET','/api/looop/status',headers={'Host':'evil.example','Origin':'http://evil.example'},origin=False)
  self.assertEqual(status,421);self.assertEqual(data,b'')
  for name in ('cache-control','content-security-policy','x-content-type-options','x-frame-options','referrer-policy'):
   self.assertIn(name,values)
  status,values,token=self.login(headers={'Host':'evil.example','Origin':'http://evil.example'},origin=False)
  self.assertEqual(status,421);self.assertIsNone(token);self.assertNotIn('set-cookie',values)
  self.assertEqual(self.login(headers={'Host':'evil.example','Origin':self.base},origin=False)[0],421)
  self.assertEqual(self.login(headers={'Host':'127.0.0.1:'+str(self.port),'Origin':'http://evil.example'},origin=False)[0],403)
  _,_,token=self.login()
  self.assertEqual(self.call('GET','/api/looop/status',token=token,headers={'Host':'localhost:'+str(self.port)})[0],200)

 def test_duplicate_host_headers_are_rejected(self):
  with socket.create_connection(('127.0.0.1',self.port),timeout=5) as sock:
   sock.sendall(f'GET /looop HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nHost: evil.example\r\nConnection: close\r\n\r\n'.encode())
   reply=sock.recv(4096).decode('latin-1')
  self.assertTrue(reply.startswith('HTTP/1.0 400') or reply.startswith('HTTP/1.1 400'),reply[:40])

 def test_auth_file_without_generation_fails_closed(self):
  _,_,old=self.login()
  path=self.http.auth.auth_path;value=json.loads(path.read_text());value.pop('generation');path.write_text(json.dumps(value))
  self.assertNotEqual(self.call('GET','/api/looop/status',token=old)[0],200)
  status,_,token=self.login()
  self.assertNotEqual(status,303);self.assertIsNone(token)
  self.assertFalse(self.http.auth.password_set())

 def test_default_port_origin_matches_its_omitted_form(self):
  http_=server.console_http
  origins=[http_._origin('https://console.test:443')]
  self.assertIsNotNone(http_.match_origin(origins,'https://console.test'))
  self.assertIsNone(http_.match_origin(origins,'https://console.test:8443'))
  self.assertIsNone(http_.match_origin(origins,'http://console.test'))

 def test_ipv6_origin_is_added_only_for_ipv6_bind(self):
  origins=server.console_http.load_origins(self.root,'::1',3120)
  self.assertTrue(any(item['text']=='http://[::1]:3120' for item in origins))
  self.assertFalse(any(item['text']==f'http://[::1]:{self.port}' for item in server.console_http.load_origins(self.root,'127.0.0.1',self.port)))

 def test_action_requires_json_object_without_child(self):
  _,_,token=self.login()
  for body in (b'[]',b'"text"',b'42',b'null'):
   self.assertEqual(self.call('POST','/api/looop/action',body,{'Content-Type':'application/json'},token=token)[0],400)
  self.assertFalse((self.root/'data/stub-action-started').exists())

 def test_login_reservations_respect_global_budget(self):
  limiter=console_auth.RateLimiter(Clock())
  with ThreadPoolExecutor(max_workers=40) as pool:allowed=list(pool.map(lambda number:limiter.begin('10.0.0.'+str(number)),range(40)))
  self.assertEqual(sum(1 for value in allowed if value),30)

 def test_concurrent_wrong_logins_reserve_budget(self):
  calls=[];lock=threading.Lock();original=self.http.auth.verify_password_generation
  def counted(password):
   with lock:calls.append(password)
   return original(password)
  self.http.auth.verify_password_generation=counted
  with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(lambda _:self.login(password='wrong password 123'),range(12)))
  self.assertLessEqual(len(calls),5);self.assertEqual(sum(1 for status,_,_ in results if status==401),5);self.assertEqual(sum(1 for status,_,_ in results if status==429),7)

 def test_partial_headers_timeout(self):
  self.http.request_timeout=0.3;client=socket.create_connection(('127.0.0.1',self.port),timeout=2)
  try:
   client.sendall(b'GET /looop HTTP/1.1\r\nHost: 127.0.0.1:'+str(self.port).encode());client.settimeout(3)
   started=time.monotonic();self.assertEqual(client.recv(1),b'');self.assertLess(time.monotonic()-started,2)
  finally:client.close()

 def test_head_method_limits_and_error_headers(self):
  _,_,token=self.login();status,values,data=self.call('HEAD','/api/looop/status',token=token)
  self.assertEqual(status,200);self.assertEqual(data,b'');self.assertNotEqual(values.get('content-length'),'0')
  status,values,data=self.call('PUT','/api/looop/status',token=token)
  self.assertEqual(status,405);self.assertEqual(data,b'');self.assertEqual(values.get('allow'),'GET, HEAD, POST')
  for name in ('cache-control','content-security-policy'):self.assertIn(name,values)
  slots=self.http.request_slots;acquired=0
  try:
   for _ in range(server.MAX_CONCURRENCY):self.assertTrue(slots.acquire(timeout=2));acquired+=1
   status,values,data=self.call('GET','/api/looop/status',token=token)
   self.assertEqual(status,503);self.assertEqual(data,b'');self.assertIn('cache-control',values)
  finally:
   for _ in range(acquired):slots.release()
  client=socket.create_connection(('127.0.0.1',self.port),timeout=2)
  try:
   client.sendall(b'GET /looop HTTP/nope\r\nHost: 127.0.0.1:'+str(self.port).encode()+b'\r\n\r\n')
   raw=b''
   while True:
    chunk=client.recv(4096)
    if not chunk:break
    raw+=chunk
  finally:client.close()
  self.assertIn(b' 400 ',raw.split(b'\r\n',1)[0]);self.assertIn(b'Cache-Control: no-store',raw);self.assertIn(b'Content-Security-Policy',raw)

 def test_password_change_race_rejects_old_sessions(self):
  auth=console_auth.Auth(self.root);other=console_auth.Auth(self.root);auth.set_password(PASSWORD)
  password=PASSWORD;next_password=NEW_PASSWORD
  for _ in range(50):
   barrier=threading.Barrier(2);result={}
   def login():
    barrier.wait();generation=auth.verify_password_generation(password)
    if generation is not False:result['token']=auth.create_session(generation)
   def change():
    barrier.wait();other.set_password(next_password)
   first=threading.Thread(target=login);second=threading.Thread(target=change)
   first.start();second.start();first.join(10);second.join(10)
   self.assertFalse(first.is_alive());self.assertFalse(second.is_alive())
   if 'token' in result:self.assertFalse(auth.validate(result['token']))
   password,next_password=next_password,password

class ConfiguredOrigins(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=make_root(self.tmp.name)
  (self.root/'data/stub-status.json').write_text(json.dumps({'projects':[],'providers':[],'tracker':'local'}));self.clock=Clock()
  probe=socket.socket();probe.bind(('127.0.0.1',0));self.port=probe.getsockname()[1];probe.close()
  (self.root/'data/local-settings.json').write_text(json.dumps({'console':{'origins':['https://console.test:'+str(self.port)]}}))
  self.http=server.make_server(self.root,port=self.port,clock=self.clock)
  self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
 def stop(self):
  self.http.shutdown();self.http.server_close();self.thread.join(5)
 def call(self,method,path,body=None,headers=None,token=None):
  headers=dict(headers or {})
  if token:headers['Cookie']=f'looop_session={token}'
  if body is not None and 'Content-Type' not in headers:headers['Content-Type']='application/x-www-form-urlencoded'
  connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
  connection.request(method,path,body=body,headers=headers);response=connection.getresponse()
  data=response.read();values={key.lower():value for key,value in response.getheaders()};connection.close()
  return response.status,values,data
 def test_configured_https_origin_and_secure_cookie(self):
  origin='https://console.test:'+str(self.port);host='console.test:'+str(self.port)
  body=urllib.parse.urlencode({'password':PASSWORD,'next':'/looop'})
  status,values,data=self.call('POST','/login',body,{'Host':host,'Origin':origin})
  self.assertEqual(status,303);self.assertEqual(values['location'],'/looop');self.assertIn('Secure',values['set-cookie'])
  token=values['set-cookie'].split(';',1)[0].split('=',1)[1]
  self.assertEqual(self.call('GET','/api/looop/status',headers={'Host':host},token=token)[0],200)
  self.assertEqual(self.call('GET','/api/looop/status',headers={'Host':'127.0.0.1:'+str(self.port)},token=token)[0],200)
  status,values,data=self.call('GET','/api/looop/status',headers={'Host':'evil.example','Origin':origin},token=token)
  self.assertEqual(status,421);self.assertEqual(data,b'');self.assertIn('cache-control',values)
  status,_,data=self.call('POST','/login',body,{'Host':'evil.example','Origin':'https://evil.example'})
  self.assertEqual(status,421);self.assertEqual(data,b'')

class RealConsoleLocalMode(unittest.TestCase):
 def test_server_status_route_never_contacts_board(self):
  with tempfile.TemporaryDirectory() as data_dir,tempfile.TemporaryDirectory() as hook_dir:
   runtime=pathlib.Path(data_dir);(runtime/'data').mkdir();(runtime/'data/local-settings.json').write_text(json.dumps({'tracker':'local'}))
   console_auth.Auth(runtime).set_password(PASSWORD)
   probe=socket.socket();probe.bind(('127.0.0.1',0));board_port=probe.getsockname()[1];probe.close()
   log=runtime/'socket-connections.log'
   hook=pathlib.Path(hook_dir)/'sitecustomize.py'
   hook.write_text("import sys\n"+f"def _hook(event,args):\n if event=='socket.connect':\n  try:open({str(log)!r},'a').write(str(args[1])+'\\n')\n  except OSError:pass\nsys.addaudithook(_hook)\n")
   env={'AGENT_RUNTIME_ROOT':str(runtime),'PAPERCLIP_URL':'http://127.0.0.1:'+str(board_port),'PYTHONPATH':str(hook_dir)}
   with patch.dict(os.environ,env):
    instance=server.make_server(ROOT,port=0,clock=Clock());thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
     token=instance.auth.create_session();connection=http.client.HTTPConnection('127.0.0.1',instance.server_address[1],timeout=20)
     connection.request('GET','/api/looop/status',headers={'Cookie':'looop_session='+token})
     response=connection.getresponse();data=response.read();connection.close()
    finally:instance.shutdown();instance.server_close();thread.join(5)
   self.assertEqual(response.status,200);value=json.loads(data);self.assertEqual(value['tracker'],'local');self.assertEqual(value['console'],'standalone')
   self.assertFalse(log.exists() and str(board_port) in log.read_text())

if __name__=='__main__':unittest.main()
