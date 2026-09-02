# RepoPilot Phase 4 验收记录

## 1. 验收结论

Phase 4 的 Agent Memory 工程实现已完成，Definition of Done 当前为 **40/44**。

本阶段已经具备 SQLite/FTS5 长期 Repository Memory、Commit-aware 生命周期、显式 Memory
Tool、Conversation Context、证据化 `ask/chat` 和 Memory 管理 CLI。Memory 仍是 Agent 可选用的
Observation 来源，不会替代 Agent 决策，也不会自动把历史内容注入 Context。

本轮没有调用真实付费模型。自动化验收使用 Fake Agent，能够验证完整的 Action → Tool →
Observation → 下一步决策 → Finish Gate 路径，同时避免产生额外模型费用。

## 2. 已实现能力

- SQLite Schema v1：Repository、Revision、Run、Memory、Evidence、Exploration、Conversation、
  Message 和 Memory Usage。
- FTS5 检索 Title、Content、Tag、Symbol 和 Path；FTS5 不可用时降级为字段 LIKE 查询。
- `recall_memory`、`search_memory`、`save_memory` 已进入统一 Tool Registry。
- Finding 保存前复用 Evidence/Finish Gate；无证据、错误行号和不匹配 Resolution 会被拒绝。
- Memory 绑定 Repository 与 Commit；跨 Commit 数据分类为 reusable、stale 或 invalid。
- reusable Memory 必须显式校验当前文件 Content Hash，才能支持 confirmed Finding。
- Context 只自动加入小型 Memory Catalog；具体内容必须由 Agent 主动调用工具获取。
- Memory 无结果时，Agent 可继续选择 Read/Search/AST 工具探索源码。
- Conversation 保存原始 Message，并使用确定性、有界摘要控制 Context，不保存隐藏推理。
- Trace 统计 recalled、cited、rejected、refreshed 和 saved Memory；引用关系写入 usage 表。
- 普通分析遇到 Memory 数据库故障时关闭 Memory 并继续；`ask/chat` 要求 Memory 可用并明确报错。
- Memory JSON Export/Import 具有版本、大小、表范围与 Secret 校验。

## 3. 自动化验收结果

执行命令：

```bash
python -m ruff format src tests
python -m ruff check src tests
python -m mypy src
python -m pytest --cov=repopilot --cov-report=term --cov-fail-under=85
```

结果：

```text
Ruff passed
Mypy passed: 66 source files
Pytest: 103 passed
Coverage: 88.36%（要求 >= 85%）
```

另外在全新临时虚拟环境中完成 `pip install -e ".[dev]"`，并验证：

```text
repopilot --help             passed
repopilot memory stats       passed
SQLite FTS5                  enabled
```

临时虚拟环境和临时 Memory 数据库已在验收后删除。

## 4. Agent 中心性验收

Fake Agent 端到端覆盖了两条不同轨迹：

```text
Goal → Agent → recall_memory → Observation → Agent → Finish
Goal → Agent → search_memory(0 results) → Agent → read_file → Observation → Agent → Finish
```

这证明 Runtime 没有固化为“先查 Memory，再由 LLM 总结”的流水线。Memory 只提供候选事实；
查询时机、Memory 是否足够以及是否继续读取源码，都由 Agent 根据 Goal 和 Observation 决定。

## 5. 安全与一致性验收

- Schema 初始化失败会回滚，不留下部分表。
- 新于程序支持版本的 Schema 会被拒绝。
- API Key 形态和显式配置的 Secret 在持久化/导出前脱敏。
- current Memory 必须具有已验证 Evidence；stale/invalid Memory 不能支持最终 confirmed Finding。
- AST ambiguous/unresolved Evidence 不能被提升为 confirmed Finding。
- Memory 结果、字符数、调用次数和单次保存数均有预算。

## 6. 尚未完成的四项

- Exact Symbol/Path 与 FTS5 检索指标尚未按方案第 26 节量化。
- 同 Commit 重复问题的 Tool Call/Token 下降尚未形成真实模型对照数据。
- 尚未完成三类真实公开仓库的 Memory/Q&A Smoke Test。
- 尚未完成一次真实 Provider 的多轮会话 completed 验收。

这些项目依赖真实仓库样本或付费模型调用，因此没有用 Fake Agent 结果冒充真实验收。工程功能可用于
Demo；如果需要宣称真实场景的召回收益和成本下降，仍需完成上述四项。

## 7. 费用说明

本次整改和验收没有调用 MiniMax、硅基流动或其他远程 LLM API，因此新增模型费用为 0。
