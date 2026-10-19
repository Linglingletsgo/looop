"""Owner-editable execution routes. Secrets remain in their existing stores."""
import fcntl,json,pathlib,re,shutil,tomllib
from runtime import ROOT
from sandbox import HARNESS_IDS,COMPATIBILITY,claude_subscription
from project_state import Conflict
from magpie_provider import PLANS as MAGPIE_PLANS,configured as magpie_configured

STAGES=('planning','build','review','acceptance','advisory')
DEFAULTS={'planning':'codex','build':'commandcode','review':'codex','acceptance':'codex','advisory':'codex'}

def read(root=ROOT):
 path=pathlib.Path(root)/'data/execution-settings.json'
 return json.loads(path.read_text()) if path.exists() else {'revision':0,'harness':'codex','routes':DEFAULTS.copy(),'codex_model':None}

def public(root=ROOT):
 value=read(root);model=None
 try:model=tomllib.loads((pathlib.Path.home()/'.codex/config.toml').read_text()).get('model')
 except (OSError,ValueError):pass
 value={k:v for k,v in value.items() if k in ('revision','harness','routes','codex_model','stage_harnesses')}
 return {**value,'inherited_codex_model':model,'compatibility':COMPATIBILITY,'harnesses':[{'id':n,'available':bool(shutil.which(n)),'installed':bool(shutil.which(n))} for n in HARNESS_IDS],'plans':[{'id':'codex','configured':(pathlib.Path.home()/'.codex/config.toml').is_file()},{'id':'commandcode','configured':(pathlib.Path(root)/'secrets/commandcode.key').is_file(),'model':'deepseek/deepseek-v4.1-flash'},{'id':'claude_subscription','configured':claude_subscription()},*({'id':plan,'configured':magpie_configured()} for plan in MAGPIE_PLANS)]}

def save(root,value,expected,request_id):
 if value.get('harness') not in HARNESS_IDS:raise ValueError('请选择 Codex、Claude Code 或 OMP。')
 routes=value.get('routes')
 if not isinstance(routes,dict) or set(routes)!=set(STAGES) or any(p not in ('codex','commandcode','claude_subscription',*MAGPIE_PLANS) for p in routes.values()):raise ValueError('每个阶段请选择已支持的 Token Plan。')
 stages=value.get('stage_harnesses',{})
 if not isinstance(stages,dict) or set(stages)-set(STAGES) or any(h not in HARNESS_IDS for h in stages.values()):raise ValueError('阶段 Harness 无效。')
 for stage,provider in routes.items():
  harness=stages.get(stage,value['harness'])
  if provider not in COMPATIBILITY[harness]:raise ValueError('Harness 与 Token Plan 不兼容：'+stage)
 if 'claude_subscription' in routes.values() and not claude_subscription():raise ValueError('请先在 Linux 执行 claude auth login，登录订阅账户。')
 if any(p in MAGPIE_PLANS for p in routes.values()) and not magpie_configured():raise ValueError('请先在 Linux 配置 Magpie 本地网关及凭据。')
 model=value.get('codex_model') or None
 if model is not None and (not isinstance(model,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,100}',model)):raise ValueError('模型名称格式无效。')
 if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}',request_id):raise ValueError('Stable request id required')
 if not isinstance(expected,int) or isinstance(expected,bool):raise ValueError('Settings revision required')
 root=pathlib.Path(root);folder=root/'data/locks';folder.mkdir(parents=True,exist_ok=True)
 command={'harness':value['harness'],'routes':routes,'codex_model':model,'stage_harnesses':stages}
 with (folder/'execution-settings').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);old=read(root)
  if old.get('request_id')==request_id:
   if any(old.get(k,{} if k=='stage_harnesses' else None)!=v for k,v in command.items()):raise Conflict('同一请求不能修改设置内容。')
   return {'revision':old['revision'],'replayed':True}
  if old['revision']!=expected:raise Conflict('执行设置已更新，请刷新。')
  if any(plan=='commandcode' for plan in routes.values()) and not (root/'secrets/commandcode.key').is_file():raise ValueError('Command Code 密钥尚未配置；请通过 SSH 安全录入。')
  result={**command,'revision':expected+1,'request_id':request_id}
  path=root/'data/execution-settings.json';temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2));temp.chmod(0o600);temp.replace(path)
  return {'revision':result['revision'],'message':'执行设置已保存；新规划和新交付使用新设置，正在执行的任务保持原路线。'}

def route(settings,stage,fallback='codex'):
 if not settings:return {'harness':'codex','provider':fallback,'model':None}
 provider=settings.get('routes',{}).get(stage,fallback)
 return {'harness':settings.get('stage_harnesses',{}).get(stage,settings.get('harness','codex')),'provider':provider,'model':settings.get('codex_model') if provider in ('codex','magpie_chatgpt') else None}
