#!/usr/bin/env python3
"""User service supervises only its named tmux session; never touches peer sessions."""
import pathlib,signal,subprocess,time,sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
SESSION='paperclip-board'
stopping=False

def stop(*_):
 global stopping
 stopping=True

def alive():return subprocess.run(['tmux','has-session','-t',SESSION],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,stop)
failures=[]
while not stopping:
 if not alive():
  now=time.monotonic();failures=[t for t in failures if now-t<600]
  if len(failures)>=5:print('Restart budget exhausted; operator attention required.',flush=True);sys.exit(1)
  failures.append(now)
  subprocess.run(['tmux','new-session','-d','-s',SESSION,'-c',str(ROOT),f'exec {ROOT}/bin/run-paperclip >>{ROOT}/logs/server.log 2>&1'],check=True)
  print('Paperclip tmux session started',flush=True)
 for _ in range(5):
  if stopping:break
  time.sleep(1)
if alive():
 subprocess.run(['tmux','send-keys','-t',SESSION,'C-c'],check=False)
 for _ in range(45):
  if not alive():break
  time.sleep(1)
 if alive():print('Owned session still draining; left intact for operator.',flush=True)
