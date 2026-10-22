# looop 通用 PM skills 调研

审核日期：2026-10-17。范围：5 个公开仓库的 README、许可证、14 个具体 SKILL.md，部分验证脚本和一个访谈分析脚本。读取固定 commit，未安装整套技能，未启动 WOS 或 GTP 开发。

## 结论

项目自己的角色、技能和审批规则优先。没有合适技能时，建议采用 deanpeters 的自主调研协议与具体调研技能，补充 phuryn 的机会与需求定义方法，按问题加载。不能把整套市场、组织、发布和增长流程默认套到每个项目。

用户确认用途为个人自用，因此 deanpeters 纳入推荐。该仓库许可证为 **CC BY-NC-SA 4.0**，不是 MIT；引入时保留署名、许可证并标明修改。自用不消除许可证条件；未来分发、商业用途需重新检查。其余四个仓库本次读取的根 LICENSE 为 MIT。

## 候选比较

| 库 | 实际审核内容 | 适配价值 | 需要修改的部分 | 推荐定位 |
|---|---|---|---|---|
| [deanpeters/Product-Manager-Skills](https://github.com/deanpeters/Product-Manager-Skills) | autonomous-investigation、competitive-research-snapshot、discovery-process | 区分交互工作坊与可调度调研；事实/推断/假设标签、真实引用、稳定结构、缺口说明 | 去除固定四选项结尾；不把缺失回答视为执行授权；不照搬来源数量阈值；完整 discovery 含招募、访谈和数周日程，不适合默认后台执行 | **需显式开启的非商业调研协议**（默认改用原创 MIT `research-core`） |
| [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | opportunity-solution-tree、competitor-analysis、prioritize-features、create-prd | 模块小；从用户问题到方案、排序和精简 PRD，覆盖完整 | 固定 5 个竞品、top 5、3+ 方案应按决策需要调整；PRD 的先问后写规则要区分后台与人工入口；不虚构 RICE 数值 | **需求定义和具体方法的主力补充** |
| [Uxcel-Lab/product-skills](https://github.com/Uxcel-Lab/product-skills) | discovery、assumption-testing、decision-quality | 明确按风险和可逆性选择研究深度；先检验关键假设，避免为小改动跑完整研究 | 正文较长；默认串联审计、固定节奏、招募等要求不能继承为调度权限 | **高不确定需求的假设检验补充** |
| [rampstackco/claude-skills](https://github.com/rampstackco/claude-skills) | ux-research、discovery-research-synthesis | 研究问题、原始观察→模式→决策的证据链；明确缺数据时交付缺口，禁止补造 | 访谈、付费招募、视频和多文档输出不宜默认；synthesis 技能长，需按需读取 | **已有访谈、支持工单等资料时启用** |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | product-manager-toolkit、product-strategist、customer_interview_analyzer.py | PRD/RICE 模板和脚本式工具便于输入已有数据 | 默认季度、团队、容量等企业设定不适合个人项目；访谈脚本以英文词匹配和正则为主，不能作为需求事实或自动优先级的裁决器 | **可选模板，不作默认自主发现引擎** |

成熟度不能等同于星数。本次看到 phuryn 的一致性测试、deanpeters 的元数据/链接/触发检查、Uxcel 的 YAML/结构验证；这些说明有维护机制，**不证明真实需求判断正确，也不证明模型遵循率**。本次没有对五套库进行真实产品调研效果对比。

## 对 looop 的建议

### 选择顺序

1. 读取项目当前状态、代码、AGENTS.md 和项目 PM 角色，确定当前问题、已批准范围及审批归属。
2. 优先选择项目规定的相关 PM 技能，不能绕过必须调用的技能或重写已有审批边界。
3. 项目无适用方法时，选择 looop 自用默认包的相关技能。只有补足明确缺口时才混用来源，避免几套 discovery 同时运行。
4. 只加载本次方法正文及确有必要的引用文件，不把整库塞入提示词，也不执行上游任意自动安装脚本。

### 最小默认组合

- **调研协议**：默认 looop 原创 MIT `research-core`；开启非商业包后改用 deanpeters `autonomous-investigation` 的适配版。每次先明确一个待决策问题、允许来源和停止条件；输出事实、推断、假设、未知。
- **公开竞品证据**（仅非商业包开启时）：需要外部比较时加载 `competitive-research-snapshot`，同时包含其必要协议依赖。竞品营销声明只证明其宣传内容，不能证明实际体验或用户需求。
- **用户问题→产品目标**：phuryn `opportunity-solution-tree`，不强制固定树宽或机会评分；缺少重要性/满意度数据时保留未知。
- **现有 backlog 排序**：phuryn `prioritize-features`，只比较现有范围，不凭空填入触达量或影响数字。
- **需求简报**：phuryn `create-prd` 的问题、用户、前后变化、成功条件和非目标；映射到当前项目状态，不默认产生不断增加的 PRD 文件。
- **关键未知**：按需使用 Uxcel `assumption-testing`。它主要设计验证方法，不能把设计了一次实验写成已经完成实验。

这是按需能力清单，不是每轮必跑六步；上游原文不能原封不动成为整个调度流程。

### 两条运行路径

- **只推进 backlog**：检查条目仍未实现、与当前代码和目标一致、价值明确、依赖可满足；通常使用仓库和既有证据，不强制重新开展市场调研。需求有关键未知时才补相应研究。
- **允许调研新需求**：从既有产品方向提出一个具体研究问题，检索允许的公开信息及项目证据，记录反证、替代方案和证据局限，再决定推进、否决、重复或等待证据。找到真实 URL 只是引用核验，不等于验证了用户需求。

共同结果：PM 选择一个用户可理解的产品目标；builder 可拆成多个实现切片，持续推进同一目标。切片完成不等于产品目标完成。reviewer 审查实现，产品审核依据既定目标决定是否达到交付条件；是否另走验收仍由项目流程决定。

### 有界项目状态

建议保存当前目标、当前切片、成功条件、剩余工作、研究结论、证据引用、实际加载技能及其版本、阻塞原因和下一步。每次更新当前状态；历史证据按现有保留策略管理，不把所有历次访谈、报告、对话拼成无限增长的上下文。独立终端会话和 looop 都读取、更新同一项目状态。

### 需要适配而非继承的规则

- 无人应答时可继续已授权的只读研究；不能据此批准需求、启动未授权实验、联系他人、支付或改变产品方向。
- 保留 `supported / rejected / insufficient_evidence` 等明确结论；来源支持程度不足时不强行生成开发任务。
- 证据数量和研究深度服务于决策风险，不用固定篇数或运行时限逼出答案。停止条件可以是问题已回答、反证否决、允许来源耗尽或需外部输入。
- 去除固定“四个后续选项”、默认周会/季度计划和不相关角色串联；不要去除影响正确性的来源追溯与未知说明。
- 引用相邻技能、模板和 reference 时，核对依赖是否实际可读；不能只拷 SKILL.md 留下一串失效链接。

## WOS 的适配结论

已读取项目 `docs/project/pm-skills-manifest.md`：现有 11 项 `wos-pm-*` 已分别取材于 phuryn、Uxcel 和 RampStack，并保存版本与许可证。**WOS 不需要换成全局通用包**，更不应把其项目副本复制到全局。

其 PM 角色负责 discovery，不能代替项目既有需求批准和开发启动权限。looop 必须显式映射这个边界，不能因为其他项目采用自动 PM→开发流程，就默认 WOS 也获得同样权限。本次没有启动或修改 WOS/DS1。

## 实测发现

在 Linux 对 Alireza 固定版本的 `customer_interview_analyzer.py` 做两条合成输入检查：

- `I do not need this feature. The workflow is not hard.` 被报告为两个痛点，前句还被判为高优先级新功能请求；脚本没有正确处理这里的否定。
- `我无法导出历史订单，每天都需要手工重新整理表格。` 没提取出痛点或需求。

这是一个具体脚本的局限，不代表整个技能库不可用；但足以说明不能让其自动分析结果直接触发需求开发。

## 可追溯版本

| 项目 | 本次审核 commit | 根许可证 |
|---|---|---|
| phuryn | [07b34f64ee828df08953f505b7f747aef85ae7c6](https://github.com/phuryn/pm-skills/tree/07b34f64ee828df08953f505b7f747aef85ae7c6) | MIT |
| deanpeters | [cfcb697f14b8891d8b3ec43c16c3547df3e70e13](https://github.com/deanpeters/Product-Manager-Skills/tree/cfcb697f14b8891d8b3ec43c16c3547df3e70e13) | CC BY-NC-SA 4.0 |
| Uxcel | [5007cd0241ccaa51ae2e4681f9618912dc10e239](https://github.com/Uxcel-Lab/product-skills/tree/5007cd0241ccaa51ae2e4681f9618912dc10e239) | MIT |
| RampStack | [482c9bf74697fc1e311bd4dca5ce301f046c4b76](https://github.com/rampstackco/claude-skills/tree/482c9bf74697fc1e311bd4dca5ce301f046c4b76) | MIT |
| Alireza | [19392f7a08264ed00486a251f5b2098321771f94](https://github.com/alirezarezvani/claude-skills/tree/19392f7a08264ed00486a251f5b2098321771f94) | MIT |

后续实现：已在 looop 的 pm-skills/ 建立 6 项精简适配方法并新增原创 MIT 方法 `research-core`，保留固定版本上游原文和许可证。仓库以 MIT 分发；deanpeters 的 `investigation` 与 `competitive-research` 仍为 CC BY-NC-SA 4.0，移入需显式开启的 `noncommercial/` 包，未开启时以 `research-core` 作为默认调研协议。项目优先选择、来源独立核验、当前研究状态和多切片目标流程已接入；具体验证以 docs/pm-workflow.md 为准。真实产品调研效果尚未作跨项目评测。
