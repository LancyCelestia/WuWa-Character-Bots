# 重启执行清单（席 RST 起草 · 2026-10-02 下午窗 · 只读席，唯一写面＝本单）

> 使命：本窗大量代码改动未重启未生效（台账 #10★）。本单让用户**重启一次到位**；提交/重启全部归用户（常令）。
> 读数凡标「实测」＝本席 2026-10-02 只读现跑（会漂移，动手前以重跑为准）。

## 〇、前置（先提交再重启，半成品不留盘）

1. **提交**：按 `patches/CM-COMMIT-PLAN-20261002.md` 顺序 **A→B→D→C→E** 执行＋`patches/CMV-COMMIT-DELTA-20261002.md` 勘误合卷（批B +1＝IVF；批E +11；新增批F 地板复录、批G 生成册）。防吞口诀（CM 单④／CMV⑤）每批必念；**每批动手前重跑 `git status --porcelain`**——TRG/M17 两工单现已落盘，按 CMV④ 归批E（在飞席仍会写盘，97→102 有实证）。
2. **TTS 三闸关**：`.env` 三枚总闸现为 false（键名见 HANDOFF §十四：`BOT_TTS_ENABLED`／`BOT_TTS_AUTO_REPLY_ENABLED`／`BOT_TTS_VOICE_HOOK_ENABLED`；值不抄进本文档）。本次重启使「三闸关」**真正生效**——重启后不得再出现自动语音。
3. **开关提示**：`BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP` 缺省 True ⇒ **未在册群里 `/bot` 命令面静默**（gate.py:88/137；HANDOFF §十一.8）。不想要此行为就置 false 再重启。

## 一、重启顺序

4. **先 SnowLuma 后 bot.py**（pre_restart_check napcat 项在册话术：SnowLuma 未启动属预期、bot 自带重连；scripts/pre_restart_check.py napcat 项文案）。
5. **生产进程管理员权限启动，杀它需提权**（AGENTS.md 〇 铁律）。

## 二、重启前一道门（rc=0 才动手）

6. 跑 `..\ChatBot_Runtime\venv\Scripts\python.exe scripts\pre_restart_check.py`（仓库根；exit 0＝无 FAIL）。
7. 现值（本席实测）：**ann_pair=PASS**（简报「已达」经本席只读点查复核）；**ruff＝All checks passed**（--no-cache）；**doc_sync rc=0**；**hash_ledger rc=0**。
8. **kb_drift＝待小库嵌入完成转绿**（简报在册）——必须转 PASS 才动手；仍红＝每条消息回落暴力扫描（#61 停摆同型），先跑 knowledge-sync 全链再重启。
9. **必须 PASS 才动手的五枚**：`ann_pair`／`kb_drift`／`ruff`／`doc_sync`／`hash_ledger`（功能降级与门禁红不放行）。`napcat` 只提示不阻断（SKIP 可动手）；其余项按脚本自身口径 SKIP 放行。

## 三、重启后验证清单（逐条判据，只打勾不算数）

10. **① ANN 走向量通道**：重启后日志**无 `knowledge ANN pair refused` 告警**（vector_knowledge.py 载入路径警告族＝拒用即回落暴力扫描）；再跑一次 pre_restart_check 看 `ann_pair` 仍 PASS；首条知识库问答无暴力扫描级时延。
11. **② 亲密人腿真群实测**（判据＝INT 工单③四腿＋HANDOFF §十五裁定「人在私聊白名单⇒任何群都能开」）：
    a. 白名单人在**任一群**发「亲密模式 开」→ **受理回执可见**（成员键进档）；
    b. 换**名单外人**同群发同样指令 → **不受理**（无回执）；
    c. 群黑白双挂的群 → 人再白也不放行（群黑名单永远赢）。
    观察点＝**回执是否出门**，不是界面/配置打勾。
12. **③ grok-4.6 第二顺位超时腿**：作为对话组第 2 顺位曾观测 1024 token 预算下 60s 超时（HANDOFF §十一.8）——重启后看告警/失败面日志该腿是否复现超时与降级轮转。
13. **④ TTS 三闸确认关**：重启后 .env 三枚总闸仍为关且 bot 零自动语音输出（含私聊 10% 自动配音腿，M-17 消费者随批 B 已带 sender 第四参）。

## 四、回滚口径

14. **代码回退＝提交哈希回退，由用户亲手 git**（规则 4：逐文件、完整 refspec、禁 add -A；按 CM 批次粒度 revert/reset）。
15. **ANN 索引回退不需要**：旧索引已被新代**原子顶替**（KnowledgeService.reindex→swap 原子换索引机制，vector_knowledge.py 文件代际号注释在册）。确要回退＝按 HANDOFF §十六 runbook **指回旧嵌入端点整代重建**（不是文件级恢复）：内存要价 n≈740k 时 **≈7 GiB 空闲起步**、知识库全链（补嵌→重建→重盖章）跑完才收工——代价高，先想清楚。

---
席 RST 落款 2026-10-02：零 git 写／零进程动作（仅只读实测四把尺＋ann_pair 点查，卫生前缀齐全）／零配置改／未派子代理；唯一写面＝本单。

---
> **收卷后更正（主会话 20:4x）**：本单 §③ 写"kb_drift 待嵌入转绿"——已过时。小库 knowledge-sync 断点续嵌已完成（35274/35274＋HNSW 重建），`pre_restart_check.py` 终验 **PASS 9 / SKIP 4 / FAIL 0 rc=0**（ann_pair 与 kb_drift 双 PASS，2026-10-02 傍窗实跑）。重启前若隔时较久，重跑一次以当时值为准即可。
