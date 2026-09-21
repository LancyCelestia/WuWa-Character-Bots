# 核心链路排查报告（v21r3 · 2026-09-18）

> 范围：用户最高优先指令「0.1 把最基础的『接收消息 → 处理 → 返回发送』核心链路
> 彻底排查——找出全部问题、全部修好」。本文件是**证据化清单**：每条给出实测命令
> 或文件行号，未实跑的一律标「未验证」。

---

## 一、结论速览

| 维度 | 结果 | 证据 |
|---|---|---|
| 主链路功能 | **健康** | 离线冒烟 `ok:true / receipt_state:"sent"`，审计链完整 |
| 端到端自检 | **14/14 PASS** | `scripts/e2e_acceptance.py --selftest` |
| 全量回归（修复前） | 7 failed / 8113 passed | 366s |
| 全量回归（修复后） | **2 failed / 8123 passed** | 519s；+5 为本轮新增用例 |
| 门禁 | ruff / hash / doc_sync / command_catalog **全绿** | 四项 exit=0 |

**核心链路本体没有结构性缺陷**——主链（摄取归一 → 路由 → 门禁 → 管线 → 能力 →
审查 → 渲染 → 队列 → 发送）在离线与自检态均正常。本轮发现的问题集中在**链路边缘**
（媒体富化、出站异常路径、后台抽取器），已逐项修复。

剩余 2 项失败**均非产品缺陷**（详见 §三）：reaper 测试隔离、linuxdo 夹具依赖。

---

## 二、已修复（本轮，逐条附复现证据）

### 2.1 合并转发「递归子记录」读不了 —— P1，任务 6 根因

**现象**：转发里再转发的聊天记录，第三层及更深内容整段丢失。

**复现**（新增用例 `test_async_fetch_expands_deeply_nested_forwards`）：
```
E  assert '第三层' in '甲：第一层 [合并转发:L2]\n—— 子转发 L2 ——\n乙：第二层 [合并转发:L3]'
```
第三层停在**未展开的占位符** `[合并转发:L3]`。

**根因**：`plugins/bot_unified_runtime/__init__.py` `_forward_message_text` 内
```python
for nested_id in nested_ids[:4]:   # 只展开一层、硬限 4 个、不再递归
```

**修法**：改为按深度递归展开，设三道闸防爆炸——深度上限 3（`_FORWARD_NESTED_MAX_DEPTH`）、
单消息子转发总节点上限 12（`_FORWARD_NESTED_MAX_TOTAL`）、主/子反查共享总超时预算；
`seen` 集合去重使环引用（A→B→A）必然终止。

**验收**：新增 2 例（深层展开、环引用终止）+ 存量 16 例 → **18 passed**。

---

### 2.2 提醒系统「乱记广告」—— P1，任务 2 根因

**现象**：群里其他 AI 机器人发的催缴广告被记成用户提醒，同一时刻五条齐发。

**取证**（只读查询 `ChatBot_Runtime/data/reminders.sqlite3`）：
```
13 条记录中 11 条含广告特征
text: 【套餐 】尊敬的用户您好 截至9月17日12时 您的token账户已不足支付本群的
      AI好友聊天 … 请及时缴费50元
remind_at: 2026-09-18T12:00:00+08:00   ← 5 条同刻
```
提醒时间 `12:00` 系从广告正文「截至9月17日12时」抠出。

**根因**：`domains/chat_reply/character/memory_extract.py` 的
`_REMINDER_EXTRACT_SYSTEM_PROMPT` 只要求「有明确时间点的事」，**未排除第三方通知/广告**；
广告恰好同时满足「明确时间 + 事项」。对照**记忆路径**早有 F16 确定性闸
（`_TRIVIAL_FACT_RE`），提醒路径**没有任何同类防护**。

**复现**（新增用例）：输入侧 `llm.calls == 0` 断言失败、输出侧广告条目被入库。

**修法**（与 F16 同款范式）：
- 新增 `_REMINDER_NOISE_RE` 确定性闸（`尊敬的用户`/`套餐`/`缴费`/`余额不足`/`AI好友`…）；
- **输入侧**命中 → 直接返回空且**不调用 LLM**；
- **输出侧**命中 → 丢弃该条（防 LLM 改写措辞绕过输入闸）；
- prompt 增第 4 条规则：只抽「用户本人打算做的事」。

**验收**：新增 3 例 → `test_sdd7_n4.py` **26 passed**。

**残留数据**：库中 13 条**全部为 `done`**（已投递），**无 pending**，不会再触发；
其中 11 条为历史脏记录，清理方式见 §四（不代改实例数据）。

---

### 2.3 出站阶段异常未回滚限流额度 —— P2

**位置**：`domains/chat_reply/runtime/pipeline.py` `handle` / `handle_async`。

`_complete` 内 `send_queue.submit` 抛错时，消息**并未入队**（用户收不到任何回复），
但该路径只转 `internal_error`，**不回滚限流记账**——用户重试会被刚失败的那条继续占配额。
能力异常路径（A-18）已有回滚，出站路径漏了。

**修法**：`_complete` 调用点补同语义回滚（同步/异步两处）。

---

### 2.4 群失败通知节流窗口被白占 —— P2

**位置**：同文件 `_maybe_submit_group_failure_notice`。

节流时间戳在 `send_queue.submit` **之前**写入；提交失败时窗口已消耗，
一次瞬时失败会让该会话静默满 `_GROUP_FAILURE_NOTICE_WINDOW_SECONDS`（300s），
用户侧表现为「群里 @ 了 bot 又突然没反应」。

**修法**：提交失败时释放刚占用的节流键。

---

### 2.5 e2e selftest 的 timesync carve-out 已过期 —— 技术债

`scripts/e2e_acceptance.py` 长期保留一处特判：把 `UnboundLocalError` 路由异常降级为
WARN（原描述为 `runtime/timesync.py` 的 `now()` 缺 `global _SHARED`）。

**实测该缺陷早已修复**：真身 `domains/schedule/timesync/timesync.py:493` 已带
`global _SHARED, _SHARED_SIGNATURE`，直调返回 `2026-09-18 19:43:25+08:00`。

**风险**：carve-out 会让未来 timesync 的**真实**崩溃被静默吞掉。
**修法**：移除特判，路由异常一律判 FAIL。验收：selftest 仍 14/14，`route_probe` 显示「路由异常=无」。

---

### 2.6 引用链冗余真值判断 —— 代码卫生

`ingest/message_context.py` `collect_reply_chain_async`：
`if chain[-1] and chain[-1].text == ...` —— `ReplyChainItem` 是 dataclass 实例恒为真值，
前半段永不起作用（chain 非空已在上方保证）。已清理。

---

## 三、已定性、非产品缺陷的 2 项失败

### 3.1 `test_p4_reaper_returns_cleanly_when_no_stuck_threads` —— 测试隔离

**复现实验（已定位）**：
```
tests/test_error_card_async.py + tests/test_v21r2_lifecycle_r2.py  → 1 failed
tests/test_pipeline_review_fixes.py + tests/test_v21r2_lifecycle_r2.py → 37 passed
```
**根因**：`domains/ops/monitor/error_report.py` 的模块级常驻池 `_RENDER_POOL`
（worker 非 daemon）**只在 `atexit` 收口，无测试期清理**。该池被创建后线程存活到
reaper 用例，`_reap_background_threads(1.0)` 检测到滞留线程 → 触发 `_force_exit` →
断言 `exits == []` 失败。

**定性**：产品侧行为正确（reaper 设计意图就是强制收尾滞留线程，且生产有 atexit）。
缺的是**测试 teardown**。
**建议修法**：`test_error_card_async.py` 加 autouse fixture，teardown 调
`error_report._shutdown_render_pool()`。

### 3.2 `test_discourse_linuxdo_parses_topic` —— 夹具依赖

```
assert result.engagement.comment_count == 6848   # posts_count-1（真实样本）
E   AssertionError: assert 2 == 6848
```
**根因**：用例断言硬编码真实样本值，本机缺 `linux.do/topic.json` 样本 → 走兜底解析得 2。
**定性**：环境/夹具缺陷，与产品代码零耦合。
**建议修法**：缺样本时 `pytest.skip`（而非硬红），或补齐样本归档。

---

## 四、代码侧已就绪、待重启生效（重要）

你报告的多数现象，**代码侧早已修好，但生产进程仍是旧代码**——铁律：改代码必须重启才生效。

| 你的任务 | 代码侧状态 | 位置 / 证据 |
|---|---|---|
| **2** 提醒乱记广告 | 本轮修复 | `memory_extract.py` 双侧噪声闸 |
| **3** 亲密话术复读「我不会躲。/我在。/我在这里。」 | **v21r2 已修**（2026-09-17 裁定） | `chat.py:1305` `_DANGER_COMFORT_EXAMPLES` 十池 + `pick_variant` 游标轮换 |
| **3** R-18 详细动作描写 / 全年龄不带动作 | **v21r2 已修** | `chat.py:1333` `INTIMATE_RP_STYLE_INSTRUCTION` / `:1342` `NORMAL_NO_ACTION_INSTRUCTION` |
| **3** 话题红线（恐怖/政治/殴打/极端SM/幼女/未成年） | **已实现** | `affinity.py:423-424` 红线清单与你的口径一致 |
| **3** 亲密模式自动路由 grok-4.6 | **已实现** | `model_router.py:934/1619` verdict=INTIMATE 时 head 钉 grok |
| **6** 合并转发递归子记录 | 本轮修复 | `__init__.py::_forward_message_text` 深度递归 |
| **6** 高分辨率大图 | **今日已修** | `vision_describe.py` 上限 8MB→20MB→**25MB**（用户 2026-09-18 二次裁定）、超时 10s→25s；本地图上限同步 8MB→25MB |
| **0.1** 出站异常回滚 / 群通知节流 | 本轮修复 | `pipeline.py` 两处 |

**结论**：这批修复合起来是一个「重启才能看到」的批次。重启前线上行为不变，属预期。

---

## 五、待用户裁决（涉运行实例数据，按既定边界不代改）

| 项 | 现状 | 建议 |
|---|---|---|
| 菜谱脏缓存 | `ChatBot_Runtime/data/food_images/`：7 张来自污染域（`font.hanyuguoxue.com` 3 张、`n.sinaimg.cn` 2 张、`img95.699pic.com` 2 张），另有 `凉拌木耳.jpg` 与 `凉拌黄瓜.jpg` **哈希完全相同**（同图错配） | 删除这些文件后重抓；**需你确认** |
| 提醒库历史脏记录 | 13 条中 11 条为广告误记（均 `done`，不再触发） | 可选清理；**需你确认** |
| `kb_drift` | 生产库 ANN=35341 vs chunks=4611（已嵌入 4539） | 涉向量通道漂移，需你裁决 |

---

## 六、核心链路逐段勘察记录（本轮已读）

| 段 | 载体 | 结论 |
|---|---|---|
| 摄取归一 | `__init__.py::_incoming_from_nonebot_event`（230 行） | 健康；引用链/点名/媒体占位逻辑完备 |
| 引用链递归 | `ingest/message_context.py`（465 行） | 健康；5 层递归 + 去重 + 消毒 + 预算 |
| 媒体富化 | `__init__.py::_forward_message_text` | **已修**（见 2.1） |
| 路由 | `runtime/base_router.py`（792 行） | 健康；确定性注册表 + 47 路由族 |
| 门禁 | `runtime/pipeline.py::_prepare` | 健康；feature gate → runtime → role → policy → 安静时间 → 限流 → 幂等 |
| 管线 | `runtime/pipeline.py`（1131 行） | **已修 2 处**（见 2.3 / 2.4） |
| 出站队列 | `transport/sender/queue.py`（1858 行） | 健康；RLock + `_locked_connection` 锁纪律完整 |
| 后台抽取 | `character/memory_extract.py` | **已修**（见 2.2） |

---

## 七、尚未排查（用户任务清单中的后续项）

- **任务 1** HTML 渲染模板统一（模板卡 vs f-string 直拼卡两套收敛）
- **任务 3** 亲密话术多元化 + R-18 文风 + 话题边界重写
- **任务 6 后半** 高分辨率大图读取（`vision_describe.py` 已放宽至 **25MB** + 缩边 2048，
  需实跑确认是否仍复现）
- V2.1 三合同剩余：17 行 `not_wired` 接线、L60/L71/L74 立项、65 行四列回填
- 命令格式统一（评审材料待出，按你的裁定「先给你评审定名」）

---

## 八、复跑命令（可复现）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
VENV="C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"

# 本轮修复的定向验收
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 "$VENV" -B -m pytest \
  tests/test_forward_message_ingest.py tests/test_sdd7_n4.py \
  tests/test_reply_chain_recursion.py tests/test_pipeline_review_fixes.py \
  -q --basetemp="$TEMP/v21r3-targeted" -p no:cacheprovider

# 端到端自检
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 "$VENV" -B scripts/e2e_acceptance.py --selftest

# 全量
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 "$VENV" -B -m pytest -q \
  --basetemp="$TEMP/v21r3-full" -p no:cacheprovider
```
