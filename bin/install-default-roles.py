#!/usr/bin/env python3
"""Preview or install missing looop default roles into an adapted project."""
import argparse,json,pathlib
from runtime import CODE_ROOT
from role_install import install_default_roles,plan_default_roles
CHECKOUT=pathlib.Path(__file__).resolve().parents[1]

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',required=True);p.add_argument('--all',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args(argv)
 repo=pathlib.Path(a.repo).expanduser().resolve(strict=True)
 if repo in (CODE_ROOT,CHECKOUT) or ((repo/'bin/role_install.py').is_file() and (repo/'default-roles').is_dir()):p.error('Refusing to install into the looop checkout itself')
 if a.apply:print(json.dumps(install_default_roles(repo,a.all),ensure_ascii=False,indent=2))
 else:
  from role_install import blocked
  view={'plan':plan_default_roles(repo,include_all=a.all),'adapter_missing':not (repo/'.agent/project.json').is_file(),'blocked':blocked(repo)}
  print(json.dumps(view,ensure_ascii=False,indent=2))
 return 0

if __name__=='__main__':raise SystemExit(main())
