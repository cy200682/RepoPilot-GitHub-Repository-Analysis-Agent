# RepoPilot Phase 1 — MVP 执行方案

## 1. 阶段目标

Phase 1 的目标是完成一个可靠、可测试的最小闭环：

```text
公开 GitHub URL
    ↓
安全 Clone
    ↓
基础 Repository Scan
    ↓
构造受限分析上下文
    ↓
调用 OpenAI-compatible LLM
    ↓
生成 Markdown 基础报告
```

用户最终可以执行：

```bash
repopilot analyze https://github.com/owner/repository
```

并获得包含项目简介、技术栈、项目目录、入口候选、核心模块候选和证据位置的基础报告。

Phase 1 首先证明三件事：

1. RepoPilot 能稳定处理真实公开仓库，而不只是读取本地示例。
2. 输入给 LLM 的上下文经过筛选和限制，不会无界读取整个仓库。
3. Phase 1 的 Scanner、Reader 和 LLM Client 可以在 Phase 2 被 Agent 直接复用和调度。

---

## 2. 阶段定位

Phase 1 是一个有意保持简单的 **Bootstrap Pipeline**，不是最终 Agent 架构。

这一阶段允许使用固定执行顺序来验证端到端产品闭环，但必须遵守以下约束：

- Scanner 只产生仓库事实，不直接断言核心架构。
- 入口和核心模块只能作为候选结果输出。
- LLM 输入和输出通过独立接口封装。
- 读取、扫描和配置解析能力不能写死在 CLI 中。
- 每个能力后续都能注册为 Phase 2 Tool。
- 不将固定 Pipeline 描述成 Agent，也不以 Phase 1 结果证明自主探索能力。

Phase 2 将把固定调度权替换为 Agent 决策：

```text
Phase 1：Application Service → 固定调用各能力
Phase 2：Agent Runtime → 根据 Goal 和 Observation 按需调用各能力
```

---

## 3. 范围

### 3.1 本阶段实现

- Python 3.11+ 项目骨架。
- Typer CLI。
- GitHub HTTPS URL 校验。
- 公开仓库浅克隆。
- 临时工作目录和任务目录管理。
- 目录过滤、文件分类和基础统计。
- README 和常见配置文件读取。
- Python 项目的基础技术栈识别。
- 受 Token/字符预算约束的 LLM 输入构建。
- OpenAI-compatible LLM Client。
- 结构化分析结果校验。
- Markdown 报告生成和保存。
- 单元测试、集成测试和一个真实仓库 Smoke Test。
- 清晰错误提示和最小日志。

### 3.2 本阶段不实现

- Agent Loop。
- Tool Registry。
- AST 分析。
- Repository Map。
- 自主多轮文件探索。
- Repository Q&A。
- FastAPI 和 Web UI。
- SQLite 会话存储。
- Git 历史分析。
- Semantic Search 或向量数据库。
- 目标仓库代码执行和依赖安装。

---

## 4. 成功标准

Phase 1 完成后，应满足：

```text
给定有效公开 GitHub URL
    ↓
在限制范围内完成 Clone 和 Scan
    ↓
生成结构合法的分析请求
    ↓
成功调用配置的 LLM
    ↓
将结果写为可读 Markdown 报告
```

最低验收门槛：

| 项目 | 验收要求 |
| --- | --- |
| CLI | `repopilot analyze <url>` 可运行并返回正确退出码 |
| Clone | 支持标准公开 GitHub HTTPS URL 和可选 `.git` 后缀 |
| Scan | 默认排除无关目录，对文件数、深度和大小设限 |
| Context | 不无界读取仓库；输入内容和截断情况可追踪 |
| LLM | API 地址、Key、模型可配置，错误不会泄露密钥 |
| Report | 包含基础固定章节，并标记候选结论和证据来源 |
| Tests | 核心模块有单元测试，主流程有集成测试 |
| Safety | 不执行仓库代码、不安装仓库依赖、不跟随逃逸符号链接 |

---

## 5. 核心技术决策

### 5.1 CLI First

Phase 1 只实现 CLI。FastAPI 和 Web UI 延后到 Phase 4，避免同时维护两套入口。

CLI 第一版命令：

```bash
repopilot analyze <github_url> [--output REPORT.md] [--keep-repo]
```

建议附加诊断命令：

```bash
repopilot doctor
```

`doctor` 只检查本地 Git、LLM 配置和输出目录，不访问或修改目标仓库。

### 5.2 使用浅克隆

默认只获取目标仓库默认分支的最新状态：

```text
depth = 1
single branch = true
submodules = false
```

Phase 1 不需要完整 Git History。报告必须记录最终 Commit SHA，保证分析结果可定位。

### 5.3 默认不执行目标仓库代码

RepoPilot 只读取文本文件和 Git 元数据：

- 不运行安装脚本。
- 不执行 `setup.py`、`Makefile` 或项目命令。
- 不导入目标仓库 Python 模块。
- 不安装目标仓库依赖。
- 不初始化 Git Submodule。

### 5.4 LLM Provider 隔离

业务代码只依赖自定义 `LLMClient` Protocol，不直接依赖某个 SDK 响应对象：

```python
class LLMClient(Protocol):
    def analyze_repository(self, request: AnalysisRequest) -> AnalysisResult: ...
```

第一版提供 `OpenAICompatibleClient` 适配器。以下配置必须外置：

- API Key
- Base URL
- Model
- Timeout
- Max retries
- Temperature

考虑到不同兼容服务支持的接口和结构化输出能力不同，Provider 特有逻辑必须封装在适配器内部。上层只接收经过 Pydantic 校验的 `AnalysisResult`。

### 5.5 结构化结果优先

LLM 不直接生成最终 Markdown。LLM 返回结构化分析结果，Report Renderer 再生成文档：

```text
LLM Response
    ↓
AnalysisResult Validation
    ↓
Markdown Renderer
    ↓
REPORT.md
```

这样可以测试字段完整性、统一报告格式，并为 Phase 2 复用相同报告模型。

### 5.6 配置优先级

建议配置优先级：

```text
CLI 参数 > 环境变量 > 配置文件 > 默认值
```

第一版建议支持：

```text
REPOPILOT_LLM_API_KEY
REPOPILOT_LLM_BASE_URL
REPOPILOT_LLM_MODEL
REPOPILOT_LLM_TIMEOUT_SECONDS
REPOPILOT_MAX_REPO_MB
REPOPILOT_MAX_FILES
REPOPILOT_MAX_FILE_BYTES
REPOPILOT_CONTEXT_CHAR_BUDGET
```

---

## 6. Phase 1 架构

```text
Typer CLI
   │
   ▼
AnalyzeRepositoryService
   │
   ├── URL Validator
   ├── Repository Loader
   ├── Repository Scanner
   ├── Context Builder
   ├── LLM Client
   └── Report Renderer
            │
            ▼
      Markdown Report
```

`AnalyzeRepositoryService` 是 Phase 1 固定流程的编排层。它不能包含扫描、Git 或 Prompt 的具体实现。

建议执行流程：

1. CLI 解析参数并加载配置。
2. URL Validator 规范化并校验 GitHub URL。
3. Repository Loader 创建任务目录并执行浅克隆。
4. Scanner 遍历允许范围，生成 `RepositorySnapshot`。
5. Context Builder 按预算选择 README、配置和目录树。
6. LLM Client 请求结构化 `AnalysisResult`。
7. Evidence Validator 检查报告中引用的文件路径是否存在。
8. Report Renderer 生成 Markdown。
9. CLI 展示报告位置、Commit SHA、耗时和截断提示。
10. 默认清理临时仓库；`--keep-repo` 时保留并显示路径。

---

## 7. 推荐目录结构

Phase 1 只创建当前需要的文件：

```text
repopilot/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── repopilot/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── exceptions.py
│       ├── application/
│       │   └── analyze_repository.py
│       ├── models/
│       │   ├── analysis.py
│       │   └── repository.py
│       ├── repository/
│       │   ├── loader.py
│       │   ├── scanner.py
│       │   ├── filters.py
│       │   └── detector.py
│       ├── context/
│       │   └── builder.py
│       ├── llm/
│       │   ├── protocol.py
│       │   ├── openai_compatible.py
│       │   └── prompts.py
│       └── report/
│           ├── renderer.py
│           └── evidence.py
└── tests/
    ├── fixtures/
    │   └── sample_python_repo/
    ├── unit/
    └── integration/
```

不提前创建 Phase 2 到 Phase 4 的空模块。

---

## 8. 核心数据契约

### 8.1 RepositorySource

```text
RepositorySource
├── original_url
├── normalized_url
├── owner
├── name
└── clone_url
```

### 8.2 RepositorySnapshot

```text
RepositorySnapshot
├── source
├── commit_sha
├── root_path
├── directory_tree
├── files
├── readme
├── dependency_files
├── config_files
├── detected_languages
├── detected_frameworks
├── entrypoint_candidates
├── stats
└── truncation_notes
```

`entrypoint_candidates` 只能包含基于文件名、配置或脚本声明发现的候选项及原因，不能假装已经完成执行链分析。

### 8.3 RepositoryFile

```text
RepositoryFile
├── relative_path
├── size_bytes
├── category
├── language
├── is_text
└── selection_reason
```

### 8.4 AnalysisRequest

```text
AnalysisRequest
├── repository_summary
├── directory_tree
├── readme_content
├── configuration_content
├── entrypoint_candidates
├── context_limits
└── output_schema
```

### 8.5 AnalysisResult

```text
AnalysisResult
├── project_summary
├── technology_stack
├── directory_overview
├── entrypoint_candidates
├── core_module_candidates
├── evidence
├── limitations
└── recommended_reading_order
```

Phase 1 的字段使用 `candidate` 命名，是为了避免将一次有限上下文总结包装成已经验证的 Agent 探索结论。

---

## 9. Repository Loader 设计

### 9.1 URL 校验

Phase 1 只接受：

```text
https://github.com/{owner}/{repository}
https://github.com/{owner}/{repository}.git
```

拒绝：

- 非 HTTPS URL。
- 非 `github.com` Host。
- 带用户名、密码或 Token 的 URL。
- 本地路径和 `file://` URL。
- SSH URL。
- 额外路径，如 `/tree/branch`、`/issues`。
- 缺少 owner 或 repository 的 URL。

### 9.2 Clone 生命周期

```text
创建任务目录
    ↓
执行浅克隆
    ↓
读取 Commit SHA
    ↓
交给 Scanner
    ↓
生成报告
    ↓
清理或按参数保留
```

Loader 应返回明确错误类型：

- `InvalidRepositoryUrlError`
- `RepositoryNotFoundError`
- `CloneTimeoutError`
- `CloneFailedError`
- `RepositoryTooLargeError`

Clone 过程不得在日志中输出凭据。

---

## 10. Repository Scanner 设计

### 10.1 默认排除目录

至少排除：

```text
.git
.hg
.svn
.idea
.vscode
node_modules
venv
.venv
env
__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
build
dist
coverage
.coverage
htmlcov
target
vendor
```

过滤规则集中维护，允许未来配置覆盖，不散落在遍历代码中。

### 10.2 优先识别文件

第一优先级：

```text
README / README.*
pyproject.toml
requirements*.txt
setup.py
setup.cfg
Pipfile
poetry.lock
uv.lock
Dockerfile
docker-compose*.yml
compose*.yml
.github/workflows/*.yml
```

第二优先级：

```text
main.py
app.py
cli.py
manage.py
__main__.py
wsgi.py
asgi.py
```

### 10.3 扫描限制

必须限制：

- 最大仓库体积。
- 最大文件数量。
- 最大目录深度。
- 单文件读取大小。
- 最终目录树长度。
- README 和配置内容总长度。
- 二进制文件探测和跳过。
- 符号链接处理。

达到限制时应生成 `truncation_notes`，而不是静默丢弃内容。

### 10.4 技术栈识别

技术栈识别只使用确定性信号：

- 文件扩展名统计。
- 依赖文件内容。
- `pyproject.toml`、`setup.cfg` 等配置。
- Docker 和 CI 配置存在性。

每项结果保留来源，例如：

```text
FastAPI
Evidence: pyproject.toml dependency "fastapi"
```

---

## 11. Context Builder 设计

Context Builder 的目标不是“尽量多地读取”，而是在固定预算内提供最高价值的 Phase 1 输入。

建议选择顺序：

1. Repository 元数据和 Commit SHA。
2. 裁剪后的目录树。
3. 主 README。
4. 主要依赖文件。
5. 构建和运行配置。
6. 入口候选的有限代码片段。

每块上下文必须包含：

- 相对路径。
- 内容或摘要。
- 是否截断。
- 被选中的原因。

Context Builder 不得自行宣称哪个文件是核心文件。它只根据透明的 Phase 1 优先级构造有限输入。

---

## 12. Prompt 与报告设计

### 12.1 Prompt 要求

System Prompt 应明确：

- 当前结果来自有限的 Phase 1 上下文。
- 不得假设未提供文件的内容。
- 入口和核心模块只能输出为候选。
- 每个重要结论尽量引用所提供的文件路径。
- 证据不足时输出限制说明。
- 只输出符合 `AnalysisResult` 的结构化数据。

### 12.2 Phase 1 报告结构

```markdown
# Repository Analysis

## 项目简介
## 技术栈
## 项目目录
## 程序入口候选
## 核心模块候选
## 已读取的关键文件
## 分析限制
## 推荐源码阅读顺序
```

Phase 1 不输出已经确认的完整“核心执行流程”和“模块依赖关系”。这些内容需要 Phase 2 自主探索和 Phase 3 AST 证据支持。

### 12.3 Evidence 校验

Phase 1 至少校验：

- Evidence 路径存在于 `RepositorySnapshot`。
- Evidence 不使用绝对路径。
- Evidence 不包含仓库根目录之外的路径。
- 无法验证的引用在报告中标记为未验证或移除。

精确行号在 Phase 1 可以作为增强项，不作为完成条件。

---

## 13. 错误处理与退出码

建议 CLI 退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 分析成功 |
| `2` | CLI 参数或配置错误 |
| `3` | Repository URL 无效 |
| `4` | Clone 或网络失败 |
| `5` | 仓库超过限制或扫描失败 |
| `6` | LLM 请求或响应校验失败 |
| `7` | 报告写入失败 |
| `1` | 未分类内部错误 |

用户错误信息应包含：

- 发生了什么。
- 用户可以采取什么操作。
- 是否生成了部分结果。

默认不打印完整堆栈；使用 `--debug` 时输出诊断信息。

---

## 14. 测试方案

### 14.1 Unit Tests

#### URL Validator

- 标准 GitHub URL。
- `.git` 后缀。
- 大小写 Host 规范化。
- SSH、本地路径、凭据 URL 和额外路径拒绝。

#### Filters / Scanner

- 排除目录不会进入结果。
- 二进制文件被跳过。
- 符号链接不会逃逸仓库根目录。
- 文件数、深度和大小限制生效。
- 截断信息可见。
- README 和依赖文件正确识别。

#### Detector

- 根据扩展名识别主要语言。
- 根据依赖配置识别框架。
- 每项技术栈结果包含证据来源。

#### Context Builder

- 内容不超过预算。
- 高优先级内容先保留。
- 截断稳定且可复现。
- 不包含绝对本地路径。

#### LLM Client

- 请求配置正确传递。
- Timeout 和有限重试生效。
- 非法 JSON 和字段缺失能被识别。
- API Key 不出现在日志和异常中。

#### Report Renderer

- 固定章节完整。
- Markdown 输出稳定。
- 候选结论和限制说明不会丢失。
- 非法 Evidence 不进入正式引用。

### 14.2 Integration Tests

使用本地 Fixture 仓库完成：

- URL 之后流程可通过 Fake Loader 注入本地仓库。
- Scanner → Context → Fake LLM → Report 完整闭环。
- Clone 失败、仓库超限、LLM 超时和报告写入失败。
- 临时目录在成功和异常后均正确处理。

### 14.3 Smoke Test

选择一个满足以下条件的固定公开仓库：

- Python 为主。
- 仓库较小。
- 默认分支稳定。
- 有 README 和依赖文件。
- 有明确入口候选。
- 不依赖 Git LFS 或 Submodule。

Smoke Test 固定到 Commit SHA，避免上游仓库变化导致结果漂移。涉及真实 LLM 的测试默认不进入普通 CI，只通过显式环境开关运行。

---

## 15. 实施里程碑

### M1 — 工程骨架与配置

交付：

- `pyproject.toml`。
- `src/` Layout。
- Typer CLI 空命令。
- 配置模型和 `.env.example`。
- 日志初始化。
- Pytest、Ruff 和类型检查基础配置。

完成条件：

- 包可安装。
- `repopilot --help` 可运行。
- 配置缺失时错误清晰。
- 基础质量命令通过。

### M2 — Repository Loader

交付：

- URL Validator。
- 浅克隆。
- Commit SHA 获取。
- 临时目录生命周期。
- Clone 错误映射。

完成条件：

- 有效仓库可克隆。
- 非法 URL 在执行 Git 前被拒绝。
- 失败不遗留不可解释的临时状态。

### M3 — Repository Scanner

交付：

- 过滤规则。
- 安全遍历。
- 文件分类和统计。
- README / 配置解析。
- 技术栈和入口候选检测。
- `RepositorySnapshot`。

完成条件：

- Fixture 扫描结果稳定。
- 所有限制都有测试。
- 所有截断都有显式记录。

### M4 — Context 与 LLM

交付：

- Context Builder。
- Prompt。
- `LLMClient` Protocol。
- OpenAI-compatible Adapter。
- `AnalysisResult` 校验。
- Fake LLM Client。

完成条件：

- 不依赖真实 API 的集成测试可运行。
- Context 不超过配置预算。
- 非法模型响应产生明确错误。

### M5 — Report 与 CLI 闭环

交付：

- Evidence Validator。
- Markdown Renderer。
- `AnalyzeRepositoryService`。
- CLI 进度、输出路径和退出码。

完成条件：

- 本地 Fixture 可端到端生成报告。
- 报告固定章节和候选标识完整。
- 成功与失败路径都能正确清理资源。

### M6 — 真实仓库验证与文档

交付：

- 固定公开仓库 Smoke Test。
- README 安装和使用说明。
- 配置说明。
- 已知限制。
- 示例报告。

完成条件：

- 至少对 3 个结构不同的小型 Python 公开仓库手工验证。
- 对其中 1 个固定 Commit 保留可复现的验收记录。
- Phase 1 Definition of Done 全部满足。

---

## 16. 推荐开发顺序

严格按垂直闭环推进：

```text
1. CLI Skeleton + Fake Dependencies
2. Fixture Repo → Fake Report 的最小闭环
3. 接入真实 Scanner
4. 接入真实 Clone
5. 接入真实 LLM
6. 完善错误与限制
7. 真实仓库验收
```

第一条可运行链路应尽早建立。不要等 Loader、Scanner、LLM 和 Renderer 全部完成后才第一次集成。

---

## 17. Phase 2 迁移准备

Phase 1 完成时，下列能力应能独立调用：

```text
validate_repository_url
clone_repository
scan_repository
read_high_value_files
build_analysis_context
analyze_with_llm
validate_evidence
render_report
```

Phase 2 可以将其中的确定性能力包装为 Tool，而无需重写内部实现：

```text
Phase 1
AnalyzeRepositoryService.scan_repository()

Phase 2
Agent → scan_repository Tool → Observation
```

为避免 Phase 1 架构阻碍 Agent 化，禁止：

- 在 CLI 中直接实现业务流程。
- Scanner 直接调用 LLM。
- LLM Client 直接遍历文件。
- Report Renderer 自行推断架构结论。
- 模块之间传递无法序列化的 SDK 私有对象。
- 使用全局变量保存仓库和分析状态。

---

## 18. Definition of Done

Phase 1 只有在以下项目全部完成后才能结束：

- [x] `repopilot analyze <github_url>` 可从干净环境运行。
- [x] URL 校验不会接受本地路径、SSH 或带凭据 URL。
- [x] Clone 使用浅克隆并记录 Commit SHA。
- [x] 默认不执行任何目标仓库代码。
- [x] Scanner 有明确过滤和资源限制。
- [x] Context Builder 有可测试的固定预算。
- [x] LLM 配置外置，密钥不会进入日志。
- [x] LLM 结果经过 Pydantic 结构校验。
- [x] 报告由结构化结果渲染，不直接使用原始模型文本。
- [x] 报告明确使用“入口候选”和“核心模块候选”。
- [x] Evidence 至少完成路径级校验。
- [x] Fake LLM 的端到端集成测试通过。
- [x] 至少一个真实公开仓库 Smoke Test 通过。
- [x] 错误场景返回明确消息和退出码。
- [x] README 包含安装、配置、使用和限制说明。
- [x] Phase 1 模块可以在 Phase 2 中包装为 Tool。

---

## 19. Phase 1 完成后的评审问题

进入 Phase 2 前进行一次架构评审：

1. Scanner 是否只返回事实和候选，而没有替 Agent 作语义判断？
2. 是否可以绕过 `AnalyzeRepositoryService` 单独调用每项能力？
3. LLM Client 是否可替换为 Fake 或其他兼容 Provider？
4. Context 是否有明确预算和截断记录？
5. 报告是否诚实表达 Phase 1 的分析限制？
6. 将 Scanner、Reader 包装为 Tool 时是否需要大规模重构？
7. Phase 1 是否已经形成稳定、可复现的端到端基线？

如果第 1、2、4、6 项不能明确回答“是”，应先完成整改，再开始 Phase 2。

### 19.1 整改后评审结论

2026-08-31 完成整改后重新评审：

| 问题 | 结论 | 验证依据 |
| --- | --- | --- |
| 1. Scanner 是否只返回事实和候选？ | 是 | Scanner 输出 `RepositorySnapshot`，入口仅为确定性候选，不生成最终架构结论 |
| 2. 是否可以绕过 Application Service 单独调用能力？ | 是 | Loader、Scanner、Reader、Context Builder、LLM Client、Evidence Validator、Renderer 均有独立公开接口 |
| 3. LLM Client 是否可替换？ | 是 | `LLMClient Protocol`、Fake Client 和 OpenAI-compatible Adapter 均已验证 |
| 4. Context 是否有预算和截断记录？ | 是 | 固定字符预算、具体截断章节、原始长度、保留长度和省略章节均进入 `AnalysisRequest` 与报告 |
| 5. 报告是否诚实表达限制？ | 是 | 报告确定性附加 Phase 1 限制和截断明细，模型越界入口候选会被白名单过滤 |
| 6. Scanner、Reader 能否包装为 Tool？ | 是 | `RepositoryReader` 已独立提取，各能力通过 Protocol 解耦，可直接作为 Phase 2 Tool 后端 |
| 7. 是否形成可复现端到端基线？ | 是 | 44 项测试、86% 覆盖率、干净虚拟环境安装、三个公开仓库扫描和真实 Provider 报告均已验证 |

Phase 1 已满足进入 Phase 2 的架构条件。代码进入版本控制后，应以对应 Commit SHA 作为正式 Phase 1 基线。
