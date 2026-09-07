# 后端核心回复执行单元实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可离线执行、可回归、可在 Git 中安全提交的后端核心回复单元，覆盖消息进入、统一运行时、人格/知识上下文、静态或真实 LLM provider、发送队列、回执和审计。

**Architecture:** 复用现有 `console_chat.run_once` 与 `RuntimePipeline`，新增稳定的 JSON 单轮 CLI 作为后端执行合同；不复制聊天业务逻辑。NoneBot 启动仍注册现有 matcher，但订阅 V2 初始化改为可选延后步骤，核心聊天启动不因订阅数据库锁文件失败而失败。

**Tech Stack:** Python 3.12、NoneBot2、Pydantic、现有 RuntimePipeline、InMemorySendQueue、pytest、PowerShell `scripts/dev.ps1`。

**Spec:** `docs/handoff-comprehensive-2026-09-05.md` 第 20、22 节及用户 2026-09-05 确认的后端优先范围。

## Global Constraints

- 只修改当前源码工作区，不扫描或写入 `ChatBot_Runtime`、`ChatBot_Archive` 或上级目录。
- 默认执行路径离线，不调用网络、不连接 NapCat/Telegram、不发送真实消息。
- 不把 `.env`、密钥、Cookie、SQLite、FAISS、聊天记忆、日志、缓存或 Runtime 虚拟环境纳入提交。
- 复用现有 contracts、RuntimePipeline、chat capability、knowledge provider 和发送回执，不新增平行业务链路。
- 每项新行为先写失败测试并确认失败，再写最小实现。

### Task 1: 固化核心后端单轮执行合同

**Files:**
- Create: `plugins/bot_unified_runtime/backend_unit.py`
- Test: `tests/test_backend_unit.py`
- Modify: `scripts/dev.ps1`

**Interfaces:**
- Produces `run_backend_unit(message_text: str, env_file: str | None = None) -> dict[str, object]`。
- CLI: `python -m plugins.bot_unified_runtime.backend_unit --message <文本> [--env <路径>]`。
- JSON 至少包含 `ok`、`request_id`、`receipt_state`、`capability_id`、`reply`、`audit_events`、`audit_tags`、`knowledge_chunks`、`web_search_used`；不输出密钥或完整 prompt。

- [ ] **Step 1: Write the failing test**

```python
def test_backend_unit_runs_offline_chat_pipeline():
    result = run_backend_unit("请介绍一下你自己", env_file=offline_env)
    assert result["ok"] is True
    assert result["receipt_state"] == "sent"
    assert result["capability_id"] == "bot.chat"
    assert result["reply"]
    assert "pipeline" in result["audit_events"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backend_unit.py::test_backend_unit_runs_offline_chat_pipeline -q`
Expected: FAIL because `plugins.bot_unified_runtime.backend_unit` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement a thin wrapper around `console_chat.run_once` or a shared extracted runner. Use `Config` with `bot_chat_provider="static"` for the offline test fixture, inspect only the in-memory send queue for reply text, and serialize audit fields safely. Return nonzero from CLI when receipt is not `sent` or config loading fails.

- [ ] **Step 4: Add knowledge/search observability test**

Use a test-only character/LLM provider injection or existing smoke seam to assert that the result reports knowledge context count without embedding raw knowledge text. Assert `web_search_used` is a boolean and remains false for the offline static path.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_backend_unit.py -q`
Expected: PASS with no warnings or cache writes in the source tree.

- [ ] **Step 6: Wire `backend-smoke` into `scripts/dev.ps1`**

Add the task to `ValidateSet`, help output, dispatch, and a function that passes `-Message` through to the module. Keep the task offline and one-shot.

- [ ] **Step 7: Run the executable unit**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\\scripts\\dev.ps1' -Task backend-smoke -Message '请用一句话说明你能做什么'"`
Expected: JSON result with `ok=true`, `receipt_state=sent`, non-empty `reply`, and exit code 0.

### Task 2: Make core NoneBot startup independent from deferred subscriptions

**Files:**
- Modify: `plugins/bot_unified_runtime/__init__.py`
- Modify: `plugins/bot_unified_runtime/smoke.py`
- Test: `tests/test_nonebot_startup_boundary.py`

**Interfaces:**
- Produces a startup option that skips subscription runtime initialization while preserving chat matcher registration.
- The startup smoke must use the option and report `subscription_runtime=deferred` rather than masking plugin import failure.

- [ ] **Step 1: Write the failing test**

```python
def test_core_startup_can_defer_subscription_runtime(monkeypatch):
    monkeypatch.setenv("BOT_DEFER_OPTIONAL_SUBSCRIPTIONS", "true")
    result = run_startup_probe_with_fake_subscription_failure()
    assert result.plugin_loaded is True
    assert result.matcher_count >= 3
    assert result.subscription_runtime == "deferred"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nonebot_startup_boundary.py::test_core_startup_can_defer_subscription_runtime -q`
Expected: FAIL because the startup path always constructs `SubscriptionStoreV2` when subscriptions are enabled.

- [ ] **Step 3: Implement the boundary**

Add one explicit environment/config gate read during plugin registration. When enabled, do not call `register_subscription_runtime_v2`; retain command parsing and core chat registration. Keep normal subscription behavior unchanged when the gate is absent/false.

- [ ] **Step 4: Update startup smoke**

Run its child process with the defer gate enabled and include a safe status field. Do not expose paths, credentials, or exception bodies beyond redacted error kind.

- [ ] **Step 5: Run focused startup tests**

Run: `pytest tests/test_nonebot_startup_boundary.py -q`
Expected: PASS.

### Task 3: Documentation, hygiene, and Git-safe release check

**Files:**
- Modify: `COMMANDS.md`
- Modify: `README.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Documents the new `backend-smoke` command, offline semantics, and deferred subscription status.
- Documents that only source/tests/scripts/docs are eligible for this commit.

- [ ] **Step 1: Add command documentation**

Document the exact PowerShell invocation and expected success fields; state that real LLM/search requires explicit configuration and is not part of the offline acceptance path.

- [ ] **Step 2: Run project checks**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\\scripts\\dev.ps1' -Task docs-check"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\\scripts\\dev.ps1' -Task plugin-check"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\\scripts\\dev.ps1' -Task runtime-layout"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\\scripts\\dev.ps1' -Task backend-smoke -Message '测试后端主链路'"
```

- [ ] **Step 3: Inspect Git diff and eligible paths**

Run `git diff --check`, `git status --short`, and `git diff --stat`. Stage only the files listed in this plan; explicitly verify that `.env`, Runtime paths, database files, cache files, and unrelated existing changes are not staged.

- [ ] **Step 4: Commit the isolated change**

Use a normal commit message such as `feat: add backend core execution unit`. Do not use reset/checkout or discard unrelated worktree changes.

- [ ] **Step 5: Attempt a non-data push**

Only after verification and commit, inspect branch/upstream state. Attempt a normal push of the new commit to its configured branch; do not force-push. If remote rejects, report the exact reason and leave local work intact.

## Verification Checklist

- [ ] Focused backend unit tests pass.
- [ ] Startup boundary tests pass.
- [ ] `backend-smoke` returns exit code 0 with static provider.
- [ ] `docs-check`, `plugin-check`, and `runtime-layout` pass.
- [ ] `git diff --check` passes.
- [ ] Staged paths contain no secrets or runtime data.
- [ ] Push attempt result is recorded accurately.
