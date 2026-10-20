"""Validate source quotations by exact content, independent of language or length."""
import pathlib
from project_adapter import safe_file

class SourceEvidenceError(ValueError):pass


def quote(repo,name,value):
 if not isinstance(name,str):raise SourceEvidenceError('Source path must be a repository file')
 try:path=safe_file(repo,name)
 except ValueError as exc:raise SourceEvidenceError('Source file unavailable: '+name[:240]) from exc
 if not isinstance(value,str) or not value.strip():raise SourceEvidenceError('Source quotation must be nonempty: '+name)
 if len(value)>2000:raise SourceEvidenceError('Source quotation exceeds 2000 characters: '+name)
 if value not in path.read_text():raise SourceEvidenceError('Source quote not found: '+name)
 return value


def artifact_path(artifacts,name,artifact_base=None):
 """Resolve explicit legacy artifact prefixes only inside this PM run."""
 if not isinstance(name,str) or not name or '..' in pathlib.PurePosixPath(name).parts:raise SourceEvidenceError('Invalid completion proof path')
 path=pathlib.Path(name);artifacts=pathlib.Path(artifacts).absolute()
 if path.is_absolute():
  try:return str(path.relative_to(artifacts))
  except ValueError:raise SourceEvidenceError('Completion proof outside current artifact root') from None
 if artifact_base is not None:
  prefix=artifacts.relative_to(pathlib.Path(artifact_base).absolute())
  if path.is_relative_to(prefix):return str(path.relative_to(prefix))
 return None


def verify_completion(repo,artifacts,goal,evidence,target,artifact_base=None):
 """Verify exact source/artifact quotations and revision identity, never usability."""
 from product_goals import completion_coverage
 completion_coverage(evidence,goal['success_criteria'],goal.get('experience'))
 runtime_kinds=('runtime_check','agent_walkthrough','user_test')
 for e in evidence:
  kind=e.get('kind');name=e.get('path')
  if kind not in (None,'repository',*runtime_kinds):raise SourceEvidenceError('Unknown completion proof kind')
  relative=artifact_path(artifacts,name,artifact_base)
  runtime=kind in runtime_kinds or relative is not None
  if runtime:
   if kind=='repository':raise SourceEvidenceError('Repository proof points to a run artifact')
   relative=relative if relative is not None else name
   quote(artifacts,relative,e.get('quote'))
   if kind in runtime_kinds or 'target_sha' in e:
    if e.get('target_sha')!=target:raise SourceEvidenceError('Runtime proof targets another revision')
   elif target not in safe_file(artifacts,relative).read_text():
    # Legacy PM reports omitted kind/SHA; accept only a run-scoped report naming this SHA.
    raise SourceEvidenceError('Legacy runtime proof must name the current target SHA')
  else:quote(repo,name,e.get('quote'))
 return evidence
