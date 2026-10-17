"""Preview/enable project execution from its existing contract; never invent a workflow."""
import fcntl,hashlib,importlib.util,json,pathlib
from execution_config import inherited_policy
from project_adapter import load
from project_state import Store,Conflict
from repository import git
from runtime import CODE_ROOT

def preview(root,lane):
 root=pathlib.Path(root);cfg=json.loads((root/'data/control.json').read_text());project=cfg['projects'][lane];repo=pathlib.Path(project['repo']);reasons=[]
 if lane=='ds1':return {'ready':False,'blockers':['DS1 为人工 UI worktree，不接入自动开发。']}
 adapter=load(repo)
 if not adapter:reasons.append('缺少项目适配层 .agent/project.json。')
 else:
  if adapter.get('execution_enabled') is False:reasons.append('适配层仍为仅观察模式；需完成项目执行映射。')
  if not adapter.get('checks'):reasons.append('未配置项目检查命令。')
  if not adapter.get('workflow') and adapter.get('workflow_mapping'):reasons.append('已有项目流程说明，但尚未映射可执行阶段。')
  workflow=(adapter or {}).get('workflow',[])
  acceptance_text='\n'.join((repo/n).read_text() for n in adapter.get('roles',{}).get('acceptance',[]) if (repo/n).is_file())
  if 'black-box' in adapter.get('workflow_mapping','') or 'black-box' in acceptance_text or '默认不提供 implementation source' in acceptance_text:
   reasons.append('当前交付器尚不支持该项目要求的无源码黑盒验收运行环境。')
 if git(repo,'status','--porcelain').strip():reasons.append('存在未提交或未跟踪文件，需在项目对话中固定执行基线；系统不会自动提交或丢弃。')
 if pathlib.Path(git(repo,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()).resolve()!=(repo/'.git').resolve():reasons.append('关联 worktree 保持人工开发，请使用主仓库。')
 if not repo.resolve().is_relative_to((root/'data/execution-repos').resolve()):reasons.append('尚未准备独立执行 checkout；需保留人工工作区，并建立已核验的执行基线。')
 if not reasons:
  try:
   inherited_policy(repo)
   from bridge import validate_profile
   if not project.get('profile'):raise ValueError('尚未建立已核验的项目执行基线 profile。')
   validate_profile(project['profile'])
  except (ValueError,OSError) as exc:reasons.append(str(exc))
 sha=git(repo,'rev-parse','HEAD').decode().strip()
 fingerprint=hashlib.sha256(json.dumps({'sha':sha,'adapter':adapter,'blockers':reasons},sort_keys=True).encode()).hexdigest()
 return {'ready':not reasons,'blockers':reasons,'fingerprint':fingerprint,'workflow':adapter.get('workflow',[]) if adapter else [],'checks':adapter.get('checks',[]) if adapter else [],'message':'准备完成后可启用配置，再选择单次或持续运行。启用本身不派发开发，也不改变合并策略。','adaptation_prompt':'完成当前项目的 looop 执行适配：保留现有角色、产品状态、未提交和未跟踪文件；把既有工作流、检查与运行环境映射到 .agent/project.json。遵守项目验收要求，检查执行器能力，无法支持的步骤明确标为阻塞。不要自动提交、推送、开启循环或改动 DS1。完成后返回 looop 的“准备自动开发”重新检查。'}

def enable(root,lane,expected,request_id,fingerprint):
 root=pathlib.Path(root);store=Store(root)
 if store.read(lane)['revision']!=expected:raise Conflict('项目状态已更新，请重新检查。')
 value=preview(root,lane)
 if value['fingerprint']!=fingerprint:raise Conflict('执行准备已变化，请重新检查。')
 if not value['ready']:raise ValueError('；'.join(value['blockers']))
 store.project_guard(lane)
 cfg=json.loads((root/'data/control.json').read_text());repo=pathlib.Path(cfg['projects'][lane]['repo'])
 # The controller refreshes only its dedicated checkout after merge; never the human workspace.
 if not repo.resolve().is_relative_to((root/'data/execution-repos').resolve()):raise ValueError('需先准备独立执行 checkout，不能把人工工作区作为自动合并后的刷新目标。')
 locks=root/'data/locks';locks.mkdir(exist_ok=True,parents=True)
 with (locks/'config').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  path=root/'data/activation'/(lane+'.json')
  prior=json.loads(path.read_text()) if path.exists() else {}
  if prior.get('status')=='pending':raise ValueError('上次配置结果待核验；不会重复创建执行 Agent。')
  if prior.get('status')=='configured' and prior.get('fingerprint')==fingerprint:return {'message':'配置已启用，请选择单次或持续运行。'}
  from lifecycle import save
  save(path,{'status':'pending','request_id':request_id,'fingerprint':fingerprint})
  spec=importlib.util.spec_from_file_location('configure_delivery',CODE_ROOT/'bin/delivery-control.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=root
  module.configure(lane)
  save(path,{'status':'configured','request_id':request_id,'fingerprint':fingerprint})
 return {'message':'自动开发配置已启用。请选择单次执行或持续运行。'}
