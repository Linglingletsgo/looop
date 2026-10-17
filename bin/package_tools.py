"""Expose the installed npm distribution without exposing the user's home or npmrc."""
import pathlib,shutil

def mount_npm(cmd,agent=False):
 found=shutil.which('npm')
 if not found:return
 cli=pathlib.Path(found).resolve()
 if cli.name!='npm-cli.js' or not (cli.parent.parent/'package.json').is_file():raise ValueError('Unsupported npm installation layout')
 idx=cmd.index('--chdir')
 cmd[idx:idx]=['--ro-bind',str(cli.parent.parent),'/tools/npm-package','--symlink','/tools/npm-package/bin/npm-cli.js','/tools/npm','--setenv','npm_config_cache','/tmp/npm-cache','--setenv','npm_config_update_notifier','false','--setenv','npm_config_audit','false','--setenv','PATH',('/opt:' if agent else '')+'/tools:/usr/bin:/bin']
