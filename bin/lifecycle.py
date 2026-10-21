"""Durable delivery receipts, failure categories, and isolated mainline verification."""
import datetime,fcntl,hashlib,importlib.util,json,pathlib,re,subprocess,time
from repository import git,snapshot
from executor import command
from roles import resolve,fingerprints

def save(path,value):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)

def failure(exc):
 from research_evidence import EvidenceGap
 from source_evidence import SourceEvidenceError
 if isinstance(exc,(EvidenceGap,SourceEvidenceError)):return {'category':'research_evidence','next_action':'按证据纠正回执补齐公开来源或当前源码实验，再重新规划；不跳过核验','retryable':False}
 text=str(exc).lower()
 if 'no repair progress:' in text:return {'category':'repair_stalled','next_action':'代码或验证证据没有修复进展；查看独立审核意见，调整修复策略后再接续，不跳过检查','retryable':False}
 if any(s in text for s in ('needs public research','requires verified repository sources','quotation not found')):return {'category':'research_evidence','next_action':'查看引文纠正记录，核对对应来源后重新规划；不跳过证据检查','retryable':False}
 if re.search(r'\bquota\b',text) or 'provider unavailable' in text:return {'category':'provider_paused','next_action':'核验订阅额度/认证后显式恢复；不切换付费路线','retryable':False}
 if any(s in text for s in ('connection reset','connection refused','remote end closed','temporary failure','network is unreachable','model connection failed')):return {'category':'connection','next_action':'连接恢复后可有限重试，重新执行全部门禁','retryable':True}
 if any(s in text for s in ('baseline','workflow','scope','role','outside packet')):return {'category':'scope_or_baseline','next_action':'检查基线/授权/规则，形成新 Packet；不自动扩权','retryable':False}
 if any(s in text for s in ('round limit','review blocked','acceptance blocked','planning blocked','builder blocked','product disposition')):return {'category':'product_disposition','next_action':'Product 判断需求、缺陷或验收阻塞；不重复同一失败','retryable':False}
 return {'category':'execution','next_action':'查看保存的日志与草稿，确认原因后显式接续','retryable':False}

def terminal(state):
 return {'merged':'done','validated':'done','closed':'cancelled','waiting_for_merge':'in_review'}.get(state)

def refresh(root,lane,binding,merge_commit):
 root=pathlib.Path(root);policy=binding['policy'];repo=pathlib.Path(policy['repo']).resolve()
 config=json.loads((root/'data/control.json').read_text());cfg=config['projects'][lane]
 # Only the dedicated execution checkout may be fast-forwarded; never an original workspace.
 managed=root/'data/execution-repos'
 if not repo.is_relative_to(managed.resolve()) or repo!=pathlib.Path(cfg['repo']).resolve():raise ValueError('Refresh requires dedicated execution repo')
 common=git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
 lock=root/'data/locks'/hashlib.sha256(common.encode()).hexdigest();lock.parent.mkdir(exist_ok=True)
 with lock.open('w') as handle:
  try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Repository busy; refresh pending') from None
  if git(repo,'status','--porcelain').strip():raise ValueError('Execution checkout dirty; inspect without resetting')
  origin=git(repo,'remote','get-url','origin').decode().strip()
  if origin not in ('git@github.com:'+policy['github_repo']+'.git','https://github.com/'+policy['github_repo']+'.git'):raise ValueError('Unexpected origin')
  branch=policy.get('base_branch','main');git(repo,'fetch','origin',branch);sha=git(repo,'rev-parse','FETCH_HEAD').decode().strip()
  git(repo,'merge-base','--is-ancestor',merge_commit,sha)
  previous=git(repo,'rev-parse','HEAD').decode().strip()
  changed=set(git(repo,'diff','--name-only',previous,sha).decode().splitlines())
  if any(pathlib.PurePosixPath(n).name in ('package.json','package-lock.json','npm-shrinkwrap.json') for n in changed):raise ValueError('Dependencies changed; reinstall from reviewed lockfiles before refresh')
  folder=root/'data/mainline-verification'/lane/sha
  receipt=folder/'result.json'
  folder.mkdir(parents=True,exist_ok=True);workspace=snapshot(repo,sha,folder/'workspace')
  if fingerprints(resolve(workspace,policy.get('project_adapter')))!=policy.get('role_registry'):raise ValueError('Mainline roles changed; review mapping')
  for name,digest in policy.get('workflow_evidence',{}).items():
   if hashlib.sha256((workspace/name).read_bytes()).hexdigest()!=digest:raise ValueError('Mainline workflow changed; review policy')
  results=[]
  for argv in policy['checks']:
   result=command(workspace,argv,dependencies=policy.get('dependencies'),timeout=None)
   results.append({'argv':argv,'exit_code':result.returncode,'output':result.stdout[-24000:]})
  data={'status':'passed' if all(x['exit_code']==0 for x in results) else 'failed','sha':sha,'merge_commit':merge_commit,'checks':results,'verified_at':time.time()};save(receipt,data)
  if data['status']!='passed':raise ValueError('Post-merge mainline verification failed; automatic queue stopped')
  git(repo,'merge','--ff-only',sha)
  profile_name=lane+'-verified-'+sha+'.json';profile=root/'profiles'/profile_name
  spec=importlib.util.spec_from_file_location('project_profile',__import__('runtime').CODE_ROOT/'bin/project-profile.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  if not profile.exists():save(profile,module.discover(repo))
  # Serialize shared config writes; do not replace another project's registration.
  with (root/'data/locks/config').open('w') as config_lock:
   fcntl.flock(config_lock,fcntl.LOCK_EX);config=json.loads((root/'data/control.json').read_text());config['projects'][lane]['profile']=profile_name;save(root/'data/control.json',config)
  save(root/'data/mainline-verification'/(lane+'.json'),data)
  return data
