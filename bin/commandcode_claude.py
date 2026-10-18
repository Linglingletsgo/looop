"""Private CLIProxyAPI bridge: Anthropic Messages to Command Code OpenAI."""
import json,os,pathlib,secrets,shutil,subprocess
MODEL='deepseek/deepseek-v4.1-flash'
BASE='http://127.0.0.1:8318'

def environment(root,env):
 env=env.copy()
 for key in ('ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN','CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY'):
  env.pop(key,None)
 key=pathlib.Path(root)/'data/commandcode-claude/client.key'
 if not key.is_file():raise RuntimeError('Run bin/setup-commandcode-claude.py before selecting Claude Code / Command Code')
 env.update(ANTHROPIC_BASE_URL=BASE,ANTHROPIC_API_KEY=key.read_text().strip(),ANTHROPIC_MODEL=MODEL,
  ANTHROPIC_DEFAULT_HAIKU_MODEL=MODEL,ANTHROPIC_DEFAULT_SONNET_MODEL=MODEL,ANTHROPIC_DEFAULT_OPUS_MODEL=MODEL,
  CLAUDE_CODE_SUBAGENT_MODEL=MODEL,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',DISABLE_AUTOUPDATER='1')
 return env

def configure(root):
 root=pathlib.Path(root);binary=shutil.which('cliproxyapi') or '/usr/local/bin/cliproxyapi'
 if not pathlib.Path(binary).is_file():raise RuntimeError('Install CLIProxyAPI before configuring the bridge')
 upstream=(root/'secrets/commandcode.key').read_text().strip()
 if not upstream:raise ValueError('Command Code key is empty')
 folder=root/'data/commandcode-claude';folder.mkdir(mode=0o700,parents=True,exist_ok=True);folder.chmod(0o700)
 (folder/'auth').mkdir(mode=0o700,exist_ok=True)
 key=folder/'client.key'
 if not key.exists():key.write_text(secrets.token_urlsafe(36))
 key.chmod(0o600)
 config={'config-version':8,'server':{'host':'127.0.0.1','port':8318},
  'management':{'secret-key':'','disable-control-panel':True},
  'access':{'api-keys':[key.read_text().strip()]},'oauth':{'auth-dir':str(folder/'auth')},
  'api-keys':{'openai-compatibility':[{'name':'commandcode-flash','base-url':'https://api.commandcode.ai/provider/v1',
   'keys':[{'api-key':upstream}],'models':[{'name':MODEL,'alias':MODEL}]}]},
  'routing':{'retry':{'request-retry':0}},
  'observability':{'logs':{'logging-to-file':False,'request-log':False,'logs-max-total-size-mb':10,'error-logs-max-files':2}}}
 path=folder/'config.json';path.write_text(json.dumps(config));path.chmod(0o600)
 service=pathlib.Path.home()/'.config/systemd/user/looop-commandcode-claude.service';service.parent.mkdir(parents=True,exist_ok=True)
 service.write_text('[Unit]\nDescription=Command Code Flash protocol bridge for Claude Code\nAfter=network-online.target\n[Service]\nType=simple\nWorkingDirectory='+str(folder)+'\nExecStart='+binary+' -local-model -config '+str(path)+'\nRestart=on-failure\nRestartSec=5\nUMask=0077\nStandardOutput=null\nStandardError=journal\n[Install]\nWantedBy=default.target\n')
 subprocess.run(['systemctl','--user','daemon-reload'],check=True)
 subprocess.run(['systemctl','--user','enable','--now',service.name],check=True)
 subprocess.run(['systemctl','--user','restart',service.name],check=True)
 print('Claude Code / Command Code bridge configured on '+BASE)
