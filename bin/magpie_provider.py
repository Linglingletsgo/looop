"""Selected subscription routes through the user's existing local Magpie gateway."""
import os,pathlib,tomllib,urllib.parse

PLANS=('magpie_chatgpt','magpie_deepseek','magpie_commandcode')
DEEPSEEK='workbuddy/deepseek-v4.1-flash'

def connection(config_path=None):
 path=pathlib.Path(config_path) if config_path else pathlib.Path.home()/'.codex/config.toml'
 config=tomllib.loads(path.read_text());provider=config.get('model_providers',{}).get(config.get('model_provider'),{})
 base=provider.get('base_url','');url=urllib.parse.urlsplit(base)
 if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.port!=3425 or url.path.rstrip('/')!='/v1' or url.username or url.password or url.query or url.fragment:raise ValueError('Magpie local gateway must be configured in Linux Codex at http://127.0.0.1:3425/v1')
 token=provider.get('experimental_bearer_token') or os.environ.get(provider.get('env_key',''),'')
 if not token:raise ValueError('Magpie gateway credential unavailable in Linux Codex configuration')
 return base.rstrip('/'),token,config.get('model','gpt-6.1-sol')

def configured():
 try:connection();return True
 except (OSError,ValueError,TypeError):return False

def selected(provider,model=None):
 base,token,inherited=connection()
 if provider=='magpie_commandcode':model='commandcode/deepseek/deepseek-v4.1-flash'
 elif provider=='magpie_deepseek':model=DEEPSEEK
 elif provider=='magpie_chatgpt':
  model=model or inherited
  if model.startswith('codex/'):model=model[len('codex/'):]
  if '/' in model or not model.startswith(('gpt-','o1','o3','o4')):raise ValueError('Magpie ChatGPT requires a ChatGPT subscription model')
  model='codex/'+model
 else:raise ValueError('Unknown Magpie subscription')
 return base,token,model

def claude_environment(env,base,token,model):
 env=env.copy()
 for key in ('CLAUDE_CODE_OAUTH_TOKEN','ANTHROPIC_AUTH_TOKEN'):
  env.pop(key,None)
 env.update(ANTHROPIC_BASE_URL=base.removesuffix('/v1'),ANTHROPIC_API_KEY=token,ANTHROPIC_MODEL=model,
  ANTHROPIC_DEFAULT_HAIKU_MODEL=model,ANTHROPIC_DEFAULT_SONNET_MODEL=model,ANTHROPIC_DEFAULT_OPUS_MODEL=model,
  CLAUDE_CODE_SUBAGENT_MODEL=model,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',DISABLE_AUTOUPDATER='1')
 return env
