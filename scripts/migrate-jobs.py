#!/usr/bin/env python3
"""Import existing bindings, delivery receipts and autonomy receipts into jobs."""
import argparse,json,pathlib,sys
CODE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'bin'))
from job_migration import migrate
from runtime import ROOT

def main(argv=None):
 parser=argparse.ArgumentParser(description='Migrate existing runtime records into data/jobs.sqlite (dry run by default).')
 parser.add_argument('--apply',action='store_true',help='write the planned jobs; default is a dry run')
 parser.add_argument('--root',default=str(ROOT),help='runtime root (default: %(default)s)')
 args=parser.parse_args(argv)
 root=pathlib.Path(args.root)
 try:result=migrate(root,apply=args.apply)
 except Exception as exc:parser.error(str(exc))
 print(json.dumps(result,ensure_ascii=False))
 return 1 if args.apply and (result['conflicts'] or result['errors']) else 0

if __name__=='__main__':sys.exit(main())
