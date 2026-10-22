"""Opt-in previews of verified mainline snapshots; never serve delivery drafts."""
import fcntl,hashlib,json,pathlib,re,shlex,shutil,socket,subprocess,time,urllib.request,urllib.error
from lifecycle_io import save
from repository import git,snapshot
from sandbox import execution_environment

def checked_target(root,lane,cfg):
 receipt=json.loads((root/'data/mainline-verification'/(lane+'.json')).read_text())
 if receipt.get('status')!='passed':raise ValueError('Preview requires passed mainline verification')
 sha=receipt.get('sha','')
 if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Preview requires a full verified SHA')
 repo=pathlib.Path(json.loads((root/'data/control.json').read_text())['projects'][lane]['repo'])
 if repo.resolve()!= (root/'data/execution-repos'/lane).resolve():raise ValueError('Preview source must be the managed execution repo')
 git(repo,'merge-base','--is-ancestor',receipt['merge_commit'],sha)
 for name,digest in cfg.get('reviewed_files',{}).items():
  if hashlib.sha256(git(repo,'show',sha+':'+name)).hexdigest()!=digest:raise ValueError('Preview needs compatibility review: '+name)
 return repo,sha

def healthy(service):
 try:
  with urllib.request.urlopen(service['url'],timeout=5) as response:code=response.status
 except urllib.error.HTTPError as exc:code=exc.code
 except (OSError,TimeoutError):return False
 return code==service.get('status',200)

def port_open(port):
 with socket.socket() as sock:
  sock.settimeout(.2);return sock.connect_ex(('127.0.0.1',port))==0

def stop(services):
 for service in reversed(services):
  name=service['session']
  if subprocess.run(['tmux','has-session','-t',name],capture_output=True).returncode:continue
  subprocess.run(['tmux','send-keys','-t',name,'C-c'],check=True)
  for _ in range(60):
   if not port_open(service['port']):break
   time.sleep(.5)
  else:raise ValueError('Preview service did not stop: '+name)
  subprocess.run(['tmux','kill-session','-t',name],capture_output=True)

def start(root,lane,repo,services):
 env=execution_environment()
 for service in services:
  log=root/'logs'/('preview-'+lane+'-'+service['session']+'.log')
  log.parent.mkdir(exist_ok=True)
  if log.exists() and log.stat().st_size>2097152:log.replace(log.with_suffix('.previous.log'))
  command='exec env '+shlex.join(['PATH='+env['PATH'],*[k+'='+v for k,v in service.get('env',{}).items()],*service['argv']])+' >> '+shlex.quote(str(log))+' 2>&1'
  subprocess.run(['tmux','new-session','-d','-s',service['session'],'-c',str(repo/service.get('cwd','.')),command],check=True)
 for _ in range(90):
  if all(healthy(s) for s in services):return
  time.sleep(1)
 raise ValueError('Preview readiness failed; inspect preview service logs')

def update(root,lane,cfg):
 if not cfg.get('enabled'):return
 if not re.fullmatch('[a-zA-Z0-9_-]+',lane):raise ValueError('Invalid preview lane')
 base=root/'data/previews'/lane;base.mkdir(parents=True,exist_ok=True)
 with (base/'lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  repo,sha=checked_target(root,lane,cfg)
  statepath=base/'state.json'
  previous=json.loads(statepath.read_text()) if statepath.exists() else {}
  config_hash=hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
  if previous.get('sha')==sha and previous.get('config_hash')==config_hash and previous.get('state')=='ready':
   if not all(healthy(s) for s in cfg['services']):raise ValueError('Preview service health failed')
   return
  releases=base/'releases';releases.mkdir(exist_ok=True)
  target=releases/sha
  if not target.exists():
   snapshot(repo,sha,target)
  # Links preserve the existing credentials and runtime data without copying secrets.
  for name,source in cfg.get('links',{}).items():
   dest=target/name
   if dest.exists() or dest.is_symlink():
    if not dest.is_symlink() or dest.resolve()!=pathlib.Path(source).resolve():raise ValueError('Preview runtime link conflicts: '+name)
   else:dest.symlink_to(source,target_is_directory=pathlib.Path(source).is_dir())
  ready=target/'.preview-installed'
  if not ready.exists():
   log=base/'install.log'
   with log.open('w') as output:
    for cwd in cfg['install_dirs']:
     result=subprocess.run(['npm','ci','--no-audit','--no-fund'],cwd=target/cwd,env=execution_environment(),stdout=output,stderr=subprocess.STDOUT)
     if result.returncode:raise ValueError('Preview dependency installation failed; inspect install.log')
   ready.touch()
  old=pathlib.Path(previous['path']) if previous.get('path') else pathlib.Path(cfg['fallback_repo'])
  try:
   stop(cfg['services']);start(root,lane,target,cfg['services'])
  except Exception:
   stop(cfg['services']);start(root,lane,old,cfg['services'])
   raise
  current=base/'current';tmp=base/'current.tmp'
  tmp.unlink(missing_ok=True);tmp.symlink_to(target,target_is_directory=True);tmp.replace(current)
  prior=previous.get('previous_path',cfg['fallback_repo']) if old.resolve()==target.resolve() else str(old)
  if pathlib.Path(prior).resolve()==target.resolve():prior=cfg['fallback_repo']
  save(statepath,{'state':'ready','sha':sha,'config_hash':config_hash,'path':str(target),'previous_path':prior,'updated_at':time.time()})
  (base/'failure.json').unlink(missing_ok=True)
  # Retain current and one prior generated release; original workspaces are never removed.
  keep={target.resolve(),pathlib.Path(prior).resolve()}
  for folder in releases.iterdir():
   if re.fullmatch('[0-9a-f]{40}',folder.name) and not folder.is_symlink() and folder.resolve() not in keep:shutil.rmtree(folder)

def sync(root):
 root=pathlib.Path(root)
 for path in sorted((root/'data/preview-policies').glob('*.json')):
  try:update(root,path.stem,json.loads(path.read_text()))
  except BlockingIOError:continue
  except Exception as exc:
   base=root/'data/previews'/path.stem;base.mkdir(parents=True,exist_ok=True)
   save(base/'failure.json',{'state':'blocked','reason':str(exc)[:2000],'at':time.time()})
   print('Preview update needs attention:',path.stem,str(exc)[:240])

if __name__=='__main__':
 from runtime import ROOT
 sync(ROOT)
