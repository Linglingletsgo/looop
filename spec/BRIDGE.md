# 按需构建：项目适配bridge实施规格

本文件是待实现规格。工具包没有运行中的bridge；project-policy.example.json也不是Paperclip官方schema。不能通过改activation或启动心跳获得以下保证。

## 优先复用

- Paperclip现有Company/Project/Agent/Issue/Routine、checkout、execution policy、run history、secrets和adapters。
- 不fork整套看板，不重写模型agent loop，不把每条规则拆成独立微服务。
- 每仓库一个隔离Company起步；同仓库多lane共享canonical repository锁。不同Company不是宿主机文件权限边界。
- 控制面定义版本化policy；普通worker不能改policy、角色关系、批准状态或自行唤醒下一角色。

## 最小模块

1. Profile resolver：读取经确认的profile与固定agent_system_sha，解析角色契约和Packet引用；保留harness原生AGENTS发现规则。对未知/冲突/不完整Packet拒绝执行。
2. State gate：事务检查合法transition、canonical repo BUILDING lease、角色身份与能力；校验baseline/target SHA、review顺序、fresh session和evidence。已有Paperclip issue checkout不能替代仓库锁。
3. Run launcher：选择明确允许的adapter/model route；每run独立context。Product/Builder在有界阶段可resume；Reviewer standard/adversarial与Acceptance不得继承前一角色会话。使用真实隔离，不让prompt承担权限控制。
4. Result validator：接收角色原有输出contract、run-result及真实artifacts，验证存在性/hash/目标SHA/cleanup；模型输出Approved/COMPLETE只是待验证claim。
5. Provider policy：监测可用quota、reset与已观察usage；额度耗尽休眠，未知按已确认policy停机，不付费fallback；任何usage采集读取先确认非破坏语义。
6. GitHub publisher：仅允许已授权任务branch push/PR；repo/default branch保护及ref broker阻止main/epic直接写入。PR按幂等键更新，merge只由用户执行。精确github权限按App或token实测，不声称“contents:write天然禁止merge”。
7. Resource manager：登记run拥有的容器/端口/进程/scratch；提供项目hub start/stop兼容入口；清理后验证，不能影响其它run。
8. Handoff builder：把run-result、Product决定、Packet和evidence组合成接续索引，不复制整段conversation；冲突返回BLOCKED。

## 持久记录

尽量使用Paperclip可扩展数据/Issue documents/activities；若需bridge数据库表，部署并管理显式migration，不手改Paperclip内部表。

- projects/lane绑定与profile版本指纹
- state及version（compare-and-swap）
- repo lease与owner/heartbeat/expiry
- run角色/mode/context namespace/provider/模型/target SHA
- decisions与scope/version（用户或有权角色的明确决定）
- SHA绑定reviews、acceptance、evidence
- convergence ledger / finding ID / admitted class /轮次/停滞状态
- quota快照/可信度/reset/采集时间
- owned_resources、幂等事件收件箱及outbox

建议幂等键：project + lane + packet + role + mode + target_sha + bounded_attempt。
重启先reconcile进程、lease和artifacts，再resume/retry；外部PR操作用outbox与查询去重，不盲目重放。

## 当前项目的硬约束

- Product主线与DS1上下文隔离，仓库级BUILDING≤1。
- PM每次一个question与结束条件；必须按当前PM contract加载相关项目方法技能；SUPPORTED只是交Product审核，不是READY。
- agent_system_sha、Product baseline和target均完整固定SHA，不能读移动branch head代替。
- high-risk standard先Approved，才fresh adversarial。target变更后两者及Acceptance失效，从deterministic gate重新开始，不能沿用Paperclip默认“回到当前review stage”。
- I类与scope外observations按现有规则交Product登记；S1–S4或6轮上限停止原循环。
- Reviewer源码只读、scratch可写；Acceptance无源码、synthetic-only。普通worker不能读agentdev生产备份凭据或原Docker socket。
- main/epic merge均等待用户，不自动执行历史handoff未授权P1/DS1任务。
- 规则修改只能通过明确版本更新与review，不自动修AGENTS让自己更易执行。

## 启用真实backlog之前必须通过

| 注入/场景 | 必须看到的结果 |
| --- | --- |
| 两个Bundle同时请求BUILDING | 只有一个成功；跨mainline/DS1同样成立 |
| 缺convergence或完整baseline | 拒绝派发，显示缺项 |
| Builder自己请求Approved | 不能产生有效review批准 |
| adversarial通过后代码增加一个commit | standard/adversarial/Acceptance全部失效 |
| Reviewer试图写源码 | runtime拒绝；不是仅提示不要写 |
| Acceptance读取src或生产secret路径 | runtime不可见/拒绝 |
| Command Code额度耗尽 | quota_paused，不循环请求，不转新收费API |
| 杀掉Product会话后恢复 | 从记录继续，不依赖旧对话 |
| 连续重复发送完成/合并事件 | 不重复PR、不重复dispatch |
| S1–S4或累计6轮 | 停止并交Product裁决，不自动Approved |
| run清理尝试处理peer资源 | 拒绝；只清显式登记的own resources |
| 无task/新事件 | 没有模型调用 |
| 人工merge后 | 事件唤醒Product选择下一项；不自动merge别的PR |

首个PoC只用fixture仓库与现有订阅路由。证明边界有效后再接低风险真实task。该规格的实现与验证结果应作为独立工程交付，不把教程脚本的preflight测试冒充上述测试。
