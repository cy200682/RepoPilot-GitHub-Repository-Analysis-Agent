# RepoPilot — GitHub Repository Analysis Agent

> Phase 3 当前验收状态见 [PHASE3_ACCEPTANCE.md](PHASE3_ACCEPTANCE.md)。

## 1. 项目概述

RepoPilot 是一个面向开发者的 GitHub 代码仓库分析 Agent。用户输入公开 GitHub Repository URL 后，系统自动克隆仓库、扫描工程结构、自主探索关键代码、识别核心模块及调用关系，并生成带源码证据的分析报告。

RepoPilot 的目标不是构建通用 Agent Framework，而是解决一个明确的工程问题：

> 帮助开发者快速、可靠地理解一个陌生代码仓库。

项目第一阶段聚焦 Python 仓库，以单 Agent、自研轻量 Agent Loop、Python AST 和 OpenAI-compatible API 为核心，不引入 LangChain、LangGraph、复杂知识图谱或多 Agent 架构。

---

## 2. 产品目标

对于一个此前完全不了解的 Python Repository，RepoPilot 应当能够：

1. 成功克隆并安全扫描仓库。
2. 识别项目语言、技术栈、依赖与配置。
3. 定位程序入口和核心模块。
4. 自主选择并阅读十几个关键文件，而非一次性加载整个仓库。
5. 追踪主要执行链、模块依赖和关键对象关系。
6. 为重要结论提供真实源码位置作为证据。
7. 输出结构清晰、基本可靠的架构分析报告。
8. 基于已经建立的仓库上下文继续回答开发者问题。

典型问题包括：

- 这个项目的入口在哪里？
- Agent 是如何创建的？
- 一次请求会经过哪些模块？
- RAG 在哪里实现？
- 数据库层是如何设计的？
- 如果修改登录逻辑，应该重点阅读哪些文件？

---

## 3. 使用方式

### 3.1 CLI

```bash
repopilot analyze https://github.com/xxx/project
```

### 3.2 Web

```text
打开 Web 页面
    ↓
粘贴 GitHub URL
    ↓
点击 Analyze
    ↓
查看分析报告
    ↓
继续针对仓库提问
```

---

## 4. 核心价值

### 4.1 Agentic Code Exploration

模型自主判断下一步应读取、搜索或分析哪些文件，不把完整仓库一次性塞入上下文。

### 4.2 AST + LLM Code Understanding

AST 负责提取确定性的代码结构，LLM 负责解释代码语义、模块职责和架构意图。

### 4.3 Evidence-grounded Analysis

核心结论尽量关联到真实文件及代码范围，例如：

```text
项目的 Agent 主循环位于 AgentRuntime.run()。

Evidence:
src/runtime/agent.py:52-118
```

---

## 5. 核心能力

### 5.1 Repository Scan

Repository Scanner 负责建立仓库的基础认知，包括：

- 克隆公开 GitHub Repository。
- 生成经过过滤的目录树。
- 识别主要语言和技术栈。
- 识别依赖、构建、测试和部署配置。
- 读取 README 及其他高价值说明文档。
- 排除 `build`、`dist`、`.git`、`venv`、`.venv`、`node_modules` 等无关目录。
- 对文件数量、类型、大小和目录深度设置安全限制。

### 5.2 Agent 自主探索

Agent 采用渐进式探索策略：

```text
扫描仓库
    ↓
判断项目类型
    ↓
寻找程序入口
    ↓
读取入口代码
    ↓
识别关键模块
    ↓
继续搜索、读取和验证
    ↓
形成架构结论
```

每轮由模型根据当前分析目标、已有结论和最近 Tool Result，决定调用工具或结束分析。

### 5.3 Code Tools

所有工具通过统一 Tool Registry 注册并调用。

第一版工具集：

| 工具 | 职责 |
| --- | --- |
| `get_tree` | 获取经过过滤和裁剪的目录树 |
| `read_file` | 按路径或行范围读取文本文件 |
| `search_code` | 在仓库中搜索字符串或正则模式 |
| `find_symbol` | 查找类、函数或方法定义 |
| `find_references` | 查找符号的引用位置 |
| `read_config` | 解析常见依赖和工程配置 |
| `git_log` | 获取有限的提交历史信息 |

后续扩展：

- `run_command`
- GitHub API
- MCP
- Semantic Code Search

所有工具应返回结构化结果，并包含路径、行号、截断状态和错误信息。

### 5.4 AST Code Analysis

第一版仅支持 Python AST 静态分析，提取：

- Class
- Function
- Method
- Import
- Inheritance
- Function Call

AST 分析结果用于构建轻量 Repository Map：

```text
main.py
   ↓
AppService
   ↓
AgentManager
   ├── Planner
   └── Executor
```

Repository Map 应优先表达可由静态代码确认的关系。无法可靠解析的动态调用，应标记为推断，不伪装成确定事实。

### 5.5 Context Management

上下文只保留完成当前分析所需的信息：

- Repository Summary
- 当前分析目标
- 关键文件摘要
- 最近 Tool Results
- 重要代码片段
- 已确认的架构结论
- 尚未验证的问题和假设

旧的文件读取结果应自动压缩为摘要。原始证据位置继续保留，以便报告生成和后续问答时回溯。

### 5.6 Evidence Grounding

分析结论按可信度区分：

- **Confirmed**：可由源码、配置或文档直接确认。
- **Inferred**：由多个代码信号推断，但缺少直接声明。
- **Unknown**：当前证据不足，不能可靠判断。

关键结论尽量包含：

```text
relative/path.py:start_line-end_line
```

报告生成前应检查证据引用是否对应真实文件和有效行号。

### 5.7 Repository Q&A

完成初始分析后，系统保留仓库摘要、Repository Map、证据索引和会话上下文，用于回答后续问题。

回答应：

- 优先使用已有证据。
- 必要时继续调用工具探索仓库。
- 明确区分事实和推断。
- 给出建议阅读或修改的文件。
- 不在证据不足时虚构实现细节。

---

## 6. 系统架构

RepoPilot 采用 **Agent-Centric Architecture**。Agent 是整个分析过程的决策中心；Scanner、AST、Repository Map、Search、Read、Evidence 等确定性模块都是 Agent 可按需调用的能力，而不是一条预先规定分析顺序的固定流水线。

```text
             User Goal / Question
                      │
                      ▼
                Agent Runtime
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
        Scan         AST         Search
          │           │           │
          ├───────────┼───────────┤
          ▼           ▼           ▼
        Read        Symbol   Repository Map
          │           │           │
          └───────────┼───────────┘
                      ▼
                 Observation
                      │
                      ▼
                Context Manager
                      │
                      ▼
                Agent Runtime
                      │
               下一步自主决策
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
       调用其他工具        Finish / Report
```

Repository Loader 只负责在 Agent Loop 开始前准备安全的本地仓库。初始扫描可以提供最低限度的仓库概况，但不能替 Agent 决定哪些文件是核心文件、入口在哪里，或主要执行链是什么。

### 6.1 核心控制关系

系统必须保持以下控制关系：

```text
Goal
  ↓
Agent 形成当前假设
  ↓
选择 Tool、范围和参数
  ↓
确定性模块执行
  ↓
Observation
  ↓
Agent 更新、验证或推翻假设
  ↓
继续探索 / 交叉验证 / Finish
```

禁止将系统实现为：

```text
Scanner
  ↓
AST
  ↓
Repository Map
  ↓
固定算法选择关键文件
  ↓
LLM 总结
```

后一种实现本质上是“静态代码分析 + LLM 总结”，不具备 RepoPilot 所要求的自主探索能力。

判断实现是否仍以 Agent 为中心，需要检查：

- 模块是否由 Agent 根据当前 Goal 和已有 Observation 主动调用？
- Agent 是否决定本次调用的范围、参数和期望验证的问题？
- 工具结果是否仅作为 Observation 返回，而不是直接形成最终架构结论？
- Agent 是否能依据结果改变原计划、推翻假设或选择另一条探索路径？
- 面对不同仓库或不同用户问题，工具调用顺序是否可能不同？

如果这些问题多数为否，确定性模块很可能已经侵占了 Agent 的决策职责。

### 6.2 组件职责

| 组件 | 主要职责 |
| --- | --- |
| Repository Loader | 校验 URL、克隆仓库、管理本地工作目录 |
| Repository Scanner | 按 Agent 指定的范围过滤和扫描目录，返回仓库事实 |
| AST Analyzer | 按 Agent 请求提取指定文件或模块的 Python 结构与静态关系 |
| Repository Map | 保存和查询探索过程中逐步发现的关系，不负责决定核心模块 |
| Tool Registry | 注册工具、校验参数、执行工具并统一返回结果 |
| Agent Runtime | 接收 Goal、解释 Observation，决定下一步工具、参数和结束条件 |
| Context Manager | 控制上下文规模，维护摘要、证据和分析状态 |
| Evidence Store | 保存 Agent 结论与源码位置的关联，不独立产生架构判断 |
| Report Generator | 渲染 Agent 已形成且带证据的结论，不代替 Agent 分析 |
| Session/Q&A | 保存分析结果并支持针对仓库的继续提问 |

### 6.3 确定性模块与 Agent 的边界

确定性模块负责回答“代码里客观存在什么”：

- 文件和目录有哪些？
- 某个符号在哪里定义？
- 某个文件导入了哪些模块？
- 某个函数中出现了哪些静态调用？
- 某条 Evidence 是否对应真实文件和有效行号？

Agent 负责回答“为了当前 Goal，下一步应该做什么，以及这些事实意味着什么”：

- 当前应该先寻找入口、配置、路由还是核心领域对象？
- 哪个入口候选最值得读取？
- AST 关系是否足以支持当前假设？
- 是否需要通过 Search 或 Read 交叉验证？
- 哪些模块是核心模块，主要执行链是什么？
- 当前证据是否足够结束探索并生成报告？

同一个仓库面对不同 Goal，应产生不同探索轨迹。例如，“登录逻辑在哪里”和“异步任务如何执行”不应运行完全相同的固定分析流水线。

---

## 7. 推荐项目结构

```text
repopilot/
├── pyproject.toml
├── README.md
├── src/
│   └── repopilot/
│       ├── cli.py
│       ├── config.py
│       ├── models/
│       │   ├── actions.py
│       │   ├── evidence.py
│       │   └── repository.py
│       ├── repository/
│       │   ├── loader.py
│       │   ├── scanner.py
│       │   ├── filters.py
│       │   └── detector.py
│       ├── analysis/
│       │   ├── ast_parser.py
│       │   ├── repository_map.py
│       │   └── relationships.py
│       ├── tools/
│       │   ├── registry.py
│       │   ├── tree.py
│       │   ├── files.py
│       │   ├── search.py
│       │   ├── symbols.py
│       │   └── git.py
│       ├── agent/
│       │   ├── runtime.py
│       │   ├── prompts.py
│       │   ├── context.py
│       │   └── state.py
│       ├── llm/
│       │   ├── client.py
│       │   └── protocol.py
│       ├── report/
│       │   ├── generator.py
│       │   └── templates.py
│       ├── storage/
│       │   ├── database.py
│       │   └── sessions.py
│       └── api/
│           ├── app.py
│           ├── routes.py
│           └── schemas.py
└── tests/
    ├── fixtures/
    ├── unit/
    └── integration/
```

该结构是开发建议，不要求在 MVP 阶段一次性创建所有模块。

---

## 8. Agent Runtime 设计

Agent Loop 保持简单、透明和可调试：

```python
while not state.finished:
    context = context_manager.build(state)
    action = llm.decide(context, available_tools)

    if action.type == "tool":
        result = tool_registry.execute(action)
        state.record(action, result)
        context_manager.compact_if_needed(state)
    elif action.type == "finish":
        state.finish(action.summary)
```

Runtime 至少需要以下保护机制：

- 最大循环轮数。
- 最大工具调用次数。
- 单文件和单次结果大小限制。
- 重复动作检测。
- 工具参数校验。
- 模型输出解析失败重试。
- 总 Token 与成本统计。
- 超时、取消和异常状态。
- 完整 Trace，便于复现分析过程。

Agent 每轮输出应遵循结构化协议，例如：

```json
{
  "reason": "需要从 CLI 入口追踪应用初始化过程",
  "action": "read_file",
  "arguments": {
    "path": "src/repopilot/cli.py"
  }
}
```

或：

```json
{
  "reason": "已有证据足以生成报告",
  "action": "finish",
  "summary": "已确认入口、核心模块和主要执行流程"
}
```

---

## 9. 技术栈

| 分类 | 技术 |
| --- | --- |
| 语言 | Python |
| 数据模型 | Pydantic |
| Git | GitPython |
| 静态分析 | Python AST |
| LLM | OpenAI-compatible API |
| 长期记忆 | SQLite + FTS5 |
| CLI | Typer + Rich |

第一版不引入 LangChain 或 LangGraph，Agent Loop 自行实现，以保持运行机制清晰、依赖较少且易于调试。

---

## 10. 报告规范

最终报告统一输出为 Markdown：

```markdown
# Repository Analysis

## 项目简介

## 技术栈

## 项目目录

## 程序入口

## 核心模块

## 核心执行流程

## 模块依赖关系

## 关键类 / 函数

## 重要设计

## 潜在工程问题

## 推荐源码阅读顺序
```

报告质量要求：

- 结论具体，避免只复述目录和 README。
- 关键架构判断附带源码证据。
- 清楚标记推断和不确定项。
- 核心执行流程应描述模块之间的真实传递关系。
- 阅读顺序应说明每一步的阅读目的。
- 工程问题应有代码依据，不生成泛化的“最佳实践”清单。

---

## 11. 数据模型建议

### 11.1 Repository

```text
Repository
├── id
├── source_url
├── local_path
├── default_branch
├── commit_sha
├── detected_languages
├── framework_hints
└── scan_status
```

### 11.2 Symbol

```text
Symbol
├── id
├── file_path
├── qualified_name
├── kind
├── start_line
├── end_line
├── signature
└── docstring_summary
```

### 11.3 Relationship

```text
Relationship
├── source_symbol
├── target_symbol
├── relation_type
├── evidence
└── confidence
```

### 11.4 Evidence

```text
Evidence
├── file_path
├── start_line
├── end_line
├── excerpt
├── claim_id
└── confidence
```

### 11.5 Analysis Session

```text
AnalysisSession
├── repository_id
├── objective
├── status
├── iteration_count
├── tool_history
├── confirmed_findings
├── open_questions
├── token_usage
└── report
```

---

## 12. 开发阶段

### Phase 1 — MVP

目标：完成从 GitHub URL 到基础分析报告的最小闭环。

详细任务拆分、模块接口、测试策略和完成标准见 [Phase 1 MVP 执行方案](./PHASE1_IMPLEMENTATION_PLAN.md)。

```text
GitHub URL
    ↓
Clone
    ↓
目录扫描
    ↓
README / 配置解析
    ↓
LLM 分析
    ↓
基础报告
```

交付内容：

- CLI `repopilot analyze <url>`。
- URL 校验和仓库克隆。
- 基础目录过滤与技术栈识别。
- README、依赖和配置文件读取。
- OpenAI-compatible LLM Client。
- Markdown 报告生成。
- 针对小型公开 Python 仓库的端到端测试。

验收标准：

- 对有效公开仓库可稳定完成分析。
- 对无效 URL、克隆失败和超大仓库给出明确错误。
- 报告至少包含项目简介、技术栈、目录、入口候选和核心模块候选。

### Phase 2 — Agent

目标：从一次 Prompt 分析升级为自主探索 Repository。

详细 Action 协议、Tool Registry、Agent Runtime、Trace、测试矩阵和验收标准见 [Phase 2 Agent 执行方案](./PHASE2_IMPLEMENTATION_PLAN.md)。

交付内容：

- Agent Loop。
- Tool Registry。
- `get_tree`、`read_file`、`search_code`、`find_symbol`。
- 结构化 Action 协议。
- 循环上限、失败重试和执行历史。
- 基于探索结果生成报告。

验收标准：

- Agent 能根据仓库类型选择不同探索路径。
- 能从入口候选继续定位主要模块。
- 不需要将仓库所有文件放入一次 Prompt。
- Trace 能解释每次工具调用的目的和结果。

### Phase 3 — Code Understanding

目标：利用 AST 和 Repository Map 提升结构理解与证据质量。

详细数据契约、按需 AST 工具、增量 Repository Map、解析边界、测试矩阵和验收门禁见 [Phase 3 Code Understanding 执行方案](./PHASE3_IMPLEMENTATION_PLAN.md)。

交付内容：

- Python AST Parser。
- 类、函数、方法、导入、继承和调用提取。
- `find_references`。
- Repository Map。
- Evidence 数据模型与引用校验。
- 模块依赖和核心执行流程生成。

验收标准：

- 能识别常见 Python 项目的入口、核心类和模块依赖。
- 主要架构结论可追溯到文件和行号。
- 静态分析无法确认的动态行为会标记为推断。

### Phase 4 — Agent Memory

目标：增加跨进程 Repository Memory、上下文管理和多轮证据化问答。

交付内容：

- SQLite + FTS5 结构化 Repository Memory。
- Repository / Commit 隔离和失效机制。
- `recall_memory`、`search_memory`、`save_memory`。
- Conversation Summary 与 Context Budget。
- CLI 多轮 Repository Q&A。
- Memory 使用 Trace 和复用收益评测。

验收标准：

- Agent 自主决定查询 Memory 或继续探索源码。
- 相同仓库和 Commit 可复用已验证 Finding 与 Evidence。
- 新 Commit 不会错误复用旧 SourceSpan。
- 多轮问答不会因无限历史消息耗尽上下文。
- 关键回答保持 100% Evidence 覆盖。

---

## 13. 第一版明确不做

为避免范围失控，第一版不实现：

- 复杂 Knowledge Graph。
- 与 Repository Analysis 无关的通用人格 Memory。
- 五六个 Sub-Agent。
- 自动修改代码。
- 自动提交 PR。
- IDE Plugin。
- 多语言 AST。
- 完整 Coding Agent。
- 复杂向量数据库。
- 全仓库级精确动态调用图。

---

## 14. 非功能要求

### 14.1 安全

- 第一版仅分析公开 GitHub 仓库。
- 默认不执行目标仓库中的任何代码或脚本。
- 不安装目标仓库依赖。
- 防止路径穿越和符号链接逃逸。
- 对仓库大小、文件数量、单文件大小和读取总量设置限制。
- 日志中不记录 API Key 等敏感配置。

### 14.2 稳定性

- 所有外部操作必须有超时。
- Clone、LLM 和 Tool 调用失败应返回可诊断错误。
- 分析过程可取消。
- 部分工具失败不应直接丢失整个分析状态。

### 14.3 可观察性

- 记录每轮 Agent Action 和 Tool Result 摘要。
- 记录 Token、耗时、重试和错误。
- 报告可关联到具体仓库 Commit SHA。
- 支持导出完整分析 Trace 供调试。

### 14.4 性能与成本

- 优先读取高价值文件和相关代码范围。
- 对重复文件读取进行缓存。
- 对相同 URL + Commit SHA 复用扫描和 AST 结果。
- 设置 Agent 最大轮次、上下文预算和输出预算。

---

## 15. 测试策略

### 15.1 单元测试

- URL 解析与校验。
- 目录过滤规则。
- 技术栈检测。
- AST 节点提取。
- Tool 参数校验和结果截断。
- Evidence 行号校验。
- Context 压缩策略。

### 15.2 集成测试

- 克隆固定的小型公开仓库或本地 Fixture 仓库。
- 从扫描到报告的完整流程。
- Agent 多轮工具选择。
- LLM 返回非法 Action 时的恢复。
- Clone、读取和搜索失败场景。

### 15.3 Golden Report Evaluation

选择若干结构不同的 Python 仓库，为以下项目建立人工标注答案：

- 正确入口。
- 核心模块。
- 一条主要执行链。
- 关键类和函数。
- 重要源码证据。

以此检查报告的覆盖率、证据准确率和明显幻觉，而不仅检查程序是否成功运行。

---

## 16. 最终验收标准

项目“完成”的判断标准不是简单地能运行，而是对于一个陌生 Python Repository，能够完成：

```text
成功 Clone
    ↓
找到入口
    ↓
找到核心模块
    ↓
自主阅读十几个关键文件
    ↓
追踪主要执行链
    ↓
给出源码证据
    ↓
输出基本可靠的架构报告
    ↓
继续回答用户关于代码的问题
```

建议使用以下指标进行验收：

| 指标 | 目标 |
| --- | --- |
| 公开 Python 测试仓库分析成功率 | ≥ 90% |
| 入口识别准确率 | ≥ 80% |
| 核心模块覆盖率 | ≥ 80% |
| 关键证据引用有效率 | ≥ 95% |
| 报告中严重无依据结论 | 0 个 |
| 分析过程 | 可追踪、可限额、可取消 |

具体数值可在建立 Golden Dataset 后根据实际结果调整。

---

## 17. 参考项目与借鉴范围

### mini-SWE-agent

主要学习：

- Agent Loop
- Shell-based Agent
- Execution History
- 极简 Runtime

不复制或扩展为复杂通用 Agent Framework。

### OpenBMB RepoAgent

主要学习：

- AST Parser
- Repository Hierarchy
- Object Relationship
- 代码结构理解

### Potpie

主要学习：

- Context 组织
- 代码关系表达
- Evidence
- Repository Understanding

第一版不实现完整 Context Graph。

---

## 18. 后续演进

在第一版稳定后，根据实际需求逐步增加：

```text
V1  单 Agent + AST
V2  Semantic Code Search
V3  Sub-Agent
V4  MCP
V5  Git History / PR / Issue
V6  修改代码 + Test + Patch
V7  IDE / VS Code Plugin
```

每次升级都应以真实用户问题和现有能力瓶颈为依据，不提前引入与当前目标无关的复杂度。

---

## 19. 当前开发原则

1. 先完成可用闭环，再提高分析深度。
2. 优先建立可靠工具和证据链，而不是堆叠 Prompt。
3. 保持单 Agent Runtime 简单、可观察、可测试。
4. AST 输出事实，LLM 解释意义，二者职责分离。
5. 所有资源消耗必须可限制。
6. 默认不执行被分析仓库的代码。
7. 报告质量以开发者能否据此继续阅读和修改代码为最终标准。
