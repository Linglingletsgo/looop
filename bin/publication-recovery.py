"""Read-only GitHub reconciliation after an interrupted publication request."""
import fcntl,hashlib,json,pathlib,subprocess
from process_owner import alive
from lifecycle import save
from gates import require_pr

def reconcile(root,board):
 results=[]
 for path in sorted((root/'data/delivery-bindings').glob('*.json')):
  try:
   binding=json.loads(path.read_text());folder=root/'data/deliveries'/path.stem;receipt=folder/'state.json'
   if not binding.get('publish') or not receipt.is_file():continue
   state=json.loads(receipt.read_text())
   if not (state['state']=='pr_ready' or state['state']=='blocked' and state.get('failed_stage')=='pr_ready'):continue
   if state.get('pr_url') or alive(state.get('owner')) is not False:continue
   repo=binding['policy']['repo'];common=subprocess.check_output(['git','-C',repo,'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()
   with (root/'data/locks'/hashlib.sha256(common.encode()).hexdigest()).open('w') as h:
    try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:continue
    require_pr(state,binding['policy'])
    checks=json.loads((folder/('checks-'+str(state['round'])+'.json')).read_text())
    if [c['argv'] for c in checks]!=binding['policy']['checks'] or any(c['exit_code'] for c in checks):raise ValueError('Local checks missing or failed')
    github_repo=binding['policy']['github_repo'];branch='agent/delivery-'+path.stem;gh=str(pathlib.Path.home()/'.local/bin/gh')
    prs=json.loads(subprocess.check_output([gh,'pr','list','--repo',github_repo,'--head',branch,'--state','all','--json','url,state,headRefOid,headRefName,baseRefName,isCrossRepository,mergedAt,mergeCommit']))
    matches=[p for p in prs if p.get('headRefOid')==state['target_sha'] and p.get('headRefName')==branch and p.get('baseRefName')==binding['policy'].get('base_branch','main') and p.get('isCrossRepository') is False and p.get('url','').startswith('https://github.com/'+github_repo+'/pull/')]
    if len(prs)!=1 or len(matches)!=1:raise ValueError('No unique matching PR; no create/push replay')
    pr=matches[0]
    if pr['state'] not in ('OPEN','MERGED','CLOSED'):raise ValueError('Unknown PR state')
    if pr['state']=='MERGED' and not pr.get('mergeCommit',{}).get('oid'):raise ValueError('Merge commit missing')
    state.update(pr_url=pr['url'],publication_reconciled=True,state={'OPEN':'waiting_for_merge','MERGED':'merged','CLOSED':'closed'}[pr['state']])
    if pr['state']=='MERGED':state.update(merge_commit=pr['mergeCommit']['oid'],merged_at=pr.get('mergedAt'),merge_authority='external')
    save(receipt,state);results.append({'job':path.stem,'state':'reconciled','pr_url':pr['url']})
  except Exception as exc:results.append({'job':path.stem,'state':'needs_attention','reason':str(exc)})
 save(root/'data/publication-recovery-status.json',{'results':results});return results
if __name__=='__main__':
 from board import ROOT,Board
 print(json.dumps(reconcile(ROOT,Board()),ensure_ascii=False))
