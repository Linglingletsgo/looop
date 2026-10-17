"""Explicit recovery carries source/check evidence forward without replaying publication."""
import datetime,difflib,fcntl,hashlib,json,pathlib,subprocess
from project_state import task_guard,configured_store

def prepare(root,issue,reason,interrupted=False):
 root=pathlib.Path(root)
 task_guard(root,issue)
 if not issue or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in issue):raise ValueError('Invalid issue id')
 binding=root/'data/delivery-bindings'/(issue+'.json');d=json.loads(binding.read_text());repo=pathlib.Path(d['policy']['repo'])
 common=subprocess.check_output(['git','-C',str(repo),'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()
 lock=root/'data/locks'/hashlib.sha256(common.encode()).hexdigest();lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('w') as handle:
  try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Repository worker still running') from None
  folder=root/'data/deliveries'/issue;state=json.loads((folder/'state.json').read_text())
  if interrupted:
   from process_owner import alive
   if state['state'] not in ('planning','building','checking','acceptance') and not state['state'].startswith('review_'):raise ValueError('Stage cannot be automatically restarted')
   if alive(state.get('owner')) is not False:raise ValueError('Original worker alive or identity unknown')
   if d.get('interruption_retries',0)>=2:raise ValueError('Interruption restart budget exhausted')
   if state.get('pr_url'):raise ValueError('Published task cannot be restarted')
  elif state['state']!='blocked' or state.get('pr_url'):raise ValueError('Only unpublished blocked attempts can be retried')
  head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
  if head!=d['packet']['baseline_sha']:raise ValueError('Baseline moved; regenerate Packet')
  sources=sorted(folder.glob('build-*'),key=lambda x:x.stat().st_mtime)
  source=sources[-1] if sources else folder/'candidate';notes=['Operator recovery: '+reason,'All prior evidence is historical; recheck scope, tests and approvals. Do not weaken assertions.']
  for name in d['packet']['allowed_paths']:
   base=folder/'baseline'/name;latest=source/name
   if base.is_symlink() or latest.is_symlink():raise ValueError('Symlink recovery refused')
   old=base.read_text() if base.is_file() else '';new=latest.read_text() if latest.is_file() else ''
   diff=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
   if diff:notes.append('Previous untrusted draft; inspect before reapplying:\n'+diff)
  for report in sorted(folder.glob('checks-*.json')):
   checks=json.loads(report.read_text());notes.append('Previous checks: '+json.dumps([{'argv':c['argv'],'exit_code':c['exit_code'],'output':c['output'][-6000:]} for c in checks],ensure_ascii=False))
  notes.append('Previous findings: '+json.dumps(state.get('reviews',{}),ensure_ascii=False))
  text='\n'.join(notes)
  if len(text)>100000:raise ValueError('Recovery evidence too large; provide a narrower Packet')
  store=configured_store(root)
  if interrupted:
   if store:store.transition(d['lane'],issue,'blocked',{'interrupted_stage':state['state']})
   d['interruption_retries']=d.get('interruption_retries',0)+1
  if store:store.transition(d['lane'],issue,'queued',{'recovery_reason':reason})
  archive=root/'data/delivery-attempts'/(issue+'-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
  archive.parent.mkdir(exist_ok=True)
  d['packet']['execution_notes']=text;d['policy'].pop('timeout',None);d['policy'].pop('check_timeout',None)
  tmp=binding.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(binding)
  folder.rename(archive)
  (archive/'recovery.json').write_text(json.dumps({'reason':reason,'source':str(source),'next_attempt_requires_fresh_gates':True},indent=2))
  return archive
