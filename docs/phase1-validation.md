# Phase 1 Validation Record

Date: 2026-08-31  
Platform: Windows, Python 3.13.3, Git 2.53.0

## Automated checks

```text
pytest --cov=repopilot: 44 passed, 86% total coverage
ruff check .: passed
mypy src/repopilot: passed
git diff --check: passed
repopilot --help: passed
clean virtual environment install and import: passed
```

The automated end-to-end test uses a local Python fixture and a fake `LLMClient`. It covers:

```text
URL → Loader boundary → Scanner → Context Builder
    → Fake LLM → Evidence validation → Markdown report
```

## Public repository Clone + Scan smoke tests

All smoke tests used a shallow clone with submodules disabled. Temporary repositories were removed after scanning.

| Repository | Commit SHA | Files | Scanned bytes | Detected languages |
| --- | --- | ---: | ---: | --- |
| `pallets/itsdangerous` | `672971d66a2ef9f85151e53283113f33d642dabd` | 50 | 286,932 | Python, Shell |
| `psf/requests` | `5460f467b02e49471c0fd6cfc9ca0adab6351f98` | 130 | 4,470,704 | Python |
| `pallets/flask` | `d318b683471101618febed18996405ad26462110` | 236 | 1,907,329 | Python, Shell |

These tests verified the real URL validator, cross-platform clone timeout implementation, Git metadata lookup, filtering, bounded scan, language detection, dependency evidence and cleanup behavior.

## Configuration checks

Before Provider configuration, `repopilot doctor` correctly reported missing required values and returned exit code `2`:

```text
OK Git executable
MISSING LLM API key
MISSING LLM model
OK LLM base URL
```

After Provider configuration, the same command reported all checks as `OK` and returned exit code `0`. The local `.env` file was confirmed to be ignored by Git.

## Provider-backed validation

A real OpenAI-compatible request was completed with the `deepseek-v4-pro` model and the official DeepSeek API endpoint:

```bash
repopilot doctor
repopilot analyze https://github.com/pallets/itsdangerous --output reports/itsdangerous.md
```

Result:

```text
doctor: passed
repository clone and scan: passed
structured LLM response validation: passed
Evidence path validation: passed
Markdown report rendering: passed
API key pattern scan of report: 0 matches
analyzed commit: 672971d66a2ef9f85151e53283113f33d642dabd
```

Manual report inspection confirmed that:

- the response passes `AnalysisResult` validation;
- all verified Evidence paths exist in the scanned snapshot;
- entrypoints and core modules are labeled as candidates;
- context truncation is disclosed in the report;
- no API key appears in console output or logs.

## Remediation validation

The Phase 1 completion audit led to the following changes:

- extracted a standalone bounded `RepositoryReader` with path traversal, binary, symlink and size protections;
- introduced capability Protocols so orchestration does not require concrete Loader, Scanner, Context Builder or Renderer implementations;
- made Context truncation details deterministic report inputs;
- mapped `CloneTimeoutError` to the documented Clone/network exit code;
- constrained model entrypoint candidates to the Scanner whitelist;
- instructed the model to return Chinese explanations and an empty entrypoint list when no deterministic candidate exists;
- moved deterministic findings and entrypoint excerpts ahead of large dependency files in the Context priority order.

The Provider-backed remediation report confirmed Chinese output and an empty entrypoint section for the library repository. A subsequent real Clone + Scan + Context smoke test produced:

```text
context characters: 59,999 / 60,000
deterministic scan findings retained: yes
deterministic entrypoint candidates: 0
dependency truncation details recorded: yes
omitted configuration section recorded: yes
```
