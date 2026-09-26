"""配置键登记总账门：读点腿（零读点点名）+ 热改面腿（每枚字段恰好一个表态）。

席 S56（中央调度收编波，2026-09-24）。为什么再立一把：本仓 `config.py` 是单一 pydantic
`Config`（`extra="ignore"` ⇒ **填错键名等同没填**），同型病已咬三口——① sync_drift 七枚键
消费方读 Config 上不存在的键 ⇒ 巡检器永不注册（AGENTS #47⑫）；② 紧急域某键"死键/已接线"
口径反复（#45/#46）；③ 席 S42 现算出「新键全树零读点＝新死键，而泛用死键门不存在」（紧急域
那把只管 `bot_emergency_info_*`）。热改面同理：一枚键在 `RESTART_REQUIRED_KEYS` 与
`SETTABLE_KEYS` 两边都不在＝"看着能热改、其实重启才生效"，两边都在＝档位无唯一真值。

## 读点腿的判据（五桶，全部机器现算，零手写归属）

一枚 `bot_*` 字段算"有读点"，当且仅当命中下列任一桶；桶之间**互斥**
（优先级 直读 > 模板 > 字面 > 中央按名 > 绕中央）：

 1. **直读**（真身＝`scripts.config_read_point_census`）：属性式 `cfg.bot_x`，或 configish
    接收者（词根 config/cfg/settings）的 `getattr/hasattr/setattr/delattr` 字面量形态，
    含"键名藏在模块常量里"的转名形态。
 2. **动态模板覆盖**：键以某枚在册 f-string 模板前缀开头（`bot_subscribe_platform_…` 一类），
    静态判不出具体键 ⇒ 不判死，但**单独计数**并钉棘轮（模板面缩了本门当场红）。
 3. **字面在场**：键名作为**字符串常量**出现在 `config.py` 以外的生产 .py 里。
    读点表 / 投影表 / 键元组都算（先例：根 `__init__.py:766` `_config_with_runtime_overrides`
    逐枚 `getattr(config, field_name)`，字段名正是以字面量住在表里；sync_drift 七枚走
    `_config_get(config, "bot_sync_drift_surfaces", …)` 同一条形).
    ⚠ 本桶只保证「不静默」，**不保证**值真被消费——逐枚归属在本席报告 §3，门只钉数量。
 4. **中央按名读**（席 S77 加，只用于**分类**）：生产 .py 里存在
    `<store>.get("<UPPER>", <configish 接收者>)` 且 `<UPPER>` **逐字等于**某枚字段的大写 env 名。
    依据＝`domains/chat_reply/runtime/settings.py:967 def get(self, key, config)` 的实现体
    `return getattr(config, normalized_key.lower(), None)`——未命中 override 时**按名机械映射**读
    `Config` 字段，故值路径活着，但直读尺（桶 1）结构上看不见它。
    ⚠ 三条不给升格的硬边界：①本桶**不**计入"有直读点＝健康"，`CORPUS_FLOOR_BASELINE` 的直读维
    一分不加；②`settings.py:974 def get_or(self, key, default)` 的实现体只
    `return self.list_overrides().get(...)`、**根本不碰 config** ⇒ 只被 `get_or` 消费的字段
    一律**不**进本桶（实测现算：`get_or` 命中集与硬死名册交集为空，分家今天不动计数，但堵死将来）；
    ③SETTABLE / RESTART 是**热改台账**、不是读点证据 ⇒ 本桶绝不从两表派生
    （由 `test_central_bucket_is_not_derived_from_hot_tiers` 执法，注毒必红）。
 5. **绕中央直读环境**（席 S77 加，**这是债、不是健康**）：生产 .py 里存在
    `os.getenv("<UPPER>")` / `os.environ["<UPPER>"]` / `os.environ.get("<UPPER>")`（含模块级
    `NAME = os.environ` 别名）直读，而该字段无直读/模板/字面/中央按名形状。
    含义＝值来自进程环境、**绕过中央件与热改层**，Config 字段本身仍是无人读的镜像。
    ⚠ 本桶与"待修总账"合并计数（`DEBT_ROSTER_*`）⇒ 把一枚键从硬死挪进本桶**不减少**待修数量。
    ⚠ 只认 `os.environ` 这一族；`scripts/` 里 `load_env()` 读 .env 得到的**普通 dict** 的
    `.get("<UPPER>")` 不算本桶（那是运维脚本自读自解，形态另见诚实边界 5）。
 6. **真无人读**（违规）：以上皆无。仅剩注释与文档串的字面 **不算** 读点；`config.py` **自家**的
    自引用也不算——否则任何字段都能靠自家注释或校验器洗白。
    旧版在此点名"已知假阳 1 枚 `bot_transport_timeout_seconds`"——席 S77 起它由桶 4 逐枚给证据，
    不再靠行内注挂着（名册见 `HARD_DEAD_BASELINE`，枚数以常量现算为准，本段不写死数）。

## 热改面腿的判据

每枚字段对热改面必须有**唯一一个**可查表态：进 `SETTABLE_KEYS`、进 `RESTART_REQUIRED_KEYS`、
或写进第三态台账 `w24.DELIBERATELY_UNLISTED`（第三态真身＝席 W24 的
`tests/test_config_hotchange_consistency_gate.py`，本门**只 import 不复制**，见
`test_third_state_authority_is_the_w24_ledger`）。两表同现＝档位无唯一真值（`load_hot_tiers`
会抛 `UnrepresentableField`，本门把它接成**点名红**而不是 error——"不可判"态不许静默跳过）。

## 与相邻门的分工（不装兜住一切）

- `test_config_read_points_declared.py`（S-PHANTOM）＝**镜像方向**：代码读了、Config 没有。
  本门＝正向：Config 有、代码没读。两门同用 census 真身，判据不复制。
- `test_config_hotchange_consistency_gate.py`（W24）腿 A＝**数量**棘轮；本腿＝**逐枚状态** +
  集合指纹（防"进 N 枚出 N 枚而数量不变"的洗白）。两把基线必须同步下调，本门把 W24 的现值
  一并打印供对账（不硬断言相等：本席禁写该件，拿别人的过期基线把自己钉成出生即红＝门作废）。

## 诚实边界（这把门抓不了什么）

1. 抓不了"值被读进变量后丢弃"的假读点；桶 3 只证明键名在场。
2. 抓不了通过 `model_dump()` / `**vars(cfg)` 整体投影的消费——那种读法**不给任何一枚键**记账，
   所以"直读面"地板只钉今天现算值，不声称是理论真值。
3. 接收者命名不在 `_CONFIGISH` 词根里（例如裸 `conf`）的直读会被漏判成"无读点"；
   那会被桶 3 兜住（键名字面仍在场），代价是它进的是"不保证活性"那一桶。
4. 只降不升的棘轮是**地板不是进度**：违规名册（硬死 ∪ 绕中央＝`DEBT_ROSTER`）仍在册，
   本门不删键、不改 config.py，枚数以常量现算为准、不写进散文。
5. **键名不是字面量**的中央件读法（`runtime_settings.get(key, config)` 里 `key` 是循环变量，
   或 `get_or(key, default)` 同形）**无法归到某一枚字段**：本门把它们单列为
   `central_dynamic_sites` 计数并钉地板（`test_dynamic_named_central_sites_are_counted`），
   只用来声明"桶 4 不可能覆盖全部间接路径"，**不**据此给任何一枚键发活性。
   同理 `load_env()` 那类自读 .env 的 dict 也不算桶 5——两种形状都只会**少**认读点，不会多认。
6. 桶 4 认的是"存在这条按名取值调用"，仍不保证取值后被消费（与桶 3 同一量级的诚实缺口）；
   它比桶 3 强的地方仅在于：名字必须逐字对上字段大写名、第二实参必须是 configish 句柄。
"""

from __future__ import annotations

import ast
import hashlib
import sys
import time
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for _p in (str(ROOT), str(TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 真身只 import、不复制（禁第二真身）：字段集 / 读点扫描 / 两表 / 第三态台账各一个来源。
import test_config_hotchange_consistency_gate as w24

import scripts.config_read_point_census as census
from scripts.board_doc_sync import load_config_fields
from scripts.config_catalog_generator_pilot import (
    UnrepresentableField,
    load_hot_tiers,
)

SETTINGS_PY = w24.SETTINGS_PY
CONFIG_UNDER_TEST = ROOT / "plugins" / "bot_unified_runtime" / "config.py"
SETTINGS_UNDER_TEST = SETTINGS_PY

# ---------------------------------------------------------------------------
# 尺身份三元组（读数用哪把量出来的，缺一即不可复现）
#   ① 字段真身 `scripts.board_doc_sync.load_config_fields`（与 `census.config_fields()` 同值，
#      由 `test_two_field_authorities_agree` 现场对账）
#   ② 读点真身 `scripts.config_read_point_census.scan(DEFAULT_SCOPES)`
#      ＝ 生产面 plugins/ + scripts/ + bot.py，**tests/ 不在内**（测试里的 getattr 多是断言缺省）
#   ③ 热改真身 `pilot.load_hot_tiers(settings.py 全文)` ＋ W24 `DELIBERATELY_UNLISTED`
# ---------------------------------------------------------------------------
MEASURED_AT_UTC = "2026-09-24T00:02:24Z"  # 四枚常量同刻现算复核（硬死名册 23:48:29Z 首算、此刻逐枚复验等值）
S77_MEASURED_AT_UTC = "2026-09-24T00:47:00Z"  # 席 S77 现算复核两枚新桶 + 待修总账 + 恒等式 18+38+1+1+41=99
# 席 S157（2026-09-24T07:2xZ）按**新字段集**现算重录地板与未表态账（裁定 R-4：四枚 `*_via_queue`
# 已从 config.py 退役 ⇒ 字段 700→696、直读点 1462→1454、生产 .py 630→634、未表态 572→568）。
# 尺身份三元组（读数用哪把量出来的，缺一即不可复算）：
#   ① 字段 696 ＝ `scripts/board_doc_sync.py:160 load_config_fields()`
#      （＝ `scripts/config_read_point_census.py:33 config_fields()`，两把尺同值由
#        `test_two_field_authorities_agree` 现场对账）
#   ② 直读点 1454 ＝ `scripts/config_read_point_census.py:101 scan(DEFAULT_SCOPES)` 的
#      `len(attr)+len(getattr)`，归账口＝本件 `read_point_leg`（函数名是锚）
#      模板前缀 3 ＝ 本件 `_template_prefixes`（派生自 `config_read_point_census.py:185`）
#      生产 .py 634 ＝ 本件 `test_read_point_leg_is_not_blind` 数 `census.py_files()`（census.py:52）
#   ③ 未表态 568 ＝ 本件 `hot_surface_leg` ＝ pilot `load_hot_tiers`
#      （`scripts/config_catalog_generator_pilot.py:254`，读 settings.py 全文）与 `w24.DELIBERATELY_UNLISTED`
#      三方对减，指纹尺＝本件 `_sha16`（sha256 前 16 位）。本件自引用只写函数名不写行号
#      （行号随落码漂，写死即成谎话——席 S157 首版就把它写成了 `:406`/`:453`，已按实况改口径）。
#   复跑命令（现算即此，勿凭记忆改数）：
#     cd <ROOT> && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
#       PYTHONPYCACHEPREFIX="$TEMP/s157-pyc" ../ChatBot_Runtime/venv/Scripts/python.exe \
#       -m pytest tests/test_config_key_registration_ledger.py \
#       -p no:cacheprovider --basetemp=$TEMP/s157-t1 -q
S157_MEASURED_AT_UTC = "2026-09-24T07:24:00Z"
RERUN_COMMAND = (
    'cd <ROOT> && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 '
    'PYTHONPYCACHEPREFIX="$TEMP/s77-pyc" ../ChatBot_Runtime/venv/Scripts/python.exe '
    "-m pytest tests/test_config_key_registration_ledger.py -p no:cacheprovider "
    "--basetemp=$TEMP/s77-t1 -q"
)

# 读点腿基线（MEASURED_AT_UTC 现算钉死，**只降不升且必须等于真值**）。
# 席 S77 摘账两枚（去向逐一可追溯，见 SEAT-S77.md §2）：
#   bot_transport_timeout_seconds → 桶 4 中央按名读（根 __init__.py:3835）
#   bot_card_asset_dir            → 桶 5 绕中央直读环境（domains/render/card_render/bridge.py:388）
HARD_DEAD_BASELINE: frozenset[str] = frozenset({
    "bot_api_key_aiprc", "bot_api_key_aiprc_gemini", "bot_api_key_aiprc_grok",
    "bot_api_key_axonhub", "bot_api_key_deepseek_official", "bot_api_key_deepseek_qian",
    "bot_api_key_hcn", "bot_api_key_qianqianye", "bot_api_key_qianqianye_night",
    "bot_api_key_starapi", "bot_api_key_toolcode_gemini", "bot_api_key_toolcode_gpt",
    "bot_api_key_toolcode_grok", "bot_api_key_umi_claude", "bot_api_key_umi_group1",
    "bot_api_key_umi_group2", "bot_api_key_umi_group3", "bot_api_key_zhipu",
    "bot_moegirl_max_candidates", "bot_poke_admin_bypass",
    "bot_potccv_api_key", "bot_prompt_approval_digest", "bot_prompt_audit_enabled",
    "bot_prompt_audit_include_messages", "bot_prompt_audit_include_untrusted_context",
    "bot_prompt_audit_retention_days", "bot_prompt_execution_mode",
    "bot_runtime_alias_enabled",
    "bot_runtime_default_persona", "bot_schedule_delivery_enabled",
    "bot_schedule_timetable_enabled", "bot_search_langsearch_api_key",
# 2026-09-27 席 S-SWITCH-REG-IMPL 摘账一枚：`bot_schedule_enabled` 已不再零读点
#   （批⑦ 第 20 项日程板给它接上了消费点），按本桶「棘轮必须等于真值」口径出册。
    "bot_search_tinyfish_api_key", "bot_search_you_api_key", "bot_share_enabled",
    "bot_share_groups", "bot_share_read_only", "bot_subscribe_card_enabled",
    "bot_subscribe_jitter_ratio",
})
TEMPLATE_COVERED_BASELINE = 18
# 2026-09-25 席 MAIN-B1 现算复录（尺身份＝本件 `read_point_leg()`，复跑命令见上方 RERUN_COMMAND）：
#   38 → 39。逐格点名核过：这新增一枚**不是本波造成的**——本波八枚键
#   （`bot_llm_billing_enabled` + 七枚 `bot_axonhub_*`）全部走 `getattr(config, "<字面量>")`
#   真直读，压根不进 AST 零直读集；现算 39 格里的新成员落在 affinity v7 / sync_drift /
#   tts / channel-probe / creation 这些**他波在飞家族**里。按门自身口径（「棘轮不等于真值，重录它」）
#   复录到真值，归属照实写在这里，不冒充本波、也不替他波压地板。
# 2026-09-26 席 S-CONSENT-WIRE 现算复录 39 → 40：新增一枚＝`bot_safetyexec_enabled`
#   （第 18 项咽喉波登记真字段，键名字面住在 consent.py::ConsentPolicy.from_config
#   与 settings_gate.py 生产件里；归属本波，逐枚点名见 AST_DEAD 注释与本桶证据用例）。
LITERAL_COVERED_BASELINE = 43
# 2026-09-27 席 S-SWITCH-REG-IMPL（批⑦b 提交前复算）现算复录 40 → 43：新增三枚＝
#   `bot_schedule_enabled` / `bot_schedule_natural_capture_enabled` /
#   `bot_schedule_status_reply_enabled`——批⑦ 第 20 项日程板入库后**名字面在场**于
#   `domains/schedule/capabilities/schedule_board.py` 生产件（真直读维仍看不见它们⇒不落直读健康面），
#   归属照实写在这里、不冒领本波。
# 2026-09-27 同批复录待修总账 41 → 40、指纹 fa0cc598abc128e6 → 7d16b0a81871fd65：
#   出账一枚＝`bot_rate_limit_chat_sender_min_interval_seconds`——09-25 摘硬死那笔复录
#   写明了「待修总账 41 与指纹一字未动」，当日现算实为**该键已离开硬死∪绕中央并集**
#   （接线后它长出了真直读点），是基线落后真值一天数的旧账，非本波放宽；本席按
#   「棘轮必须等于真值」口径降到实况。
# 席 S77 两枚新桶：只从"AST 零直读"的残余里分类，**不给任何一枚发健康证**。
CENTRAL_NAMED_BASELINE = 1
CENTRAL_NAMED_SET_SHA = "18f47ea015589c42"
ENV_DIRECT_BASELINE = 1
ENV_DIRECT_SET_SHA = "8ce3202eecb11078"
# 待修总账＝硬死 ∪ 绕中央（挪桶不减债；只有真接上中央件消费点或裁键才许降）。
DEBT_ROSTER_BASELINE = 40
DEBT_ROSTER_SET_SHA = "7d16b0a81871fd65"
# 2026-09-26 席 S-CONSENT-WIRE（第 18 项咽喉接线波）现算复录 99 → 100：
#   唯一新增成员＝`bot_safetyexec_enabled`——咽喉波登记的真字段，读点形如
#   `ConsentPolicy.from_config` 的 `read("bot_safetyexec_enabled", ...)`（名字经
#   形参转手 ⇒ AST 直读尺结构上看不见，与 sync_drift 七枚同形），键名字面在场于
#   consent.py/settings_gate.py 生产件 ⇒ 落**字面桶**、不落硬死（待修总账 41 与
#   各指纹逐字未动，下方逐桶恒等式现场复算兜底）。
AST_DEAD_BASELINE = 102  # = 18 + 43 + 1 + 1 + 39（恒等式由 test_bucket_arithmetic_holds 现场核）
# 2026-09-27 席 S-SWITCH-REG-IMPL 现算复录 100 → 102：+3 全进字面桶（日程板三枚，
#   见上 LITERAL_COVERED 注）；同批 `bot_schedule_enabled` 长出真直读点摘硬死一枚
#   （AST 零直读集里它已消失），两笔相抵后恒等式现场复算成立。
# 2026-09-25 现算复录 101 → 100：`bot_rate_limit_chat_sender_min_interval_seconds`
# 这一枚**接上线了**（同波在 build_rate_limit_settings 补上读点 ⇒ 它不再是 AST 零直读，
# 已同时从 HARD_DEAD_BASELINE 摘牌）。这是"降到实况"而不是漏计：R3 同人 45 秒冷却
# 此前改 .env 完全无效，属第 2 项（消息被吞）的配套根修。
# 2026-09-26 席 E 现算复录 100 → 99（两笔各自独立、逐枚可点名的**接线**，不是放宽判据）：
#   −11 硬死：poke 跟戳 / 回复后戳人 + randpic 派发两族 11 枚键的值路径本来就活，
#     但门身 `proactive_action_allowed` 用 `getattr(config, f"{prefix}probability")`
#     动态取数 ⇒ 直读尺结构性看不见它们。修法＝四枚门参数改由调用点（根 `__init__.py`）
#     **按字面键名**取好、以 `ProactiveActionKnobs` 交进门身 ⇒ 硬死名册回到与基线
#     **逐枚等值**（现算 added=[] / removed=[]，待修总账 41 与指纹 fa0cc… 一字未动）。
#     防回潮锁＝`test_proactive_action_call_sites_pass_literal_knobs`。
#   −1 字面：一枚键从「只在字面表里」长出真直读点（他波在飞件，归属照实写在这里、
#     不冒领），故 LITERAL_COVERED_BASELINE 40 → 39。
# 四维地板同批复录到现算真值（739 / 1516 / 3 / 648）：字段 +19 ＝ P14 poke/randpic
# 族 14 枚 ＋ goal-12 meme 族 5 枚（两波都是**在册**新键，此前直读维看不见它们）；
# 直读维 +26 含本席 12 处字面门参数读点与他波读点；.py +6 ＝ meme 三件
# （send_history / meme_selection / shorekeeper_absorb）＋他波在飞件。
# 中央件"键名非字面量"的同形状读点数（不可归枚，只声明桶 4 覆盖面有界）：地板只升不降。
CENTRAL_DYNAMIC_SITE_FLOOR = 4
# 幽灵按名读点（向中央件取一个 Config 里不存在的键名）：现算 1 名 / 5 站点，**只准降不准升**。
GHOST_BY_NAME_BASELINE = 1
GHOST_BY_NAME_SET_SHA = "01daed191cb06480"
# 变瞎地板：四维＝(字段数, 直读点条数, 在册动态模板前缀数, 生产 .py 文件数)。容差只准收紧。
# 席 S157 按新字段集现算重录（S157_MEASURED_AT_UTC，尺身份见上方三元组＋复跑命令）：
#   字段 700→696（R-4 退役四枚 `*_via_queue`）、直读点 1462→1454（同批删的读点 8 处）、
#   模板前缀 3→3（未动）、生产 .py 630→634（他波在飞件，地板**收紧**到现算值）。
# 2026-09-25 席 MAIN-B1 复录（四维全部收紧到现算真值 708 / 1477 / 3 / 641）：
#   字段维 696→708：本波 +8（`bot_llm_billing_enabled` 从读点幽灵升真字段 + 七枚 `bot_axonhub_*`），
#     另 +4 属他波在飞件，照实计入真值不摘。
#   直读点维 1454→1477 / .py 维 634→641：**本波一度故意不动这两维**（怕把地板抬到别人的
#     中间态、他们一落地就红），结果被 `test_poison_11` 揭穿是错的——地板落后真值 23 时，
#     「一次性砍穿容差」那发注毒变成 `DID NOT RAISE`＝**这一维的检测力被自己的保守吃掉了**。
#     容差 200 未动 ⇒ 收紧后仍有 200 条余量，他波回退不会立刻红，红的是"集体变瞎"。
CORPUS_FLOOR_BASELINE = (748, 1541, 3, 654)  # 2026-09-27 席 S-SWITCH-REG-IMPL（批⑦b）现算复录字段维 746→748：
#   +2 ＝ `bot_schedule_natural_capture_enabled` / `bot_schedule_status_reply_enabled`，
#   随批⑦ 日程板 `6b57654` 入库（config.py 对 HEAD 现算零 diff，两枚按提交逐个 git show
#   归因；属已入库批次欠账，非本波引入）。
#   同批复录另两维（毒发 11 第一发以 1532−201 不红现形＝地板落后真值吃掉检测力）：
#   直读维 1532→1541 +9＝批⑤~⑧ 已入库接线新增的字面读点（日程板三键、出站限额、
#   吸收台账等，逐枚归属随各批登记）；.py 维 674→654 −20＝批⑤ `ec9b91b` 垫片退役
#   删 25 件、批⑥⑦ 回补新件净差 −20（git show --diff-filter=D 现算）。模板维 3 未动。
#   ——2026-09-26 席 S-FILESLAND-2 现算复录（四维＝现算真值）：
#   740→746 字段 +6＝本波 `bot_files_write_*` 五枚 + `bot_files_read_confined_max_bytes`
#   一枚（需求 16(2) 写盘口收编波，六枚四处同生已核：config.py 字段 / config-catalog
#   A26 增量区 / .env.example / RESTART_REQUIRED_KEYS，且六枚都有 `config.<字面量>` 形态
#   的**真直读点**（唯一读点 domains/files/capabilities/file_exchange.py 装配节）⇒ 六枚
#   逐枚现算不落任何债桶（hard_dead/env_direct/ast_dead/template/literal/central 全空）。
#   1524→1532 直读维 +8＝本波 7 处（上述六枚键在 file_exchange.py 的 7 个字面读点，
#   `bot_files_write_enabled` 两处各算一条）＋ 另 1 处属他波在飞件（本席不点名、不冒领）。
#   模板维 3 未动。672→674 生产 .py +2＝mtime 现算落在 05:17 之后的两枚新件
#   `chat_reply/policy/redrive_ledger.py`(05:59) 与 `domains/core/temporal_words.py`(07:00)，
#   **均非本波产物**（限流补回波 / 时刻词波）——按本门口径「四维必须等于现算」照实计入。
#   归属可点名的依据＝两枚 mtime：config.py 08:12 晚于本件上次落盘 05:17。
#   ——上一行原为 S-CONSENT-WIRE 复录（740/1524/3/672），其归属说明照原文留在下方
#   （历史记录只加限定、不改写）：
#   739→740 字段 +1＝本波 `bot_safetyexec_enabled`（第 18 项咽喉波登记真字段）；
#   1516→1524 直读维 +8 全属**他波在飞件**（本波对直读尺零贡献，新键走字面桶）；
#   模板维 3 未动；648→672 生产 .py +24 亦属他波在飞件（goal-18 safety_exec 九件、
#   files 波 sender 族等）——按本门口径「四维必须等于现算」复录，逐维归属照实写。
# 2026-09-25 分句折一轮/限流补回波复录（四维=现算真值，字段与模板维容差 0）：
#   708→720（本波 +12 枚配置键：折句五键 + 回执自适应四键 + 补回三键）、
#   1477→1490（直读维 +13：本波新增 message_coalescing.py 的读点与 rate_limit/
#   progress_ack 各新读口，另含他波在飞件——按本门口径"四维必须等于现算"复录，
#   逐维归属如上，不代他波降账）、641→642（py 文件 +1＝本波新件
#   domains/chat_reply/runtime/message_coalescing.py）。
CORPUS_FLOOR_SLACK = (0, 200, 0, 50)

# 热改面腿基线：数量 + 集合指纹（同刻现算）。指纹防"进 N 出 N 而数量不变"。
# 席 S157：四枚 `*_via_queue` 退役 ⇒ 未表态 572→568（四枚既不在 SETTABLE/RESTART、
# 也不在 W24 第三态台账，故它们**出册即出账**，不是"在册但不读"）。
# 现算尺＝本件 `hot_surface_leg` 三方对减，指纹尺＝本件 `_sha16`（都不写行号，理由见上）；
# 复跑命令见 `S157_MEASURED_AT_UTC` 上方注释块。
# 2026-09-26 席 S-ACG-SWITCH 现算复录 568 → 562、指纹 acbd185333c26a5b → ed6e20e6a08cc2c5：
# 六枚 `bot_search_acg_*` 补登记 SETTABLE_KEYS（ACG 竖源开关腿根修，chat.py 每消息
# get_or 现读、覆盖面此前无入口；同批 W24 门基线同步下调，两门读同一群键）。
# 2026-09-27 席 S-SWITCH-REG-IMPL（批⑦b 存量开关归册）现算复录 562 → 554、指纹
# ed6e20e6a08cc2c5 → cf3f5dac64820b65：八枚运行开关（TTS 双闸、表情库双闸、记忆总线、
# 好感度 v7、维基知识库、控制面）按 SWITCH-REG-PREP 判据全登 RESTART_REQUIRED_KEYS，
# 未表态 8 枚出账；同批 W24 门基线同步下调（两门读同一群键，见 test_third_state_authority_is_the_w24_ledger）。
UNACCOUNTED_BASELINE = 554
UNACCOUNTED_SET_SHA = "cf3f5dac64820b65"


# ---------------------------------------------------------------------------
# 取数（现场读盘，零写盘）
#
# **一趟全树 AST 扫描**同时喂「字面在场」（席 S56 的桶 3）与三种间接形状
# （席 S77 的桶 4/桶 5 + 两条旁证账）。合并前是两趟，本门跑时长从 ≈100s 涨到 ≈300s，
# 故把第二趟并回第一趟；两个缓存键（树身份）语义不变。
# ---------------------------------------------------------------------------
def _literal_pairs(root: str, config_py: str, scope_key: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """(键, 文件) 全清单——`_production_scan` 的一个投影。缓存键带**树身份**（root+config.py
    路径）：沙箱注毒各用不同 tmp_path，若只按 scope 缓存，第一发沙箱的结果会漏进第二发
    ＝用例互相依赖（本波栽过的同型病）。
    """
    return _production_scan(root, config_py, scope_key)[4]


def _string_constant_fields(scopes: list[str]) -> dict[str, list[str]]:
    pairs = _literal_pairs(str(census.REPO), str(census.CONFIG_PY), tuple(scopes))
    found: dict[str, set[str]] = {}
    for key, rel in pairs:
        found.setdefault(key, set()).add(rel)
    return {k: sorted(v) for k, v in sorted(found.items())}


def _template_prefixes(scopes: list[str]) -> frozenset[str]:
    return frozenset(
        d["template"] for d in census.dynamic_key_points(list(scopes))
        if d["template"].startswith("bot_")
    )


# ---------------------------------------------------------------------------
# 席 S77：两种"名字换过手"的间接形状（机械派生，零手写归属）
#
# 判据本体（谓词，可逐条复核）：
#   桶 4 central_named  ⇔ 存在 Call 节点，func 为 Attribute 且 attr == "get"，
#       第 1 实参是**字符串常量**且 `.strip().upper()` **逐字等于**某枚字段的大写名，
#       且第 2 实参经 `census._is_configish` 判为 configish（非 NON_PLUGIN_CONFIG_RECEIVERS）。
#       依据＝`settings.py:967 get()` 未命中 override 时 `getattr(config, key.lower(), None)`。
#       ⇒ `get_or` 不在列：`settings.py:974` 只读 override，从不碰 config。
#   桶 5 env_direct    ⇔ 存在 `os.getenv("<UPPER>")` / `os.environ.get("<UPPER>")` /
#       `os.environ["<UPPER>"]`，或模块级 `NAME = os.environ` 别名的同形读法。
#   旁证 central_dynamic ⇔ 与桶 4 **同形状**（attr == "get"、第 2 实参 configish）但第 1 实参
#       **不是**字符串常量（键名是算出来的）；不可归枚，只计数 ⇒ 声明桶 4 的覆盖面有界。
#   旁证 ghost_by_name ⇔ 同上形状、第 1 实参是常量但**对不上任何字段**且以 BOT_ 开头。
#       这类站点经 `get()` 的 `getattr(config, name, None)` 必然拿不到值（＝CM-P-24(b) 的
#       静默退 None 面在生产里的实际发生数）：只准降、不准升，新出现即点名红。
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def _production_scan(root: str, config_py: str, scope_key: tuple[str, ...]) -> tuple[
    dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], int, dict[str, tuple[str, ...]],
    tuple[tuple[str, str], ...],
]:
    """一趟 AST 扫出字面在场 + 三种间接形状 + 幽灵名。缓存键带**树身份**（同上一条的教训：
    只按 scope 缓存会让第一发沙箱的结果漏进第二发）。"""
    del root  # 只作缓存身份；实际走文件仍由 census.py_files 用同一棵 REPO（调用方保证一致）
    return _production_scan_uncached(list(scope_key), Path(config_py))


def _environ_aliases(tree: ast.Module) -> set[str]:
    """模块级 `NAME = os.environ` 别名（机械可判才认，函数内别名不认 ⇒ 只会少认不会多认）。"""
    names: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Attribute):
            continue
        if stmt.value.attr != "environ" or not isinstance(stmt.value.value, ast.Name):
            continue
        if stmt.value.value.id != "os":
            continue
        for tgt in stmt.targets:
            if isinstance(tgt, ast.Name):
                names.add(tgt.id)
    return names


def _is_environ_expr(node: ast.expr, aliases: set[str]) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "environ" \
            and isinstance(node.value, ast.Name) and node.value.id == "os":
        return True
    return isinstance(node, ast.Name) and node.id in aliases


def _reads_environment(node: ast.Call, aliases: set[str]) -> bool:
    """字面形态判"这行是在直读进程环境"：`os.getenv(...)` / `os.environ.get(...)` /
    `os.environ[...]`（含模块级 `NAME = os.environ` 别名）。`import os as x` 之类换名**不认**
    ⇒ 只会少认、不会多认。"""
    if not isinstance(node.func, ast.Attribute):
        return False
    recv = node.func.value
    if node.func.attr == "getenv":
        return (isinstance(recv, ast.Name) and recv.id == "os") or _is_environ_expr(recv, aliases)
    if node.func.attr == "get":
        return _is_environ_expr(recv, aliases) or (
            isinstance(recv, ast.Attribute) and recv.attr == "environ"
        )
    return False


def _field_by_env_name(name: str, upper_to_field: dict[str, str]) -> str | None:
    """**逐字**等值匹配（大写、去首尾空白）。不做前缀/词干匹配＝"名字对不上也算读到"的入口。"""
    return upper_to_field.get(name.strip().upper())


def _production_scan_uncached(scopes: list[str], config_py: Path) -> tuple[
    dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], int, dict[str, tuple[str, ...]],
    tuple[tuple[str, str], ...],
]:
    fields = set(census.config_fields())
    upper_to_field = {name.upper(): name for name in fields}
    central: dict[str, list[str]] = {}
    env: dict[str, list[str]] = {}
    ghosts: dict[str, list[str]] = {}
    pairs: list[tuple[str, str]] = []
    dynamic = 0
    for path in census.py_files(scopes):
        if path == config_py:
            continue  # config.py 自家自引用不算读点（与字面桶同一条边界）
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(census.REPO).as_posix()
        # —— 桶 3（字面在场）：与席 S56 的判据逐字同形，只搬进同一趟扫描 ——
        present = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        } & fields
        pairs.extend((key, rel) for key in sorted(present))
        # —— 桶 4/5 与两条旁证账 ——
        aliases = _environ_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and _is_environ_expr(node.value, aliases):
                key = node.slice.value if isinstance(node.slice, ast.Constant) else None
                if isinstance(key, str) and key.strip().upper() not in upper_to_field:
                    continue  # 非 BOT_* 在册形态的环境变量，与本门无关
                field = _field_by_env_name(key, upper_to_field) if isinstance(key, str) else None
                if field:
                    env.setdefault(field, []).append(f"{rel}:{node.lineno} environ[...]")
                elif isinstance(key, str):
                    ghosts.setdefault(key.strip().upper(), []).append(f"{rel}:{node.lineno} environ[...]")
                continue
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr, recv = node.func.attr, node.func.value
            on_environ = _reads_environment(node, aliases)
            first = node.args[0] if node.args else None
            literal = census._const_str(first) if first is not None else None
            field = _field_by_env_name(literal, upper_to_field) if isinstance(literal, str) else None
            if attr in {"getenv", "get"} and on_environ:
                if field:
                    env.setdefault(field, []).append(f"{rel}:{node.lineno} {ast.unparse(node)[:60]}")
                continue
            if attr == "get" and isinstance(literal, str) and len(node.args) >= 2 \
                    and census._is_configish(node.args[1], rel):
                # 中央件"按名取值"站点：**逐字**对上字段才记读点，对不上就记幽灵
                # （CM-P-24(b) 的可见面——拼错键名会静默退 None，这里先让它出账）。
                if field:
                    central.setdefault(field, []).append(
                        f'{rel}:{node.lineno} recv={ast.unparse(recv)[:32]}.get("{literal}", ...)'
                    )
                elif literal.strip().upper().startswith("BOT_"):
                    ghosts.setdefault(literal.strip().upper(), []).append(
                        f'{rel}:{node.lineno} recv={ast.unparse(recv)[:32]}.get("{literal}", ...)'
                    )
                continue
            if attr == "get" and first is not None and not isinstance(first, ast.Constant) \
                    and len(node.args) >= 2 and census._is_configish(node.args[1], rel):
                # 与桶 4 **同形状**、只是键名是算出来的 ⇒ 归不到枚，只计数（覆盖面自证）。
                dynamic += 1
    return (
        {k: tuple(v) for k, v in sorted(central.items())},
        {k: tuple(v) for k, v in sorted(env.items())},
        dynamic,
        {k: tuple(v) for k, v in sorted(ghosts.items())},
        tuple(sorted(pairs)),
    )


def central_named_sites(scopes: list[str] | None = None) -> dict[str, tuple[str, ...]]:
    used = tuple(scopes or census.DEFAULT_SCOPES)
    return _production_scan(str(census.REPO), str(census.CONFIG_PY), used)[0]


def env_direct_sites(scopes: list[str] | None = None) -> dict[str, tuple[str, ...]]:
    used = tuple(scopes or census.DEFAULT_SCOPES)
    return _production_scan(str(census.REPO), str(census.CONFIG_PY), used)[1]


def central_dynamic_site_count(scopes: list[str] | None = None) -> int:
    used = tuple(scopes or census.DEFAULT_SCOPES)
    return _production_scan(str(census.REPO), str(census.CONFIG_PY), used)[2]


def ghost_by_name_sites(scopes: list[str] | None = None) -> dict[str, tuple[str, ...]]:
    """按名取值站点里"名字对不上任何字段"的那批（只准降不准升，见常驻用例）。"""
    used = tuple(scopes or census.DEFAULT_SCOPES)
    return _production_scan(str(census.REPO), str(census.CONFIG_PY), used)[3]


def bucketize(
    ast_dead: set[str],
    literals: set[str],
    templates: frozenset[str],
    central: set[str] | None = None,
    env_direct: set[str] | None = None,
) -> dict[str, frozenset[str]]:
    """判据本体（纯函数，喂合成集即可测杀伤力）：AST 零直读集 → 五桶，互斥且穷尽。

    优先级 模板 > 字面 > 中央按名 > 绕中央 > 真无人读。两枚新桶**只从残余里分类**，
    故既不动 S56 那两桶的语义与基线，也不给任何一枚发健康证。
    """
    central = central or set()
    env_direct = env_direct or set()
    templated = {k for k in ast_dead if any(k.startswith(prefix) for prefix in templates)}
    literal_only = {k for k in ast_dead if k not in templated and k in literals}
    residual = ast_dead - templated - literal_only
    centered = {k for k in residual if k in central}
    envied = {k for k in residual if k not in centered and k in env_direct}
    return {
        "ast_dead": frozenset(ast_dead),
        "template_covered": frozenset(templated),
        "literal_covered": frozenset(literal_only),
        "central_named": frozenset(centered),
        "env_direct": frozenset(envied),
        "hard_dead": frozenset(residual - centered - envied),
    }


def read_point_leg(scopes: list[str] | None = None) -> dict[str, Any]:
    """现算读点腿：五桶 + 地板输入 + 逐枚字面/间接归属（供点名与自锁）。"""
    used = list(scopes or census.DEFAULT_SCOPES)
    fields = set(census.config_fields())
    literals = _string_constant_fields(used)
    central = central_named_sites(used)
    env = env_direct_sites(used)
    buckets = bucketize(
        set(census.dead_config_keys(used)), set(literals), _template_prefixes(used),
        set(central), set(env),
    )
    attr, getatt, dyn, _exc = census.scan(used)
    return {
        "buckets": buckets,
        "fields": len(fields),
        "direct_reads": len(attr) + len(getatt),
        "dynamic_sites": len(dyn),
        "literal_files": literals,
        "templates": sorted(_template_prefixes(used)),
        "central_sites": central,
        "env_sites": env,
        "ghost_sites": ghost_by_name_sites(used),
        "central_dynamic_sites": central_dynamic_site_count(used),
    }


def debt_roster(buckets: dict[str, frozenset[str]]) -> frozenset[str]:
    """待修总账＝硬死 ∪ 绕中央。把一枚键从前一桶挪进后一桶**不减**债，只有接上真消费点才减。"""
    return buckets["hard_dead"] | buckets["env_direct"]


def _sha16(names: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()[:16]


def assert_corpus_not_blind(sizes: tuple[int, int, int, int]) -> None:
    """解析面一瞎四桶就集体"恒绿"，所以先量尺子本身；地板由基线派生，不另记一组数。"""
    names = ("Config 字段数", "直读点条数", "在册动态模板前缀数", "生产 .py 文件数")
    for index, (got, base, slack, name) in enumerate(
        zip(sizes, CORPUS_FLOOR_BASELINE, CORPUS_FLOOR_SLACK, names, strict=True)
    ):
        assert got >= base - slack, (
            f"{name} 现算 {got}，低于地板 {base - slack}（基线 {base} − 容差 {slack}）⇒ 门正在变瞎"
        )
        assert 0 <= slack <= base, f"地板容差本身不合法（第 {index} 维）：{slack}/{base}"


def hot_surface_leg(source: str | None = None) -> dict[str, Any]:
    """现算热改面腿：逐枚字段 → 状态集；两表同现 → 点名（pilot 的异常接成可断言的红）。"""
    text = SETTINGS_PY.read_text(encoding="utf-8") if source is None else source
    overlap_error: list[str] = []
    try:
        tiers = load_hot_tiers(text)
    except UnrepresentableField as exc:  # 不可判态 ⇒ 判红并带原文（原文自带重叠键名清单）
        tiers, overlap_error = {}, [str(exc)]
    fields = set(load_config_fields())
    declared = set(w24.DELIBERATELY_UNLISTED)
    settable = {k for k, v in tiers.items() if v == "settable"}
    restart = {k for k, v in tiers.items() if v == "restart"}
    unaccounted = fields - settable - restart - declared
    return {
        "fields": fields, "settable": settable, "restart": restart, "declared": declared,
        "unaccounted": unaccounted,
        "both": sorted(fields & settable & restart), "overlap_error": overlap_error,
        "sha16": _sha16(unaccounted),
    }


def state_of(key: str, leg: dict[str, Any]) -> set[str]:
    """一枚键的热改面状态集：恰好 1 ＝ 有唯一表态；0 ＝ 未声明；>1 ＝ 自相矛盾。"""
    states: set[str] = set()
    if key in leg["settable"]:
        states.add("settable")
    if key in leg["restart"]:
        states.add("restart")
    if key in leg["declared"]:
        states.add("deliberately-unlisted")
    return states


# ---------------------------------------------------------------------------
# 读点腿
# ---------------------------------------------------------------------------
def test_read_point_leg_is_not_blind() -> None:
    leg = read_point_leg()
    files = sum(1 for _ in census.py_files(list(census.DEFAULT_SCOPES)))
    assert_corpus_not_blind((leg["fields"], leg["direct_reads"], len(leg["templates"]), files))
    assert leg["dynamic_sites"] > 0, "动态读点站点为 0 ⇒ census 对 getattr 形态已瞎"


def test_bucket_arithmetic_holds() -> None:
    """**总账恒等式**：五桶两两互斥且穷尽 AST 零直读集，枚数之和 == 基线，漏计一枚当场红。"""
    buckets = read_point_leg()["buckets"]
    names = ("template_covered", "literal_covered", "central_named", "env_direct", "hard_dead")
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            assert buckets[left] & buckets[right] == frozenset(), f"{left} 与 {right} 不互斥"
    union = frozenset().union(*(buckets[name] for name in names))
    assert union == buckets["ast_dead"], "桶划分没穷尽 AST 零直读集 ⇒ 有键被静默丢掉"
    total = sum(len(buckets[name]) for name in names)
    assert total == len(buckets["ast_dead"]) == AST_DEAD_BASELINE, (
        f"五桶之和 {total} / AST 零直读 {len(buckets['ast_dead'])} / 基线 {AST_DEAD_BASELINE} 不等"
        " ⇒ 要么漏计一枚（判据被绕），要么有人接了线（把各桶基线一起降到实况）："
        + "｜".join(f"{name}={len(buckets[name])}" for name in names)
    )
    # 两枚新桶只准**分类**：成员必须仍在"AST 零直读"集里，绝不偷偷长出直读点。
    assert buckets["central_named"] <= buckets["ast_dead"]
    assert buckets["env_direct"] <= buckets["ast_dead"]


def test_hard_dead_keys_are_named_and_ratcheted() -> None:
    """硬死桶＝违规名册：逐枚点名，只降不升，且集合必须等于基线（换一枚也算动账）。"""
    live = read_point_leg()["buckets"]["hard_dead"]
    added = sorted(live - HARD_DEAD_BASELINE)
    removed = sorted(HARD_DEAD_BASELINE - live)
    assert not added, (
        f"新增零读点配置键（登记即无人读＝静默失效预备役）：{added}"
        "｜处置＝接上消费点；或确属休眠预留（R65 口径）则点名并入基线、说明为何值得留"
    )
    assert not removed, f"这些键已不再零读点，请把基线摘账（棘轮必须等于真值）：{removed}"
    assert live == HARD_DEAD_BASELINE


def test_indirect_coverage_buckets_are_ratcheted() -> None:
    """模板桶 / 字面桶各自钉数：面在缩水（动态读法改直读）是好事 ⇒ 降到实况。"""
    buckets = read_point_leg()["buckets"]
    assert len(buckets["template_covered"]) == TEMPLATE_COVERED_BASELINE, (
        f"动态模板覆盖现算 {len(buckets['template_covered'])} ≠ 基线 {TEMPLATE_COVERED_BASELINE}"
    )
    assert len(buckets["literal_covered"]) == LITERAL_COVERED_BASELINE, (
        f"字面覆盖现算 {len(buckets['literal_covered'])} ≠ 基线 {LITERAL_COVERED_BASELINE}"
    )


def test_literal_coverage_names_its_evidence() -> None:
    """字面桶不得变藏污所：每枚都说得出**哪个文件**里有它的字面，且那文件不是测试。"""
    leg = read_point_leg()
    for key in sorted(leg["buckets"]["literal_covered"]):
        files = leg["literal_files"].get(key) or []
        assert files, f"{key} 进了字面桶却给不出在场文件 ⇒ 判据被绕"
        assert all(not f.startswith("tests/") for f in files), (
            f"{key} 的在场证据落在 tests/（测试里的读点不算）：{files}"
        )


def test_two_field_authorities_agree() -> None:
    """字段两把尺必须同值，否则两腿量的不是同一群键。"""
    assert set(census.config_fields()) == set(load_config_fields())


# ---------------------------------------------------------------------------
# 两枚新桶（席 S77）：只分类、不发健康证
# ---------------------------------------------------------------------------
def test_central_named_bucket_is_ratcheted_with_fingerprint() -> None:
    """桶 4 钉数量 **和** 集合指纹：进一枚出一枚也抓得到（同 W24 未表态面的手法）。"""
    buckets = read_point_leg()["buckets"]
    assert len(buckets["central_named"]) == CENTRAL_NAMED_BASELINE, (
        f"中央按名读现算 {len(buckets['central_named'])} 枚 ≠ 基线 {CENTRAL_NAMED_BASELINE}。"
        "变多 ⇒ 有人把消费点从直读改成按名取值（值路径仍活，但直读面缩了：把各桶基线一起对齐）；"
        "变少 ⇒ 那枚键的中央件消费行没了，它必须掉回硬死并当场红"
    )
    assert _sha16(buckets["central_named"]) == CENTRAL_NAMED_SET_SHA, (
        f"桶 4 **集合**指纹漂了（现算 {_sha16(buckets['central_named'])} ≠ 基线 {CENTRAL_NAMED_SET_SHA}）"
        "而数量没变 ⇒ 有人进一枚出一一枚洗白：逐枚对账后重钉"
    )


def test_central_named_bucket_names_its_evidence() -> None:
    """桶 4 的每一枚都要给得出 `文件:行号` 消费点，且那行里逐字写着它的大写 env 名。"""
    leg = read_point_leg()
    fields = set(census.config_fields())
    for key in sorted(leg["buckets"]["central_named"]):
        sites = leg["central_sites"].get(key) or []
        assert sites, f"{key} 进了桶 4 却没有消费点 ⇒ 判据被绕（或有人手写了归属）"
        for site in sites:
            assert not site.startswith("tests/"), f"{key} 的证据落在 tests/：{site}"
            path, rest = site.split(":", 1)
            line_no = int(rest.split(" ", 1)[0])
            text = (census.REPO / path).read_text(encoding="utf-8-sig").splitlines()[line_no - 1]
            assert key.upper() in text and ".get(" in text, (
                f"{key} 的证据行 {site} 里逐字看不到 {key.upper()} 与 .get( ⇒ 桶 4 在凭别的东西发活性"
            )
    # 反向自锁：桶 4 成员必须是**在册字段**（名字对不上也算读到＝这条必红）。
    assert set(leg["central_sites"]) <= fields, (
        f"扫出来的「按名读」键里有不在 Config 的名：{sorted(set(leg['central_sites']) - fields)}"
    )


def test_env_direct_bucket_is_debt_not_health() -> None:
    """桶 5 是**债**：它不得计入健康面，且待修总账（硬死 ∪ 桶 5）数量与指纹双双钉死。"""
    leg = read_point_leg()
    buckets = leg["buckets"]
    debt = debt_roster(buckets)
    assert len(debt) == DEBT_ROSTER_BASELINE, (
        f"待修总账现算 {len(debt)} 枚 ≠ 基线 {DEBT_ROSTER_BASELINE}（= 硬死 {len(buckets['hard_dead'])}"
        f" ＋ 绕中央 {len(buckets['env_direct'])}）⇒ 挪桶不减债，只有接上中央件消费点或裁键才许降"
    )
    assert _sha16(debt) == DEBT_ROSTER_SET_SHA, (
        f"待修总账**集合**指纹漂了（现算 {_sha16(debt)} ≠ 基线 {DEBT_ROSTER_SET_SHA}）而数量没变"
    )
    # 桶 5 的成员同时必须出现在环境直读证据里（防"名字进来了、其实是别的形状"）。
    for key in sorted(buckets["env_direct"]):
        assert leg["env_sites"].get(key), f"{key} 进了桶 5 却没有 os.environ/os.getenv 证据"
    # 健康面只有"直读"一维：桶 4/桶 5 谁都不许给它加分（独立复算，不走桶划分那条边）。
    attr, getatt, _dyn, _exc = census.scan(list(census.DEFAULT_SCOPES))
    directly_read = {hit["key"] for hit in attr} | {hit["key"] for hit in getatt}
    for name in ("central_named", "env_direct"):
        assert not (buckets[name] & directly_read), f"{name} 里有直读成员 ⇒ 桶名写错了：{sorted(buckets[name] & directly_read)}"
        assert buckets[name] & buckets["template_covered"] == frozenset()
        assert buckets[name] <= buckets["ast_dead"], f"{name} 长出了 AST 直读成员 ⇒ 它在偷偷发健康证"


def test_dynamic_named_central_sites_are_counted() -> None:
    """键名非字面量的中央件读法**不可归枚**：只计数并钉地板，声明桶 4 的覆盖面有界。"""
    count = central_dynamic_site_count()
    assert count >= CENTRAL_DYNAMIC_SITE_FLOOR, (
        f"中央件动态键名读点现算 {count}，低于地板 {CENTRAL_DYNAMIC_SITE_FLOOR} ⇒ 扫描面缩了，"
        "或这些读法被逐枚钉死成常量（那属于桶 4 覆盖面扩大，同步上调地板并在报告留账）"
    )


def test_ghost_by_name_sites_are_named_and_ratcheted() -> None:
    """向中央件按名取一个 Config 里**不存在**的键＝`getattr(config, name, None)` 必拿不到值。
    这是 CM-P-24(b) 那面"拼错不响"的账在今天的实际发生数：只准降，枚数与指纹双双钉死。"""
    ghosts = read_point_leg()["ghost_sites"]
    assert len(ghosts) == GHOST_BY_NAME_BASELINE, (
        f"幽灵按名读点现算 {len(ghosts)} 名 ≠ 基线 {GHOST_BY_NAME_BASELINE}（名单：{sorted(ghosts)}）。"
        "变多 ⇒ 有人新增了一条「向中央件取不存在的键」的读法：若它是**故意的**纯运行时键"
        "（先例 BOT_MUSIC_MODE，见 docs/config-catalog-full.md 明写「config.py 无此字段」），"
        "那就登记进目录后重钉本基线；若是**拼错**，它会静默退 None，必须改名或补字段。"
        "本门分不清这两种，正是 CM-P-24(b) 待裁的那句。变少 ⇒ 摘了账，枚数与指纹一起降到实况"
    )
    assert _sha16(ghosts) == GHOST_BY_NAME_SET_SHA, (
        f"幽灵名**集合**指纹漂了（现算 {_sha16(ghosts)} ≠ 基线 {GHOST_BY_NAME_SET_SHA}）而数量没变"
        " ⇒ 换了一枚幽灵顶上去：逐名对账后重钉"
    )
    for name, sites in sorted(ghosts.items()):
        assert sites, f"{name} 被判幽灵却给不出站点"


# ---------------------------------------------------------------------------
# 热改面腿
# ---------------------------------------------------------------------------
def test_no_field_sits_in_both_hot_lists() -> None:
    leg = hot_surface_leg()
    assert not leg["overlap_error"], f"同键两表 ⇒ 热改档位无唯一真值：{leg['overlap_error']}"
    assert not leg["both"], f"这些字段同时在两张热改名单里：{leg['both']}"


def test_every_field_has_exactly_one_hot_surface_state() -> None:
    """逐枚表态：状态数 ≠1 的字段全部点名；未表态集合钉数量 + 指纹（只降不升且等于真值）。"""
    leg = hot_surface_leg()
    both = sorted(k for k in leg["fields"] if len(state_of(k, leg)) > 1)
    assert not both, f"这些字段有多个热改表态（自相矛盾）：{both}"
    unaccounted = leg["unaccounted"]
    assert len(unaccounted) == UNACCOUNTED_BASELINE, (
        f"对热改面未表态的字段现算 {len(unaccounted)} 枚，基线 {UNACCOUNTED_BASELINE}。"
        "变多 ⇒ 新字段既没进 SETTABLE_KEYS/RESTART_REQUIRED_KEYS、也没写进 W24 第三态台账："
        "三条出路 ①有合并层实时读点→SETTABLE ②装配期冻结→RESTART ③确不开放→进那张台账"
        "（本席禁写该件，故只点名不代修）。"
        f"样例（名字序前 8 枚）：{sorted(unaccounted)[:8]}"
    )
    assert leg["sha16"] == UNACCOUNTED_SET_SHA, (
        f"未表态**集合**指纹漂了（现算 {leg['sha16']} ≠ 基线 {UNACCOUNTED_SET_SHA}）而数量没变"
        " ⇒ 有人进 N 枚出 N 枚洗白：逐枚对账后重钉指纹与数量"
    )


def test_third_state_authority_is_the_w24_ledger() -> None:
    """第三态只有一个真身；两门基线差值打印出来供对账（本席禁写那件，故不硬绑）。"""
    leg = hot_surface_leg()
    assert leg["declared"] == set(w24.DELIBERATELY_UNLISTED)
    assert len(leg["declared"]) == w24.DELIBERATELY_UNLISTED_BASELINE, (
        "W24 的第三态台账连它自己的基线都不一致 ⇒ 那门已红，先修它再来动本门"
    )
    drift = len(leg["unaccounted"]) - w24.UNACCOUNTED_BASELINE
    assert drift >= 0, (
        f"本门现算未表态 {len(leg['unaccounted'])} < W24 基线 {w24.UNACCOUNTED_BASELINE}"
        " ⇒ 两门读的不是同一群键（字段真身分叉），不是简单的账没跟上"
    )
    print(f"[两门对账] 本门未表态 {len(leg['unaccounted'])}｜W24 基线 {w24.UNACCOUNTED_BASELINE}"
          f"｜差 {drift}（≠0 时两门基线须同步下调）")


def test_hot_lists_are_not_self_satisfying() -> None:
    """两表非空 + 判据真读 source：换成空文本必须看到"两表皆无"的形状。"""
    leg = hot_surface_leg()
    assert len(leg["settable"]) >= 40 and len(leg["restart"]) >= 60, "热改两表提取面塌了"
    empty = hot_surface_leg("x = 1\n")
    assert empty["settable"] == set() and empty["restart"] == set()
    # 两表读空 ⇒ 未表态＝字段全集减去第三态台账（台账不参与"名单读空"这件事）
    assert len(empty["unaccounted"]) == len(leg["fields"]) - len(leg["declared"] & leg["fields"])
    assert len(empty["unaccounted"]) > len(leg["unaccounted"]), "读空反而更少 ⇒ 判据在编造名单"


# ---------------------------------------------------------------------------
# 注毒（简报要求的 3 发 + 覆盖面自证 4 发；逐发验牙）
#
# 全在**临时副本 / 进程内文本**上做：读点腿用 tmp_path 合成树（monkeypatch census.REPO/
# CONFIG_PY，照 S-PHANTOM 门先例），热改面腿把 settings.py 的**内存文本**喂 hot_surface_leg。
# 真 config.py / settings.py 一字节都不写，每发自带 sha 自证。
# ---------------------------------------------------------------------------
POISON_UNREAD = "bot_s56_poison_unread"
POISON_COMMENTED = "bot_s56_poison_commented"
POISON_TABLE = "bot_s56_poison_table"
# 动态模板：键名必须以模板前缀**打头且更长**（真树先例 bot_subscribe_platform_ → …_bilibili）。
POISON_TEMPLATE_PREFIX = "bot_s56_poison_dyn_"
POISON_TEMPLATE = POISON_TEMPLATE_PREFIX + "covered"
# 席 S77 三枚新形状：中央按名读 / 绕中央直读环境（getenv 与 environ[] 两式）/ 名字对不上的幽灵。
POISON_CENTRAL = "bot_s77_poison_central"
POISON_ENV = "bot_s77_poison_env"
POISON_ENV_SUB = "bot_s77_poison_env_sub"
POISON_GHOST_NEAR = "bot_s77_ghost_near"
POISON_GHOST_NAME = "BOT_S77_GHOST_NO_FIELD"  # 全树无此字段，只在消费点里出现
# 席 S157：裁定 R-4 退役的四枚开关（本门把「退役彻底」与「不许改判成在册但不读」双双锁死）。
RETIRED_VIA_QUEUE_KEYS: tuple[str, ...] = (
    "bot_group_welcome_via_queue",
    "bot_cookie_qr_via_queue",
    "bot_cookie_expiry_reminder_via_queue",
    "bot_file_export_via_queue",
)

SANDBOX_CONFIG_SRC = (
    "from pydantic import BaseModel\n\n\n"
    "class Config(BaseModel):\n"
    "    bot_real_direct: bool = True\n"
    "    bot_real_literal: bool = True\n"
    f"    {POISON_UNREAD}: bool = False\n"
    f"    {POISON_COMMENTED}: bool = False\n"
    f"    {POISON_TABLE}: str = ''\n"
    f"    {POISON_TEMPLATE}: str = ''\n"
    f"    {POISON_CENTRAL}: str = ''\n"
    f"    {POISON_ENV}: str = ''\n"
    f"    {POISON_ENV_SUB}: str = ''\n"
    f"    {POISON_GHOST_NEAR}: str = ''\n"
)
# 直读 1 枚；字面表 2 枚（含 1 枚真字段，用来证明桶不是只看直读）；
# 注释 1 枚（毒）；f-string 模板 1 枚（毒）；完全无人读 1 枚（毒）；
# 席 S77 追加：中央按名读 1 枚、绕中央 getenv 1 枚、绕中央 environ[] 1 枚、名字对不上 1 枚（毒）。
SANDBOX_CONSUMER_SRC = f'''
import os


def read_direct(config):
    return config.bot_real_direct


KEY_TABLE = ("bot_real_literal",)


def uses_literal(sink):
    return sink.get("bot_real_literal") or sink.get("{POISON_TABLE}")


def commented_out():
    return None


# {POISON_COMMENTED} 只出现在注释里，不是读点
def dynamic(config, name):
    return getattr(config, f"{POISON_TEMPLATE_PREFIX}{{name}}", None)


def central_named_read(store, config):
    return store.get("{POISON_CENTRAL.upper()}", config)


def ghost_named_read(store, config):
    return store.get("{POISON_GHOST_NAME}", config)


def env_direct_read():
    return os.getenv("{POISON_ENV.upper()}")


def environ_subscript_read():
    return os.environ["{POISON_ENV_SUB.upper()}"]
'''


def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    pkg = tmp_path / "plugins" / "bot_unified_runtime"
    pkg.mkdir(parents=True)
    cfg = pkg / "config.py"
    cfg.write_text(SANDBOX_CONFIG_SRC, encoding="utf-8")
    (pkg / "consumer.py").write_text(SANDBOX_CONSUMER_SRC, encoding="utf-8")
    monkeypatch.setattr(census, "REPO", tmp_path)
    monkeypatch.setattr(census, "CONFIG_PY", cfg)
    return read_point_leg(["plugins"])


def _sha_now(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_untouched(before: dict[Path, str]) -> None:
    moved = [str(p) for p, h in before.items() if _sha_now(p) != h]
    assert not moved, f"注毒落到真文件了！sha 变化：{moved}"


def test_poison_1_unread_field_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 1（简报①）：config.py 多一枚无人读的键 ⇒ 读点腿硬死桶点名它。"""
    before = {CONFIG_UNDER_TEST: _sha_now(CONFIG_UNDER_TEST), SETTINGS_UNDER_TEST: _sha_now(SETTINGS_UNDER_TEST)}
    real_hard = read_point_leg()["buckets"]["hard_dead"]  # 必须在沙箱接管 census 之前取，否则量到的是沙箱自己
    buckets = _sandbox(tmp_path, monkeypatch)["buckets"]
    # 席 S77 起沙箱多出 POISON_GHOST_NEAR 一枚（消费点名字对不上字段）：它仍算无人读 ⇒ 名册 +1。
    assert buckets["hard_dead"] == frozenset({POISON_UNREAD, POISON_COMMENTED, POISON_GHOST_NEAR}), (
        f"硬死桶不符预期：{sorted(buckets['hard_dead'])}"
    )
    assert POISON_UNREAD in buckets["hard_dead"]
    assert POISON_UNREAD not in real_hard and buckets["hard_dead"] != real_hard, (
        "沙箱与真树同形 ⇒ 本毒在空跑"
    )
    # 牙口打在**真身用例**上：毒树喂进去，那条常驻断言必须红（写死答案的门不会红）。
    with pytest.raises(AssertionError):
        test_hard_dead_keys_are_named_and_ratcheted()
    _assert_untouched(before)


def test_poison_1b_comment_mention_is_not_a_read_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 1b（覆盖面）：只在注释里出现 ⇒ 仍算零读点（注释洗白必被点名）。"""
    buckets = _sandbox(tmp_path, monkeypatch)["buckets"]
    assert POISON_COMMENTED in buckets["hard_dead"], "注释里的字面被当成读点 ⇒ 判据可被洗白"


def test_poison_1c_string_table_counts_as_read_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 1c（覆盖面）：键名以字符串常量进表 ⇒ 进字面桶、**不**进硬死桶。

    这一发是本腿不假红的关键：真树里 sync_drift 七枚走的正是这条边
    （`_config_get(config, "bot_sync_drift_surfaces", …)`）。把它判成死键 ⇒ 门一出生就红 7 枚
    ⇒ 下一个 AI 做的第一件事是把它调松。
    """
    buckets = _sandbox(tmp_path, monkeypatch)["buckets"]
    assert POISON_TABLE in buckets["literal_covered"], "字面在场的键被误判死 ⇒ 门会假红一片"
    assert POISON_TABLE not in buckets["hard_dead"]
    assert "bot_real_literal" in buckets["literal_covered"], "只住在读点表里的真字段被判死 ⇒ 同上"
    assert POISON_TEMPLATE in buckets["template_covered"], "f-string 动态读点未覆盖 ⇒ 误判成死键"
    # 席 S77 追加四枚沙箱字段后，AST 零直读集从 5 枚长到 9 枚（沙箱夹具扩大，判据未放松）。
    assert buckets["ast_dead"] == frozenset({
        POISON_UNREAD, POISON_COMMENTED, POISON_TABLE, POISON_TEMPLATE, "bot_real_literal",
        POISON_CENTRAL, POISON_ENV, POISON_ENV_SUB, POISON_GHOST_NEAR,
    })


def test_poison_1d_blind_direct_scanner_is_named_by_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """毒发 1d（覆盖面自证）：把直读扫描换成空表 ⇒ 地板必须红，而不是"字段都在字面桶里"地绿。"""
    original = census.scan
    census.scan = lambda scopes=(): ([], [], [], [])  # type: ignore[assignment,misc]
    try:
        leg = read_point_leg()
        assert leg["direct_reads"] == 0, "注毒没生效 ⇒ 这一发在空跑"
        with pytest.raises(AssertionError):
            test_read_point_leg_is_not_blind()
        # 桶划分的兜底层仍在动：字面桶走本门自己那趟 AST，不随 census.scan 一起瞎。
        assert leg["buckets"]["literal_covered"], "直读面塌了而字面桶也空 ⇒ 两桶共用同一把尺，双瞎"
    finally:
        census.scan = original
    test_read_point_leg_is_not_blind()


def _poisoned_settings_copy(tmp_path: Path, text: str) -> Path:
    """把注毒后的 settings 源码落到 **tmp 副本**（真件只读），供真身用例吃同一份文本。"""
    copy = tmp_path / "settings_poison_copy.py"
    copy.write_text(text, encoding="utf-8")
    return copy


def test_poison_2_key_in_both_hot_lists_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 2（简报②）：某枚键同时塞进两表 ⇒ 热改面腿点名（pilot 异常接成红，不是 error）。"""
    before = {SETTINGS_UNDER_TEST: _sha_now(SETTINGS_UNDER_TEST)}
    real = SETTINGS_PY.read_text(encoding="utf-8")
    victim = min(hot_surface_leg(real)["settable"])
    poisoned = real.replace(
        "RESTART_REQUIRED_KEYS: dict[str, str] = {\n",
        f'RESTART_REQUIRED_KEYS: dict[str, str] = {{\n    "{victim.upper()}": "席 S56 注毒",\n',
        1,
    )
    assert poisoned != real, "注毒替换未生效 ⇒ 这一发在空跑"
    leg = hot_surface_leg(poisoned)
    assert leg["overlap_error"], "两表同现竟然无表态冲突 ⇒ 本腿没读两表"
    assert victim in leg["overlap_error"][0], f"报错没点出受害键：{leg['overlap_error']}"
    assert hot_surface_leg(real)["overlap_error"] == [], "真树本来就有同现键 ⇒ 本毒在空跑"
    # 牙口打在真身用例上：把副本喂给门自己的取数路径，两条常驻断言必须红。
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "SETTINGS_PY", _poisoned_settings_copy(tmp_path, poisoned))
    with pytest.raises(AssertionError):
        module.test_no_field_sits_in_both_hot_lists()
    with pytest.raises(AssertionError):
        module.test_every_field_has_exactly_one_hot_surface_state()
    _assert_untouched(before)


def test_poison_3_key_removed_from_both_lists_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 3（简报③）：某枚已表态的键从两表都删掉 ⇒ 未表态集合 +1，数量与指纹双双不放过。"""
    before = {SETTINGS_UNDER_TEST: _sha_now(SETTINGS_UNDER_TEST)}
    real = SETTINGS_PY.read_text(encoding="utf-8")
    leg_real = hot_surface_leg(real)
    victim = min(leg_real["settable"])
    poisoned = real.replace(f'"{victim.upper()}"', '"BOT_S56_UNRELATED_RENAMED"', 1)
    assert poisoned != real, "注毒替换未生效 ⇒ 这一发在空跑"
    leg = hot_surface_leg(poisoned)
    assert victim in leg["unaccounted"] and victim not in leg_real["unaccounted"], "删表未致无表态 ⇒ 判据假"
    assert len(leg["unaccounted"]) == len(leg_real["unaccounted"]) + 1
    assert len(leg["unaccounted"]) != UNACCOUNTED_BASELINE, "数量棘轮对此不敏感 ⇒ 它是装饰"
    assert leg["sha16"] != UNACCOUNTED_SET_SHA, "集合指纹对此无感 ⇒ 指纹是装饰"
    # 同一枚键从 SETTABLE 摘掉而**不**进第三态台账 ⇒ 逐枚状态判据也必须抓到它。
    monkeypatch.setattr(sys.modules[__name__], "SETTINGS_PY", _poisoned_settings_copy(tmp_path, poisoned))
    with pytest.raises(AssertionError):
        sys.modules[__name__].test_every_field_has_exactly_one_hot_surface_state()
    assert state_of(victim, leg) == set(), "摘表后该键状态集非空 ⇒ 逐枚判据在别处给它发了表态"
    _assert_untouched(before)


def test_poison_4_blind_field_authority_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 4（门自身不变夹具）：字段真身读空 ⇒ 一致性用例与地板都必须红，不许"零违规"地绿。"""
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "load_config_fields", lambda: set())
    with pytest.raises(AssertionError):
        test_two_field_authorities_agree()
    # 其余三维**从基线派生**（席 S157：不再手抄旧快照数，免得跟着字段集漂移成假毒/空跑）：
    # 只有字段维归零，红必须来自"字段尺瞎了"，而不是别维的过期硬编码。
    with pytest.raises(AssertionError):
        assert_corpus_not_blind((0, *CORPUS_FLOOR_BASELINE[1:]))
    with pytest.raises(AssertionError):
        test_every_field_has_exactly_one_hot_surface_state()


# ---- 席 S77 追加的四发注毒（简报要求的 ①②③ 各一发 ＋ 恒等式漏计一枚一发）----


def test_poison_5_ghost_env_name_rescues_no_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 5（简报①）：伪造一条 `store.get("BOT_FAKE_KEY", config)` 而字段不存在 ⇒ 必红。

    两腿都验：**(a) 现行判据**下这条幽灵读点既不给近名字段发活性、也不进桶 4，但它**必须**被
    单列进幽灵账（否则就是"名字对不上就当没看见"）；**(b) 松判据杀伤力**——把等值匹配换成
    "前 12 字相同即算命中"，同一行就会把 `bot_s77_ghost_near` 洗进桶 4，证明**逐字等值**这一条
    是承重的，不是装饰。
    """
    leg = _sandbox(tmp_path, monkeypatch)
    buckets = leg["buckets"]
    assert POISON_CENTRAL in buckets["central_named"], "真按名读点未进桶 4 ⇒ 判据不认这一形（假阴）"
    assert POISON_GHOST_NAME in leg["ghost_sites"], "沙箱那条幽灵读点没被扫到 ⇒ 扫描面对幽灵已瞎"
    assert POISON_GHOST_NEAR not in buckets["central_named"], "名字对不上也算读到 ⇒ 桶 4 在发假活性"
    assert POISON_GHOST_NEAR in buckets["hard_dead"]

    fields = set(census.config_fields())

    def loosened(name: str, upper_to_field: dict[str, str]) -> str | None:
        head = name.strip().upper()[:12]
        return next((f for u, f in sorted(upper_to_field.items()) if u.startswith(head)), None)

    assert POISON_GHOST_NEAR in fields and POISON_GHOST_NAME not in {f.upper() for f in fields}
    module = sys.modules[__name__]
    cfg_py = Path(census.CONFIG_PY)
    original_matcher = _field_by_env_name
    monkeypatch.setattr(module, "_field_by_env_name", loosened)
    loose_central = _production_scan_uncached(["plugins"], cfg_py)[0]
    # 这里**不用** monkeypatch.undo()：那会连 `_sandbox` 打的 REPO/CONFIG_PY 一起还原，
    # 下一趟"紧判据"就去扫真树、断言的是另一个世界（本席首版正踩在此，实跑推翻后改写）。
    monkeypatch.setattr(module, "_field_by_env_name", original_matcher)
    assert POISON_GHOST_NEAR in loose_central, (
        "松判据也没把幽灵洗成读点 ⇒ (b) 腿在空跑，本发毒没有杀伤力（换名规则得改到真能误伤）"
    )
    tight_central = _production_scan_uncached(["plugins"], cfg_py)[0]
    assert POISON_GHOST_NEAR not in tight_central and POISON_CENTRAL in tight_central
    assert set(tight_central) == set(central_named_sites(["plugins"])), "还原后判据不稳 ⇒ 有隐藏状态"
    # 牙口打在真身用例上：松判据喂进常驻桶用例 ⇒ "证据腿"当场红（数量腿今天抓不到，见毒发 6）。
    monkeypatch.setattr(module, "central_named_sites", lambda scopes=None: loose_central)
    with pytest.raises(AssertionError):
        module.test_central_named_bucket_names_its_evidence()


def test_poison_6_hot_tier_membership_is_not_a_read_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 6（简报②）：把桶 4 的派生换成"只要在 SETTABLE 就算有读点" ⇒ 必红。

    今天 SETTABLE 与残余的交集**恰好也是那一枚** `bot_transport_timeout_seconds`，所以数量与指纹
    这一发抓不到（照实写出来）——抓得到它的是**证据腿**：台账成员给不出 `文件:行号` 的 `.get(` 站点。
    这正是 S56 论证过的"用腿 2 的数据洗腿 1"必须靠证据而非数量来挡。
    """
    module = sys.modules[__name__]
    real = read_point_leg()
    tiers = hot_surface_leg()
    residual = real["buckets"]["ast_dead"] - real["buckets"]["template_covered"] \
        - real["buckets"]["literal_covered"]
    forged_names = set(tiers["settable"]) & residual
    assert forged_names, "SETTABLE 与残余交集为空 ⇒ 本毒在空跑，换 restart 面重来"
    assert forged_names == set(real["buckets"]["central_named"]), (
        "本发毒的构造前提变了：台账派生集已与真判据集不同，数量腿就会红，"
        "请把本断言改成条件式并把两条红都记进报告"
    )
    monkeypatch.setattr(module, "central_named_sites",
                        lambda scopes=None: {k: () for k in forged_names})
    with pytest.raises(AssertionError):
        module.test_central_named_bucket_names_its_evidence()



def test_poison_7_deleting_the_consumption_line_drops_it_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 7（简报③）：删掉某枚真间接读点的消费行 ⇒ 它必须从桶 4 掉回硬死并当场红。"""
    module = sys.modules[__name__]
    key = "bot_transport_timeout_seconds"
    sites = central_named_sites()
    assert key in sites and key in read_point_leg()["buckets"]["central_named"], "本毒前提不在"
    original_sites = central_named_sites

    def thinned(scopes: list[str] | None = None) -> dict[str, tuple[str, ...]]:
        return {k: v for k, v in sites.items() if k != key}

    monkeypatch.setattr(module, "central_named_sites", thinned)
    leg = read_point_leg()
    assert key not in leg["buckets"]["central_named"]
    assert key in leg["buckets"]["hard_dead"], "删了消费行却没掉回硬死 ⇒ 判据在别处给它发了活性"
    assert len(leg["buckets"]["ast_dead"]) == AST_DEAD_BASELINE, "删行不该改变 AST 零直读总数"
    with pytest.raises(AssertionError):
        module.test_central_named_bucket_is_ratcheted_with_fingerprint()
    with pytest.raises(AssertionError):
        module.test_hard_dead_keys_are_named_and_ratcheted()
    # 证据腿**看不见被删掉的键**（它只遍历在册成员），所以那一发不归它红——本席首版把它
    # 写成必红、实跑 DID NOT RAISE，已按实况删掉该断言（照实记进报告 §4）。
    # 掉回硬死的账由数量腿＋待修总账腿共同接住：债 +1 是真信号，只有接上消费点才许减债。
    with pytest.raises(AssertionError):
        module.test_env_direct_bucket_is_debt_not_health()
    monkeypatch.setattr(module, "central_named_sites", original_sites)
    leg = read_point_leg()
    assert key in leg["buckets"]["central_named"] and key not in leg["buckets"]["hard_dead"]
    module.test_central_named_bucket_is_ratcheted_with_fingerprint()
    module.test_hard_dead_keys_are_named_and_ratcheted()


def test_poison_7b_deleting_the_source_line_really_drops_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 7b（简报③的"真删行"版）：不碰派生字典，只改**沙箱源文件**那一行。

    毒发 7 摘的是派生结果（等价于"扫描器看不见那行"），本发摘**源文件里的那一行**——
    测的是扫描器自己，不是字典。顺带暴露并锁住一条真实隐患：`_production_scan` 的 `lru_cache`
    **以路径为身份、不认内容 mtime** ⇒ 同进程原地改文件必须显式失效缓存，否则下一趟读到旧结果
    （本门常驻用例靠"一进程一树"规避，沙箱改树则必须 `cache_clear`——写死在这里防后人忘记）。
    """
    leg = _sandbox(tmp_path, monkeypatch)
    consumer = tmp_path / "plugins" / "bot_unified_runtime" / "consumer.py"
    assert POISON_CENTRAL in leg["buckets"]["central_named"], "前提：那行在场时桶 4 认它"
    text = consumer.read_text(encoding="utf-8")
    needle = f'    return store.get("{POISON_CENTRAL.upper()}", config)\n'
    thinned_source = text.replace(needle, "    return None\n")
    assert thinned_source != text, "注毒替换未生效 ⇒ 这一发在空跑"
    consumer.write_text(thinned_source, encoding="utf-8")
    _production_scan.cache_clear()
    after = read_point_leg(["plugins"])
    assert POISON_CENTRAL not in after["buckets"]["central_named"]
    assert POISON_CENTRAL in after["buckets"]["hard_dead"], "删了源行却没掉回硬死 ⇒ 扫描器另有记忆或缓存未失效"
    assert len(after["buckets"]["ast_dead"]) == len(leg["buckets"]["ast_dead"]), "删行不该改变 AST 零直读总数"


def test_poison_8_unaccounted_key_breaks_the_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    module = sys.modules[__name__]
    original = module.bucketize

    def dropping(*args: Any, **kwargs: Any) -> dict[str, frozenset[str]]:
        buckets = original(*args, **kwargs)
        victim = min(buckets["hard_dead"])
        return {
            name: (keys - {victim} if name != "ast_dead" else keys)
            for name, keys in buckets.items()
        }

    monkeypatch.setattr(module, "bucketize", dropping)
    with pytest.raises(AssertionError):
        module.test_bucket_arithmetic_holds()
    monkeypatch.setattr(module, "bucketize", original)
    module.test_bucket_arithmetic_holds()


def test_poison_9_env_direct_shape_does_not_make_a_field_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 9（硬红线自证）：桶 5 的成员**不得**被算成"有读点"。

    杀伤力对象＝沙箱里那两枚只被 `os.getenv` / `os.environ[...]` 读到的字段：它们必须留在
    待修总账（硬死 ∪ 桶 5）里，且直读集不含它们。
    """
    leg = _sandbox(tmp_path, monkeypatch)
    buckets = leg["buckets"]
    assert buckets["env_direct"] == frozenset({POISON_ENV, POISON_ENV_SUB}), (
        f"绕中央直读环境未单独成桶：{sorted(buckets['env_direct'])}"
    )
    debt = debt_roster(buckets)
    for key in (POISON_ENV, POISON_ENV_SUB):
        assert key in debt, f"{key} 出了待修总账 ⇒ 桶 5 被当成健康了"
        assert key not in buckets["hard_dead"], f"{key} 仍被记成硬死 ⇒ 桶 5 没接住它"
    assert len(debt) == len(buckets["hard_dead"]) + len(buckets["env_direct"]), "债账有重计"
    assert POISON_CENTRAL not in debt, "桶 4 的成员被并进了待修总账（应单独分类）"
    # 真树侧同一条：桶 5 成员必须仍在 ast_dead（＝零直读）里，绝不因分类而长出读点。
    real = read_point_leg()
    assert real["buckets"]["env_direct"] <= real["buckets"]["ast_dead"]


# ---- 席 S157：R-4 退役四枚 `*_via_queue` 之后的重账牙口（三发注毒 ＋ 一枚彻底性锁）----


def _mini_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, extra_fields: Iterable[str]
) -> dict[str, Any]:
    """第二座沙箱：只造「登记了却一行都不读」的字段，与 `_sandbox` 分开以免稀释断言。

    `_production_scan` 的缓存键带**树身份**（tmp_path 各异）⇒ 沙箱结果不串进真树，
    这里也就不需要 `cache_clear`（同路径原地改内容才需要，见毒发 7b 的注记）。
    """
    pkg = tmp_path / "plugins" / "bot_unified_runtime"
    pkg.mkdir(parents=True)
    cfg = pkg / "config.py"
    body = "".join(f"    {name}: bool = False\n" for name in extra_fields)
    cfg.write_text(
        "from pydantic import BaseModel\n\n\n"
        "class Config(BaseModel):\n"
        "    bot_s157_anchor_direct: bool = True\n" + body,
        encoding="utf-8",
    )
    (pkg / "consumer.py").write_text(
        "def read(config):\n    return config.bot_s157_anchor_direct\n", encoding="utf-8"
    )
    monkeypatch.setattr(census, "REPO", tmp_path)
    monkeypatch.setattr(census, "CONFIG_PY", cfg)
    return read_point_leg(["plugins"])


def test_poison_10_re_registered_retired_keys_are_named_as_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒发 10（简报硬规「禁把键改判成在册但不读」）：四枚退役键塞回 Config 而不接消费点 ⇒ 必红。

    本席重录的**唯一合法方向**是"账随字段集现算"；这一发钉住反面：留字段、只把它从违规名册
    里划掉，一定被硬死桶点名，且常驻用例当场红。
    """
    retired = frozenset(RETIRED_VIA_QUEUE_KEYS)
    real_fields = set(census.config_fields())
    assert not (retired & real_fields), "前提已变：四枚键又回 Config 了 ⇒ 本毒在空跑"
    buckets = _mini_sandbox(tmp_path, monkeypatch, extra_fields=sorted(retired))["buckets"]
    assert retired <= buckets["hard_dead"], (
        f"再登记却无人读竟没进硬死桶：{sorted(retired - buckets['hard_dead'])}"
    )
    for name in ("template_covered", "literal_covered", "central_named", "env_direct"):
        assert not (retired & buckets[name]), f"{name} 桶给再登记的死键发了活性"
    with pytest.raises(AssertionError):
        test_hard_dead_keys_are_named_and_ratcheted()


def test_poison_11_new_field_floor_tracks_the_field_set() -> None:
    """毒发 11：重录后的地板四维**必须等于现算真值**，且字段维少一枚当场红（证明 696 不是抄的）。"""
    leg = read_point_leg()
    files = sum(1 for _ in census.py_files(list(census.DEFAULT_SCOPES)))
    sizes = (leg["fields"], leg["direct_reads"], len(leg["templates"]), files)
    assert_corpus_not_blind(sizes)
    assert sizes[0] == CORPUS_FLOOR_BASELINE[0], (
        f"字段维地板 {CORPUS_FLOOR_BASELINE[0]} ≠ 现算 {sizes[0]} ⇒ 棘轮不等于真值，重录它"
    )
    assert sizes[2] == CORPUS_FLOOR_BASELINE[2], (
        f"模板维地板 {CORPUS_FLOOR_BASELINE[2]} ≠ 现算 {sizes[2]} ⇒ 同上（这一维容差为 0）"
    )
    with pytest.raises(AssertionError):
        assert_corpus_not_blind((sizes[0] - 1, *sizes[1:]))
    # 直读维容差今天仍是 200：一次性砍穿才该红（证明这一维没被写成"恒过"）。
    with pytest.raises(AssertionError):
        assert_corpus_not_blind(
            (sizes[0], sizes[1] - CORPUS_FLOOR_SLACK[1] - 1, sizes[2], sizes[3])
        )


def test_poison_12_unaccounted_ratchet_is_live_on_the_new_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """毒发 12：重录后的 568 仍是**活**棘轮——字段集进一枚、出一枚都必须红，还原即复绿。"""
    module = sys.modules[__name__]
    original = module.load_config_fields
    leg = hot_surface_leg()
    assert len(leg["unaccounted"]) == UNACCOUNTED_BASELINE, "基线已不等于现算 ⇒ 先改对再谈牙口"
    assert leg["sha16"] == UNACCOUNTED_SET_SHA, "集合指纹已不等于现算 ⇒ 同上"
    victim = min(leg["unaccounted"])  # 一枚今天「无表态」的真字段
    monkeypatch.setattr(
        module, "load_config_fields", lambda: sorted(set(original()) | {"bot_s157_forged_field"})
    )
    with pytest.raises(AssertionError):
        module.test_every_field_has_exactly_one_hot_surface_state()
    monkeypatch.setattr(module, "load_config_fields", lambda: sorted(set(original()) - {victim}))
    with pytest.raises(AssertionError):
        module.test_every_field_has_exactly_one_hot_surface_state()
    monkeypatch.setattr(module, "load_config_fields", original)
    module.test_every_field_has_exactly_one_hot_surface_state()


def _production_sites_reading(names: Iterable[str]) -> dict[str, list[str]]:
    """生产面里以任何**代码**形态碰过这些名字的站点（属性式 / 恰等的字符串常量 / 关键字实参）。

    注释与 docstring 不是 AST 节点 ⇒ 退役说明留在注释里不会误伤本判据；反过来，谁把键偷偷改回
    "在册但不读"（字段留、名册划掉、消费点不接），这条当场点名。一趟扫完四枚，别按枚数乘遍树。
    """
    wanted = set(names)
    hits: dict[str, list[str]] = {name: [] for name in sorted(wanted)}
    for path in census.py_files(list(census.DEFAULT_SCOPES)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            found: str | None
            if isinstance(node, ast.Attribute):
                found = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                found = node.value
            elif isinstance(node, ast.keyword):
                found = node.arg
            else:
                found = None
            if found in wanted:
                line_no = getattr(node, "lineno", 0)  # ast.AST 基类不声明 lineno，三支合流后只能取
                hits[found].append(f"{path.relative_to(census.REPO).as_posix()}:{line_no}")
    return hits


def test_retired_via_queue_keys_left_no_residual() -> None:
    """彻底性锁（简报「顺带核」的落盘形态）：四处皆零残留，缺一个面就是退役不彻底。"""
    fields = set(census.config_fields())
    leg = hot_surface_leg()
    tiers = load_hot_tiers(SETTINGS_PY.read_text(encoding="utf-8"))
    settings_text = SETTINGS_PY.read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    code_sites = _production_sites_reading(RETIRED_VIA_QUEUE_KEYS)
    for key in RETIRED_VIA_QUEUE_KEYS:
        assert key not in fields, f"{key} 还在 Config 里 ⇒ 退役没退干净"
        assert key not in leg["settable"] and key not in leg["restart"], f"{key} 还挂在热改名单里"
        assert key not in leg["declared"], f"{key} 被塞进第三态台账 ＝ 改判成在册但不读"
        assert key not in tiers, f"{key} 仍在 pilot 解析出的两张名单里"
        assert key.upper() not in settings_text, f"{key} 的大写 env 名还写在 settings.py 原文里"
        assert key.upper() not in env_example, f"{key} 在 .env.example 里留了孤儿行"
        assert not code_sites[key], f"{key} 退役后仍有生产读点：{code_sites[key]}"


# ---------------------------------------------------------------------------
# 席 E（2026-09-26）：poke / randpic 两族「字面读点」防回潮锁
#
# 为什么放本门而不是别的门：本波 11 枚键进硬死桶的**唯一**原因是读点名算不出来
# （`getattr(config, f"{prefix}probability")`）。把取值挪到调用点后，谁再挪回门身
# 里动态拼名，直读尺就又看不见那 11 枚 ⇒ 同一笔债原地重借。这条锁盯的是**形状**，
# 与桶基线（盯数量）互补：基线可以被逐枚重录，形状不能被悄悄改回去。
# ---------------------------------------------------------------------------
def _literal_field_names(node: ast.AST) -> set[str]:
    """子树里以**字符串常量**形态出现的在册字段名（就是直读尺认的那种形状）。"""
    fields = set(census.config_fields())
    return {
        const.value
        for const in ast.walk(node)
        if isinstance(const, ast.Constant) and isinstance(const.value, str) and const.value in fields
    }


def _proactive_call_violation(call: ast.Call) -> str:
    """一个 `proactive_action_allowed(...)` 调用点 → 违规说明（合规返回空串）。

    判据（纯函数，喂合成 AST 即可测杀伤力，不碰磁盘）：必须有 `knobs=` 实参，且那
    个实参的子树里至少写着 **四枚** 在册字段名（enabled / probability /
    cooldown_seconds / max_per_hour）。少于四枚＝又有人把其中几枚改回动态取数。
    """
    knobs = next((kw for kw in call.keywords if kw.arg == "knobs"), None)
    if knobs is None:
        return "缺 knobs=（门身将退回 f\"{prefix}probability\" 动态取数 ⇒ 直读尺看不见）"
    named = _literal_field_names(knobs.value)
    if len(named) < 4:
        return f"knobs 里只有 {len(named)} 枚字面键名（要 4 枚）：{sorted(named)}"
    return ""


def test_proactive_action_call_sites_pass_literal_knobs() -> None:
    """生产面每个门身调用点都按字面键名交 knobs ⇒ 那 11 枚键的读点永不重新变隐形。"""
    violations: list[str] = []
    seen = 0
    for path in census.py_files(list(census.DEFAULT_SCOPES)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "")
            if name != "proactive_action_allowed":
                continue
            seen += 1
            bad = _proactive_call_violation(node)
            if bad:
                violations.append(
                    f"{path.relative_to(census.REPO).as_posix()}:{node.lineno} {bad}"
                )
    assert seen >= 3, (
        f"生产面只数到 {seen} 个 proactive_action_allowed 调用点 ⇒ 本锁在空跑"
        "（调用点被删、被改名，或扫描面缩了）"
    )
    assert not violations, "这些调用点会把手册上的键重新变成零读点：" + "；".join(violations)


def test_poison_13_dynamic_knob_call_is_named() -> None:
    """注毒 13（防回潮锁自己的牙口）：旧「动态拼名」形状与「只写一枚字面键」的半修
    形状都必须被判违规；全字面形状判合规。纯 AST 断言，不碰磁盘、不改真件。"""
    legacy = ast.parse(
        "proactive_action_allowed(\n"
        "    merged_config,\n"
        '    prefix="bot_poke_follow_",\n'
        "    gate=gate, session_key=key, message_key=mkey,\n"
        ")\n"
    )
    legacy_call = next(node for node in ast.walk(legacy) if isinstance(node, ast.Call))
    assert _proactive_call_violation(legacy_call), "旧形状竟然判合规 ⇒ 这条锁是装饰"
    half = ast.parse(
        "proactive_action_allowed(\n"
        "    merged_config,\n"
        '    prefix="bot_poke_follow_",\n'
        "    gate=gate, session_key=key, message_key=mkey,\n"
        "    knobs=ProactiveActionKnobs(\n"
        '        enabled=bool(getattr(merged_config, "bot_poke_follow_enabled", False)),\n'
        "        probability=0.2, cooldown_seconds=120.0, max_per_hour=4,\n"
        "    ),\n"
        ")\n"
    )
    half_call = next(node for node in ast.walk(half) if isinstance(node, ast.Call))
    assert _proactive_call_violation(half_call), "只写一枚字面键的半修形状必须被抓 ⇒ 判据太松"
    good = ast.parse(
        "proactive_action_allowed(\n"
        "    merged_config,\n"
        '    prefix="bot_poke_follow_",\n'
        "    gate=gate, session_key=key, message_key=mkey,\n"
        "    knobs=ProactiveActionKnobs(\n"
        '        enabled=bool(getattr(merged_config, "bot_poke_follow_enabled", False)),\n'
        '        probability=float(getattr(merged_config, "bot_poke_follow_probability", 0.2)),\n'
        '        cooldown_seconds=float(getattr(merged_config,'
        ' "bot_poke_follow_cooldown_seconds", 120.0)),\n'
        '        max_per_hour=int(getattr(merged_config, "bot_poke_follow_max_per_hour", 4)),\n'
        "    ),\n"
        ")\n"
    )
    good_call = next(node for node in ast.walk(good) if isinstance(node, ast.Call))
    assert _proactive_call_violation(good_call) == "", "合规形状被判违规 ⇒ 常驻用例迟早被人调松"


def test_gate_reads_code_not_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    """门自身不许变夹具：换掉**取数口**，真身用例必须跟着动（写死答案的门不会动）。

    本波已两次栽在"把被测前提手写进夹具"（#50 记的 tags 硬编码两犯）。这里被改的必须是
    门真在调的那个函数，且还原后立刻复绿——否则红来自阈值噪声而非判据。
    """
    assert read_point_leg()["buckets"]["hard_dead"], "硬死桶今天竟是空的 ⇒ 本腿无可测对象，名存实亡"
    module = sys.modules[__name__]
    original = module.read_point_leg

    def forged() -> dict[str, Any]:
        leg = original()
        leg["buckets"] = {**leg["buckets"], "hard_dead": frozenset({"bot_s56_forged"})}
        return leg

    monkeypatch.setattr(module, "read_point_leg", forged)
    with pytest.raises(AssertionError):
        module.test_hard_dead_keys_are_named_and_ratcheted()
    monkeypatch.setattr(module, "read_point_leg", original)
    module.test_hard_dead_keys_are_named_and_ratcheted()


def test_real_files_untouched_after_whole_suite() -> None:
    """落盘自证：本文件所有用例只读。开跑 sha 即时取（不钉常量）⇒ 不因并发波改件而假红。"""
    before = {CONFIG_UNDER_TEST: _sha_now(CONFIG_UNDER_TEST), SETTINGS_UNDER_TEST: _sha_now(SETTINGS_UNDER_TEST)}
    time.sleep(0.01)
    _assert_untouched(before)
