# 项目状态与角色交接

项目当前状态文件 `.agent/local/runtime/data/project-state/<lane>.current.json` 是权威当前状态；`current.json` 是兼容别名，SQLite 保存事务索引及同步队列。代码和实际检查说明当前实现，产品需求及有效决定说明目标。Paperclip 是投影。角色结果文件是一次执行的输入或证据，不是第二份项目状态。

## 独立使用

项目工具只依赖 Python 标准库；结构化提交还会调用 Git。不需要 Paperclip 或 looop 服务在线：

```sh
python3 .agent/tools/project-session.py context --repo .
python3 .agent/tools/project-session.py start --repo . --id task-123 --summary '本次授权范围'
python3 .agent/tools/project-session.py progress --repo . --id task-123 --summary '当前变化及未完成项'
python3 .agent/tools/project-session.py result --repo . --id task-123 --result-file .agent/local/result.json
python3 .agent/tools/project-session.py finish --repo . --id task-123 --summary '会话结束；实际成果及剩余事项'
```

先取得 start 的接受结果，再开展独立工作。未提交草稿使用 progress，不要求为写状态擅自 commit。已有经过授权的提交且工作区干净后，才使用绑定提交的 result。结果文件放在忽略目录；工具核对任务 ID、两个提交存在、baseline 是 target 的祖先、target 是当前 HEAD，以及工作区无未提交/未跟踪修改。Git 身份核对不能证明检查已经运行或代码正确。

`result` 不结束会话；`finish` 仅结束独立会话、释放串行占用，不代表审核通过、合并或交付完成。提交的角色结论均标记 self_reported，不会修改调度任务门禁或授予发布权限。普通对话应显式调用命令；Agent 退出本身不代表完成。异常退出保留活动状态，不能按时间推断成功。

## 结果格式

以 [模板](../templates/stage-receipt.example.json) 为起点，替换任务 ID、角色和真实 SHA。字段如下：

| 字段 | 内容 |
|---|---|
| version | 固定 1 |
| task_id、role、stage | 稳定任务 ID、项目角色、职责阶段 |
| baseline_sha、target_sha | 完整提交 SHA |
| verdict | approved、changes_requested 或 blocked；build/plan/advisory 不接受 changes_requested |
| summary | 当前阶段的简短结论 |
| findings | 具体问题：严重程度、位置、证据和修复要求 |
| checks | 实际执行的检查及结果，或检查回执路径 |
| artifacts | 必要产物位置 |
| unverified | 尚未验证的内容；不能填成通过 |
| cleanup | 待收尾事项，写明责任人、资源及下一步 |

stage 可为 plan、advisory、build、review、acceptance、integration、cleanup；可用不代表项目必须增加该阶段。后五个字段均为字符串数组。空数组表示没有报告对应事项，不是系统认证已完成。

同一会话按 role:stage 覆盖最新结果，最多 16 组，不追加逐轮日志。已结束会话可补交同一阶段结果以纠正证据或解除待处理项；仍核验来源、revision 和 Git。每个角色维护自己报告的未完成项，不能凭 cleanup 阶段的新结论自动抹掉其它阶段的阻塞。

自动交付沿用带 run_id/nonce 的 handoff.json，运行器校验身份与阶段结果后，为 Builder、Reviewer 和可选 Acceptance 生成同格式 stage-receipt.json。Builder 记录绑定采纳后的候选提交；审核记录绑定被审核提交及检查回执。共享校验在 lifecycle_io.py；自动执行仍通过自身检查、独立上下文、SHA 和合并门禁，不从自述记录推断批准。

## 读取、同步与保留

默认 context 只读取活动任务、有效决定、活动独立会话，以及仍报告阻塞、未验证项或待清理资源的会话。查看保留历史时显式使用 `context --history`。cached 不连接，只提供上次缓存，可能过时。历史参数仅影响读取，不授予权限。

离线事件保留在 pending.json，sync 按 revision 重试；冲突必须核对，不自动重写 revision。独立状态接入调度器时，角色结果一并导入；不重放代码修改。事件和诊断按保留策略清理，未同步事件、活动工作及未解决的角色结果不作为普通历史丢弃。

执行 Agent 只报告和收尾自己创建的资源。人工工作区、其它会话、有效未提交内容和运行依赖不能由通用清理程序删除。项目已有协调角色可负责关闭收尾；普通项目不因此新增 Product 或 Acceptance。保留分支不等于必须保留 worktree，历史已提交证据按固定 SHA 查询，避免重复归档。

## 升级边界

修改 looop 中的工具和 skill 不会自动覆盖已接入项目的 .agent/tools。每个项目在自己的对话中审核升级并保留本地改动、状态和绑定；首次适配先在一次性副本验证。WOS 保持 context-only，DS1 保持人工工作区。
