# RepoPilot

RepoPilot 是一个面向开发者的 GitHub 仓库分析 Agent。它会克隆公开仓库，在只读工具和资源预算约束下自主选择目录、源码与符号进行探索，最后生成带源码证据的中文 Markdown 报告。

当前 Phase 2 的重点是让 Agent 处于决策中心：Scanner 只提供初始事实，`get_tree`、`read_file`、`search_code` 和 `find_symbol` 只返回观察结果；下一步读什么、何时改变路线以及何时完成分析，都由模型根据 Goal 和已有 Observation 决定。

## 环境要求

- Python 3.11 或更高版本
- `PATH` 中可以使用 Git
- OpenAI-compatible 服务的 API Key、Base URL 和模型名称

## 安装

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

请根据当前 Shell 使用相应命令激活虚拟环境。

## 配置

将 `.env.example` 复制为 `.env`，至少填写：

```dotenv
REPOPILOT_LLM_API_KEY=your-api-key
REPOPILOT_LLM_BASE_URL=https://api.openai.com/v1
REPOPILOT_LLM_MODEL=your-model
```

MiniMax 国内 OpenAI-compatible 配置示例：

```dotenv
REPOPILOT_LLM_BASE_URL=https://api.minimaxi.com/v1
REPOPILOT_LLM_MODEL=MiniMax-M2.7
```

MiniMax 响应会自动启用 reasoning split；API Key 仍只写入本地 `.env`。

不要把 `.env` 或 API Key 提交到版本控制。检查本地 Git 和模型配置：

```bash
repopilot doctor
```

Agent 的迭代次数、工具调用、文件读取量、搜索结果量和上下文长度都可通过 `.env.example` 中的对应变量调整。

## 成本控制

默认配置采用有界的经济模式：最多 12 次模型决策、10 次 Tool 调用、4 万字符上下文、
8 万累计 Token，单个 AST Tool 最多返回 60 条结构事实。达到任一预算后，Agent 停止继续
调用模型并输出明确标记的部分报告。

可在单次命令中进一步限制累计 Token：

```bash
repopilot analyze https://github.com/owner/repository \
  --max-iterations 8 \
  --max-total-tokens 40000
```

也可以通过环境变量长期配置：

```dotenv
REPOPILOT_AGENT_MAX_TOTAL_TOKENS=80000
REPOPILOT_AGENT_CONTEXT_CHAR_BUDGET=40000
REPOPILOT_LLM_MAX_OUTPUT_TOKENS=6000
REPOPILOT_AST_MAX_TOOL_RESULTS=60
```

Provider 返回 Token Usage 时，Trace 和报告记录真实的 Prompt、Completion 与 Total Token；
不返回 Usage 时使用字符数进行保守估算并标记为 `estimated`。金额取决于模型平台价格，
RepoPilot 使用 Provider 无关的 Token 上限作为硬断路器。

## 使用方式

默认使用 Agent 模式：

```bash
repopilot analyze https://github.com/owner/repository
```

指定分析目标、报告和可复现 Trace：

```bash
repopilot analyze https://github.com/owner/repository \
  --goal "找出一次 CLI 请求经过的主要模块，并给出源码证据" \
  --max-iterations 12 \
  --max-total-tokens 80000 \
  --output reports/project.md \
  --trace-output reports/project-trace.json
```

在 PowerShell 中可将续行符 `\` 换成反引号，或直接写成一行。

保留克隆仓库以便本地检查：

```bash
repopilot analyze https://github.com/owner/repository --keep-repo
```

使用 Phase 1 的一次性 Bootstrap 分析作为回归基线：

```bash
repopilot analyze https://github.com/owner/repository --mode bootstrap
```

## Agent 如何工作

```text
Goal
  -> AgentDecision
  -> 一个只读 Tool Action
  -> Observation
  -> Agent 根据新证据决定下一步
  -> Finish Gate 校验证据
  -> Report + Trace
```

Runtime 只负责执行、校验、记录和限额，不包含“固定选出关键文件”的算法。程序入口、核心模块、执行流程和模块关系使用结构化 Finding，每条 Finding 都必须声明置信度并引用已验证 Evidence；证据缺失或引用无效的 Finish 会被拒绝。预算耗尽时则输出明确标记的部分报告。

## 安全边界

- 只接受公开的 `https://github.com/owner/repository` URL。
- 不执行目标仓库代码，不安装其依赖，也不初始化 Git Submodule。
- Agent Registry 仅提供七个只读代码与 AST 查询工具，没有 Shell、网络或密钥读取工具。
- README、注释和源码均作为不可信数据，不作为系统指令执行。
- 拒绝绝对路径、路径穿越、符号链接和仓库外文件访问。
- 跳过常见构建、虚拟环境、缓存和依赖目录。
- 限制仓库大小、文件数、目录深度、单次读取、累计读取、搜索结果、上下文和迭代次数。
- Trace 与错误信息会进行密钥脱敏。

## 开发与测试

```bash
pytest
ruff check .
mypy src/repopilot
```

项目总体方案见 [PROJECT_PLAN.md](./PROJECT_PLAN.md)，Phase 1 方案见 [PHASE1_IMPLEMENTATION_PLAN.md](./PHASE1_IMPLEMENTATION_PLAN.md)，Phase 2 方案见 [PHASE2_IMPLEMENTATION_PLAN.md](./PHASE2_IMPLEMENTATION_PLAN.md)，Phase 3 方案见 [PHASE3_IMPLEMENTATION_PLAN.md](./PHASE3_IMPLEMENTATION_PLAN.md)。

## 当前边界

Phase 2 使用文本搜索和启发式符号候选，不会把候选结果伪装成精确 AST 结论。Python AST、调用关系、Repository Map 属于 Phase 3；长期会话、SQLite、FastAPI、Web 页面和多轮 Repository Q&A 产品形态仍未实现。
