"""Short timer/API launcher; model work stays in independent tmux sessions."""
import json,shlex,subprocess
from runtime import ROOT
from loop_control import settle

def launch(root=ROOT,lane_filter=None):
 cfg=json.loads((root/'data/control.json').read_text())
 for lane in cfg['projects']:
  if lane_filter is not None and lane!=lane_filter:continue
  if not (root/'data/autonomy-policies'/(lane+'.json')).exists():continue
  mode=settle(root,lane)
  if not mode['allowed'] or mode['mode']=='paused' or mode['mode']=='once' and mode.get('attempt'):continue
  session='looop-loop-'+lane
  if subprocess.run(['tmux','has-session','-t',session],capture_output=True).returncode==0:continue
  cmd='export PATH="$HOME/.local/bin:$PATH"; exec /usr/bin/python3 '+shlex.quote(str(root/'bin/autonomy.py'))+' '+shlex.quote(lane)+' >> '+shlex.quote(str(root/'logs'/('loop-'+lane+'.log')))+' 2>&1'
  subprocess.run(['tmux','new-session','-d','-s',session,'-c',str(root),cmd],check=True)
if __name__=='__main__':launch()
