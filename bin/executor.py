"""Project checks use the same Linux tools as native harness jobs."""
import os,pathlib,subprocess

def command(workspace,argv,timeout=None,stdin=None,writable=False,dependencies=None):
 if not isinstance(argv,list) or not argv or not all(isinstance(x,str) for x in argv):raise ValueError('Check argv required')
 from sandbox import workspace_environment,execution_environment
 from repository import source_fingerprint
 env=execution_environment();env['PYTHONDONTWRITEBYTECODE']='1'
 before=source_fingerprint(workspace) if not writable else None
 with workspace_environment(workspace,dependencies):
  result=subprocess.run(argv,cwd=workspace,input=stdin,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout or None,env=env)

 if before is not None and source_fingerprint(workspace)!=before:raise RuntimeError("Check command modified source; result rejected")
 return result
