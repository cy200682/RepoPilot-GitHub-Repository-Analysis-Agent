# RepoPilot Phase 2 验收记录

## 1. 验收结论

Phase 2 的 Agent 主链路已经完成：模型根据 Goal 与 Observation 逐轮选择只读工具，Runtime 只负责协议校验、执行、预算、恢复、Trace 和 Finish Gate，不包含固定关键文件算法。

自动化测试、三类真实仓库 Smoke Test 和人工抽查均通过。关键结论结构化整改后，又使用完整 Observation Trace 对固定 `itsdangerous` commit 完成真实模型回归，Finding 与 Evidence 的逐条引用校验通过。

## 2. 验收环境

- 日期：2026-09-01
- Python：3.13.3（项目最低要求为 3.11）
- 模型：deepseek-ai/DeepSeek-V4-Pro
- OpenAI-compatible Base URL：https://api.siliconflow.cn/v1
- Agent 最大工具调用：18
- 连续错误上限：3
- 相同 Action 上限：2
- 累计读取字符上限：200000
- Agent Context 字符预算：80000
- API Key：仅从本地 .env 读取，未写入本文、报告或 Trace

## 3. 自动化验证

| 检查项 | 结果 |
| --- | --- |
| pytest | 67 passed |
| 覆盖率 | 89% |
| Ruff | passed |
| mypy strict | passed（45 个源码文件） |
| git diff --check | passed，仅有 Git 的 LF/CRLF 提示 |
| 干净虚拟环境安装 | passed |
| 干净环境测试 | 67 passed |
| CLI 安装入口 | passed |

测试覆盖以下关键行为：

- Tool Action → Observation → 下一轮 Decision → Finish 的垂直闭环。
- 未注册工具返回错误 Observation，Agent 可改用合法工具后完成。
- 重复 Action 被拒绝且不会无限循环。
- 无探索或无证据的 Finish 被拒绝。
- 任意一条无效 Evidence 都会导致 Finish 被拒绝。
- 同一仓库面对不同 Goal 可以产生不同工具 Action。
- 最近 Observation 在 Context 截断时仍被保留。
- Trace 导出完整 Observation、Evidence Location 和截断信息。
- Registry 不存在 Shell 工具，仓库外路径与忽略目录不可访问。
- Agent Prompt 明确将 README、源码和注释视为不可信数据。
- Agent 失败状态对应 CLI 退出码 8，不再错误返回 0。

## 4. 真实仓库 Smoke Test

### 4.1 Python Library

- Repository：pallets/itsdangerous
- Commit：672971d66a2ef9f85151e53283113f33d642dabd
- Goal：分析公开入口、核心模块和主要调用流程
- 结果：completed
- 迭代：11
- Tool calls：10
- 读取文件：7
- Evidence：10 verified / 0 unverified
- 轨迹摘要：__init__.py → signer.py → serializer.py → timed.py / url_safe.py → encoding.py / _json.py
- 入口判断：正确识别为库的公开导入入口，而非虚构可执行入口

### 4.2 CLI Application

- Repository：encode/uvicorn
- Commit：eed8e7212a60681a9c3c865305cdd227a2b16f90
- Goal：追踪 CLI 参数解析到服务器启动
- 结果：completed
- 迭代：13
- Tool calls：11
- 读取文件：3
- Search：2
- Evidence：5 verified / 0 unverified
- 轨迹摘要：__main__.py → main.py → search_code / find_symbol → server.py
- 恢复验证：第一次 Finish 含越界一行的 Evidence，被收紧后的 Finish Gate 拒绝；Agent 修正后第二次 Finish 通过

### 4.3 FastAPI / Web Application

- Repository：fastapi/full-stack-fastapi-template
- Commit：486f054cc8d1aead59ec96cc0a16933d06c10e0d
- Goal：追踪 FastAPI 入口、路由注册和请求到数据库层
- 结果：completed
- 迭代：12
- Tool calls：11
- 读取文件：6
- Evidence：5 verified / 0 unverified
- 轨迹摘要：backend/app/main.py → api/main.py → routes/items.py → deps.py → core/db.py → models.py
- 大仓库行为：初始目录信息被截断，但 Agent 根据 Goal 收敛到 backend，没有读取整个仓库

## 5. Golden 人工抽查

样本量为三个固定 commit，适合作为 Phase 2 工程验收基线，不代表统计学意义上的通用准确率。

| 指标 | 结果 | Phase 2 目标 |
| --- | ---: | ---: |
| Agent Run 成功率 | 3/3（100%） | ≥ 90% |
| 入口判断准确率 | 3/3（100%） | ≥ 85% |
| 核心模块覆盖 | 3/3 达到人工标注主要模块 | ≥ 80% |
| Evidence 路径/范围有效率 | 20/20（100%） | ≥ 95% |
| 严重无依据架构结论 | 0 | 0 |
| 无限循环或预算越界 | 0 | 0 |
| 三类仓库轨迹不同 | 3/3 | 100% |

人工抽查只将源码证据可支持的入口、模块和执行路径计为命中。潜在工程问题仍属于模型分析意见，不能与已验证的执行路径结论等同。

## 6. Agent-Centric 审计

- 删除 LLM 后，系统只剩 Scanner 和只读事实工具，无法自主决定关键文件或完成语义报告。
- Scanner 只产生初始仓库事实，不产生固定阅读队列。
- Runtime 不识别框架入口，也不维护“关键文件评分”。
- Tool Registry 只校验和执行模型选择的 Action。
- 三类仓库使用了不同文件序列；CLI 场景还动态使用 search_code 和 find_symbol。
- 错误、空结果、重复动作和 Finish 拒绝都会成为下一轮 Observation。
- Phase 2 的 find_symbol 明确标记为文本候选，不声称具备 AST 精度。
- Phase 3 可替换 Tool Handler 或新增 AST 工具，无需重写 Agent Runtime。

## 7. 已知限制

1. search_code 当前使用受控 Python 实现。以 rg 参数数组调用并保留 Python fallback 的性能优化尚未实现；这不影响 Phase 2 功能闭环，但大型仓库搜索性能仍有优化空间。
2. Golden 样本仍较少，后续应固定更多 commit 并引入可重复的自动评分。
3. Finish Gate 可以验证引用完整性和源码范围，无法确定 Evidence 与自然语言 claim 在语义上是否完全一致，仍需模型评测与人工抽查。
4. AST、精确符号关系、调用图和 Repository Map 仍属于 Phase 3。

## 8. 关键结论 Evidence 整改（2026-09-01）

第 30 节评审发现：旧 Finish Gate 只能保证提交的 Evidence 引用有效，不能保证报告中的每条关键结论都绑定 Evidence。本轮完成以下整改：

- 新增结构化 `AgentFinding`：`claim + confidence + evidence_ids`。
- `entrypoints`、`core_modules`、`execution_flows`、`module_relationships` 不再接受裸字符串。
- 每条 `AgentEvidence` 必须带唯一 `evidence_id`。
- Finish Gate 拒绝无 Finding、Finding 无 Evidence、未知 Evidence ID、未验证 Evidence、重复 Evidence ID 和倒置行号范围。
- Prompt 与 Context 明确要求 `confirmed`、`inferred`、`candidate` Finding 都必须引用观察证据。
- Report Renderer 直接从结构化 Finding 渲染关键章节并展示 Evidence ID。
- 新增 Provider JSON 解析、逐 Finding 校验、重复 ID、未知 ID、空引用、倒置行号、渲染及错误脱敏测试。

当前自动化结果为 67 tests passed、覆盖率 89%、Ruff passed、Mypy strict passed、干净环境 67 tests passed。

真实仓库新 Schema 回归已通过：

- Provider：SiliconFlow
- Model：`deepseek-ai/DeepSeek-V4-Pro`
- Repository：`pallets/itsdangerous`
- Commit：`672971d66a2ef9f85151e53283113f33d642dabd`
- Status：completed
- Steps：13
- Tool Actions：11
- Finish：2 次尝试，第一次被 Gate 拒绝后修正
- Findings：17
- Finding → Evidence 引用：28
- Evidence：10 verified / 0 unverified
- 缺失引用：0
- 无 Evidence Finding：0

第 30 节第 5 项现可回答“是”，Phase 3 门禁解除。
