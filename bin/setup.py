#!/usr/bin/env python3
"""Install the pinned runtime and skill; do not enable project execution."""
import argparse,json,pathlib,shutil,subprocess

def main():
 p=argparse.ArgumentParser();p.add_argument('--skip-runtime',action='store_true');a=p.parse_args();root=pathlib.Path(__file__).resolve().parents[1]
 for n in ('data','logs','cache','profiles','secrets','.runtime'):(root/n).mkdir(exist_ok=True,mode=0o700)
 if not a.skip_runtime:
  for n in ('package.json','package-lock.json'):shutil.copy2(root/'runtime'/n,root/'.runtime'/n)
  subprocess.run(['npm','ci','--no-audit','--no-fund'],cwd=root/'.runtime',check=True)
 dest=pathlib.Path.home()/'.codex/skills/project-adapter';dest.parent.mkdir(parents=True,exist_ok=True)
 if not dest.exists() and not dest.is_symlink():dest.symlink_to(root/'skills/project-adapter')
 elif dest.resolve()!=(root/'skills/project-adapter').resolve():raise ValueError('Another project-adapter skill is installed; inspect before replacing it')
 settings=root/'data/local-settings.json'
 if not settings.exists():settings.write_text(json.dumps({'board_url':'http://127.0.0.1:3101'},indent=2))
 print('Runtime/skill prepared. Configure local credentials and project registrations separately; no scheduling enabled.')
if __name__=='__main__':main()
