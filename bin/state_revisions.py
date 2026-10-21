"""Console input appends commute with progress; edits retain optimistic locking."""

def check(expected,current,command,source):
 if expected is None or expected==current:return
 # Only independent new inputs can append to the latest state under the writer
 # lock. Updates, supersession, task changes and execution controls stay strict.
 if source=='looop-console' and command.get('type') in ('requirement','decision') and type(expected) is int and 0<=expected<current:return
 from project_state import Conflict
 raise Conflict('Project state changed: expected '+str(expected)+', current '+str(current)+'; reread and reassess')
