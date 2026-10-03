# 席 INT 工单 — 亲密模式群侧人腿「人在白名单 ⇒ 任何群都能开」（2026-10-02 下午窗）

裁定：用户 2026-10-02。前席被平台并发墙弹回零产出，本席重派全量实施。
零 git 写、零进程动作、零 .env/配置改、未装包、未派子代理。

## ① 现状核实（改前，file:line 均为本席实读）

- 群分支死读群号不读人：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`
  `explicit_allowed_for_session`（函数 :893-942），群分支 :928-939，收口逐字
  `return str(group_id or "").strip() in (wl - bl)`；同函数私聊分支集合推导形态 :911-926。
- 已带 sender 的三处（核实后未动）：`chat.py:3958`（关键字形态）、`__init__.py:9449`、
  `content_route.py:981`（resolve_intimate_context 内）。
- 消费者缺口：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py:1554`
  M-17 自动配音安全门 `explicit_allowed_for_session("group", group_id, config)` 无第四参；
  同文件 :1339-1344 已传（未动）。tts.py 全文 `"group"` 字面量调用仅此一处（grep 实证）。
- 测试基线：`tests/test_intimate_group_switch_delivery.py` 12 腿全绿。

## ② 改法与理由

- **content_route.py 群分支改四步顺序（顺序即裁定；改后群分支 :931-968）**：
  ① 群黑名单命中 ⇒ False（永远赢，压过人腿）→ ② 群白名单命中 ⇒ True（既有行为
  一字不动）→ ③ 新增人腿：`sender_id`（strip 后非空）逐字命中
  `bot_content_route_private_whitelist` 且不在 `bot_content_route_private_blacklist`
  ⇒ True → ④ 其余 False。名单集合化一次、收集形态照抄同函数私聊分支的集合推导；
  docstring 同批补裁定行（改后 :898-903）。**只动 admission**：chat.py 管理员门、
  tier 来源/群级钉/成员键优先级、TTL 一律未触。
- **tts.py:1554 带第四参** `sender_id=str(getattr(message, "sender_id", "") or "")`
  （形态照同文件 :1343 既有款；改后调用 :1556-1561），旁注同步——旧注
  「白名单空=群面关闭」在裁定后不再为真，不改正文注释会留假话。缺 sender＝
  人腿对该消费者永远关闭＝半条腿，故必须同批。
- **三条正确性硬点的落法**：空私聊白名单 ⇒ 人腿整体关闭（`pwl and` 显式守卫，
  私聊"空=默认放开"语义不带入群侧）；私聊黑名单只关人腿、不撤销②的既有放行
  （①②先于人腿判定的顺序保证）；空 `sender_id` 缺省调用面与旧版逐字节等价
  （`gid in (wl - bl)` ≡ 黑⇒F、白⇒T、人腿关）。

## ③ 判据读数（实跑末行原样；venv 解释器 `ChatBot_Runtime/venv/Scripts/python.exe`）

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <venv-py> -m pytest \
  tests/test_intimate_group_switch_delivery.py -q -p no:cacheprovider \
  --basetemp="$TEMP/qoder-INT/bt-main"
```
- 改前基线：`12 passed in 4.65s`
- 改后：`16 passed in 4.02s`——新增四腿全在
  `tests/test_intimate_group_switch_delivery.py`：① 人腿端到端正例（`_G_PERSON_LEG`
  =700100019，群白空＋私聊白有 `_MEMBER_A`，主链短路受理→回执出门→成员键进档，
  尾部判定函数直读）② 反例（`_G_PERSON_NEG`=700100020，名单外人 False＋空
  sender 护栏＋群白命中对无 sender 调用面照旧 True，主链不受理）③ 反例
  （`_G_PERSON_BLACK`=700100021，群黑白双挂＋人白，黑胜，主链不受理）
  ④ 消费者 AST 腿（ast.parse tts.py，定位 group 形 `explicit_allowed_for_session`
  调用，断言第四参在且真引用 `message.sender_id`）
- 邻域锁（test_content_route_v3 / test_v21r2_content_probe / test_tts_speech_gate /
  test_tts_contract_layer）：改前 `97 passed in 4.33s` ／ 改后 `97 passed in 3.81s`
- 终态五文件合并跑：`113 passed in 4.96s`

## ④ 净新增红 A/B

- **A（改后）**：0 枚净新增红；邻域四文件读数与改前逐位相同（97=97）。
- **B（注毒自证）**：人腿判据临时反接（`pwl and sid in pwl` → `sid not in pwl`，
  即"名单读反/空名单放开"族），实跑末行 `3 failed, 13 passed in 3.67s`——红＝
  ⑦ `test_empty_group_whitelist_closes_the_switch_instead_of_guessing_open`、
  新① `test_person_in_private_whitelist_can_switch_in_group_outside_group_whitelist`、
  新②反例腿（恰好覆盖简报要求的"⑦与新①必须红"）；③黑名单腿与④AST腿仍绿＝
  顺序护栏不被毒波及。毒已还原（`grep -c POISON-INT`＝0）并复跑 16/16。
- 改前既有红：未观测到（基线 12/12、97/97 全绿）。

## ⑤ 未尽事项

- **零 git 写**：三个源件＋本工单全部未提交；提交、推送、重启由用户执行——
  **bot 未重启 ⇒ 本改动未生效**（台账 #10 既有事实，本席未新增）。
- `tests/test_intimate_group_switch_delivery.py` 为未跟踪新件（D1 席今日产出，
  git status `??`），本席只追加 import/三枚群号常量/`_TTS_SOURCE`/四腿。
- 工作区有大面积他席在飞 WIP（`git diff --stat` 60 文件脏面，含 content_route.py
  与 tts.py 的他席 hunk）；本席按 hunk 独占面落笔，未触碰任何禁写面。
- M-17 语义外溢（设计如此）：私聊白名单内的人在群里时自动配音面随之放开；
  上线后可在 tts 拒绝日志观察分布，若要回退只撤 tts.py 第四参（人腿判定保持）。

## §六 傍窗主会话隐私修正（PRV 席扫出，2026-10-02 21:0x）

PRV 席隐私扫描实证 `_G_ACK`/`_G_DEEP` 两常量与模块 docstring 一处叙述共 3 处写了**现网真实群号**。修正（主会话亲笔，夹具自喂白名单故零判据影响）：两常量换 700 假号段（700100030/31）、docstring 改脱敏叙述（"群号见生产白名单，本件不抄录"）。复跑 `pytest tests/test_intimate_group_switch_delivery.py -q` → **18 passed**（当时值，零判据变化）。`_G_MEMBER = 662948429` 按 PRV 定性为灰区（全仓既有惯例形态）未动，留用户裁。
