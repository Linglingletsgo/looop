"""Commands in a private namespace, without model API or host credentials."""
import os,pathlib,subprocess

def command(workspace,argv,timeout=None,stdin=None,writable=False,dependencies=None):
 if not argv or argv[0] not in ['python3','/usr/bin/python3','node','npm']:raise ValueError('Unapproved check executable')
 cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/etc','--dir','/tools','--tmpfs','/home','--setenv','HOME','/tmp','--setenv','PATH','/usr/bin:/bin','--setenv','PYTHONDONTWRITEBYTECODE','1','--bind' if writable else '--ro-bind',str(pathlib.Path(workspace).resolve()),'/workspace','--chdir','/workspace',*argv]
 if argv[0]=='npm' and not dependencies:raise ValueError('npm checks require verified project dependencies')
 if dependencies:
  (pathlib.Path(workspace)/'node_modules').mkdir(exist_ok=True)
  node=(pathlib.Path.home()/'.local/bin/node').resolve()
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(node),'/tools/node','--ro-bind',str(pathlib.Path(dependencies).resolve()),'/workspace/node_modules','--setenv','PATH','/tools:/usr/bin:/bin']
 if dependencies:
  from package_tools import mount_npm
  mount_npm(cmd)
 if dependencies and (pathlib.Path(dependencies).parent/'web/node_modules').is_dir():
  (pathlib.Path(workspace)/'web/node_modules').mkdir(parents=True,exist_ok=True)
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str((pathlib.Path(dependencies).parent/'web/node_modules').resolve()),'/workspace/web/node_modules']
 from runtime import ROOT
 browser_root=ROOT/'data/browsers'
 browsers=list(browser_root.glob('chromium-*/chrome-linux*/chrome'))
 if browsers:
  idx=cmd.index('--chdir');cmd[idx:idx]=['--ro-bind',str(browser_root),'/browsers','--setenv','CHROMIUM_PATH','/browsers/'+str(browsers[0].relative_to(browser_root))]
  if pathlib.Path('/etc/fonts').exists():cmd[idx:idx]=['--ro-bind','/etc/fonts','/etc/fonts']
 return subprocess.run(cmd,input=stdin,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout or None,env={'PATH':'/usr/bin:/bin'})
