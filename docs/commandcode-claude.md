# Claude Code / Command Code

Command Code 的 DeepSeek V4.1 Flash 仅支持 OpenAI Chat Completions 和 Responses；Claude Code 原生使用 Anthropic Messages，直连返回 HTTP 400。本地 CLIProxyAPI 负责协议转换，不替换 Claude Code 工具执行循环。

在 Linux looop 目录运行：
 
    python3 bin/setup-commandcode-claude.py

使用现有 CLIProxyAPI 二进制及 secrets/commandcode.key。配置、网关客户端密钥与独立空 OAuth 目录保存在 data/commandcode-claude，权限仅当前账户可读；不使用原有 8317 服务或其凭据。用户服务 looop-commandcode-claude.service 仅监听 127.0.0.1:8318，仅配置 deepseek/deepseek-v4.1-flash，无其他模型或凭据后备。请求日志关闭，错误文件最多 2 份。密钥变更后重新执行安装命令。

在任意项目目录独立使用：

    claude-commandcode

也可直接执行：

    python3 /home/agentdev/projects/looop/bin/claude-commandcode.py

looop 执行设置中选择 Harness「Claude Code」和 Token Plan「Command Code」。保存只对新任务生效，不自动切换正在运行的任务。Claude 订阅入口保持独立；本路线不要求 Claude 订阅登录。模型和辅助模型均固定为 Flash。模型名不被 Claude 内置目录识别的警告不代表自动换成 Claude 模型。

检查服务：

    systemctl --user status looop-commandcode-claude.service

官方文档：https://commandcode.ai/docs/provider
