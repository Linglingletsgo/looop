# looop

**让 AI Agent 协作，把需求推进到经过检查与独立审核的交付。**<br>
**Turn requirements into checked, independently reviewed deliveries with AI agents.**

looop 是本地运行的开源 Agent 调度器，将产品规划、开发、审核和项目状态连接起来。你决定方向，looop 协调执行。

looop is a local, open-source agent scheduler connecting product planning, development, review and project state. You set the direction; looop coordinates the work.

**Beta · Linux · MIT** — 欢迎试用、反馈和一起开发。目前尚未开箱即用，项目适配与运行环境仍需手动配置。<br>
Early adopters and contributors welcome. Not yet plug-and-play: project adaptation and runtime setup still require manual configuration.

## 为什么使用 looop / Why looop

- **少写重复的 handoff**：换会话、换 Agent，不必每次重新整理进展。当前状态属于项目，各会话从同一入口接续工作。<br>
  **Spend less time on handoffs**: keep current state with the project, so new sessions and agents can pick up the work without rebuilding the context each time.
- **先适配，再按需自动化**：用 `project-adapter` skill 沿用项目规则、角色和检查。适配层可独立使用，无需接入调度器。<br>
  **Adapt first, automate when ready**: the `project-adapter` skill preserves project rules, roles and checks. Use the adapter on its own, without the scheduler.
- **围绕目标持续推进**：选择只开发 backlog，或允许 PM 在既定方向内调研、提出任务，再经开发、检查与独立审核推进 PR。<br>
  **Keep goals moving**: work through the backlog, or let PM research within the approved direction and propose tasks, then move toward PRs through development, checks and independent review.
- **自由选择 Agent**：支持 Codex、Claude Code、OMP 和 DeepSeek Harness，按阶段配置。<br>
  **Choose your agents**: configure Codex, Claude Code, OMP or DeepSeek Harness per stage.
- **保持掌控**：在本地控制台查看证据、单次或持续运行、暂停新任务。独立对话共享项目状态。<br>
  **Stay in control**: inspect evidence, run once or continuously, and pause new work. Project conversations share the same state.

## 快速开始 / Quick start

**从 [`project-adapter` skill](skills/project-adapter/SKILL.md) 开始。** 先克隆并运行 setup，将 skill 链接到 `~/.codex/skills/`：<br>
**Start with the [`project-adapter` skill](skills/project-adapter/SKILL.md).** Clone and run setup to link the skill into `~/.codex/skills/`:

```sh
git clone https://github.com/Linglingletsgo/looop.git
cd looop
python3 bin/setup.py
```

在你要适配的项目中开启 Agent 会话，调用：<br>
Open an agent session in the project you want to adapt and ask:

> 使用 $project-adapter 适配当前项目，保留已有规则和工作流，先独立使用，不开启自动调度。
>
> Use $project-adapter to adapt this project, preserving its rules and workflow. Start in standalone mode without enabling scheduling.

独立状态工具只需 Python 3；适配后即可跨会话读取状态、记录进展。想自动推进时，再配置调度器。<br>
Standalone state tools need only Python 3. After adaptation, sessions can read shared state and record progress. Configure scheduling when you want automatic execution.

调度器需要 Linux、Python 3、Git、tmux；部分 Agent CLI 需要 Node.js 24+。另行安装并登录所选 Agent CLI，然后在 looop 目录启动控制台：<br>
The scheduler requires Linux, Python 3, Git and tmux; some agent CLIs need Node.js 24+. Install and authenticate your chosen agent CLI, then start the console from the looop directory:

```sh
python3 bin/console-auth.py set-password
python3 bin/console-server.py
```

打开 [本地控制台](http://127.0.0.1:3120/looop)，使用刚设置的密码登录（至少 12 位）。接入项目、完成工作流配置、选择执行器，再主动开启单次或持续运行。安装不会自动启动任务；模型服务需自行配置。

Open the [local console](http://127.0.0.1:3120/looop) and sign in with your password (at least 12 characters). Connect a project, complete its workflow mapping, choose an execution harness, then explicitly start a single or continuous run. Setup does not start tasks; model access is configured separately.

## 参与开发 / Contribute

欢迎通过 [Issues](https://github.com/Linglingletsgo/looop/issues) 分享使用体验、报告问题和讨论想法，也欢迎提交 PR。问题反馈请附复现步骤、版本和所用 Agent，隐去凭据与私有项目内容。

Share feedback, report bugs or discuss ideas in [Issues](https://github.com/Linglingletsgo/looop/issues), or open a pull request. Include reproduction steps, the version and agent used; omit credentials and private project content.

核心代码在 `bin/`，控制台在 `ui/`，测试在 `tests/`。遵循 [项目约定](AGENTS.md)，保持改动聚焦，并运行相关检查：<br>
Core code lives in `bin/`, the console in `ui/`, and tests in `tests/`. Follow [project conventions](AGENTS.md), keep changes focused and run relevant checks:

```sh
python3 -m unittest discover -s tests
node tests/intervention-ui.mjs
```

## 深入了解 / Documentation

- [架构与部署 / Architecture & deployment](docs/standalone-architecture.md)
- [升级与服务配置 / Upgrades & service setup](docs/cutover.md)
- [项目状态与交接 / Project state & handoff](docs/project-state-protocol.md)
- [产品规划 / Product planning](docs/pm-workflow.md)
- [PM 方法与来源 / PM methods & attribution](pm-skills/README.md)

## 许可证 / License

原创代码、文档与默认 PM 方法包采用 [MIT License](LICENSE)，允许商用、修改和再分发，需保留许可声明。可选[非商业 PM 方法包](pm-skills/noncommercial/README.md)及其 Dean Peters 上游素材采用 **CC BY-NC-SA 4.0**，保留原有授权；该包默认禁用。

Original code, documentation and the default PM method pack use the [MIT License](LICENSE), permitting commercial use, modification and redistribution with the license notice retained. The optional [noncommercial PM pack](pm-skills/noncommercial/README.md) and its Dean Peters upstream materials retain **CC BY-NC-SA 4.0** terms. That pack is disabled by default.
