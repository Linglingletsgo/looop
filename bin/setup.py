#!/usr/bin/env python3
"""Prepare the local runtime root and skill; do not enable project execution."""
import argparse,json,pathlib

def main():
 p=argparse.ArgumentParser();p.add_argument('--skip-runtime',action='store_true');a=p.parse_args();root=pathlib.Path(__file__).resolve().parents[1]
 for n in ('data','logs','cache','profiles','secrets'):(root/n).mkdir(exist_ok=True,mode=0o700)
 dest=pathlib.Path.home()/'.codex/skills/project-adapter';dest.parent.mkdir(parents=True,exist_ok=True)
 if not dest.exists() and not dest.is_symlink():dest.symlink_to(root/'skills/project-adapter')
 elif dest.resolve()!=(root/'skills/project-adapter').resolve():raise ValueError('Another project-adapter skill is installed; inspect before replacing it')
 settings=root/'data/local-settings.json'
 if not settings.exists():settings.write_text(json.dumps({'tracker':'local'},indent=2))
 print('Runtime/skill prepared. Configure local credentials and project registrations separately; no scheduling enabled.')
if __name__=='__main__':main()
