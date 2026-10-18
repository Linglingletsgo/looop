"""Readable owner intervention, derived from current receipts; never grants authority."""
import json,subprocess
from lifecycle import failure
from process_owner import alive

STAGES={'planning':'任务规划','building':'开发','checking':'自动检查','acceptance':'项目验收','waiting_for_merge':'合并','merged':'主线复验'}
GUIDANCE={
 'provider_paused':('订阅额度或认证需要处理','先检查所用订阅的额度和登录状态；额度恢复或重新登录后再重试。可在 Harness / Token Plan 设置中选择已有订阅。'),
 'connection':('执行连接中断','确认 Linux 到所用模型服务的网络已恢复，再重试。'),
 'model_output':('阶段交接文件未通过校验','需要核对本次执行的 handoff.json，而不是修改聊天总结。代码草稿和检查记录已保留；请将诊断交给维护对话，补齐交接文件后从保存的结果或同一提交恢复检查与审核。'),
 'scope_or_baseline':('任务基线、范围或项目规则不匹配','需要在项目对话中核对当前代码和任务范围，重新生成匹配的任务。反复重试旧任务不能解决此问题。'),
 'product_disposition':('规划或审核发现阻塞问题','阅读具体原因，明确需要修复的缺陷或补充的产品决定。若需改变任务范围，先通过“提需求 / 记决定”记录，再由维护对话处理当前任务。'),
 'execution':('执行失败，需要确认原因','阅读具体原因，在 Linux 项目对话中检查对应文件、依赖或检查结果；完成处理后填写说明并重新执行。')}

def describe(root,lane,item,state,doc):
 error=str(state.get('error') or item.get('evidence',{}).get('error') or '尚无失败原因记录；请核对任务证据。')[:4000]
 category=state.get('failure',{}).get('category') or failure(Exception(error))['category']
 title,instruction=GUIDANCE.get(category,GUIDANCE['execution'])
 stage=state.get('failed_stage') or state.get('state') or item['phase']
 stage='独立审核' if stage.startswith('review_') else STAGES.get(stage,stage)
 blocked=item['phase']=='blocked';holds=item.get('holds',[])
 reason=None
 if not blocked:reason='任务仍在执行，不能重复启动。'
 elif holds:reason='先处理下面的产品决定，解除任务变更等待。'
 elif state.get('pr_url') or item.get('evidence',{}).get('pr_url'):reason='任务已有 PR；请通过 PR 处理审核、合并或主线复验，不重新开发。'
 elif category in ('model_output','scope_or_baseline'):reason='需要修复协议或任务契约；此处不提供会重复开发的普通重试。'
 elif not state:reason='缺少执行记录，需要在维护对话中核对任务绑定。'
 elif alive(state.get('owner')) is not False:reason='执行进程仍在运行或身份无法确认；请等待或在 Linux 核对进程。'
 if reason is None:
  try:
   binding=json.loads((root/'data/delivery-bindings'/(item['id']+'.json')).read_text())
   if binding['lane']!=lane:raise ValueError('binding mismatch')
   head=subprocess.check_output(['git','-C',binding['policy']['repo'],'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
   if head!=binding['packet']['baseline_sha']:reason='代码基线已变化，需要重新规划任务，不能重试旧契约。'
  except (OSError,ValueError,KeyError,subprocess.CalledProcessError):reason='无法核对任务绑定与代码基线；请在维护对话中检查。'
 decisions=[{'id':i,'title':doc['intents'][i]['title']} for i in holds if i in doc.get('intents',{})]
 sha=state.get('target_sha') or item.get('evidence',{}).get('target_sha')
 return {'title':title,'stage':stage,'cause':error,'category':category,'instruction':instruction,'preserved':('候选提交 '+sha[:12]+'；' if sha else '')+'已保存的草稿、检查与审核证据保留在 Linux，不会因打开此页而重跑。','retry_allowed':reason is None,'unavailable_reason':reason,'retry_effect':'重新排队开发，并把旧草稿和失败证据交给 Builder 参考；重新执行检查与独立审核。这不是从失败阶段原地继续。','decisions':decisions,'diagnostic':f'项目: {lane}\n任务: {item["id"]}\n阶段: {stage}\n分类: {category}\n原因: {error}\n证据目录: {root}/data/deliveries/{item["id"]}\n请求: 核对当前代码与状态，保留已有工作，修复后接续，不跳过检查与独立审核。'}
