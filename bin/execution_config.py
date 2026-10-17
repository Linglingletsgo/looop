"""Inherit project contracts; runtime credentials and harness stay controller-owned."""
import copy,json,pathlib,re,shutil
from runtime import ROOT,CODE_ROOT
from project_adapter import load,evidence
from roles import resolve,fingerprints
from repository import git

def inherited_policy(repo):
 repo=pathlib.Path(repo).resolve();adapter=load(repo)
 if not adapter:raise ValueError('缺少 .agent/project.json，请先完成项目适配。')
 if adapter.get('execution_enabled') is False:raise ValueError('项目当前为仅观察模式，请先在项目对话中确认现有工作流可执行。')
 defaults=CODE_ROOT/'runtime/execution-defaults.json'
 local=ROOT/'data/execution-defaults.json'
 base=json.loads(defaults.read_text())
 if local.exists():base.update(json.loads(local.read_text()))
 registry=resolve(repo,adapter)
 workflow=copy.deepcopy(registry['workflow'] or base['workflow'])
 checks=adapter.get('checks',[])
 if not checks:raise ValueError('适配层缺少项目检查命令。')
 for argv in checks:
  if not isinstance(argv,list) or not argv or argv[0] not in ('node','python3','npm'):raise ValueError('当前执行环境尚不支持此检查命令；请适配运行环境：'+str(argv))
  if not shutil.which(argv[0]):raise ValueError('缺少运行工具：'+argv[0])
 origin=git(repo,'remote','get-url','origin').decode().strip()
 match=re.fullmatch(r'(?:git@github.com:|https://github.com/)([\w.-]+/[\w.-]+?)(?:\.git)?',origin)
 if not match:raise ValueError('当前发布器需要 GitHub origin；不会替换项目 remote。')
 branch=git(repo,'branch','--show-current').decode().strip()
 if not branch:raise ValueError('执行配置需要项目主分支，不能使用 detached HEAD。')
 policy={'enabled':True,'repo':str(repo),'github_repo':match[1],'base_branch':branch,'project_adapter':adapter,'workflow':workflow,'checks':checks,'max_rounds':base['max_rounds'],'role_registry':fingerprints(registry),'workflow_evidence':evidence(repo,adapter)}
 if adapter.get('allowed_paths'):
  policy['allowed_paths']=adapter['allowed_paths']
 else:policy.update(scope_mode='task_paths',allowed_paths=[])
 deps=repo/'node_modules'
 if (repo/'package.json').is_file():
  if not deps.is_dir():raise ValueError('请先在 Linux 按项目锁文件安装依赖。')
  policy['dependencies']=str(deps)
 return policy

def inherited_mandate(policy):
 adapter=policy.get('project_adapter',{})
 result={'enabled':False,'pm_role':adapter.get('planning_role','product-manager'),'scope_approval':'pm','purpose':'Advance current project backlog and confirmed requirements within native project rules and product direction. Research only when enabled in current state.','evidence_paths':sorted(evidence(policy['repo'],adapter)),'backlog_paths':adapter.get('backlog_paths',[n for n in adapter.get('rules',{}).get('common',[])+adapter.get('rules',{}).get('reference',[]) if 'backlog' in pathlib.PurePosixPath(n).name.lower()])}
 if policy.get('scope_mode')!='task_paths':result['allowed_paths']=policy['allowed_paths']
 return result
