# RepoPilot Phase 4 完整执行计划

## 1. 阶段目标

Phase 4 在前三阶段已经完成的 Repository Loader、Scanner、Agent Loop、只读 Tool Registry、
Python AST、增量 Repository Map、Finding、Evidence 和 Finish Gate 之上，增加与 Agent 直接相关的
长期记忆和多轮 Repository Q&A。

本阶段不再建设通用后端平台。目标是：

> 让 Agent 能够记住以前对某个仓库确认过什么、探索过什么、还有什么没有确认，并在后续问题中
> 自主决定复用记忆还是继续读取源码。

本阶段完成后，RepoPilot 应能够：

1. 将已验证的 Repository Finding、Evidence 和探索摘要持久化到 SQLite。
2. 按 Repository 与 Commit SHA 隔离长期记忆。
3. 使用结构化过滤和 SQLite FTS5 检索记忆，不依赖 Embedding。
4. 由 Agent 自主调用 Memory Tool，而不是由 Runtime 自动注入全部历史。
5. 判断历史记忆是 current、reusable、stale 还是 invalid。
6. 在记忆不足或过期时继续调用 Read、Search、Symbol 和 AST Tool。
7. 支持针对同一个 Repository 的多轮 CLI 问答。
8. 对旧对话和 Observation 做摘要，控制上下文和模型费用。
9. 保持所有具体代码结论可以回溯到当前 Commit 的 Evidence。
10. 用可复现测试证明长期记忆确实改变了 Agent 路线，而不是只保存聊天记录。

Phase 4 主链路：

```text
历史 Analysis
      ↓
Verified Finding / Evidence / Exploration Summary
      ↓
SQLite Repository Memory
      ↓
用户提出新问题
      ↓
Agent 自主选择 Memory Tool
      ↓
Memory Observation
      ↓
Agent 判断：复用 / 验证 / 继续探索
      ↓
Evidence-grounded Answer
```

---

## 2. 为什么不用 Embedding 也能做长期记忆

长期记忆的本质是“跨进程持久保存并可按需召回的信息”，不等于向量数据库。

Phase 4 使用以下形式保存记忆：

```text
SQLite 普通表
├── Repository / Revision
├── Analysis Run
├── Structured Memory Entry
├── Finding / Evidence
├── Exploration Summary
├── Conversation / Message
└── Memory 使用记录

SQLite FTS5 虚拟表
└── 对 title、content、tags、symbol_names、paths 做全文检索
```

一次已确认的记忆示例：

```json
{
  "memory_id": "mem_...",
  "repository": "pallets/itsdangerous",
  "commit_sha": "672971d...",
  "memory_type": "symbol_finding",
  "title": "Signer.sign 生成签名值",
  "content": "Signer.sign 对输入值计算签名并返回组合结果。",
  "tags": ["signer", "sign", "signature", "签名"],
  "symbol_names": ["Signer.sign", "Signer.get_signature"],
  "paths": ["src/itsdangerous/signer.py"],
  "confidence": "confirmed",
  "evidence_ids": ["ev_..."],
  "status": "current"
}
```

检索时不计算向量相似度，而是组合：

1. Repository/Revision 精确过滤。
2. Memory Type 过滤。
3. Symbol Name、Path、Tag 精确或前缀匹配。
4. SQLite FTS5 的 BM25 全文排序。
5. Evidence 质量和 Commit 新鲜度排序。

这足以支持：

- “入口在哪里” → 搜索 `entry point main cli app` 标签和内容。
- “Agent 怎么创建” → 搜索 `AgentRuntime create initialize` 和符号名。
- “签名逻辑在哪” → 搜索 `sign signature 签名`、Path 和 Symbol。
- “修改登录应该看什么文件” → 搜索 `login auth 登录` 以及相关 Finding。

Embedding 适合更模糊、更大规模的语义召回，但不是长期记忆成立的前提。当前项目以 Agent 决策、
Evidence 和 Context Management 为重点，FTS5 更简单、更透明，也更容易在面试中解释和验证。

---

## 3. Phase 3 交接基线

Phase 4 必须复用以下现有能力：

- `RepositoryLoader`：公开 GitHub 仓库安全克隆与 Commit 固定。
- `RepositoryScanner`：目录过滤、规模限制和初始事实。
- `AgentRuntime`：Goal → Decision → Tool → Observation 循环。
- `ToolRegistry`：七个只读代码/AST 工具。
- `AgentState`、`AgentTrace`：运行状态、步骤、预算和 Token Usage。
- `PythonAstParser`、`CodeIndex`、`RepositoryMap`：增量代码理解。
- `Finding`、`AgentEvidence`、`FinishGate`：证据化结论。
- CLI `analyze`、`doctor` 和 Bootstrap 回归入口。

当前质量基线：

```text
83 tests passed
90.04% coverage
ruff passed
mypy passed
clean editable install passed
```

Phase 3 尚未完成的三类真实仓库 Smoke Test 和 Golden Evaluation 继续保留为未完成项。Phase 4
不能用“记住了旧结果”掩盖代码理解质量不足。

---

## 4. 本阶段范围

### 4.1 实现

- SQLite Repository Memory。
- SQLite Schema Version 与轻量 Migration。
- Repository/Revision/Run/Memory/Evidence/Conversation 数据模型。
- Structured Memory Entry。
- SQLite FTS5 全文检索。
- `recall_memory`、`search_memory`、`save_memory`。
- Memory Validation Gate。
- Commit-aware Memory Invalidation。
- Conversation Summary。
- Context Budget 与 Memory Budget。
- CLI Repository Q&A。
- Memory Trace 与使用统计。
- Fake Agent 和真实仓库验收。

### 4.2 不实现

- Embedding。
- pgvector、FAISS、Chroma、Qdrant。
- PostgreSQL。
- FastAPI。
- React/Web 页面。
- Redis、Celery 或消息队列。
- 用户系统、OAuth、JWT 和 RBAC。
- Docker 微服务编排。
- Prometheus、OpenTelemetry。
- 通用人格记忆。
- 复杂 Knowledge Graph。
- Sub-Agent。
- 自动修改代码和 PR。
- 多语言 AST。

这些能力不影响 RepoPilot 作为 Agent 项目的完整性。

---

## 5. Agent-Centric 硬约束

### 5.1 Memory 必须是 Tool

正确流程：

```text
Goal
  ↓
Agent
  ├── recall_memory
  ├── search_memory
  ├── read_file
  ├── search_code
  └── inspect_python
  ↓
Observation
  ↓
Agent 下一步决策
```

错误流程：

```text
数据库自动搜索
  ↓
全部结果自动塞入 Prompt
  ↓
LLM 总结
```

要求：

- Agent 通过显式 Tool Action 查询记忆。
- Memory Tool Result 是普通 Observation。
- Trace 记录 Agent 为什么查询、查询条件和结果摘要。
- Runtime 不规定第一轮必须查询记忆。
- Runtime 不根据固定关键词自动选择核心 Memory。
- Agent 可以忽略 Memory、验证 Memory 或继续探索源码。

### 5.2 记忆不是事实真相

- `confirmed` Memory 代表它在某个 Commit 上通过过 Evidence Gate。
- 新问题仍需要检查它是否属于当前 Commit。
- 用户问题可能超出旧分析覆盖范围。
- 旧 Finding 只能回答它确实覆盖的范围。
- 没有 Evidence 的历史回答不能成为 confirmed Memory。

### 5.3 删除 LLM 后的边界

删除 LLM 后，系统可以：

- 保存和查询 Memory。
- 按 FTS5 排序候选。
- 返回历史 Finding 和 Evidence。
- 判断 Commit 是否一致。

删除 LLM 后，系统不能：

- 判断当前 Goal 应查询什么。
- 决定要不要相信旧 Memory。
- 决定下一步读取哪个源码文件。
- 生成新的架构解释。
- 判断什么时候已经充分回答问题。

### 5.4 Memory 不替代源码 Evidence

- Memory 只是历史知识入口。
- 回答具体代码结论仍要引用 Evidence。
- FTS5 命中分数不能作为 Evidence。
- `historical` 或 `stale` Memory 不能支撑当前 Commit 的 confirmed Finding。
- SourceSpan、Resolution 和原 Observation 继续由 Finish Gate 校验。

---

## 6. Memory 分类

### 6.1 Repository Summary Memory

保存：

- 项目用途。
- 技术栈。
- 主要目录。
- 应用类型。
- 已知入口。

来源必须是完成或部分完成的 Analysis Run，并记录覆盖范围。

### 6.2 Finding Memory

保存已经通过 Gate 的结构化 Finding：

- `entry_points`。
- `core_modules`。
- `execution_flows`。
- `module_relationships`。
- `important_designs`。
- `engineering_issues`。
- `reading_order`。

它是长期记忆的核心。

### 6.3 Symbol/File Summary Memory

保存 Agent 已探索文件和符号的有限摘要：

- Path。
- Symbol ID / Qualified Name。
- Symbol Kind。
- 职责摘要。
- SourceSpan。
- Content Hash。
- 来源 Observation。

不保存整个源码文件全文。

### 6.4 Exploration Memory

记录某个 Goal 下：

- 已探索文件。
- 已调用工具。
- 已验证假设。
- 被否定假设。
- 未解决问题。
- Coverage Notes。
- 预算耗尽或失败原因。

Exploration Memory 用于避免无意义重复，不直接作为业务结论。

### 6.5 Conversation Memory

保存：

- 用户问题。
- Assistant 最终回答。
- 回答状态。
- Evidence IDs。
- Conversation Summary。
- 当前固定 Revision。

旧 Message 保存在 SQLite 中，但只有最近有限条和 Summary 进入当前 Context。

### 6.6 Negative Memory

保存经过验证的失败路线：

- 某个 Symbol 在当前 Revision 不存在。
- 某个文件是候选但与当前 Goal 无关。
- 某个动态关系无法用静态 AST 确认。
- 某类 Tool 调用因为 SyntaxError 降级。

Negative Memory 必须有范围和过期条件，防止 Agent 在新 Commit 中永久放弃有效路线。

---

## 7. 不保存的内容

- 模型隐藏推理过程。
- 每轮完整 Prompt。
- 未脱敏 Provider Response。
- API Key 或 `.env` 内容。
- 整个 Repository 源码。
- 默认完整 AST Tree。
- 一万行 Trace 自动注入 Memory。
- 没有来源的自然语言猜测。
- FTS5 搜索分数作为事实。
- `ambiguous/unresolved` 关系作为 confirmed 结论。
- 已被新 Commit 修改且没有重新验证的 SourceSpan。

完整 Trace 继续作为调试 Artifact，而不是长期语义记忆。

---

## 8. 总体架构

```text
                     User Goal / Question
                              │
                              ▼
                         Agent Runtime
                              │
                 AgentDecision: Tool Action
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
  Code Tools              AST Tools             Memory Tools
 Read/Search/Symbol   Inspect/Relationships   Recall/Search/Save
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                         Observation
                              │
                              ▼
                       Agent 下一步决策
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
                Continue           Finish Gate
                                          │
                                          ▼
                                  Answer / Report
                                          │
                                          ▼
                                Verified Memory Writer
                                          │
                                          ▼
                                     SQLite + FTS5
```

### 8.1 组件职责

| 组件 | 负责 | 不负责 |
|---|---|---|
| Memory Store | 持久化结构化记忆 | 判断记忆是否回答了 Goal |
| FTS5 Index | 全文候选检索和 BM25 排序 | 判断架构正确性 |
| Memory Tools | 将查询结果变成 Observation | 自动注入全部历史 |
| Memory Validator | 校验 Revision、Evidence 和状态 | 解释业务语义 |
| Memory Writer | 保存通过验证的候选 Memory | 保存模型隐藏推理 |
| Context Manager | 控制进入 Prompt 的记忆和消息 | 永久删除原始记录 |
| Agent | 选择查询、验证和探索路线 | 绕过 Evidence Gate |
| Finish Gate | 校验最终回答引用 | 决定下一步 Tool |

---

## 9. 技术选型

| 领域 | 技术 | 理由 |
|---|---|---|
| 持久化 | Python `sqlite3` | 标准库、零服务、适合 CLI Agent |
| Schema | SQL + 轻量 Repository Adapter | 保持数据行为透明，避免 ORM 复杂度 |
| 全文检索 | SQLite FTS5 | 无 Embedding 的 BM25 关键词检索 |
| 数据契约 | Pydantic 2 | 复用现有模型和严格校验 |
| Migration | `PRAGMA user_version` + 版本化 SQL | 规模小、无需 Alembic |
| CLI | Typer + Rich | 复用现有入口并实现交互问答 |
| 测试 | Pytest | 复用现有测试体系 |

不引入 ORM 的原因：

- 当前只有单进程 CLI 和少量关系表。
- SQL 查询本身就是 Memory 召回逻辑的重要组成部分。
- 面试时更容易解释事务、索引、FTS5 和数据一致性。
- 避免为了“技术栈多”削弱 Agent 主线。

如果实现过程中原生 SQL 明显阻碍维护，再单独评估 SQLAlchemy，而不是预先引入。

---

## 10. 标识与版本规范

### 10.1 ID

- Repository、Revision、Run、Memory、Conversation、Message 使用 UUID4。
- Agent 现有 Run ID、Observation ID、Evidence ID 保持兼容。
- AST Symbol ID 保持稳定 Hash 规则。

### 10.2 Repository Identity

```text
repository_key = normalized_github_owner + "/" + normalized_repository_name
revision_key   = repository_key + ":" + full_commit_sha
```

- URL 去掉尾部 `.git` 和无意义斜杠。
- Commit SHA 保存完整 40 位。
- Branch 只是解析来源，不能替代 Commit。
- Fork 被视为不同 Repository。

### 10.3 Schema Version

SQLite 使用：

```sql
PRAGMA user_version;
```

每次 Schema 修改：

1. 新增顺序 Migration。
2. 在事务中执行。
3. 成功后更新 `user_version`。
4. 失败时回滚。
5. 测试从空库和上一版本升级。

### 10.4 Tool/Memory Version

Memory Entry 记录：

- `memory_schema_version`。
- `agent_prompt_version`。
- `parser_version`。
- `source_run_id`。

版本变化不会自动删除旧 Memory，但可以将不兼容记录标记 `needs_review`。

---

## 11. SQLite 数据模型

### 11.1 repositories

```text
repositories
├── id                 TEXT PK
├── normalized_url     TEXT UNIQUE NOT NULL
├── owner              TEXT NOT NULL
├── name               TEXT NOT NULL
├── default_branch     TEXT
├── created_at         TEXT NOT NULL
└── updated_at         TEXT NOT NULL
```

### 11.2 revisions

```text
revisions
├── id                 TEXT PK
├── repository_id      TEXT FK NOT NULL
├── commit_sha         TEXT NOT NULL
├── source_branch      TEXT
├── tree_fingerprint   TEXT
├── detected_stack     TEXT JSON
├── created_at         TEXT NOT NULL
└── UNIQUE(repository_id, commit_sha)
```

### 11.3 analysis_runs

```text
analysis_runs
├── id
├── revision_id
├── goal
├── final_status
├── model_name
├── llm_request_count
├── prompt_tokens
├── completion_tokens
├── total_tokens
├── tool_call_count
├── report_path
├── trace_path
├── started_at
└── ended_at
```

### 11.4 memory_entries

```text
memory_entries
├── id
├── repository_id
├── revision_id
├── source_run_id
├── memory_type
├── title
├── content
├── tags_json
├── symbol_names_json
├── paths_json
├── confidence
├── status
├── content_hash
├── coverage_json
├── memory_schema_version
├── created_at
└── updated_at
```

`status`：

```text
current
reusable
stale
invalid
superseded
needs_review
```

### 11.5 evidence

```text
evidence
├── id
├── memory_id
├── revision_id
├── observation_id
├── source_kind
├── resolution
├── path
├── start_line
├── start_col
├── end_line
├── end_col
├── content_hash
├── verified
└── created_at
```

### 11.6 exploration_episodes

```text
exploration_episodes
├── id
├── run_id
├── revision_id
├── goal
├── explored_paths_json
├── tools_used_json
├── confirmed_summary
├── rejected_hypotheses
├── unresolved_questions
├── coverage_notes
├── stop_reason
└── created_at
```

### 11.7 conversations

```text
conversations
├── id
├── repository_id
├── revision_id
├── title
├── summary
├── summarized_through_sequence
├── created_at
└── updated_at
```

Conversation 固定 Revision；切换 Commit 时新建 Conversation 或执行显式 Migration，不静默切换。

### 11.8 messages

```text
messages
├── id
├── conversation_id
├── sequence
├── role              user | assistant | system_event
├── content
├── answer_status
├── source_run_id
├── evidence_ids_json
├── token_usage_json
└── created_at
```

### 11.9 memory_usage

```text
memory_usage
├── id
├── run_id
├── memory_id
├── observation_id
├── usage_type        recalled | cited | rejected | refreshed
├── query
└── created_at
```

用于证明 Memory 是否真正改变 Agent 行为，而不是只存不用。

---

## 12. FTS5 索引设计

建立外部内容 FTS5 表：

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
    title,
    content,
    tags,
    symbol_names,
    paths,
    content='memory_entries',
    content_rowid='rowid',
    tokenize='unicode61'
);
```

### 12.1 索引内容

- `title`：短结论。
- `content`：有限摘要。
- `tags`：中英文概念、技术名、职责词。
- `symbol_names`：Qualified Name 和短名称。
- `paths`：完整 Path 和拆分后的目录词。

### 12.2 中文检索说明

SQLite `unicode61` 对无空格中文的分词能力有限。因此保存 Memory 时应生成少量显式中英文 Tags：

```text
登录 login auth authentication
签名 sign signature signer
入口 entry main cli application
数据库 database db repository session
```

Tags 由 Agent 在 `save_memory` 候选中提供，但必须：

- 限制数量和长度。
- 去重和规范化。
- 不作为 Evidence。
- 可以由确定性规则补充 Path/Symbol Token。

如果用户查询是完整中文短语，Search Tool 可以同时执行：

- FTS5 查询。
- `LIKE` 有界短语匹配。
- Symbol/Path 精确匹配。

### 12.3 排序

候选排序参考：

```text
score =
    FTS5 BM25
    + exact_symbol_bonus
    + exact_path_bonus
    + current_revision_bonus
    + verified_evidence_bonus
    + memory_type_bonus
```

排序只影响候选展示顺序，不判断核心模块或结论正确性。

### 12.4 无 FTS5 降级

启动时检查 SQLite 是否支持 FTS5：

- 支持：使用 FTS5 + 精确字段检索。
- 不支持：使用 Repository/Revision/Type 过滤 + 有界 `LIKE`。
- `doctor` 明确显示当前检索能力。
- 不因为 FTS5 缺失阻止基础 Memory 使用。

---

## 13. Memory 写入流程

### 13.1 写入来源

允许保存：

- Finish Gate 接受的 Finding。
- 已验证 Evidence。
- Tool Observation 生成的文件/符号事实摘要。
- Run 结束时生成的 Exploration Summary。
- Evidence 完整的 Q&A Answer。
- 有边界的 Negative Memory。

### 13.2 Candidate Memory

Agent 通过 `save_memory` 提交候选：

```json
{
  "memory_type": "symbol_finding",
  "title": "Signer.sign 负责签名",
  "content": "...",
  "tags": ["signer", "signature", "签名"],
  "symbol_names": ["Signer.sign"],
  "paths": ["src/itsdangerous/signer.py"],
  "evidence_ids": ["ev_123"]
}
```

### 13.3 Memory Validation Gate

写入 active Memory 前校验：

1. Repository 与 Revision 属于当前 Run。
2. Evidence ID 存在于当前或已验证历史 Observation。
3. SourceSpan 与原 Observation 完全匹配。
4. Resolution 与原 AST/Text Record 匹配。
5. `confirmed` 只使用可接受 Evidence。
6. Execution Flow 只能标记 `inferred`。
7. Content 不包含 Secret。
8. Content、Tag、Symbol、Path 数量不超预算。
9. 同 Content Hash 不重复保存。
10. Memory Type 与字段组合合法。

失败时返回普通 Tool Error Observation，Agent 可以修正后重试。

### 13.4 自动保存边界

Run 成功 Finish 后，Application 层可以机械地将已经通过 Gate 的结构化 Finding 写入 Memory，
因为这只是持久化已确认结果，不是生成新结论。

Application 层不得：

- 从 Report 文本自行抽取新 Finding。
- 重新判断核心模块。
- 给没有 Evidence 的摘要补造 Evidence。
- 将 rejected Finding 写成 active Memory。

---

## 14. Commit-aware Memory 生命周期

### 14.1 相同 Commit

- Evidence 可直接重新定位。
- 已验证 Finding 可作为 current Memory 返回。
- Agent 仍根据当前 Goal 决定是否足够。

### 14.2 新 Commit、文件 Hash 相同

- Memory 标记 `reusable`。
- Tool 返回旧 Revision 和 Hash 一致事实。
- Agent 可通过轻量验证将 Evidence 重新绑定当前 Revision。
- 未重新绑定前不能直接支撑当前 confirmed Finding。

### 14.3 新 Commit、文件改变

- 对应 Path 的 Memory 标记 `stale`。
- SourceSpan 不再可信。
- Agent 必须重新 Read/AST。
- 新 Evidence 通过后生成新 Memory，旧 Memory 保留审计记录。

### 14.4 文件删除

- Memory 标记 `invalid`。
- Tool Result 明确说明文件已不存在。
- Negative Memory 可记录删除事实，但仍绑定新 Revision。

### 14.5 未知变化

无法获取或验证 Content Hash 时：

- 保守标记 `needs_review`。
- 不支持 confirmed 结论。
- Agent 可决定重新 Clone/Read。

---

## 15. Memory Tools

### 15.1 `recall_memory`

用于结构化召回，不要求自由文本查询。

输入：

```json
{
  "memory_types": ["entry_point", "core_module"],
  "paths": [],
  "symbols": [],
  "statuses": ["current", "reusable"],
  "limit": 10
}
```

输出：

- Memory ID。
- Title/Content。
- Repository/Revision/Commit。
- Memory Type。
- Status/Freshness。
- Evidence 摘要。
- Coverage Notes。
- Source Run。
- 截断信息。

### 15.2 `search_memory`

用于 FTS5/关键词检索。

输入：

```json
{
  "query": "登录认证入口",
  "memory_types": [],
  "revision_scope": "current",
  "limit": 8
}
```

输出额外包含：

- Match Fields。
- BM25/Exact Match 信息。
- Query Terms。
- Candidate 声明。

搜索结果必须标记为 `candidate_memory`，直到 Agent 检查其中 Evidence。

### 15.3 `save_memory`

用于 Agent 主动提出值得跨会话保存的记忆。

约束：

- 只保存与 Repository Understanding 有关的内容。
- 必须给出 Memory Type。
- Finding 类型必须引用 Evidence。
- Exploration 类型可以没有源码 Evidence，但必须引用 Run/Observation，并且不能标 confirmed。
- Tool 调用经过 Memory Validation Gate。

### 15.4 `get_memory_detail`

为了控制首次召回体积，可选增加详情工具：

```text
recall/search → 返回短摘要和 Memory ID
get_memory_detail → 按 ID 返回完整 Evidence 和 Coverage
```

如果前三个 Tool 已能在预算内返回必要信息，则不增加第四个 Tool，避免 Registry 膨胀。

### 15.5 Tool Budget

新增：

```dotenv
REPOPILOT_MEMORY_MAX_RESULTS=10
REPOPILOT_MEMORY_MAX_RESULT_CHARS=12000
REPOPILOT_MEMORY_MAX_CALLS_PER_RUN=6
REPOPILOT_MEMORY_MAX_SAVES_PER_RUN=20
```

Memory Tool 计入总 Tool Call 预算，但可以单独统计。

---

## 16. Context Management

### 16.1 进入 Prompt 的内容

只保留：

- 当前 Goal/Question。
- 当前 Repository/Commit。
- 当前预算。
- 最近有限 Observation。
- 已确认 Finding 摘要。
- Agent 主动召回的有限 Memory Observation。
- Conversation Summary。
- 最近有限条 Message。

### 16.2 不自动进入 Prompt

- 全部历史 Analysis Run。
- 全部 Memory Entry。
- 全部旧 Message。
- 完整 Trace。
- 完整 AST Map。
- 整篇旧 Report。

### 16.3 Memory Catalog

Bootstrap 可以提供非常小的目录信息：

```text
Repository memory available:
- current revision memories: 18
- previous revision memories: 24
- conversations: 2
- memory types: entry_point, core_module, symbol_summary
```

Catalog 只告诉 Agent“有记忆可查”，不告诉它应该相信什么，也不返回完整内容。

### 16.4 Conversation Summary

达到 Message/字符阈值后：

1. 使用一次有界模型调用生成摘要候选。
2. 摘要保留用户目标、已回答问题、关键 Evidence ID 和未解决问题。
3. 不保存模型隐藏推理。
4. 新摘要覆盖 Conversation 的 Summary 字段。
5. 原 Message 继续存在 SQLite。
6. 摘要失败时退回确定性裁剪，不阻塞问答。

### 16.5 Context 预算

```text
System + Tool Schema
Repository Bootstrap
Conversation Summary
Recent Messages
Recalled Memory
Recent Tool Observations
Confirmed Findings
Finish Instructions
```

每块有独立字符上限，不能只依赖总字符截断。

---

## 17. Repository Q&A

### 17.1 CLI 入口

建议新增：

```bash
repopilot chat https://github.com/owner/repository
```

指定已有 Conversation：

```bash
repopilot chat --conversation CONVERSATION_ID
```

单次问题：

```bash
repopilot ask https://github.com/owner/repository \
  "如果修改登录逻辑应该看哪些文件？"
```

### 17.2 首次进入

1. 解析 Repository URL 和 Commit。
2. 查询是否存在相同 Revision。
3. 创建或选择 Conversation。
4. 向 Agent 提供 Memory Catalog。
5. Agent 决定 Recall、Search 或直接探索。

### 17.3 每轮问题

```text
User Question
  ↓
Question Goal
  ↓
Agent Decision
  ├── recall_memory
  ├── search_memory
  ├── code/AST tools
  └── finish answer
  ↓
Q&A Finish Gate
  ↓
Message + Evidence + 可选 Memory
```

### 17.4 回答状态

- `completed`：核心结论均有有效 Evidence。
- `partial`：只回答了部分问题或预算耗尽。
- `insufficient_evidence`：无法静态确认。
- `failed`：运行错误，无可靠答案。

### 17.5 指代与追问

Conversation Summary 保留必要实体：

```text
当前主题：登录认证流程
已讨论：AuthRouter → AuthService → UserRepository
当前 Commit：abc123...
未解决：Token 刷新逻辑是否复用相同 Service
```

用户问“那刷新 Token 呢”时，Agent 能恢复指代，但仍需通过 Memory 或代码工具取得 Evidence。

### 17.6 Revision 切换

当远端 Commit 变化：

- CLI 提示发现新 Revision。
- 用户可继续固定旧 Revision，或创建新 Conversation。
- 不在原 Conversation 中静默替换 Commit。
- 新 Conversation 可看到旧 Memory Catalog，但旧项标 historical/stale。

---

## 18. Agent State、Trace 与统计

### 18.1 AgentState 新增

```text
conversation_id
repository_id
revision_id
memory_calls
memory_results_seen
memory_entries_cited
memory_entries_saved
stale_memories_rejected
conversation_summary_chars
```

### 18.2 Trace 新增事件

- `memory_query`。
- `memory_observation`。
- `memory_rejected`。
- `memory_refreshed`。
- `memory_saved`。
- `conversation_summarized`。
- `revision_changed`。

### 18.3 Trace 体积控制

- Trace 只记录 Memory 结果摘要和 Memory ID。
- 完整 Memory 内容通过 SQLite 查询，不在每个 Step 重复复制。
- Cached Observation 记录原 Observation ID。
- 大型 AST Observation 继续执行现有截断。
- 不将数据库文件提交到 Git。

### 18.4 报告/回答统计

输出：

```text
Memory available: 18
Memory calls: 2
Memory candidates seen: 7
Memory entries cited: 3
Stale memories rejected: 1
New code tools called: 2
New memories saved: 2
```

这些数据用于证明长期记忆是否真正减少重复探索。

---

## 19. Persistence 接口

Domain/Application 层定义 Protocol：

```text
RepositoryMemoryStore
├── get_or_create_repository
├── get_or_create_revision
├── save_run
├── save_memory
├── get_memory
├── recall_memories
├── search_memories
├── update_memory_status
├── save_exploration_episode
└── record_memory_usage

ConversationStore
├── create_conversation
├── get_conversation
├── append_message
├── list_recent_messages
├── update_summary
└── list_conversations
```

实现：

- `SqliteRepositoryMemoryStore`。
- `SqliteConversationStore`。
- `InMemoryRepositoryMemoryStore`，用于单元测试。
- `NullRepositoryMemoryStore`，保持现有无 Memory CLI 兼容。

规则：

- Runtime 不直接执行 SQL。
- Tool 通过 `ToolContext` 获取 Memory Store。
- 数据库操作使用短事务。
- SQLite Connection 生命周期由 Application 管理。
- 测试使用临时文件或 `:memory:`。

---

## 20. SQLite 文件与并发

默认路径：

```text
.repopilot/memory.db
```

配置：

```dotenv
REPOPILOT_MEMORY_ENABLED=true
REPOPILOT_MEMORY_DATABASE=.repopilot/memory.db
REPOPILOT_MEMORY_FTS_ENABLED=true
REPOPILOT_MEMORY_MAX_RESULTS=10
REPOPILOT_MEMORY_MAX_RESULT_CHARS=12000
REPOPILOT_CONVERSATION_RECENT_MESSAGES=6
REPOPILOT_CONVERSATION_SUMMARY_TRIGGER_CHARS=20000
```

SQLite 设置：

- `PRAGMA foreign_keys = ON`。
- `PRAGMA journal_mode = WAL`。
- `PRAGMA busy_timeout` 有界设置。
- 每次写入使用显式事务。
- 单进程 CLI 是主要运行模式。
- 不承诺多 Worker 高并发。

数据库文件、WAL、SHM 和备份文件加入 `.gitignore`。

备份：

```bash
repopilot memory export --output repopilot-memory.json
repopilot memory import repopilot-memory.json
```

导入必须验证 Schema Version、Repository URL、Commit 和 Evidence，不接受任意数据库文件覆盖。

---

## 21. 错误与降级策略

| 场景 | 行为 |
|---|---|
| SQLite 不可写 | 当前 Run 降级为无长期记忆，并明确告警 |
| SQLite 损坏 | 停止 Memory 写入，代码分析仍可继续 |
| FTS5 不可用 | 降级精确过滤和有界 LIKE |
| Memory 无结果 | Agent 继续使用代码/AST Tool |
| Memory 超预算 | 截断并返回 Coverage Notes |
| Memory Evidence 缺失 | 标 invalid，不进入 Context |
| Commit 改变 | 标 stale/reusable，要求重新验证 |
| 保存重复 Memory | 返回已有 Memory ID |
| Conversation Summary 失败 | 使用最近消息和确定性裁剪 |
| Memory Tool 连续失败 | 触发现有错误阈值，但不破坏数据库 |
| Schema 版本过新 | 拒绝打开，避免旧代码破坏数据 |
| Migration 失败 | 事务回滚，保留原数据库 |

所有降级必须出现在 Observation、Trace 和回答限制说明中。

---

## 22. 安全要求

- 数据库不保存 API Key。
- Error、Trace、Memory Content 继续使用密钥脱敏。
- Repository Content 和历史 Memory 均视为不可信数据。
- Memory 不得包含新的 System Instruction。
- Memory Tool 只查询当前 Repository 范围。
- Path 继续使用 Repository 相对 POSIX 路径。
- 导入 JSON 有大小、字段数量和 Schema 校验。
- SQLite Path 禁止目录穿越到允许的数据目录外。
- Memory Content、Tags、Symbols 和 Paths 都有长度/数量限制。
- Conversation 输入继续受 Goal 长度限制。
- 不执行 Memory 中出现的命令。
- 数据库和导出文件默认加入 `.gitignore`。

Prompt 中明确分隔：

```text
SYSTEM POLICY
USER QUESTION
REPOSITORY FACTS
HISTORICAL MEMORY — UNTRUSTED DATA
TOOL OBSERVATIONS
```

---

## 23. 推荐目录结构

```text
src/repopilot/
├── agent/
│   ├── context.py                 # 增加有限 Memory Context
│   ├── runtime.py                 # 保持 Agent 决策中心
│   └── state.py                   # Memory 使用统计
├── application/
│   ├── analyze_repository_agent.py
│   ├── ask_repository.py
│   └── protocols.py
├── memory/
│   ├── __init__.py
│   ├── models.py                  # Memory/Conversation 契约
│   ├── database.py                # SQLite Connection / Migration
│   ├── repository.py              # Store 实现
│   ├── search.py                  # FTS5 + exact search
│   ├── validation.py              # Memory Gate
│   ├── lifecycle.py               # Commit freshness
│   ├── summarizer.py              # Conversation/Exploration Summary
│   └── export.py                  # 安全导入导出
├── tools/
│   ├── recall_memory.py
│   ├── search_memory.py
│   └── save_memory.py
└── cli.py                         # chat / ask / memory commands

tests/
├── fixtures/
│   └── versioned_python_repo/
├── unit/
│   ├── test_memory_database.py
│   ├── test_memory_search.py
│   ├── test_memory_validation.py
│   ├── test_memory_lifecycle.py
│   └── test_conversation_context.py
└── integration/
    ├── test_memory_agent_pipeline.py
    └── test_repository_qa.py
```

每个里程碑按需创建目录，不提前生成空模块。

---

## 24. 实施里程碑

### M1 — Memory Contracts 与 SQLite

交付：

- Repository/Revision/Run/Memory/Evidence/Conversation Pydantic Model。
- SQLite Connection Factory。
- Schema v1。
- Migration Runner。
- Repository Memory Store Protocol。
- SQLite/InMemory/Null Adapter。

完成条件：

- 从空库初始化成功。
- Foreign Key、Unique 和事务测试通过。
- 相同 Repository + Commit 不重复。
- Schema Migration 失败可回滚。
- 现有 CLI 在 Memory Disabled 时保持兼容。

### M2 — Memory Writer 与 Validation Gate

交付：

- Finding → Memory Entry 映射。
- Evidence 持久化。
- Exploration Episode。
- Content Hash 去重。
- Memory Validation Gate。
- Secret Redaction。

完成条件：

- Gate 接受的 Finding 可保存。
- Rejected Finding 不能进入 current Memory。
- AST Resolution 与原 Observation 一致。
- Execution Flow 保持 inferred。
- 重复运行不会产生重复 Memory。

### M3 — FTS5 与 Memory Tools

交付：

- FTS5 Schema 和同步逻辑。
- Exact/Symbol/Path/Tag Search。
- BM25 排序。
- `recall_memory`。
- `search_memory`。
- `save_memory`。
- Tool Budget 和 Trace。

完成条件：

- Agent 可自主选择 Memory Tool。
- FTS5 缺失可降级。
- 中文查询通过 Tags/短语匹配取得合理候选。
- Search Result 明确标 candidate。
- Memory Tool 不自动读取其他 Repository。

### M4 — Commit Lifecycle

交付：

- current/reusable/stale/invalid/needs_review 状态。
- Content Hash 比较。
- Revision Change Detection。
- Evidence Rebind 流程。
- 版本化 Repository Fixture。

完成条件：

- 相同 Commit 可安全复用。
- 文件不变的 Memory 可重新验证。
- 文件改变后旧 SourceSpan 不支持 confirmed。
- 文件删除后 Memory 变 invalid。
- 无法确认时保守 needs_review。

### M5 — Context 与 Conversation

交付：

- Conversation/Message Store。
- Memory Catalog。
- Conversation Summary。
- Recent Message Window。
- Memory Context Budget。
- Q&A Finish Gate。

完成条件：

- 多轮 Message 不无限进入 Prompt。
- Summary 保留实体、Evidence 和未解决问题。
- Agent 只看到主动召回的完整 Memory。
- 无 Evidence 回答进入 insufficient/partial。
- Conversation 固定 Revision。

### M6 — CLI Repository Q&A

交付：

- `repopilot chat`。
- `repopilot ask`。
- `repopilot memory list/show/stats`。
- `repopilot memory export/import`。
- Rich Evidence 展示。

完成条件：

- 用户可以连续提问。
- 第二轮能理解受控指代。
- Agent 能在 Recall 后继续探索源码。
- 回答显示 Path、Line、Commit 和 Confidence。
- 中断会话后可重新打开。

### M7 — Evaluation 与真实验收

交付：

- Fake Agent Memory 路线测试。
- 三类仓库问题集。
- 同 Commit 重复问答对比。
- 新 Commit 失效测试。
- Token/Tool/Latency 对比。
- `PHASE4_ACCEPTANCE.md`。

完成条件：

- Memory 确实减少重复 Tool 调用。
- 不同 Goal 产生不同 Memory 查询路线。
- Memory 不足时会继续探索。
- Stale Memory 不污染新回答。
- 关键回答 Evidence 覆盖率 100%。
- 至少一次真实多轮会话完整结束。

---

## 25. 测试策略

### 25.1 Unit Tests

- Repository URL/Revision Identity。
- SQLite Schema 初始化。
- Migration Upgrade/Rollback。
- Transaction Commit/Rollback。
- Memory Content Hash 去重。
- Memory Status Lifecycle。
- FTS5 Query Escaping。
- Exact Symbol/Path Match。
- BM25 排序。
- 无 FTS5 降级。
- Memory Validation Gate。
- Secret Redaction。
- Conversation Summary Window。
- Context Budget。

### 25.2 Integration Tests

- Fake Agent Finish 后自动保存 Memory。
- 新 Goal 下 Agent 主动 `recall_memory`。
- Recall 结果足够时减少 Code Tool。
- Recall 结果不足时继续 Search/Read/AST。
- Candidate Memory 无法直接支持 confirmed Finding。
- 相同 Commit 复用。
- 新 Commit 文件变化后重新验证。
- Conversation 关闭后重新打开。
- Memory DB 不可写时安全降级。

### 25.3 Agent-Centric 轨迹测试

场景 A：已有当前 Commit 的入口 Memory。

```text
Agent → recall_memory → 检查 Evidence → Finish
```

场景 B：只有旧 Commit Memory。

```text
Agent → search_memory → stale Observation → read_file/inspect_python → 新 Evidence → Finish
```

场景 C：Memory 与 Goal 无关。

```text
Agent → search_memory → no relevant result → search_code → read_file → Finish
```

场景 D：Memory 声称 resolved，但原 AST Record unresolved。

```text
Agent → save_memory → Gate Reject → 修正或放弃
```

这些测试必须验证“Observation 改变下一步决策”，不能只断言数据库里有记录。

### 25.4 真实仓库问题集

继续使用：

- `pallets/itsdangerous`。
- `encode/uvicorn`。
- `fastapi/full-stack-fastapi-template`。

每个仓库准备问题：

- 入口在哪里？
- 核心对象如何创建？
- 一次请求经过哪些模块？
- 某个核心功能在哪里实现？
- 如果修改某功能应该阅读哪些文件？
- 上一轮回答中的某个对象还负责什么？

真实 Provider 每个仓库最多进行一次有界会话，修复优先依赖 Fake Test，不连续盲目重跑。

---

## 26. Evaluation 指标

### 26.1 Memory 检索

| 指标 | 最低目标 |
|---|---:|
| Repository/Revision Filter 正确率 | 100% |
| Exact Symbol/Path Top-3 命中率 | ≥ 95% |
| FTS5/Tag Recall@5 | ≥ 80% |
| Stale Memory 被错误标 current | 0 |
| 无 Evidence Memory 被标 confirmed | 0 |

### 26.2 Agent 行为

| 指标 | 最低目标 |
|---|---:|
| 已有相关 Memory 时自主查询率 | ≥ 80% |
| 无关 Memory 后转向 Code Tool | 100% |
| Stale Memory 后重新验证 | 100% |
| 不同 Goal 产生不同 Tool 轨迹 | 100% 测试场景 |
| Memory 被 Runtime 自动全量注入 | 0 |

### 26.3 回答质量

| 指标 | 最低目标 |
|---|---:|
| 关键回答 Evidence 覆盖率 | 100% |
| Evidence 当前 Commit 有效率 | 100% |
| ambiguous/unresolved 错误提升 | 0 |
| 无法确认时明确降级 | 100% |
| Conversation 指代测试正确率 | ≥ 90% |

### 26.4 复用收益

同 Repository、Commit 和问题重复执行，对比：

- LLM Request 数量。
- Tool Call 数量。
- 新读取文件数量。
- Prompt Token。
- 完成耗时。
- Evidence 一致性。

目标不是完全不调用模型，而是在保持 Agent 决策和证据质量的前提下减少重复探索。

---

## 27. 推荐开发顺序

```text
1. Memory Pydantic Contracts
2. Repository / Revision Identity
3. SQLite Connection + Schema v1
4. Migration Runner
5. Store Protocol + InMemory Adapter
6. SQLite Repository Memory Store
7. Finding / Evidence Memory Writer
8. Memory Validation Gate
9. FTS5 Index + Exact Search
10. recall_memory
11. search_memory
12. save_memory
13. Tool Registry / ToolContext 集成
14. AgentState / Trace Memory 统计
15. Commit Status Lifecycle
16. Versioned Repository Fixture
17. Conversation / Message Store
18. Memory Catalog
19. Conversation Summary
20. Q&A Context Builder
21. Q&A Finish Gate
22. repopilot ask
23. repopilot chat
24. memory list/show/stats/export/import
25. Fake Agent 端到端轨迹
26. 三类仓库受控真实验收
27. PHASE4_ACCEPTANCE.md
```

不要先实现 Chat UI 再补 Memory Gate；应先保证保存和召回的数据可信。

---

## 28. 风险与应对

| 风险 | 应对 |
|---|---|
| 记忆只是保存旧报告 | 拆成结构化 Finding、Evidence、Exploration 和 Conversation |
| Memory 自动控制 Agent | 只通过显式 Tool Observation 提供 |
| FTS5 中文召回较弱 | 中英文 Tags、Path/Symbol Exact Match、短语 LIKE 降级 |
| Tag 变成固定核心算法 | Tag 只帮助候选检索，不产生架构判断 |
| 旧 Commit 污染 | Revision 强隔离 + Content Hash + Stale Gate |
| 错误 Finding 永久记住 | 只保存 Gate 通过项，支持 invalid/superseded |
| Context 因 Memory 再次爆炸 | Catalog + Tool 查询 + 结果/字符/调用预算 |
| SQLite 并发限制 | Phase 4 明确单进程 CLI，不做多 Worker |
| Trace 和 DB 重复膨胀 | Trace 记录 Memory ID，内容只保存一份 |
| Conversation Summary 丢细节 | 保留原 Message，Summary 引用 Evidence ID |
| Agent 为省事盲信 Memory | Prompt + Gate 要求检查 Revision 和 Evidence |
| Memory Tool 增加模型费用 | Catalog 极小、结果有界、对比复用收益 |
| 技术栈太少显得简单 | 强调 Agent Memory、FTS5、Context、Commit 失效和 Evaluation 深度 |

---

## 29. Definition of Done

- [x] Phase 1–3 的全部自动化测试继续通过。
- [x] Memory Disabled 时现有 CLI 行为不变。
- [x] SQLite Schema 可从空库初始化。
- [x] Schema Migration 失败可回滚。
- [x] Repository 与 Revision 按 URL + Commit 正确去重。
- [x] Memory Entry、Evidence、Exploration 和 Conversation 可持久化。
- [x] 数据库不保存 API Key、隐藏推理或完整源码。
- [x] 只有通过 Validation Gate 的 Finding 可进入 current Memory。
- [x] Memory Evidence 可回溯到 Revision、Observation、Path 和 SourceSpan。
- [x] AST Evidence Resolution 与原 Record 一致。
- [x] Execution Flow Memory 只能标 inferred。
- [x] FTS5 可检索 Title、Content、Tag、Symbol 和 Path。
- [x] 无 FTS5 时有明确降级。
- [x] 中文查询可通过 Tag/短语/字段检索合理召回。
- [x] `recall_memory` 可独立调用。
- [x] `search_memory` 可独立调用。
- [x] `save_memory` 会拒绝无效候选。
- [x] Memory Tool 已加入统一 Registry 和 ToolContext。
- [x] Agent 自己决定是否查询 Memory。
- [x] Runtime 不自动注入全部 Memory。
- [x] Memory Tool 遵守调用、结果和字符预算。
- [x] 相同 Commit Memory 可安全复用。
- [x] 新 Commit 文件变化会使旧 Memory stale。
- [x] Stale Memory 不支持当前 confirmed Finding。
- [x] 文件未变化的 Memory 有显式重新绑定流程。
- [x] Conversation 固定 Repository Revision。
- [x] Conversation Summary 不保存隐藏推理。
- [x] 最近 Message 和 Summary 有独立 Context 预算。
- [x] `repopilot ask` 可完成单次证据化问答。
- [x] `repopilot chat` 可恢复多轮会话。
- [x] 追问中的受控指代可以解析。
- [x] Memory 不足时 Agent 会继续调用 Code/AST Tool。
- [x] 回答展示 Commit、Path、SourceSpan 和 Confidence。
- [x] Trace 可统计 recalled/cited/rejected/refreshed/saved Memory。
- [x] 数据库损坏或不可写时安全降级。
- [x] Memory Export/Import 有 Schema、范围和 Secret 校验。
- [ ] Exact Symbol/Path 与 FTS5 指标达到第 26 节目标。
- [x] 关键回答 Evidence 覆盖率 100%。
- [x] ambiguous/unresolved 被错误提升次数为 0。
- [ ] 同 Commit 重复问题的 Tool/Token 使用量有可测下降。
- [ ] 三类真实仓库 Memory/Q&A Smoke Test 完成。
- [ ] 至少一次真实多轮会话状态为 completed。
- [x] Ruff、Mypy、Pytest 和 Coverage 通过。
- [x] `PHASE4_ACCEPTANCE.md` 如实记录通过与未通过项。

---

## 30. Phase 4 完成后的评审问题

进入后续阶段前必须回答：

1. 长期记忆是否保存结构化仓库知识，而不是只保存上一份 Markdown 报告？
2. 删除 LLM 后，系统是否只能查询 Memory，不能生成新的架构结论？
3. Agent 是否自主决定调用 Memory Tool 或代码工具？
4. Runtime 是否没有固定“先查数据库再总结”的流程？
5. 全部历史 Memory 是否不会被自动塞入 Prompt？
6. Memory 是否绑定 Repository 和完整 Commit SHA？
7. 新 Commit 是否会触发 stale/reusable/invalid 判断？
8. 旧 SourceSpan 是否不会直接支持新 Commit 的 confirmed Finding？
9. FTS5/BM25 是否只排序候选，而不充当 Evidence？
10. Memory Finding 是否可以追溯到原 Run、Observation 和 Evidence？
11. 没有 Evidence 的聊天回答是否不会进入 confirmed Memory？
12. Agent 在 Memory 不足时是否继续自主探索源码？
13. 不同 Goal 是否产生不同 Memory/Code Tool 轨迹？
14. Conversation Summary 是否控制 Context，同时保留原 Message 供审计？
15. Memory 是否确实降低了重复 Tool Call 或 Token，而不是增加额外开销？
16. SQLite、FTS5 和 Context Manager 是否都直接服务于 Agent 能力？
17. 项目是否没有为了技术栈数量加入与目标无关的后端组件？
18. 所有具体代码回答是否仍然 Evidence-grounded？

如果第 1、2、3、4、5、6、8、9、12、13、18 项不能明确回答“是”，Phase 4 不得标记完成。

---

## 31. 简历与面试展示

完成后可以准确描述为：

> 为 GitHub Repository Analysis Agent 设计跨会话长期记忆，使用 SQLite + FTS5 持久化并召回
> Repository Finding、AST Symbol、Evidence 和 Exploration Episode；实现 Commit-aware Memory
> Invalidation、Memory Tool、Conversation Summary 与 Evidence-grounded 多轮 Q&A，在保证 Agent
> 自主决策的同时减少重复代码探索和上下文成本。

演示路径：

```text
1. 首次分析陌生仓库，Agent 自主读取代码并保存 verified Memory
2. 退出程序后重新进入，证明 Memory 跨进程存在
3. 提问“入口在哪里”，Agent 主动 recall_memory 并引用旧 Evidence
4. 提问新问题，Memory 不足，Agent 转向 Search/Read/AST
5. 展示新 Finding 被保存为 Memory
6. 切换到新 Commit，旧 Memory 变 stale
7. Agent 重新读取变化文件并刷新 Evidence
8. 展示 Tool Call、Token 和 Context 对比
```

这条路径可以集中展示：

- Agent 自主决策。
- Tool Use。
- Working/Episodic/Semantic Memory。
- Context Engineering。
- SQLite/FTS5 检索。
- Commit-aware Cache Invalidation。
- Evidence Grounding。
- 多轮 Repository Q&A。
- 可测量的成本优化。

这里的 `Semantic Memory` 指“保存的是仓库语义结论”，不表示必须使用向量 Embedding。
