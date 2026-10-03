# 席 REV 工单 — 亲密人腿对抗复核（2026-10-02 下午窗）

对象＝席 INT 交付（`patches/INT-INTIMATE-PERSON-GATE-20261002.md`）：content_route
群分支人腿 + tts.py:1556 消费者第四参。使命＝找漏测边界、补 ≤2 腿、点名行为错误。
零 git 写、零进程动作、零 .env/配置改、未装包、未派子代理。生产件零改动（只读）。
写前 mtime 自检：content_route.py 16:09 / tts.py 16:06（+0800，均早于 17:00 界）⇒ 放行。

## ① 六条对抗推理表（逐条对现码演算；三态＝已有腿覆盖 / 无腿覆盖 / 行为错误）

| # | 构造 | 演算（content_route.py 群分支 :931-968） | 三态 |
|---|---|---|---|
| 1 | 人挂私聊白**+私聊黑**双名单、群不在群白/群黑 | :966 `pwl and sid in pwl and sid not in pbl` ⇒ `sid not in pbl`=False ⇒ 人腿不进 ⇒ False ✓ 正确。**既有腿只锁群黑压人腿（`_G_PERSON_BLACK`）与人不在 pwl（`_G_PERSON_NEG`），私聊黑压人腿零覆盖**；INT 注毒自证里「③黑名单腿仍绿」指群黑腿，私聊黑闸被摘无人拦 | 无腿覆盖＋行为正确 ⇒ **补腿 1** |
| 2 | sender=" 2950687868 " 或名单条目带空白；空/纯空白 sender | :954 sid strip、:957/:963 名单收集同 strip ⇒ 两边归一对齐，带空白同判 ✓；纯空白 sender ⇒ sid="" ⇒ `if sid:` 不进 ⇒ 人腿关闭，群白空 ⇒ False ✓；纯空白名单条目被收集 `if …strip()` 过滤，无幽灵键 ✓。既有腿全传干净字符串，归一零覆盖 | 无腿覆盖＋行为正确 ⇒ **补腿 2** |
| 3 | 群号 int vs str；条目带空格 | `str(group_id or "")` 归一（**旧形态既有**，非本波引入），int 700100022 → "700100022" 同判 ✓；int 0 falsy ⇒ ""（合理：非法群号走人腿）。行为正确；价值排序第三未补 | 无腿覆盖＋行为正确（未补） |
| 4 | 私聊白空＋人不在任何名单 | :966 `pwl and` 显式守卫 ⇒ 人腿整体关闭 ⇒ False 不放开 ✓。既有 `_G_UNLISTED` 腿 cfg 私聊白默认空、端到端走同一函数；INT 注毒「空名单放开」族该腿实测红（INT 工单 ④） | 已有腿覆盖 |
| 5 | console/private 分支被污染？ | `git diff HEAD` 实查：仅两 hunk（docstring :896 增 3 行；:926 起群分支），增删行全落群分支内，private/console 均为上下文行零改动；`test_private_ack_…`＋邻域 97 绿佐证 | 已有腿覆盖（diff 级证据 verified） |
| 6 | tts 消费者 message 无 sender_id 属性 | tts.py:1560 `getattr(message,"sender_id","") or ""` ⇒ "" ⇒ 人腿跳过 ≡ 旧版逐字节等价 ✓；AST 腿已静态锁第四参真引 sender_id | 已有腿覆盖 |

改写等价性顺带核过：旧收口 `str(group_id or "").strip() in (wl - bl)` ≡ 新①②对旧路径
逐字节等价（双挂黑胜、白命中 True、皆不命中落到③/④）。

## ② 补的腿与理由（`tests/test_intimate_group_switch_delivery.py` 只 append，16 腿判据零触碰）

1. `test_private_blacklist_beats_the_person_leg`（`_G_PERSON_PBL`=700100022）：人
   pwl+pbl 双挂、群白空 ⇒ 判定直读 False＋端到端主链不受理（开关句不短路、
   无 MANUAL_ON_REPLY、无 content_route tag）。锁「私聊黑名单永远赢」这第二把闸
   （毒形＝摘 `sid not in pbl` ⇒ 推演该腿红；注毒未实跑——禁改生产件）。
2. `test_person_leg_matches_after_stripping_sender_and_list_entries`
   （`_G_PERSON_WS`=700100023）：群白空下①条目带空白/sender 干净 ⇒ True、
   ②sender 带空白 ⇒ True、③纯空白 sender 与缺省 ⇒ False；名单纯空白条目
   不产幽灵键。锁两侧 strip 归一（任一侧丢 strip 当场红）。纯判定直读，
   不端到端（pydantic 字段清洗行为不在本格锁面）。

## ③ 实跑末行（原样）

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_intimate_group_switch_delivery.py -q -p no:cacheprovider \
  --basetemp="$TEMP/qoder-REV/bt"
18 passed in 5.79s
```
（16 既有＋2 新补全绿；venv 真身在 `ChatBot/` 平级 `ChatBot_Runtime/` 下，INT 工单
所写相对路径自仓库根不可达，属笔误非阻塞。）

## ④ 行为错误点名

无。六条对抗项现码行为全部正确，无复现脚本需要。

## ⑤ 未尽事项

- 本席补腿亦未提交（零 git 写）；测试文件现含未跟踪 WIP，提交由用户执行；
  **bot 未重启 ⇒ 人腿改动未生效**（台账 #10 既有）。
- 腿 1 的注毒有效性为推演非实跑（生产件禁改）；如需实证可由主会话授权后
  按 INT 工单 ④ 同法自证。
- 条 3（int 群号归一）未补腿，已记①表备查；若未来 IncomingMessage.group_id
  类型面收窄须回看。
- 工作区大面积他席在飞 WIP 未触碰；本席写面仅测试文件 append＋本工单。
