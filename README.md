# RepoPilot

RepoPilot 是一个面向开发者的 GitHub Repository Analysis Agent。输入公开 GitHub 仓库
URL，它会在资源预算和只读安全边界内自主探索代码，结合 Python AST 建立增量
Repository Map，最终生成带精确源码证据的中文 Markdown 分析报告。

```bash
repopilot analyze https://github.com/owner/repository
```

RepoPilot 的重点不是把整个仓库塞给模型，也不是先由固定算法选出“关键文件”再让 LLM
总结。模型始终位于探索决策中心：它根据 Goal 和每轮 Observation 决定下一步调用哪个工具、
读取什么文件、追踪什么符号，以及何时提交最终结论。

## 核心能力

- **Agentic Code Exploration**：Agent 自主组合 Tree、Read、Search、Symbol 和 AST 工具，
  Runtime 不内置固定关键文件选择算法。
- **AST + LLM Code Understanding**：Python AST 提供符号、Import、继承、调用和引用等
  确定性事实，LLM 负责解释架构语义。
- **Incremental Repository Map**：只记录 Agent 已探索的代码，不在扫描阶段解析整个仓库。
- **Evidence-grounded Analysis**：关键 Finding 必须关联真实 Observation 和精确 SourceSpan；
  无效 Evidence 会被 Finish Gate 拒绝。
- **Bounded Runtime**：限制模型决策、工具调用、Token、上下文、读取量以及 AST 节点和关系数量。
- **Reproducible Trace**：可导出完整 Agent 决策、Tool Observation、预算消耗和失败原因。
- **Safe by Default**：不执行目标仓库代码、不安装目标依赖、不向 Agent 暴露 Shell。

## 工作流程

```text
GitHub URL
    │
    ▼
Repository Loader / Scanner ──► 初始仓库事实
    │
    ▼
Goal ──► Agent ──► Tool Action ──► Observation
            ▲                           │
            └────── 下一步决策 ◄────────┘
                         │
                         ▼
                    Finish Gate
                         │
                         ▼
              Evidence Report + Trace
```

确定性模块只负责安全克隆、扫描、AST 解析、关系解析和事实查询。入口判断、核心模块识别、
探索路线与架构解释均由 Agent 根据目标和观察动态决定。

## 当前实现状态

RepoPilot 当前已完成前三个工程阶段，足以作为可运行的 Repository Agent Demo：

| 阶段 | 能力 | 状态 |
|---|---|---|
| Phase 1 | Clone、目录扫描、技术栈识别、README/配置解析、基础报告 | 已完成 |
| Phase 2 | Agent Loop、Tool Registry、自主 Read/Search/Symbol 探索、Finding/Evidence | 已完成 |
| Phase 3 | Python AST、受限 Resolver、增量 Repository Map、AST Evidence Gate | 工程实现完成 |
| Phase 4 | SQLite/FTS5 Repository Memory、Context、CLI 多轮问答 | 工程实现完成，自动化验收通过 |

Phase 3 当前 Definition of Done 为 **30/34**。83 项自动化测试通过，覆盖率 **90.04%**；
尚未完成三类真实仓库 Smoke Test、人工 Golden Evaluation 和至少一次以 `completed` 结束的
真实 Provider 验收。因此项目可以演示，但不会把尚未完成的质量验证描述为已完成。

详细记录见 [Phase 3 验收记录](./PHASE3_ACCEPTANCE.md)。

Phase 4 当前 Definition of Done 为 **40/44**。未完成项是量化检索指标、重复问题成本下降对照、
三类真实仓库 Smoke Test 和真实 Provider 多轮会话。为控制模型费用，本轮只运行 Fake Agent
端到端验收，没有发起付费模型请求。详见 [Phase 4 验收记录](./PHASE4_ACCEPTANCE.md)。

## 环境要求

- Python 3.11 或更高版本
- `PATH` 中可使用 Git
- OpenAI-compatible 服务的 API Key、Base URL 和模型名称

## 安装

```bash
git clone https://github.com/cy200682/RepoPilot-GitHub-Repository-Analysis-Agent.git
cd RepoPilot-GitHub-Repository-Analysis-Agent
python -m venv .venv
python -m pip install -e ".[dev]"
```

请根据当前 Shell 激活虚拟环境，然后检查运行环境：

```bash
repopilot --help
repopilot doctor
```

## 模型配置

将 `.env.example` 复制为 `.env`，至少填写：

```dotenv
REPOPILOT_LLM_API_KEY=your-api-key
REPOPILOT_LLM_BASE_URL=https://api.openai.com/v1
REPOPILOT_LLM_MODEL=your-model
```

MiniMax 国内 OpenAI-compatible API 示例：

```dotenv
REPOPILOT_LLM_BASE_URL=https://api.minimaxi.com/v1
REPOPILOT_LLM_MODEL=MiniMax-M2.7
```

MiniMax 响应会自动启用 reasoning split。API Key 只应保存在本地 `.env`；该文件已被
`.gitignore` 排除，禁止将真实密钥写入 README、Trace 或提交历史。

## 快速体验

分析一个公开 Python 仓库：

```bash
repopilot analyze https://github.com/pallets/itsdangerous
```

指定目标并导出报告与 Trace：

```bash
repopilot analyze https://github.com/pallets/itsdangerous \
  --goal "定位公开 API、核心签名与验签流程，并给出精确源码证据" \
  --max-iterations 10 \
  --max-total-tokens 70000 \
  --output reports/itsdangerous.md \
  --trace-output reports/itsdangerous-trace.json
```

PowerShell 可以将续行符 `\` 换成反引号，或者把命令写成一行。

其他常用方式：

```bash
# 保留克隆仓库，便于手工核对源码
repopilot analyze https://github.com/owner/repository --keep-repo

# 使用 Phase 1 的一次性 Bootstrap 分析作为回归基线
repopilot analyze https://github.com/owner/repository --mode bootstrap
```

## Agent 工具

当前 Tool Registry 包含七个只读代码工具和三个持久化 Memory Tool：

| 工具 | 用途 |
|---|---|
| `get_tree` | 按范围查看仓库目录结构 |
| `read_file` | 读取带行号的有限源码片段 |
| `search_code` | 搜索文本、文件名和代码模式 |
| `find_symbol` | AST 精确查找，并保留文本候选降级 |
| `find_references` | 查询 resolved、candidate、ambiguous 或 unresolved 引用 |
| `inspect_python` | 按 Agent 指定文件提取 Python AST 结构事实 |
| `get_relationships` | 查询当前已探索 Repository Map 的局部关系 |
| `recall_memory` | 按类型、Symbol 和 Path 召回当前 Commit 的结构化记忆 |
| `search_memory` | 使用 SQLite FTS5 和字段匹配搜索候选记忆 |
| `save_memory` | 保存携带有效 Evidence 的 Agent 记忆候选 |

AST Tool 不会自动扩展成全仓库分析；解析哪些文件仍由 Agent 决定。

## Repository Memory 与多轮问答

Phase 4 使用本地 SQLite 保存 Repository、Commit、Analysis Run、Finding、Evidence、探索摘要
和 Conversation。FTS5 只负责检索候选；Memory 是否足够、是否需要重新验证或继续读取源码，
仍由 Agent 决定。不同 Commit 的 Evidence 默认隔离。

```bash
# 单次证据化提问
repopilot ask https://github.com/owner/repository "项目入口在哪里？"

# 交互式多轮问答
repopilot chat https://github.com/owner/repository

# 查看长期记忆
repopilot memory stats
repopilot memory list
repopilot memory show MEMORY_ID

# 安全导出或合并导入 JSON
repopilot memory export --output repopilot-memory.json
repopilot memory import repopilot-memory.json
```

默认数据库位于 `.repopilot/memory.db`，已被 Git 忽略。可以通过 `.env` 修改：

```dotenv
REPOPILOT_MEMORY_ENABLED=true
REPOPILOT_MEMORY_DATABASE=.repopilot/memory.db
REPOPILOT_MEMORY_FTS_ENABLED=true
REPOPILOT_MEMORY_MAX_RESULTS=10
REPOPILOT_MEMORY_MAX_CALLS_PER_RUN=6
```

## 报告内容

报告覆盖：

- 项目简介与技术栈
- 项目目录与程序入口
- 核心模块和关键类/函数
- 核心执行流程与模块依赖
- 重要设计和潜在工程问题
- 推荐源码阅读顺序
- Agent 状态、探索统计、Token Usage 和 Evidence

程序入口、核心模块、执行流程和模块关系使用结构化 Finding。每条关键 Finding 都必须引用
已验证 Evidence；静态 Call Site 只能支持推断的执行流程，不能被夸大为运行时必然调用。

## 成本控制

默认配置采用有界模式：最多 12 次模型决策、10 次 Tool 调用、4 万字符 Agent Context、
8 万累计 Token，单个 AST Tool 最多返回 60 条结构事实。达到预算后停止继续调用模型，并
生成明确标记为部分完成的报告。

可以在单次运行中进一步收紧预算：

```bash
repopilot analyze https://github.com/owner/repository \
  --max-iterations 8 \
  --max-total-tokens 40000
```

Provider 返回 Usage 时，报告和 Trace 记录真实 Prompt、Completion 与 Total Token；否则
使用字符数保守估算并标记为 `estimated`。金额由模型平台定价决定，RepoPilot 使用与
Provider 无关的 Token 上限作为断路器。

## 安全边界

- 只接受公开的 `https://github.com/owner/repository` URL。
- 不执行目标仓库代码，不安装其依赖，不初始化 Git Submodule。
- Agent 没有 Shell、任意网络或密钥读取工具；Memory Tool 只能访问当前仓库范围。
- README、注释和源码均被视为不可信数据，而不是系统指令。
- 拒绝绝对路径、路径穿越、符号链接和仓库外文件访问。
- 跳过常见构建、虚拟环境、缓存和依赖目录。
- 限制仓库大小、文件数、目录深度、读取量、搜索结果、上下文和迭代次数。
- Trace 与错误信息进行密钥脱敏；`.env` 和生成的 `reports/` 默认不提交。

## 开发与验证

```bash
python -m ruff check src tests
python -m mypy src
python -m pytest --cov=repopilot --cov-report=term --cov-fail-under=85
```

当前基线：

```text
103 passed
88.36% coverage
ruff passed
mypy passed
clean editable install passed
```

## 项目文档

- [项目总体方案](./PROJECT_PLAN.md)
- [Phase 1 执行方案](./PHASE1_IMPLEMENTATION_PLAN.md)
- [Phase 2 执行方案](./PHASE2_IMPLEMENTATION_PLAN.md)
- [Phase 3 执行方案](./PHASE3_IMPLEMENTATION_PLAN.md)
- [Phase 3 验收记录](./PHASE3_ACCEPTANCE.md)
- [Phase 4 执行方案](./PHASE4_IMPLEMENTATION_PLAN.md)
- [Phase 4 验收记录](./PHASE4_ACCEPTANCE.md)

## 当前边界

当前版本支持公开 Python 仓库的单次分析和 SQLite/FTS5 长期 Repository Memory、CLI 多轮
问答。Embedding、向量数据库、FastAPI/Web、多语言 AST、代码修改和 PR 自动化不在当前
计划中；Phase 4 的真实多轮 Provider 与三类仓库评测仍待完成。
