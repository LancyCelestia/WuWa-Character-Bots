# v21r5 MINOR-SWEEP 席工作日志（关闭终审 3 个可修 Minor）

## 任务与依据
- 关闭 FINAL-REVIEW-3（docs/design/v21r5-FINALREVIEW-log.md Minor 清单）登记的 3 个可修 Minor：
  1. **A-Minor-1**：fail-fast 工厂异常路径 provider_error 不重置连续网络计数，与 model_router.py:78-79 注释窄缝隙——按 FIX-N1 同款（except 分支补计数重置或按代码实读判定正确语义），带探针测试。
  2. **C-Minor-6**：asphyxiation 词面 `卡` 字医疗误伤面——「喉咙卡了鱼刺」类医疗陈述在性语境共现窗内是否被 ②窒息词面误拦，实跑判定；误拦则加性语境锚定/医疗 grounding 例外，不误拦则如实记录不改动。
  3. **B-Minor-3**：`_extra_patterns` 退役槽位死重——实读确认无消费者后移除（grep 全树零引用），连带测试同步。
- 红线遵守：六硬线语义未改（②窒息判定面仅排除异物名词回望卫命中的医疗陈述族，性窒息 8/8 探针全拒+公开面拒）；explicit_allowed_for_session 签名零触碰；未成年/儿童化 fail-closed 逻辑零触碰（v4 §1-§8 77 例存量全绿）；禁碰清单（root __init__/campus/AGENTS/HANDBOOK 等）零接触。
- 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest `--basetemp="$TEMP/minorsweep-tmp" -p no:cacheprovider`；禁 git 写/子代理/真实 LLM/发送/重启/.env 读值；不 commit。

## 坐标勘误
- B-Minor-3 真身=`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`（简报所写 content_safety.py 系坐标偏差；FINALREVIEW log B-Minor-3 条目与 grep 全树实证均在 content_route.py）。

## 逐项施工记录

### Item 1（A-Minor-1）：判定=已被 CRIT-FIX-3 Fix4 收口，本席零改动+实跑复证

- **改前实读**：`model_router.py` 通用 `except Exception` 分支（L2333-2352）L2343 **已有** `consecutive_network_failures = 0`，注释明引「评审探针 P2（v21r5 CRIT-FIX-3）」；L78-79 注释「provider_error 打断计数」与实现已一致。crisure：v21r5-CRITFIX-log.md Fix4 明载「通用分支补 `consecutive_network_failures = 0`（一行）+ failfast P2 场景测试」——终审（FINALREVIEW 先于 CRIT-FIX-3 落码）所记缝隙已在此后关闭。
- **探针测试**（v4 电池 §8 两只锁，本席实跑复证）：
  `pytest tests/test_content_safety_v4.py -k "network_streak"` → `2 passed`（`test_raw_exception_provider_error_breaks_network_streak`：4×timeout+1×RAW RuntimeError+1×timeout → reply=ok:g、calls a→g 全拨、无 failfast abort；`test_classified_provider_error_still_breaks_network_streak` 对照锁）。
- **结论**：A-Minor-1 关闭（他席已修，本席复证）；A-Minor-2（白盒读私有态）不在本席三项、按终审「登记备查」维持。

### Item 2（C-Minor-6）：误拦实锤→「卡」分支医疗 grounding 例外

- **BEFORE 探针**（`$TEMP/minorsweep-probe.py`，18 样本，`assess_public_content(explicit_allowed=True)` 最宽参数实判）：**医疗 6/9 误拒**——「鱼刺卡住喉咙了/被鱼刺卡住了喉咙/糖果卡住气管了怎么办/孩子被硬币卡住喉咙，需要急救吗/骨头卡住了喉咙/坚果卡住气管，呼吸不上来」全 `REFUSE(asphyxiation)`；FINALREVIEW 样本「喉咙卡了鱼刺」因语序（身体部位在动词前）本就放行，误拦面实为「<异物>卡住+身体部位」语序族。性窒息 8/8 全拒+公开面拒（正确保持）。mismatch=6。
- **修法**（`content_safety.py` L123-137，一处）：`卡` 从直拦动词组 `(?:掐|勒|扼|卡|捂)` 拆出，单独分支加异物名词负向回望卫——
  ```diff
  -r"|(?:掐|勒|扼|卡|捂)(?:[住着了上紧扼][^，。；！？,.!?\n]{0,4}?)?(?:脖子|脖颈|咽喉|喉咙|颈部|气管|口鼻|鼻子)"
  +r"|(?:掐|勒|扼|捂)(?:[住着了上紧扼][^，。；！？,.!?\n]{0,4}?)?(?:脖子|脖颈|咽喉|喉咙|颈部|气管|口鼻|鼻子)"
  +#「卡」分支带异物名词回望卫（MINOR-SWEEP C-Minor-6 医疗 grounding）。
  +r"|(?<!" + _ASPHYX_STUCK_OBJ_RE.pattern
  +        + r")卡(?:[住着了上紧扼][^，。；！？,.!?\n]{0,4}?)?(?:脖子|脖颈|咽喉|喉咙|颈部|气管|口鼻|鼻子)"
  ```
  `_ASPHYX_STUCK_OBJ_RE = 鱼刺|鱼骨|骨头|软骨|异物|食物|糖果|药丸|药片|胶囊|硬币|纽扣|果冻|坚果|饭粒|枣核|假牙`（17 支全 2 字定宽，满足 Python re 回望定宽要求；按文件惯例 re.compile 真身经 `.pattern` 拼装，避文案扫红门）。掐/勒/扼/捂直拦不动。
- **语义边界（诚实登记）**：判定面收窄仅限「卡前紧邻异物名词」的匹配——即「<异物>卡住喉咙」医疗族；「用手卡住她的喉咙」等无异物锚定照旧命中（AFTER 探针含此例仍拒）。已知残余（不修）：①异物在动词后的语序（「卡住了喉咙，是鱼刺」）仍直拦（宁拦勿漏）；②回望表外异物词（「硬糖卡住」）仍直拦；③「用鱼刺卡住她喉咙」类荒谬组合会放行（词面层不可表达，概率趋零）。
- **memory_sanitize 单一来源**：清洗面经 `HARD_LINE_SANITIZE_PATTERNS` 自动继承——医疗卡喉句不再入清洗面、性窒息句照洗（v4 §9 `test_medical_choking_not_sanitized_from_memory` 锁死）。
- **AFTER 探针**：医疗 9/9 allow、性窒息 8/8 refuse、公开面 refuse，**mismatch=0**。

### Item 3（B-Minor-3）：`_extra_patterns` 一元化（退役槽位移除）

- **改前实读**：`_extra_patterns` 返回 `tuple[Pattern|None, Pattern|None]` 第二元恒 None（`patterns = (_compile_word_list(...), None)`），唯一消费点 `observe_turn` 以 `strong_re, _borderline_retired = ...` 解包后弃第二元。grep 全树（plugins+tests）：`_extra_patterns` 仅定义+1 消费点、`_extra_words_cache` 仅本类、测试零引用——死重实锤。
- **施工**（`content_route.py` 三处）：
  - `_extra_patterns` 返回类型 `re.Pattern[str] | None`（与 `_compile_word_list` 真实签名对齐，None=空词表语义保留），内部 `strong_re = _compile_word_list(list(_STRONG_WORDS) + extra)` 直接缓存返回，docstring 注明退役缘由；
  - `self._extra_words_cache: tuple[str, re.Pattern[str] | None] | None`；
  - 消费点 `strong_re = self._extra_patterns(config)`（`_borderline_retired` 解包删除）。
- **测试同步**：全树零测试引用退役槽位→无需改存量；消费面行为由既有 `tests/test_content_route.py:102`（`bot_content_route_words="自定义黑话A, 自定义黑话B"` 功能级测试，本批合跑绿）覆盖。

## 测试与静态门（实跑输出原文）

- v4 全量（77 存量+18 新增）：
  ```
  ........................................................................ [ 75%]
  .......................                                                  [100%]
  95 passed in 3.99s
  ```
- 受影响族回归批（FINALREVIEW 126 批口径+v4+content_route v1：llm_failfast/content_route_v3/content_route/content_safety_v2/v3/v4/memory_sanitize/affinity/copy_redline_gate/persona_source_sync/doc_sync_gates/v21r2_content_probe）：
  ```
  247 passed in 10.04s
  ```
- ruff（content_safety.py+content_route.py+test_content_safety_v4.py）：`All checks passed!`
- mypy（项目旗标 `--explicit-package-bases --ignore-missing-imports`，两源文件）：`Success: no issues found in 2 source files`
- 树卫生：plugins/tests 零 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`data/` 残留；qx.json 完好。

## 改动面清单（共享工作树增量，未 commit）
- `plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`（M，本席 delta=「卡」分支拆分+异物回望卫+注释块）
- `plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`（M，本席 delta=_extra_patterns 一元化三处）
- `tests/test_content_safety_v4.py`（??，本波新建未跟踪文件，本席追加头注 1 行+§9 电池 4 只测试/18 例）
- `docs/design/v21r5-MINORSWEEP-log.md`（??，本 log）
- 旧路径垫片（security/content_safety.py、runtime/content_route.py 活导出 shim）零改动自动透传。

## 终审判定对照
| 终审 Minor | 本席处置 | 证据 |
|---|---|---|
| A-Minor-1 fail-fast provider_error 窄缝隙 | 已由 CRIT-FIX-3 Fix4 收口，零改动+复证 | model_router.py:2343 重置在位；v4 §8 两锁 2 passed |
| A-Minor-2 白盒读私有态 | 不在本席三项，维持终审「登记备查」 | — |
| B-Minor-3 _extra_patterns 死重 | 已移除（一元化三处） | 家族批 247 passed+ruff/mypy 绿 |
| C-Minor-4 3.2/3.3/3.4 词面落点 | 不在本席三项（3.4 已由 CRIT-FIX-3 Fix6 落码，3.2/3.3=登记不实施） | — |
| C-Minor-5 人格显式度差异 | 不在本席三项（R18 十词门禁构成措辞约束，维持） | — |
| C-Minor-6 asphyxiation「卡」误伤面 | 误拦实锤（6/9）→医疗 grounding 例外落地 | BEFORE mismatch=6 / AFTER mismatch=0；v4 §9 18 例 |

MINORSWEEP-SEAT DONE
