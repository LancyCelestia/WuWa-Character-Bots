# v21r2 重组 W14 transport 域施工日志（RW15 席执行）

> 日期：2026-09-18。席位：RW15（简报原指派 W15=subscribe 订阅域）。
> **改波记录**：开工前实读 `docs/design/v21r2-COORDINATION.md`，subscribe 域已被 RW12 席认领占域（"W8 subscribe 域：认领占域施工中"），按简报规则改取**下一无冲突波 = 方案书 §5 W14 transport**（sender/ 9 件 + mail_adapter + mail_bridge = 11 件）。在飞席 RW11 media / RW12 subscribe / RW13 assistant / RW14 render 与 transport 零交集；transport 的原冲突批（发送队列/UNKNOWN 确认、mail 韧性 R2b、FIX worker 测试同步）均已收口（COORDINATION 实证）。本波全程零 git 写操作、未跑 dev.ps1、未再派代理。

## 一、波前取证（第 1 步）

- `git status`：transport 面 WIP = `sender/onebot.py`、`sender/worker.py`、`mail_adapter.py` 三件 M 态（R2b TG 降噪/bot_unavailable 静默/mail 退避批次遗留）→ 按 RW6/RW10/RW11 先例 **WIP 随迁零内容改动**。
- 全库引用面（rg + AST ImportFrom 扫描）：`bot_unified_runtime.sender.*` 命中 51 文件（插件 7 + tests 42 + scripts/e2e_acceptance 1），mail_adapter 6、mail_bridge 6。
- **monkeypatch 清单**（字符串式 + 对象式全量）：
  - 字符串式：`test_nonebot_sender.py` ×6（`_TG_VOICE_CACHE_DIR`×4 / `shutil.which` / `_convert_audio_to_ogg`）、`test_operational_failures.py:334`（`onebot._ONEBOT_SEND_RETRY_DELAYS`）——补丁打壳模块打不进真身，**波内必改**。
  - 对象式（模块对象经旧路径绑定）：`test_a20`（worker）、`test_bgroup`（nonebot/onebot/queue）、`test_f03`（file_gateway）、`test_onebot_chunk_budget_floor`（onebot）、`test_part_idempotent_resume`（onebot+worker 两行）、`test_prfix_sender`（onebot/queue/receipts 三行）、`test_v21r2_lifecycle_r2`（onebot+mail_adapter）、`test_mail_adapter_resilience`（mail_adapter）——补丁名（`_BUSY_ALERT_SUPPRESSION`/`_download_proxy_provider`/`_default_gateway`/`_MAIL_SEARCH_TIMEOUT_SECONDS` 等）全部由真身体内消费，绑定必须切真身。
  - **LEGAL 保留判定：零**。本域无「生产函数级旧路径取符号 + 测试打旧路径」的合法对（root `__init__` 函数级 `from .sender.X import` 取的是值引用，测试补丁均打模块级全局、真身消费）。
- `sender/mail` 11 文件 **零 `__file__`/`parents[]` 深度锚**；兄弟相对导入仅 `sender/__init__.py`（`from .onebot` 等，整包随迁原语义保留）；叶子模块全用绝对导入，仅兄弟引用需切 canonical。
- 垫片私名转出清单（AST 名字级全量 from-import 扫描）：onebot ← `_TimeoutBudget/_segment_from_mixed_part/_mixed_segments/_resolve_local_file_ref`；worker ← `_fallback_text_for_media/_call_transport_safely/_update_queue_state/_notify_operational_issue_safely`；其余模块跨界外引全为公开名（`import *` 覆盖，叶子模块均无 `__all__`）。
- 文本锚排查：`test_control_plane_log_collectors.py:62` 合成 LogRecord 用旧 logger 名字符串（断言 source=="sender"，合成名不受迁移影响，仍过）；`verify_hashes.py` 零 transport 条目；echo.py:2737 引用的是测试文件路径非模块路径；smoke.py:1233 `importlib.import_module("...sender.onebot")` 旧路径经垫片解析，零改动覆盖。
- **log_collectors 分类器影响评估**：sender 族 logger 全部 `getLogger(__name__)`，迁移后 `__name__` 变 `...domains.transport.sender.*`；`control_plane/log_collectors._SUBSYSTEMS` 按 `local.startswith(prefix+".")` 匹配，旧锚 `sender`/`mail_adapter` 将失配 → 事件源从 sender/mail 降级 bot。属真行为面，波内同步补新锚（见 §三.4）。

## 二、移动（第 2 步，文件系统 mv）

```
sender/{__init__,queue,worker,onebot,nonebot,file_gateway,receipts,gateway,timeout}.py ×9
  → domains/transport/sender/（__init__.py 的 .onebot/.queue/.receipts/.worker 兄弟相对导入随整包原样保留）
mail_adapter.py → domains/transport/mail/mail_adapter.py（零插件内 import，纯搬）
mail_bridge.py  → domains/transport/mail/mail_bridge.py（同上）
新增：domains/transport/__init__.py（域根 docstring）
新增：domains/transport/extensions/__init__.py（W-PA5 reserved 占位，首行 docstring 带 reserved:）
```

真身随迁修正（8 行兄弟引用切 canonical）：queue→receipts/timeout、worker→queue/receipts、onebot→file_gateway/timeout、nonebot→file_gateway/timeout。外部引用零改动：config/contracts/audit/runtime.alerts/runtime.deadline（未迁域真身）、`output.plain_text`（W13 render 在飞，旧路径垫片覆盖，禁前向引用——W7 http_util 教训）、`sources.downloader`（file_gateway.py:275 函数级旧路取符号 = W8 判定的 LEGAL 形态，保持）。

## 三、垫片与同波改写（第 3 步）

1. **旧位 11 张 re-export 薄壳**（house style 同 W2/W3）：`sender/__init__.py` 壳 `from ...domains.transport.sender import *`（真身包 `__all__` 22 名随转）；子模块壳公开名 `import *` 转出 + 下划线名显式列转（onebot 4 名、worker 4 名；其余 8 壳纯 `import *`）。mail_adapter 壳保证 bot.py 的 `mail_adapter.ResilientMailAdapter` 直连零改动（方案书 §3.2）。
2. **测试同波改写 20 处**：字符串式 7（nonebot 6 + operational_failures 1 → `domains.transport.sender.*` 真身路径）；模块绑定 13（上列 9 文件 13 行 → canonical；中途补漏 2：`test_part_idempotent_resume` worker 绑定行、`test_prfix_sender` receipts 绑定行——首版 AST 清单转录遗漏，被域测试红抓出，教训见 §五）。
3. **垫片同一性冒烟**：11 垫片 73 名 `is` 断言全过 + 插件导入 OK（`import plugins.bot_unified_runtime` + `mail_adapter.ResilientMailAdapter`）。
4. **log_collectors 分类锚同步**：`_SUBSYSTEMS` 增 `"domains.transport.sender": "sender"`、`"domains.transport.mail": "mail"` 两锚（旧锚保留，垫片退役尾声波再议）；`test_control_plane_log_collectors` 增新 logger 名断言一行锁死。

## 四、回归实跑（第 4 步；解释器 venv 固定，PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，basetemp=$TEMP/v21r2-rw15，-p no:cacheprovider）

| 门 | 命令 | 结果 |
|---|---|---|
| 域关键词全库轮 | `pytest tests -k "sender or queue or mail or transport or onebot or worker or receipts or gateway or file_gateway or delivery"` | **281 passed / 1 xfailed**（7781 收集零错=全库关键词扫自证） |
| 消费方显式批 | 16 文件（error_report/e2e/pipeline/feature_gate/perf_hotpath/lifecycle_r2 等） | **233 passed / 1 skipped / 1 failed（外部归因，见 §五）** |
| ruff（波面 27 文件） | `ruff check <wave files>` | **All checks passed**（--fix 收 21：I001×9 + RUF100 星号行 noqa×12） |
| mypy（dev.ps1 权威口径） | `mypy --explicit-package-bases --ignore-missing-imports plugins` | 547 文件 **2 错全为 control_plane/api/platform.py:79/:254 既有**（V1 席归因 A12 台账 #36），本波面 0 错 |
| 哈希门 | `tests/verify_hashes.py --check` | **exit 0** |
| 事实册门 | `pytest tests/test_doc_sync_gates.py` | **4 passed** |
| 树卫生数据写守卫 | `pytest tests/test_no_source_tree_data_writes.py` | **5 passed** |
| runtime-layout | `scripts/runtime_layout_smoke.py` | 2 FAIL=BOT_KNOWLEDGE_FILES 用户外部目录「AI智能体有关材料/鸣潮…」缺失（RW5/RW10 同见，环境面非本波引入） |
| 树卫生缓存/杂数据 | find | 零 `__pycache__`/`.pytest_cache`/`*.pyc`/源码树 `data/` |
| qx.json | sha256 | **e8285e77… 完好**（W3 随迁位 domains/weather/assets/） |
| AST 终验 | 全库扫描字符串式旧路径补丁 + 旧路径子模块/根 mail 绑定 | **RESIDUAL = 0** |

## 五、偏差与外部归因（如实登记）

1. **改波**：subscribe 被 RW12 认领 → 本席执行 W14 transport（见页首）。
2. **外部既有红 1**：`test_error_report.py::test_config_snapshot_whitelist_and_secret_masking`——根因=他席搜索批 WIP（config.py +152 行新增 `bot_search_acg_*` 键族未入 error_report 密钥掩码白名单，config/error_report/test 三件均为未提交 WIP 态）。与本波零交集（本波零触 config/error_report），移交该搜索批收口。
3. **首版清单转录遗漏 2 处绑定**：worker/receipts 模块对象绑定行漏改（`test_part_idempotent_resume`/`test_prfix_sender`），被域测试红当场抓出即改即复。教训重申：**AST 清单生成后必须机读直驱改写，禁人工转录**。
4. **log_collectors 属 W16 域但波内最小触碰**：仅 `_SUBSYSTEMS` 加 2 锚 + 其测试加 1 断言（分类器按 logger `__name__` 前缀匹配，迁移必改锚，等同「文本锚随真身同波同步」纪律）；control_plane 其余零触碰。
5. `test_bgroup_chat_pipeline.py` 的 M 态为他席 WIP，本席零触碰。
6. 未跑 dev.ps1 全量门（席位禁令）、渲染契约（未触 output/）、command_catalog --write（未触 echo/config）。

## 六、移交注记

- 垫片退役（尾声波）：`sender/` 11 壳 + log_collectors 旧锚 `sender`/`mail_adapter` 两条一并清理；退役前需统计旧路径 import 残留（smoke.py:1233 importlib 字符串与 file_gateway.py:275 函数级 downloader 旧路取符号两处需同波收口）。
- RW14 render 波注意：`domains/transport/sender/nonebot.py:24` 经旧路径 `output.plain_text` 取 `redact_local_secrets`（模块级），render 迁移垫片覆盖即可，无需本域配合。
- 本波全程未 commit（工作树多席共享，提交裁决权在用户）。
