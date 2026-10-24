"""Independent maintenance steps; one failed integration must not suppress others."""
import json,pathlib,subprocess
from tracker import local_mode

def commands(root):
 config=json.loads((root/'data/control.json').read_text());local=local_mode(root)
 steps=[['python3','bin/retention.py'],['python3','bin/binding_requests.py'],['python3','bin/planning-recovery.py'],['python3','bin/publication-recovery.py'],['python3','bin/restart-recovery.py'],['python3','bin/dispatch.py'],['python3','bin/state-sync.py'],['python3','bin/delivery-control.py','sync-prs'],['python3','bin/health.py']]
 for lane,cfg in config['projects'].items():
  if (cfg.get('id') or local) and (root/'data/autonomy-policies'/(lane+'.json')).exists():steps.append(['python3','bin/loop-status.py',lane])
 return steps

def main(root=None):
 root=pathlib.Path(root or pathlib.Path(__file__).resolve().parent.parent);failed=False
 for argv in commands(root):
  try:
   result=subprocess.run(argv,cwd=root,check=False);failed=failed or result.returncode!=0
  except OSError as exc:print('Maintenance step unavailable:',argv,exc,flush=True);failed=True
 return int(failed)
if __name__=='__main__':raise SystemExit(main())
