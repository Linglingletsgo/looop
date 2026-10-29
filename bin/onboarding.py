"""Project onboarding previews and explicit context-only connections; no command execution."""
import hashlib,importlib.util,json,pathlib,shutil,subprocess,re
from runtime import ROOT
from project_adapter import load,summary
from roles import resolve,fingerprints
from role_install import install_default_roles,plan_default_roles

spec=importlib.util.spec_from_file_location('project_profile',ROOT/'bin/project-profile.py');profile=importlib.util.module_from_spec(spec);spec.loader.exec_module(profile)

def preview(repo,projects_root=None,root=None):
 root=ROOT if root is None else pathlib.Path(root)
 base=pathlib.Path(projects_root or pathlib.Path.home()/'projects').resolve();path=pathlib.Path(repo).expanduser().resolve(strict=True)
 if path==base or not path.is_relative_to(base):raise ValueError('请选择 Linux ~/projects 下的项目目录。')
 actual=pathlib.Path(profile.git(path,'rev-parse','--show-toplevel').decode().strip()).resolve()
 if actual!=path:raise ValueError('请选择 Git 仓库根目录。')
 draft=profile.discover(path);adapter=load(path);registry=resolve(path,adapter)
 names=profile.git(path,'ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')
 files=set(n for n in names if n and len(pathlib.PurePosixPath(n).parts)<4)
 workflow=registry['workflow'] or [{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer','mode':'standard'}]
 common=pathlib.Path(draft['git_common_dir']).resolve();worktree=common!=(path/'.git').resolve()
 checks=adapter.get('checks',[]) if adapter else [v['command'] for v in draft['suggested_checks'].values()]
 dependencies=[]
 def dependency(name,needed,kind='user',note=''):
  if needed:dependencies.append({'name':name,'installed':bool(shutil.which(name)),'installation':kind,'note':note})
 dependency('git',True);dependency('node','package.json' in files);dependency('npm','package-lock.json' in files or 'package.json' in files);dependency('pnpm','pnpm-lock.yaml' in files);dependency('yarn','yarn.lock' in files);dependency('uv','uv.lock' in files);dependency('python3','pyproject.toml' in files or 'requirements.txt' in files)
 docker=any(pathlib.PurePosixPath(n).name in ('Dockerfile','compose.yaml','compose.yml','docker-compose.yml','docker-compose.yaml','config.toml') and (n.startswith('supabase/') or 'Docker' in n or 'compose' in n) for n in files)
 dependency('docker',docker,'review','需要核验 daemon/rootless 服务；发现 CLI 不表示后台服务可用。')
 warnings=list(draft['warnings']);warnings+=['检查命令仅预览，未执行；数据库、系统库与浏览器依赖仍需按项目部署说明核验。']
 if worktree:warnings.append('这是关联 worktree，仅允许预览；主线接入需单独选择主仓库。')
 if adapter and adapter.get('execution_enabled') is False:warnings.append('项目适配层为 context-only，不允许自动执行。')
 role_list=[{'name':n,'source':r['source'],'project_defined':n in registry['project_roles']} for n,r in registry['roles'].items()]
 rule_paths=sorted(set([r['path'] for r in draft['rules']]+(['.agent/project.json'] if adapter else [])))
 if adapter:rule_paths+=list(summary(path,adapter)['instruction_evidence'])
 link=path/'.agent/local/link.json'
 lane=json.loads(link.read_text())['lane'] if link.exists() else re.sub('[^a-z0-9-]','-',path.name.lower()).strip('-')[:40]
 if not lane or not lane[0].isalpha():lane='project-'+lane
 local_targets=['.gitignore','AGENTS.md','.agent/project.json','.agent/tools/project-session.py','.agent/tools/project_state.py','.agent/tools/state_revisions.py','.agent/tools/product_goals.py','.agent/tools/lifecycle_io.py','.agent/local/link.json']
 rule_paths+= [n for n in local_targets if (path/n).is_file()]
 role_plan=plan_default_roles(path,adapter)
 evidence={n:hashlib.sha256((path/n).read_bytes()).hexdigest() for n in sorted(set(rule_paths))}
 result={'suggested_lane':lane,'planned_changes':['.agent/project.json（仅在缺失时创建 context-only 配置）','.agent/tools/（安装独立状态工具，已有不同版本时停止）','.agent/local/（忽略 Git 的项目当前状态）','AGENTS.md / .gitignore（追加简短状态入口与本地状态忽略规则）','本地任务队列（不创建远端项目，不启用自动开发）'],'repo':str(path),'name':path.name,'revision':draft['repository_revision'],'tier':draft['profile_tier'],'worktree':worktree,'adapter_present':bool(adapter),'roles':role_list,'workflow':workflow,'checks':checks,'rules':sorted(set(rule_paths)),'references':[n for n in sorted(files) if pathlib.PurePosixPath(n).name.lower() in ('handoff.md','backlog.md','readme.md')][:20],'lockfiles':sorted(n for n in files if pathlib.PurePosixPath(n).name in ('package-lock.json','pnpm-lock.yaml','yarn.lock','uv.lock','poetry.lock')),'dependencies':dependencies,'warnings':warnings,'automatic_scheduling':False,'allowed_paths':adapter.get('allowed_paths',[]) if adapter else [],'next_action':'已适配项目可通过项目对话维护当前状态；尚未适配的项目请让 agent 使用 project-adapter skill 完成映射。预览不授予执行或发布权限。'}
 if role_plan:result['planned_changes'].insert(1,'.agent/roles/（补齐缺失的默认角色：'+'、'.join(i['role'] for i in role_plan)+'；只写入不存在的文件，不覆盖项目角色）')
 result['fingerprint']=hashlib.sha256(json.dumps({'revision':result['revision'],'evidence':evidence,'roles':fingerprints(registry),'checks':checks,'workflow':workflow,'default_roles':role_plan},sort_keys=True).encode()).hexdigest()
 return result

def connect(root,repo,fingerprint):
 """Adapt/connect context only: one local project entry, no remote board side effects."""
 import fcntl,re,importlib.util
 from project_state import Store
 from lifecycle import save
 root=pathlib.Path(root);value=preview(repo)
 if value['fingerprint']!=fingerprint:raise ValueError('项目文件已变化，请重新预览。')
 if value['worktree']:raise ValueError('关联 worktree 不作为自动开发项目；请选择主仓库。')
 repo=pathlib.Path(value['repo']);lane=value['suggested_lane'];local=repo/'.agent/local';runtime=local/'runtime'
 locks=root/'data/locks';locks.mkdir(parents=True,exist_ok=True)
 with (locks/'config').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  cfg=json.loads((root/'data/control.json').read_text())
  if lane in cfg['projects']:
   if pathlib.Path(cfg['projects'][lane]['repo']).resolve()!=repo:raise ValueError('项目标识已被其他仓库使用。')
   return {'connected':True,'lane':lane,'automatic_scheduling':False}
  for p in cfg['projects'].values():
   if pathlib.Path(p['repo']).resolve()==repo:raise ValueError('该仓库已接入，请使用现有项目。')
  for name in ('.agent','.agent/local','.agent/local/runtime','.agent/local/runtime/data','.agent/local/runtime/data/project-state','.agent/local/runtime/data/project-state/state.sqlite','.agent/tools','.agent/roles','.gitignore','AGENTS.md','.agent/project.json'):
   if (repo/name).is_symlink():raise ValueError('接入目标存在符号链接，请在项目对话中核验。')
  link=local/'link.json'
  if link.exists():
   existing=json.loads(link.read_text())
   if pathlib.Path(existing['runtime']).resolve()!=runtime.resolve() or existing['lane']!=lane:raise ValueError('项目已有其它状态绑定，请在项目对话中连接，不能覆盖。')
  tool_sources={'project-session.py':root/'bin/project-session.py','project_state.py':root/'bin/project_state.py','state_revisions.py':root/'bin/state_revisions.py','product_goals.py':root/'bin/product_goals.py','lifecycle_io.py':root/'bin/lifecycle_io.py'}
  for name,source in tool_sources.items():
   target=repo/'.agent/tools'/name
   if target.exists() and (target.is_symlink() or target.read_bytes()!=source.read_bytes()):raise ValueError('项目工具已有不同版本；请在项目对话中审核升级。')
  local.mkdir(parents=True,exist_ok=True);journal=local/'onboarding.json'
  receipt=json.loads(journal.read_text()) if journal.exists() else {'lane':lane,'phase':'prepared'}
  # One local project entry; no remote project is created and no ids are stored for consumers.
  receipt.update(company=None,project=None,phase='project_ready',tracker='local');save(journal,receipt)
  adapter_path=repo/'.agent/project.json';created=not adapter_path.exists()
  if created:save(adapter_path,{'version':1,'role_discovery':'auto','roles':{},'rules':{'common':[],'reference':value['references']},'workflow':value['workflow'],'allowed_paths':[],'checks':value['checks'],'execution_enabled':False})
  installed_roles=None
  if created:
   # Roles are optional: a failure is reported, never blocks connecting (run the CLI later).
   try:installed_roles=install_default_roles(repo)
   except Exception as exc:installed_roles={'error':str(exc)[:500]}
  (repo/'.agent/tools').mkdir(parents=True,exist_ok=True)
  for name,source in tool_sources.items():
   target=repo/'.agent/tools'/name
   if not target.exists():target.write_bytes(source.read_bytes())
  ignore=repo/'.gitignore';text=ignore.read_text() if ignore.exists() else ''
  if '.agent/local/' not in text.splitlines():ignore.write_text(text+('' if not text or text.endswith('\n') else '\n')+'.agent/local/\n')
  agents=repo/'AGENTS.md';text=agents.read_text() if agents.exists() else ''
  if '<!-- looop-state -->' not in text:agents.write_text(text+'\n\n<!-- looop-state -->\nRead `.agent/project.json` and current state with `python3 .agent/tools/project-session.py context --repo .`. Use start/progress/finish for independent work; start must be accepted before editing. Submit commit-backed stage evidence with result --result-file; finish is self-reported, not review or merge. Historical HANDOFF is context, not current permission. State and tools need no scheduler service.\n')
  Store(runtime).ensure(lane,{'repository':str(repo),'integration':'observe'})
  if not link.exists():save(link,{'runtime':str(runtime),'lane':lane});save(local/'pending.json',[])
  save(local/'snapshot.json',Store(runtime).context(lane))
  locations=root/'data/project-state/locations.json';routes=json.loads(locations.read_text()) if locations.exists() else {};routes[lane]=str(Store(runtime).path);save(locations,routes)
  entry={'repo':str(repo),'integration':'observe','name':value['name']}
  cfg['projects'][lane]=entry;save(root/'data/control.json',cfg)
  (root/'data/project-state/enabled').touch()
  receipt['phase']='connected';save(journal,receipt)
  return {'connected':True,'lane':lane,'automatic_scheduling':False,'default_roles':installed_roles,'message':'已接入当前状态。独立对话可读写同一状态；没有创建执行 agent，也没有启用自动开发。'}
