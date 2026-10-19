# Agent 工作流

looop 负责队列、并发、启动原生 Harness、结果文件结构与身份校验、版本冲突、重试和看板投影。它不运行项目测试或实验、不推导测试命令、不解释证据、不判断产品是否完成。Git 工作区管理、PR 发布和既有批准后的合并仍由调度侧按项目配置执行；不新增审批，也不自动部署。

项目已有角色和流程优先。PM 调研并提出目标和任务；Builder 实现；项目定义的验证角色或默认 QA 使用原生 Harness 运行检查并保存证据；Reviewer 独立审查；PM 根据当前代码和执行证据判断目标是否完成。没有配置的 Acceptance 不自动加入。

运行 Harness 和 Token Plan 沿用设置页。Magpie / ChatGPT 使用本机 Codex 已配置的 3425 网关和 `codex/` 模型；Magpie / WorkBuddy DeepSeek 固定 `workbuddy/deepseek-v4.1-flash`。Magpie / Command Code 固定 `commandcode/deepseek/deepseek-v4.1-flash`。凭据只从本机配置读取，不复制到仓库。Claude Code 通过 Magpie 的 Messages 接口直接使用所选模型；不依赖旧 CPA 协议桥，也不自动跨提供商回退。验证使用 review 路由。项目依赖临时接入源码快照，不在快照中重新安装。真实数据库、邮件、外部模型和生产数据仍遵守项目原有边界；隔离测试库按项目说明使用。无新增任务总时限。

所有角色通过文件工具更新本次运行的 handoff.json.result，保留 version、run_id、nonce。自然语言对话不参与状态解析。结果的结论由 Agent 负责；字段缺失触发有界纠正，不得为了格式虚报成功。源码变化、并发外部工作和目标版本冲突仍须重新判断。

研究计划注明 new_requirement、existing_defect 或 backlog_validation，选择与问题相关的项目研究方法。PM 自行核实引用、反证和价值；公开调研不能用模型猜测代替。需要实验时可自己在运行产物目录执行，或请求 looop 派发验证 Agent；looop 不执行模型生成脚本、不把退出零解释为产品结论。

交付检查仍是必需工作，但由验证 Agent 执行。Reviewer 应核对实际执行产物和当前提交是否一致，不能仅凭一句通过批准。目标缺少集成证据时，PM 应使用已安装环境直接补跑，或提出验证工作，不能反复要求调度器推导业务检查。

交付修复默认不限轮次（策略 `max_rounds: null` 或省略）；显式正整数上限仍生效。明确的 `changes_requested` 回到 Builder，传递最新审核意见，并对新提交重新检查和独立审核。调度器不判断缺陷是否修好；若候选代码重复最近 8 个已拒绝版本之一，记录 `repair_stalled` 并显示处理入口，不继续空转。Builder 无修改、明确的 blocked、范围/基线变化仍停止。

旧轮次上限导致的受阻，可在确认策略后运行 `python3 bin/delivery-control.py resume-repair <issue> --reason "说明"`。该入口只接受未发布、原进程已停止、候选代码干净且契约匹配、有当前提交修改意见的旧轮次受阻任务；保留候选提交和历史证据，从下一轮 Builder 开始，不能跳过检查或审核。

持续循环按当前 loop_control 推进；暂停只停止新选题，既有工作继续完成；once 保持一次目标语义。普通研究证据不足（包括公开来源暂不可用）按 no_work 结束本轮，continuous 立即进入下一轮，不设选题冷却或休眠间隔；只有明确的 human_decision 保留人工处理入口。公开只读调研与离线合成实验使用不同边界，不能伪造需求维持忙碌。WOS/DS1 边界不变。

## 当前状态

项目级 `.agent/local/runtime/data/project-state/<lane>.current.json` 是权威当前状态。`current.json` 为兼容读取别名；SQLite 只保留事务索引、幂等事件及看板同步队列。Paperclip 是投影，不是另一份产品状态。

独立对话使用项目内 `project-session.py context/start/progress/finish`，其文件写入使用相同版本校验和锁。Agent 通过角色结果文件记录执行结果，调度器只验证所属任务并流转。不要直接改看板或数据库伪造审核通过，不将历史 handoff 当作当前授权。

当前状态覆盖更新；事件、日志和运行产物按 retention.json 保留。文件与索引的提交使用恢复标记，异常时保留现场。迁移前状态保存在 data/backups，不删除原项目。

## Magpie 子代理资源库

在 Linux 的 looop 目录运行 `python3 bin/sync-magpie-subagents.py`，将 `default-roles/` 的 8 个默认角色更新到 Magpie 原生资源库，并由 Magpie 分发到其支持的 Codex 和 Claude Code。条目使用通用角色名（如 `product-manager`、`builder`、`reviewer`），提示词直接采用角色职责，不添加调度器身份包装。项目角色优先，角色可用不等于自动加入执行流程。保留已有模型、账号及其它原生角色；OMP 当前不在 Magpie 支持的子代理分发目标内。修改前备份到 `data/backups/`，同步后回读核对；不将提示词塞进共享全局指令。

Product Manager 关联 6 个通用 skills：`pm-investigation`、`pm-competitive-research`、`pm-opportunities`、`pm-backlog-prioritization`、`pm-requirement-brief` 和 `pm-assumption-testing`。优先使用项目规定的方法，其余按当前决策选用，不要求每次全部执行。同步脚本从已审核的 `pm-skills/` 生成中性名称的独立导出，保留上游署名和许可证，不修改调度器校验的源文件。Claude Code 原生绑定角色 skills；Codex 安装相同 skills，由角色指令引用（其子代理格式没有 skills 绑定字段）。旧前缀条目迁移为同名通用条目，同名原生配置替换前完整备份。
