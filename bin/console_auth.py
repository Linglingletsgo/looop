"""Owner password, file-backed sessions and login rate limits for the console."""
import hashlib,hmac,json,os,pathlib,secrets,tempfile,threading,time

IDLE=12*60*60
ABSOLUTE=7*24*60*60
AUTH_FILE='data/console-auth.json'
SESSIONS_FILE='data/console-sessions.json'
COOKIE='looop_session'
COOKIE_MAX_AGE=ABSOLUTE
SCRYPT={'n':16384,'r':8,'p':1}
_UNSET=object()

def default_root():
 env=os.environ.get('AGENT_RUNTIME_ROOT')
 return pathlib.Path(env).expanduser().resolve() if env else pathlib.Path(__file__).resolve().parent.parent

def _read(path):
 try:value=json.loads(path.read_text())
 except (OSError,ValueError):return None
 return value if isinstance(value,dict) else None

def _write(path,value):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=str(path.parent))
 try:
  with os.fdopen(fd,'w') as handle:
   json.dump(value,handle,ensure_ascii=False,separators=(',',':'))
   handle.flush();os.fsync(handle.fileno())
  os.chmod(tmp,0o600);os.replace(tmp,path);path.chmod(0o600)
 finally:
  try:os.unlink(tmp)
  except OSError:pass

def _key(token):
 return hashlib.sha256(token.encode()).hexdigest()

class Auth:
 """Password verification and opaque server-side sessions. Scrypt only; no plaintext at rest."""
 def __init__(self,root,clock=time.time):
  self.root=pathlib.Path(root);self.clock=clock;self.lock=threading.RLock()
  self.auth_path=self.root/AUTH_FILE;self.sessions_path=self.root/SESSIONS_FILE

 def password_set(self):
  value=_read(self.auth_path);scrypt=(value or {}).get('scrypt')
  generation=(value or {}).get('generation')
  return isinstance(scrypt,dict) and all(k in scrypt for k in ('salt','hash')) and isinstance(generation,str) and bool(generation)

 def set_password(self,password):
  if not isinstance(password,str) or len(password)<12:raise ValueError('密码至少需要 12 个字符。')
  salt=secrets.token_bytes(16)
  digest=hashlib.scrypt(password.encode(),salt=salt,n=SCRYPT['n'],r=SCRYPT['r'],p=SCRYPT['p'],dklen=32)
  generation=secrets.token_urlsafe(18)
  with self.lock:
   self._save({})
   _write(self.auth_path,{'version':1,'generation':generation,'scrypt':{'n':SCRYPT['n'],'r':SCRYPT['r'],'p':SCRYPT['p'],'salt':salt.hex(),'hash':digest.hex()}})

 def generation(self):
  value=_read(self.auth_path);generation=(value or {}).get('generation')
  return generation if isinstance(generation,str) else None

 def verify_password_generation(self,password):
  """Return the generation verified with this password, or False on failure."""
  if not isinstance(password,str):return False
  value=_read(self.auth_path);scrypt=(value or {}).get('scrypt')
  try:
   salt=bytes.fromhex(scrypt['salt']);expected=bytes.fromhex(scrypt['hash'])
   digest=hashlib.scrypt(password.encode(),salt=salt,n=int(scrypt.get('n',SCRYPT['n'])),r=int(scrypt.get('r',SCRYPT['r'])),p=int(scrypt.get('p',SCRYPT['p'])),dklen=len(expected))
  except (KeyError,TypeError,ValueError,MemoryError):return False
  if not hmac.compare_digest(digest,expected):return False
  generation=(value or {}).get('generation')
  # A missing generation is a corrupt auth file: fail closed.
  return generation if isinstance(generation,str) and generation else False

 def verify_password(self,password):
  return self.verify_password_generation(password) is not False

 def _load(self):
  value=_read(self.sessions_path);sessions=(value or {}).get('sessions')
  return sessions if isinstance(sessions,dict) else {}

 def _prune(self,sessions,now):
  for key in list(sessions):
   item=sessions[key]
   try:created=float(item.get('created',0));seen=float(item.get('last_seen',created))
   except (AttributeError,TypeError,ValueError):del sessions[key];continue
   if now-created>ABSOLUTE or now-seen>IDLE:del sessions[key]

 def _save(self,sessions):
  now=self.clock();self._prune(sessions,now);_write(self.sessions_path,{'version':1,'sessions':sessions})

 def create_session(self,generation=_UNSET):
  token=secrets.token_urlsafe(32);now=self.clock()
  with self.lock:
   if generation is _UNSET:generation=self.generation()
   sessions=self._load();self._prune(sessions,now)
   sessions[_key(token)]={'created':now,'last_seen':now,'generation':generation};self._save(sessions)
  return token

 def validate(self,token):
  if not isinstance(token,str) or not token:return False
  key=_key(token);now=self.clock()
  with self.lock:
   sessions=self._load();item=sessions.get(key)
   if not isinstance(item,dict):return False
   try:created=float(item.get('created',0));seen=float(item.get('last_seen',created))
   except (TypeError,ValueError):sessions.pop(key,None);self._save(sessions);return False
   current=self.generation()
   if now-created>ABSOLUTE or now-seen>IDLE or not current or item.get('generation')!=current:
    sessions.pop(key,None);self._save(sessions);return False
   item['last_seen']=now;self._save(sessions)
   return True

 def destroy(self,token):
  if not isinstance(token,str) or not token:return
  with self.lock:
   sessions=self._load();sessions.pop(_key(token),None);self._save(sessions)

 def clear_sessions(self):
  with self.lock:self._save({})

class RateLimiter:
 """In-memory failed-login budget: per client and globally, sliding 15 minute window."""
 def __init__(self,clock=time.time,limit=5,window=15*60,global_limit=30):
  self.clock=clock;self.limit=limit;self.window=window;self.global_limit=global_limit
  self.lock=threading.Lock();self.clients={};self.failures=[]

 def _prune(self,now):
  cutoff=now-self.window
  for ip in list(self.clients):
   kept=[at for at in self.clients[ip] if at>cutoff]
   if kept:self.clients[ip]=kept
   else:del self.clients[ip]
  self.failures=[at for at in self.failures if at>cutoff]

 def blocked(self,ip):
  with self.lock:
   now=self.clock();self._prune(now)
   return len(self.clients.get(ip,()))>=self.limit or len(self.failures)>=self.global_limit

 def begin(self,ip):
  """Reserve one attempt atomically before password verification."""
  with self.lock:
   now=self.clock();self._prune(now)
   if len(self.clients.get(ip,()))>=self.limit or len(self.failures)>=self.global_limit:return False
   self.clients.setdefault(ip,[]).append(now);self.failures.append(now);return True

 def succeeded(self,ip):
  with self.lock:
   now=self.clock();self._prune(now)
   values=self.clients.get(ip)
   if values:
    values.pop()
    if not values:self.clients.pop(ip,None)
   if self.failures:self.failures.pop()

 def failed(self,ip):
  with self.lock:
   now=self.clock();self._prune(now)
   self.clients.setdefault(ip,[]).append(now);self.failures.append(now)
