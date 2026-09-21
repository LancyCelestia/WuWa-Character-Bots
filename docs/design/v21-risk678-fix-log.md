# V2.1 风险修复席（A13）修复日志——风险 6/7/8

> 2026-09-17。取证依据：`docs/design/v21-risk-red-report.md`（风险 6/7/8 三节）。
> 硬约束遵守：无 git 写操作、未派子代理、未扫 Runtime/Archive、未读 .env 明文；
> 直跑解释器=`../ChatBot_Runtime/venv/Scripts/python.exe`，全程
> `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`、pytest
> `--basetemp="$TEMP/v21-risk678" -p no:cacheprovider`、未用 dev.ps1。
> 收尾实测：**6 条 xfail 全部转正且绿**；相关域回归 355 passed / 5 xfailed（xfailed
> 均为风险 5（3 条，按分工不动）与 control_plane 在飞席的风险 4（2 条））；改动 7 文件
> ruff All checks passed；mypy（`--explicit-package-bases --ignore-missing-imports
> --follow-imports=silent`）**4 个源码文件 Success: no issues**（另见的全量模式 2 处
> `control_plane/api/platform.py` 错误属并行修复席在飞未跟踪文件，非本席文件域）。

---

## 风险 6：TG poll 阶段 catch-all 把 401/409 永久归为网络故障（2 测）

**文件**：`scripts/telegram_resilience.py`（未跟踪文件，2026-09-16 批产物，本席独占修改）

**根因**（取证报告 verified）：`poll` 以 `retry(..., "startup", catch_all=True)` 包裹，
catch_all 分支跳过 `isinstance(exc, network_error)` 与 `retryable(exc)` 两道分类——上游把
HTTP 401（token 失效）/403/409（多实例 getUpdates 冲突）也包装成 NetworkError，全部被按
"网络暂不可用"指数退避无限重试：409 形成两实例互踢 token 死循环、401 烧穿预算且永不自愈。

**修法**（对齐合同 §7：仅网络/TLS 临时错误/429/5xx 退避；鉴权暂停告警不重试；409 停止争抢；
未知异常隔离诊断不称网络错误）：
- 新增 `permanent_telegram_status(exc)`：从上游 NetworkError 的 `msg="Received unexpected NNN ..."`
  前缀仅提取三位码（消息体可能含 token，绝不落原文），命中 `{401,403,409}` 返回码否则 None。
- `retry()` 新增 `permanent` 形参（仅与 catch_all 搭配、poll 阶段传入）：先于退避分类命中时
  记**定向告警**（409="实例冲突（另一实例正在 getUpdates，停止争抢）"、401/403="鉴权失败
  （token 无效或被吊销，暂停重试）"，明示"这不是网络问题"），**优雅停轮询返回 None**。
- 保留 2026-09-16 不变量：异常不上抛（启动链逃逸会连带 QQ 侧启动失败）；其余未知异常
  （代理抖动等形态不定的临时故障）维持 catch_all 退避；`_call_api` getUpdates 分支
  （catch_all=False，retryable 分类）与 offset/取消语义零改动。
- 设计取舍说明：取证测试注释原文写"直接抛出原异常"，但抛出会让异常沿启动链逃逸、重启
  2026-09-16 修掉的"setup 异常炸整个进程"缺陷（该缺陷恰因 401/409 形态异常上抛才引入
  catch_all）；故 GREEN 语义取"停轮询+定向告警+不上抛"，测试断言 `poll(None) is None`
  （既证明未进退避 sleep——进 sleep 即 `_LoopEscape` 逃逸判红——又锁住不逃逸不变量）。

**转正测试**（`tests/test_v21_risk_red_dispatch_and_telegram.py`，移除 `xfail(strict)`
标记、docstring 注明转正）：
- `test_risk6_poll_does_not_retry_auth_conflict[401]`
- `test_risk6_poll_does_not_retry_auth_conflict[409]`

**实跑**：修复后先 XPASS(strict) 双双转红（`[XPASS(strict)] V21-risk-6: ...`），转正后
`6 passed, 3 xfailed`（3 xfailed=风险 5 未动）；`tests/test_telegram_resilience.py`
存量 12 例全绿（含 409 真适配器上抛、取消逃逸、退避梯度、token 不落日志各锁）。

## 风险 7a：节日表按 MM-DD 跨年复用错报（1 测）

**文件**：`plugins/bot_unified_runtime/character/temporal.py`

**根因**：`DEFAULT_HOLIDAYS_2026` 为 `(MM-DD, 名称)` 二元组表，`holiday_of` 仅按月日匹配
无年份维度——2026 农历节日（春节 02-17 等）被原样套到任意年份（2027 春节实为 02-06）。

**修法**：节日表拆年份维度——`_GREGORIAN_HOLIDAYS`（9 条公历固定节日：元旦/情人节/妇女节/
清明 04-05 近似/劳动节/儿童节/国庆/平安夜/圣诞，逐年复用）+ `_LUNAR_HOLIDAYS_2026`（7 条
农历近似换算：除夕/春节/元宵/端午/七夕/中秋/重阳，仅 2026 成立）；`DEFAULT_HOLIDAYS_2026 =
_LUNAR + _GREGORIAN`（仍 16 条，公开常量不变）。`holiday_of`：默认表且 `day.year != 2026`
时只查公历子表；显式注入 `table`（`BOT_HOLIDAYS_FILE` 路径）按表原样匹配（年份语义由表作者
负责，既有签名/格式零破坏）。`RuleBasedTemporalProvider` 新增 `_holiday_table_is_default`
标记：未注入自定义表时 snapshot 经 `holiday_of(now, None)` 走按年选表——修复 provider 路径
（2027 年对话上下文不再错报春节）。

**转正测试**（`tests/test_v21_risk_red_tz_and_files.py`）：
- `test_risk7_holiday_table_not_reused_across_years`（2026-02-17=春节；2027-02-17=空）

**实跑**：先 XPASS(strict) 转红，转正后绿；`tests/test_temporal_http_client.py` 12 例绿；
探针实测 2027 元旦/圣诞仍报、2027-02-17 为空、`RuleBasedTemporalProvider().snapshot()` 正常。

## 风险 7b：提醒链 `_as_local` 用进程本地时区不读 bot_timezone（1 测）

**文件**：`plugins/bot_unified_runtime/character/reminders.py`（本席独占写权）

**根因**：`_as_local = moment.astimezone()`（进程本地时区）+ 全模块 13 处调用，从不读
`config.bot_timezone`（默认 Asia/Hong_Kong）——UTC 服务器上"明天9点"墙钟推算错位（极端差
一整天）；`parse_reminder_intent` 对 aware 注入 `now` 还沿用其时区推墙钟。

**修法**（统一走配置时区，IANA）：
- 新增进程级绑定面：`_DEFAULT_BOT_TIMEZONE = "Asia/Hong_Kong"`（与 config.py:254 缺省一致）、
  `configure_reminder_timezone(tz_name)`（装配期绑定；空串=测试局部 config 缺字段不改动；
  非法名保持原绑定防垃圾串毒化）、`_bot_zone()`（解析失败退进程本地时区，提醒链绝不因时区崩）。
- `_as_local` 重定义：naive 按 `_bot_zone()` 解释（`replace(tzinfo=...)`）、aware 一律
  `astimezone(_bot_zone())`——全模块唯一归一点换锚，13 处调用点自动统一。
- `parse_reminder_intent`：`current` 三分支收敛为 `_as_local(...)`（naive/aware/缺省
  timesync now 都换算到配置时区再推墙钟）；docstring 同步改口径。
- `due()` 的 `_local_now()` 分支同样过 `_as_local` 归一。
- 绑定点：`build_reminder_store(config)` 在既有 `timesync.configure_from(config)` 旁调用
  `configure_reminder_timezone(config.bot_timezone)`——生产装配（能力层×3、`__init__`×2）
  全部途经此处，零新增接线。

**转正测试**（`tests/test_v21_risk_red_tz_and_files.py`）：
- `test_risk7_reminder_wallclock_follows_config_timezone`（UTC 18:30 说"明天9点"→香港
  09-19 09:00）

**存量断言更新（逐条注明理由，未删测试）**：`tests/test_reminder.py`
`test_parse_utc_now_wall_clock_stays_in_now_frame` → 更名
`test_parse_utc_now_wall_clock_follows_config_timezone` 并改断言（UTC 05:51 说「23点」=
配置时区 23:00=15:00Z，不再=23:00Z）。理由：旧断言锁定的正是本风险修复废除的"now 时区
推墙钟"语义（UTC 服务器"明天9点"推错一天的根因之一），两者互斥；测试体内已写明更新理由。
其余 115 例 reminder 族（解析矩阵/存储/治理回执/投递/勾选/触发词）零改动全绿——治理回执
与顺延断言均以 `astimezone(_TZ)` 时刻比较，时区换锚透明。

**域外登记（不动，留给响应域 owner）**：`character/memory_extract.py:212` 的
`.astimezone()` 旁注释"与 parse_reminder_intent 同口径"因本次口径变更变为过期陈述
（该文件不在本席文件域，行为未改）。

**实跑**：先 XPASS(strict) 转红，转正后绿；探针实测 `Asia/Shanghai` 绑定生效、非法名
`Not/AZone` 保持原绑定、空串 no-op、naive now 路径不崩。

## 风险 8：.xls/.ppt 伪装 OOXML 解析致读取链崩溃（2 测）

**文件**：`plugins/bot_unified_runtime/sources/file_reader.py`

**根因**：`.xls` 并入 openpyxl 分支（原 :122）、`.ppt` 并入 python-pptx 分支（原 :137）；
OLE2 魔数（D0CF11E0）文件被当 OOXML 解析，openpyxl 抛 `InvalidFileException`、python-pptx
抛 `PackageNotFoundError`（连同 zipfile `BadZipFile`）均不在 `except (ImportError, OSError,
ValueError, TypeError)` 元组内 → `read_supported_file` 直接抛，控制面 `/files/read` 500。

**修法**（旧格式明确 unsupported 诚实报错；venv 实测 xlrd 未安装，无真实适配器可走，故取
降级路径、不加依赖）：
- `.xls` / `.ppt` 拆独立分支：不再尝试任何解析，直接返回
  `FileReadResult(kind, "", name, {"status": "parser_unavailable", "format": "legacy .xls/.ppt (OLE2)"})`
  ——对齐 `.pdf` 分支 parser_unavailable 先例；控制面 `/files/read` 现有消费逻辑按
  kind 返回 200+metadata（415 化属 control_plane 在飞席文件域，本席不碰 platform.py）。
- 现代 `.xlsx` / `.pptx` 分支加固：库导入改前置守卫（ImportError 形状与原分支一致）；
  except 元组补 `InvalidFileException` / `PackageNotFoundError` / `BadZipFile`——损坏或
  被改名的伪 OOXML 同族异常也诚实降级，包级异常彻底不逃出读取链（风险 8 同族防御，
  探针实测 OLE 魔数 .xlsx/.pptx 均降级不抛）。

**转正测试**（`tests/test_v21_risk_red_tz_and_files.py`）：
- `test_risk8_legacy_office_not_misparsed[legacy.xls-spreadsheet]`
- `test_risk8_legacy_office_not_misparsed[legacy.ppt-presentation]`

**实跑**：先 XPASS(strict)×2 转红，转正后绿；消费方回归
`tests/test_phase0_3_features.py` + `tests/test_runtime_subfeatures.py` 37 例绿；
探针实测真 .xlsx（含中文）/真 .pptx 仍正常解析（openpyxl/pptx round-trip）。

---

## 收尾核验（全部实跑）

| 门 | 命令（摘要） | 结果 |
|---|---|---|
| 转正 6 测+风险5不动 | `pytest tests/test_v21_risk_red_tz_and_files.py tests/test_v21_risk_red_dispatch_and_telegram.py -rx` | 6 passed, 3 xfailed |
| 相关域全量 | 上表 14+2 文件（reminder 族/temporal/file_reader 消费方/TG/触发词/auditfix + cp 两 red 文件） | **355 passed, 5 xfailed, 0 failed**（5 xfailed=风险5×3+cp 风险4×2，非本席域） |
| ruff（改动 7 文件） | `ruff check <files>` | All checks passed!（含修复取证席遗留的 I001 与 2 处 DTZ001，后者按 test_divination.py `# noqa: DTZ001` 惯例） |
| mypy（改动 4 源文件） | `mypy --explicit-package-bases --ignore-missing-imports --follow-imports=silent ...`（cache 在 %TEMP%） | Success: no issues found in 4 source files |
| 树卫生 | find `__pycache__/.pytest_cache/*.pyc` | 零残留；qx.json 完好 |

**改动文件清单**：`scripts/telegram_resilience.py`、
`plugins/bot_unified_runtime/character/temporal.py`、
`plugins/bot_unified_runtime/character/reminders.py`、
`plugins/bot_unified_runtime/sources/file_reader.py`、
`tests/test_reminder.py`、`tests/test_v21_risk_red_dispatch_and_telegram.py`（转正）、
`tests/test_v21_risk_red_tz_and_files.py`（转正）。
**人格话术红线**：未触碰任何文案模板（`_REMINDER_TEXT_TEMPLATES`/治理回执池零改动）。
**部署注记**：代码层修复，按铁律待用户提权重启 bot 后生效。
