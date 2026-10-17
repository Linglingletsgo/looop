"""Explicitly scoped GTP regression-test pilot; no application service or DB access."""
import fcntl,json,os,pathlib,shutil,subprocess,time,uuid
from board import Board,ROOT
from bridge import snapshot,git
from executor import command
from sandbox import run
from pipeline import files,verdict
from gates import require_pr,require_reviews,update_target,GateError
b=Board();control=json.loads((ROOT/'data/gtp-control.json').read_text())
if os.environ.get('PAPERCLIP_AGENT_ID')!=control['agent']:raise ValueError('Identity mismatch')
tasks=b.api('GET',f'/companies/{control["company"]}/issues?assigneeAgentId={control["agent"]}&status=todo,in_progress')
tasks=[t for t in tasks if t.get('projectId')==control['project'] and t['status'] in ['todo','in_progress']]
if not tasks:print('No task; no model call.');raise SystemExit()
task=tasks[0];issue=task['id'];root=ROOT/'data/gtp-pilot'/issue
if root.exists():print('Existing attempt; no automatic replay.');raise SystemExit()
root.mkdir(mode=0o700)
state={'state':'planning','risk':'low','reviews':{},'acceptance':None}
def emit(stage):
 state['state']=stage;tmp=root/'state.tmp';tmp.write_text(json.dumps(state,indent=2));tmp.replace(root/'state.json')
 print(stage,flush=True);b.api('POST','/issues/'+issue+'/comments',{'body':'GTP pilot: '+stage})
repo=ROOT/'data/gtp-pilot/repo';sha=git(repo,'rev-parse','HEAD').decode().strip();deps=repo/'node_modules'
packet={'bundle':'valid-delivery-count-regression','baseline_sha':sha,'agent_system_sha':sha,'requirements':['仅修改 src/run/delivery-gap.test.ts，保持已有测试和断言，不修改产品实现/配置/规则。','补充有效交付数 validDeliveredResults 与 deliveredResults 不同的用例：已交付5但有效2、target3时 have2/delivered5/shortfall1/metfalse；显式有效计数空对象应按0处理，不回退已交付；有效计数缺失保持旧兼容行为。','现有 assertSameStandard 的 helper 把 view.have 等同 deliveredCount，这只适用于旧数据相同的情形；可修正 helper 使用 validDeliveredCount，而 delivered 仍断言 deliveredCount；不得降低已有断言。','测试只用 synthetic makeGoal/makeCollectedState，不调用真实模型/网络/数据库/SMTP，不启动服务。'],'allowed_paths':['src/run/delivery-gap.test.ts'],'checks':[['node','node_modules/vitest/vitest.mjs','run','src/run/delivery-gap.test.ts','--maxWorkers=1','--configLoader=runner','--no-cache']]}
(root/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2))
lock=(ROOT/'data/locks/gtp').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('GTP busy')
def role(name,workspace,prompt,provider='codex',metadata=None):
 rid=name+'-'+uuid.uuid4().hex[:10]
 text=run(workspace,root/rid,prompt,role=name,provider_id=provider,dependencies=deps,git_metadata=metadata,timeout=600)
 return rid,text
try:
 # Dedicated fixture must have completed before any real-project model dispatch.
 candidates=list((ROOT/'data/pipelines').glob('*/state.json'))
 if not any(json.loads(p.read_text()).get('state')=='waiting_for_merge' for p in candidates):raise GateError('Synthetic end-to-end verification not yet passed')
 b.api('PATCH','/issues/'+issue,{'status':'in_progress'});emit('planning')
 candidate=root/'candidate';subprocess.run(['git','clone','--quiet','--no-hardlinks',str(repo),str(candidate)],check=True)
 branch='agent/paperclip-gtp-'+issue[:8];git(candidate,'checkout','-b',branch,sha)
 baseline=snapshot(candidate,sha,root/'baseline')
 handoff=(baseline/'HANDOFF.md').read_text()
 _,plan=role('product',baseline,'你是本项目 Product/PO，做一次有终点的只读计划。当前用户授权用此项目验证调度器，选择仅补充回归测试的低风险任务，不恢复应用服务。HANDOFF 的历史 HEAD 与旧未提交状态不是当前事实。工作区为 /workspace，没有 .git，基线由可信控制器固定。只规划以下 Packet，不扩大范围。\n'+json.dumps(packet,ensure_ascii=False)+'\nHANDOFF:\n'+handoff)
 (root/'product-handoff.md').write_text(plan)
 workspace=snapshot(candidate,sha,root/'builder-workspace');before=files(workspace);emit('building')
 rid,report=role('builder',workspace,'你是 Builder，仅实现已批准测试 Packet。工作目录 /workspace；只能修改 allowed_paths。项目依赖已只读挂载，聚焦测试用 node node_modules/vitest/vitest.mjs run src/run/delivery-gap.test.ts --maxWorkers=1 --configLoader=runner --no-cache 。不能 npm install、不能操作原工作区、不能提交或推送。最终总结测试。\n'+json.dumps(packet,ensure_ascii=False)+'\nPO plan:\n'+plan,provider='commandcode')
 after=files(workspace);changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
 if not changed or not changed<=set(packet['allowed_paths']):raise GateError('Outside approved scope/no change')
 for path in changed:shutil.copy2(workspace/path,candidate/path)
 git(candidate,'add','--',*sorted(changed));git(candidate,'-c','core.hooksPath=/dev/null','-c','user.name=Agent Control','-c','user.email=agent-control@localhost','commit','-m','test: cover valid versus delivered count gaps')
 target=git(candidate,'rev-parse','HEAD').decode().strip();state.update(target_sha=target,builder_run=rid);emit('checking')
 review=snapshot(candidate,target,root/'review-workspace')
 for argv in packet['checks']:
  p=command(review,argv,dependencies=deps);(root/'focused-tests.log').write_text(p.stdout)
  if p.returncode:raise GateError('Focused tests failed')
 # All root unit/display tests and typecheck, never integration/DB.
 for name,argv in [('all-unit',['node','node_modules/vitest/vitest.mjs','run','--maxWorkers=4','--configLoader=runner','--no-cache']),('typecheck',['node','node_modules/typescript/bin/tsc','--noEmit'])]:
  p=command(review,argv,timeout=240,dependencies=deps);(root/(name+'.log')).write_text(p.stdout)
  if p.returncode:raise GateError(name+' failed; inspect scoped log')
 emit('review_standard')
 rr,text=role('reviewer',review,'你是 fresh 独立 Reviewer。源码 /workspace 只读，.git 元数据只读可核验目标SHA及基线diff。检查测试是否真实覆盖需求、是否保留原有断言、是否只修改允许文件，可运行聚焦测试。不要改代码。最终仅返回 JSON {"verdict":"approved|changes_requested|blocked","findings":[...]}。\n'+json.dumps(packet,ensure_ascii=False)+'\nTarget SHA:'+target,metadata=candidate/'.git')
 v=verdict(text);state['reviews']['standard']={**v,'run_id':rr,'mode':'standard','target_sha':target};require_reviews(state)
 emit('acceptance_mutation')
 mutation=root/'mutation';shutil.copytree(review,mutation)
 source=mutation/'src/run/delivery-gap.ts';s=source.read_text();old='const have = validDeliveredCount(goal.deliverable.kind, collected);'
 if old not in s:raise GateError('Mutation target changed')
 source.write_text(s.replace(old,'const have = deliveredCount(goal.deliverable.kind, collected);'))
 p=command(mutation,packet['checks'][0],dependencies=deps);(root/'mutation-test.log').write_text(p.stdout)
 if p.returncode==0:raise GateError('New regression tests failed to kill delivered-count mutation')
 state['acceptance']={'run_id':'deterministic-mutation-'+uuid.uuid4().hex[:10],'target_sha':target,'verdict':'approved','evidence':'Baseline tests pass; candidate focused/full unit/typecheck pass; wrong-count mutation fails. Synthetic test-only acceptance, no browser/DB/SMTP claims.'};require_pr(state);emit('pr_ready')
 remote='git@github.com:Linglingletsgo/goal-to-people.git';git(candidate,'remote','set-url','origin',remote);git(candidate,'push','-u','origin',branch)
 body=root/'pr-body.md';body.write_text('交付缺口测试此前主要覆盖有效数量与已交付数量相同的情形。本变更补充两者不同、显式空有效计数和缺省兼容行为的回归测试，仅修改测试文件。\n\n验证：聚焦测试、全量 root unit/display 测试、root typecheck、独立只读 Reviewer；将配额口径错误替换为已交付读数后，新测试能阻止该回归。未启动应用服务、未连接数据库、未发送邮件。\n\nBaseline: '+sha+'\nCandidate: '+target+'\nEvidence: '+str(root)+'\n\n等待人工合并。\n')
 url=subprocess.check_output([str(pathlib.Path.home()/'.local/bin/gh'),'pr','create','--repo','Linglingletsgo/goal-to-people','--head',branch,'--base','main','--title','test: cover valid versus delivered count gaps','--body-file',str(body)],text=True).strip();state['pr_url']=url;emit('waiting_for_merge')
 b.api('PATCH','/issues/'+issue,{'status':'in_review','comment':'真实项目试点完成，等待人工合并：'+url+'\nEvidence: '+str(root)})
except Exception as e:
 state['error']=str(e);emit('blocked');b.api('PATCH','/issues/'+issue,{'status':'blocked','comment':'Pilot stopped: '+str(e)});raise
