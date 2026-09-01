# RepoPilot Phase 3 验收记录

## 当前结论

截至 2026-09-01，Phase 3 的 M1–M6 已完成，M7 尚未通过，因此第三阶段当前状态为：

> 工程实现完成，真实 Provider 与 Golden Evaluation 验收未完成。

不得将当前状态标记为 Phase 3 全部完成。

## 已完成范围

- Python AST 数据契约、稳定 ID 与 SourceSpan。
- 单文件安全 AST Parser，不 Import、不执行目标仓库代码。
- Module Index、受限 Resolver、Lazy Code Index 与缓存。
- 增量 Repository Map，以及 Node、Edge、文件和结果预算。
- `inspect_python`、AST 增强 `find_symbol`、`find_references`、`get_relationships`。
- 默认 Tool Registry 与每次 Agent Run 独立的 ToolContext 集成。
- AgentState 中的 AST、Map、Reference 与 Relationship 统计。
- Agent Runtime 所有的累计 AST 预算。
- 有界 AST Observation 上下文压缩，不向 Prompt 注入完整 Repository Map。
- AgentEvidence `source_kind`、`resolution` 与 Finish Gate 校验。
- 报告中的 AST/Map 探索统计与 Evidence 元数据。
- Fake Agent 根据 AST Observation 改变下一步 Action 的端到端测试。

## 自动化质量结果

```text
pytest: 83 passed
coverage: 90.04%（门槛 85%）
ruff: passed
mypy src: passed
clean editable install: passed
clean environment CLI startup: passed
```

Phase 1 Bootstrap 与 Phase 2 Read/Search/Agent/Finding 回归均包含在上述测试中。

## 成本控制整改

真实回归暴露成本问题后，默认运行预算已调整为：

- 12 次模型决策、10 次 Tool 调用。
- 8 万累计 Token 硬断路器。
- 4 万字符 Agent Context。
- 单次 AST Tool 最多返回 60 条事实。
- 最多解析 30 个 AST 文件，每个候选型 Tool 最多新增 10 个文件。
- Provider Usage 写入 State、Trace 与报告；缺失时使用保守估算。
- CLI 支持 `--max-total-tokens` 单次覆盖。

## 真实仓库回归

目标仓库：`pallets/itsdangerous`

固定 Commit：`672971d66a2ef9f85151e53283113f33d642dabd`

### 回归 1

- 状态：`budget_exhausted`
- Trace：`reports/itsdangerous-phase3-trace.json`
- 发现：模型把 `get_tree` 目录结果错误声明为 `map_query` 行号 Evidence。
- Gate 行为：正确拒绝。
- 整改：明确 `get_tree` 仅用于导航；增加 Evidence 来源不匹配的明确拒绝原因。

### 回归 2

- 状态：`budget_exhausted`
- Trace：`reports/itsdangerous-phase3-accepted-trace.json`
- 发现：大型 AST Observation 占用近期上下文，模型重复探索并在最后一轮提交缺少
  `evidence_ids` 的 Finding。
- Gate 行为：正确拒绝。
- 整改：压缩近期 AST Observation、前置 Finish 规则、规范化列表型 Action 指纹。

### 回归 3

- 状态：`budget_exhausted`
- Trace：`reports/itsdangerous-phase3-accepted-v2-trace.json`
- 有效 Evidence：19/20。
- Agent 自主解析：`signer.py`、`serializer.py`、`timed.py`、`url_safe.py`。
- Agent 自主调用：Read、Search、Inspect、Get Relationships。
- 发现：模型把多个离散 Map Span 合并为一个宽泛范围。
- Gate 行为：正确拒绝该 Evidence 及其依赖 Finding。
- 整改：明确禁止合并离散 SourceSpan，并要求至少预留两轮 Finish 修正空间。

### 回归 4

- 状态：`failed`
- Trace：`reports/itsdangerous-phase3-final-trace.json`
- 已完成 9 次有效 Tool Action 后，Provider 返回 HTTP 402：账户余额不足。
- 未在 Trace、报告或本文中记录 API Key。

### 回归 5（MiniMax 低预算）

- Provider：MiniMax 国内 OpenAI-compatible API，模型 `MiniMax-M2.7`。
- 状态：`budget_exhausted`。
- Trace：`reports/itsdangerous-phase3-minimax-trace.json`。
- 硬限制：8 轮、40,000 Token；没有自动重跑。
- 实际：7 次请求，45,411 Token；单次请求可能越过累计断路器，因此最终略超上限。
- 发现：模型连续读取源码而未调用 AST Tool；一轮响应不符合纯 JSON 解析器。
- 整改：首轮后移除重复 README、压缩 Bootstrap Tree；Goal 明确要求 AST 时提示优先
  使用 AST Tool；兼容 MiniMax 思考文本包裹的最终 JSON 对象。
- 整改验证：仅运行本地 Fake/单元测试，没有继续发起真实生成请求。

### 回归 6（MiniMax Phase 3 受控真实验收）

- Provider：MiniMax 国内 OpenAI-compatible API，模型 `MiniMax-M2.7`。
- 状态：`budget_exhausted`，未生成被 Finish Gate 接受的最终报告。
- 报告：`reports/itsdangerous-phase3-minimax-final.md`。
- Trace：`reports/itsdangerous-phase3-minimax-final-trace.json`。
- 硬限制：10 轮、70,000 Token；仅执行一次，没有自动重跑。
- 实际：7 次模型请求，71,512 Prompt Token、5,511 Completion Token，合计
  77,023 Token。单次请求结束后才可核算 Provider Usage，因此最后一次请求越过累计上限。
- Agent 自主调用 `inspect_python` 分析 `__init__.py`、`signer.py` 和
  `serializer.py`；共访问 2,491 个 AST 节点，增量 Map 达到 40 个节点、1,109 条边。
- 第 3 轮主动提交 Finish，但 Gate 正确拒绝缺失或未验证的 Evidence；之后继续探索。
- 另有一轮模型响应不符合 `AgentDecision` 契约；最终没有预留出可完成修正的轮次与预算。
- 本轮暴露并完成两项本地 Gate 加固：AST Evidence 声明的 `resolution` 必须与精确
  SourceSpan 对应的原始 AST Record 一致；`execution_flows` Finding 即使引用 resolved
  静态 Call，也只能标记为 `inferred`，不得夸大为运行时必然执行。
- 加固后只运行本地测试，没有再次调用真实模型。

## Agent-Centric 审查

已确认：

1. Scanner 后没有无条件全仓库 AST 解析。
2. AST 文件由模型根据 Goal 与 Observation 通过 Tool Action 选择。
3. Repository Map 只包含当前已探索文件，不计算核心模块评分或固定关键路径。
4. 删除 LLM 后，确定性模块只剩事实解析与查询能力，不能生成架构结论。
5. Finish Gate 能拒绝来源不匹配、范围无效、缺少 Evidence、模型篡改 AST resolution，
   以及 unresolved 支撑的 confirmed Finding；静态调用链只能形成 inferred 执行流程。
6. Fake Agent 测试证明 AST Observation 可以改变下一步探索路线。

尚未确认：

1. 三类真实仓库 Smoke Test。
2. 三类仓库的人工标注与 Golden 指标。
3. 至少一次真实 Provider 运行以 `completed` 结束。
4. Phase 2 与 Phase 3 的完整报告质量对比。

## 恢复验收步骤

继续真实验收时执行：

```bash
repopilot analyze https://github.com/pallets/itsdangerous \
  --output reports/itsdangerous-phase3-final.md \
  --trace-output reports/itsdangerous-phase3-final-trace.json \
  --goal "定位公开 API、核心签名/验签流程，并使用 AST 追踪关键符号与静态调用关系" \
  --max-iterations 10 \
  --max-total-tokens 70000
```

随后继续对 CLI Application 与 FastAPI/Web 仓库执行 Smoke Test，并填写 Golden 指标。

## 完成判定

只有以下条件全部满足后，才能把 Phase 3 标记为完成：

- 至少一次真实 `itsdangerous` 回归状态为 `completed`。
- 三类真实仓库 Smoke Test 通过。
- Golden Evaluation 达到 `PHASE3_IMPLEMENTATION_PLAN.md` 第 24 节最低指标。
- 所有关键 Finding 的 Evidence 验证率为 100%。
- 不存在 ambiguous/unresolved Evidence 被提升为 confirmed 的情况。
