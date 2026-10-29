"""Short timer/API launcher; model work stays in independent tmux sessions."""
import json,shlex,subprocess,sys
from runtime import ROOT
from loop_control import settle
from jobs import Jobs
from tracker import LocalTracker,resolve_tracker

def delivery_pending(root,lane):
 # A bound delivery job no live worker holds. in_progress is included, as the retired
 # heartbeat did, so a worker that died before writing a receipt is resumed.
 if not (root/'data/jobs.sqlite').exists():return []
 tracker=LocalTracker(Jobs(root),root)
 return [job for job in tracker.assigned(lane,lane+':delivery',('todo','in_progress')) if tracker.jobs.holder(job['id']) is None]

def launch_delivery(root,lane):
 # Delivery continues while planning is paused: a bound Packet keeps running.
 if not delivery_pending(root,lane):return
 session='looop-delivery-'+lane
 if subprocess.run(['tmux','has-session','-t',session],capture_output=True).returncode==0:return
 cmd='export PATH="$HOME/.local/bin:$PATH"; exec /usr/bin/python3 '+shlex.quote(str(root/'bin/delivery-worker.py'))+' '+shlex.quote(lane)+' >> '+shlex.quote(str(root/'logs'/('delivery-'+lane+'.log')))+' 2>&1'
 subprocess.run(['tmux','new-session','-d','-s',session,'-c',str(root),cmd],check=True)

def launch(root=ROOT,lane_filter=None):
 resolve_tracker(root)
 cfg=json.loads((root/'data/control.json').read_text())
 for lane in cfg['projects']:
  if lane_filter is not None and lane!=lane_filter:continue
  if (root/'data/delivery-policies'/(lane+'.json')).exists():
   # A broken jobs table or tmux failure must not stop planning launches.
   try:launch_delivery(root,lane)
   except Exception as exc:print('Delivery launch skipped for '+lane+': '+str(exc)[:300],file=sys.stderr)
  if not (root/'data/autonomy-policies'/(lane+'.json')).exists():continue
  mode=settle(root,lane)
  if not mode['allowed'] or mode['mode']=='paused' or mode['mode']=='once' and mode.get('attempt'):continue
  session='looop-loop-'+lane
  if subprocess.run(['tmux','has-session','-t',session],capture_output=True).returncode==0:continue
  cmd='export PATH="$HOME/.local/bin:$PATH"; exec /usr/bin/python3 '+shlex.quote(str(root/'bin/autonomy.py'))+' '+shlex.quote(lane)+' >> '+shlex.quote(str(root/'logs'/('loop-'+lane+'.log')))+' 2>&1'
  subprocess.run(['tmux','new-session','-d','-s',session,'-c',str(root),cmd],check=True)
if __name__=='__main__':launch()
