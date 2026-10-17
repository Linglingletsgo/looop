"""Linux process identity survives PID reuse checks and distinguishes machine boots."""
import os,pathlib

def identity(pid=None):
 pid=os.getpid() if pid is None else pid
 stat=pathlib.Path('/proc')/str(pid)/'stat'
 return {'pid':pid,'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'start_ticks':stat.read_text().rsplit(')',1)[1].split()[19]}

def alive(owner):
 if not owner:return None
 try:return identity(owner['pid'])==owner
 except FileNotFoundError:return False
 except (KeyError,PermissionError,ValueError,IndexError):return None
