# TTS 统一波（G 契约层 + H 传输层）交接文档 —— 交测试 AI 用

> 交接时刻：2026-09-20 06:5x（机器重启前收束）。HEAD=`9d758a5`，分支 `v0.0.1-alpha.2`。
> 本文档=唯一交接入口；事实底座=`.superpowers/sdd/2026-09-19-unify-audit/`（progress.md G2 段 + report-T*.md 60+ 份席报）。
> 测试 AI：本文档 §5 是你的测试手册；§6 是你必须验证的清单；§7 是不能碰的东西。

---

## 1. 30 秒身份

- 项目：QQ 聊天机器人「守岸人」（NoneBot2 + OneBot V11/SnowLuma），主包 `plugins/bot_unified_runtime/`，运行数据在 `ChatBot_Runtime/`（venv 也在那）。
- 本两波任务：用户主张「TTS 一切经中央统一处理」——经 26+ 席审计（77 条缺陷 M-01…M-77 + 17 条全仓共性 S-01…S-17）后，G 波（契约层）+ H 波（传输层）施工收口。
- 终验：**GO×4**（T91 全量 9415P/2F 归属他席 → T110 phase1 2153P → T128 phase2 468P → T141 pre 404P → T154 phase3 正式轮 726P/0F 真失败空）。全部离线证据；**重启后才生效**（铁律）。

## 2. 已实现（全部已入库，哈希可溯）

### 2.1 审计闭环总账
**P0×6 全结**：M-01 虚词劫持（d3a53ea+T59/T66/T83/T92）｜M-02 语音零内容闸（d3a53ea+12f956b）｜M-03 打码漏（d3a53ea+T61）｜M-05 domains 零跟踪（c40c8e1 等 10 笔基线，416 件全入库）｜M-63 mixed 盲重投（194a2ca 段级记账 9→1）｜M-04 死路径出站（743505b 绝对路径闸）。
**P1×28 全结**：M-06 体检闸（7c566f7）/M-07 静音三指纹（T61）/M-08+11 缓存身份（T57+T61）/M-09 退避真闸（T57）/M-10+13 自动配音接中央 hook（9f1e81a）/M-12 音色守望（1b2860c）/M-14 变换审计化（b77b7f4）/M-15+16 触发词合并+繁體 16 词（b13913d+ff091dc）/M-17 语音门中央名单（b77b7f4）/M-19 出站契约（6c34858）/M-20 测试证明力（7d40d8f）/M-32 SSRF 闸（034bcb8）/M-38 死路径（743505b）/M-39 文件名 uuid（1a4200b）/M-52 路径重映射（2401c5c）/M-61 工具链收编（c78951f）/M-64 摘要链 S1-S5（d823232/c24282a/b605692/c3ac342）/M-67 体检器重建（7e2fe36）/M-68 装载唯一入口（6a7573e）/M-73 括号动作剥除+M-77 读法词典（5ddf704）等。
**P2 择优 6 条**：M-32/M-39/M-61/M-66 文档面/M-52/M-68。

### 2.2 新架构件（测试对象）
| 件 | 位置 | 作用 |
|---|---|---|
| 中央触发词边界件 | `domains/core/text_boundary.py` | 六副本唯一权威：casefold/繁簡登记/虚词集；tts/randpic/media_archive/group_info/mentions/base_router 全走它 |
| 中央语音预设表 | `domains/media/tts_presets.py` + config `bot_tts_preset` | 20 键单源化：参数+域值（抄引擎 WebUI）+rationale+seed_policy+读法词典 |
| 契约层规格 | `docs/design/tts-contract-layer.md` | G-1 五件事：引擎 HTTP 契约表/预设表/0=不限/管线十阶段/缓存键算法 |
| 摘要层 | `domains/media/digest.py` + renderer 第三冻结键 content_sha256 + pipeline dedupe d 段 | 音频字节唯一内容身份（uuid 文件名后 digest=唯一身份源） |
| 语音 hook | `domains/media/voice_enricher.py` + pipeline `outbound_voice_enricher` + 根 init 双态装配 | 自动配音移 review 后；键 `bot_tts_voice_hook_enabled=False` 缺省字节不变 |
| 健康探针 | `domains/media/voice_health_probe.py` | 惰性 TCP ≤2s/300s 抑制/恢复态；echo /bot status 已接线 |
| 音色守望 | scripts/pre_restart_check.py 第 10 项 + scripts/tts_voice_baseline.json | yaml 语义断言+sha256 基线；换底模/权重丢失→FAIL 人话 |
| 装载唯一入口 | `scripts/load_runtime_config.py` | pre_restart/verify_chatbot_env/smoke 三消费方切换；生产 .env 351 键三链对拍零差异 |
| 传输层段级记账 | `domains/transport/sender/{onebot,worker}.py`（194a2ca） | mixed 原子投递/退码白名单+1400/100/1200 终态化/W1 文字兜底 |
| 语料工具链 | `scripts/tts_corpus/`（4 脚本收编+反向毒化修复 d210082） | 溯源块+原件 sha256 双向防漂移锚+18 例冒烟门 |
| 真机辅助 | `scripts/tts_offline_selfcheck.py`（一键自检三步）+ `scripts/tts_retcode_collect.py`（retcode 采集） | 重启前自检/真机窗判据采集 |
| 出站体检 | renderer `canonicalize_audio_parts`（voice→record 归一+content_sha256 第三冻结键） | onebot data 白名单恰 {file} 咬合 |

### 2.3 行为变更报备（测试时预期这些「变了」）
1. 同句恒同音色（seed=cache_key 确定性，G2-R3 已裁）。
2. 触发词 11→16（繁體 說/語音/唸/朗讀/語音合成 现在触发合成；繁體日常句仍零劫持）。
3. 括号动作段（（…））不再被念出，只念台词；25℃→25摄氏度 等稳定念法（50% 刻意不替换）。
4. 确定性 4xx 拒绝（如 ref 越界）不再传染 30s 退避窗。
5. bot_tts_api_url 非 loopback → 装载期直接拒（SSRF 闸 fail-closed；生产 127.0.0.1 零影响）。
6. scope=all 群面配音必须过中央四名单（白名单空=群面关闭绝不猜群）。
7. 落盘文件名 uuid 化（tts-{uuid4}.wav，不再含内容指纹）。
8. 键空间换代 → 旧 wav 成孤儿（回收靠 enforce_quota，缺省关）。
9. SnowLuma 真实 1200=终态化（不再挂 30 分钟）。

## 3. 未实现 / 未闭合（诚实清单）

| # | 项 | 状态 | 归属 |
|---|---|---|---|
| 1 | **引擎侧六预案**（U-21 yaml 绝对路径→基线重录→U-22 stdout 落盘→删 /control→Sec-Fetch 门→语料订正+杂散件隔离） | 预案全成文：`.superpowers/sdd/2026-09-19-unify-audit/engine-actions-plan.md`（六预案九步，含备份/回滚/验证/锚串断言） | **等用户一句授权** |
| 2 | 语料门 3 处 xfail 摘牌 | 依赖预案四（tsv 订正）执行；门现钉现状病（strict，修后 XPASS 逼删标） | 授权链内 |
| 3 | M-45 引擎暴露面其余（防火墙 U-18 netsh） | 纵深缺口已披露（Sec-Fetch 门只防浏览器 CSRF） | 等授权 |
| 4 | M-40 回复引用语音听不懂 | 跨域 P2（ingest/chat ASR 面），未派 | 下一波 |
| 5 | M-21 chat 注入闸五处手抄 | 跨域 P1，非 TTS 范围 | 独立波 |
| 6 | M-37 时长维度 | 真机 U-02（估秒硬拦会误杀，等真机数据） | 真机窗 |
| 7 | M-74 语气匹配 b/c 档 | U-28 未裁（确定性已落=方差已关；语义匹配独立波） | 待裁 |
| 8 | M-77 读法词典全量 | 最小集 8 条已落（T104）；人名/专名读法另波 | 下一波 |
| 9 | M-68 smoke 并集（.env.prod 覆盖） | 行为变更待裁决（T142 披露） | 待裁 |
| 10 | S-08 摘要层收尾 | S1-S5 全链已闭合；U-107-C 已落 4f48be6；无剩余（media_archive 外 7 处 A 类手抄=增量收编候选） | — |
| 11 | 全量四门禁 + auto-facts --write + theme_tokens 重录 | 收尾合流轮（theme_tokens DRIFT=他会话在飞面 867b010） | 合流波 |
| 12 | 真机项打包：dlopen 补证/耳听终审/retcode 真包采集/8 条池听辨 | acceptance-manual §6.6.11 E/R 段 | 真机窗 |
| 13 | 跨域 5 席未回席审计遗留（T40/T43/T44/T45 跨域移交单等） | 前波审计遗留，非本两波范围 | 独立波 |

## 4. 台账与对账指针

- **缺陷编号唯一源**：`.superpowers/sdd/2026-09-19-unify-audit/report-T29.md`（M/S/U 三层 134 行已带 2026-09-20 终态标注——T122/T131/T146 三席落）。
- **席位动态全录**：同目录 `progress.md` G2 段（45+ 席逐席哈希/证据/披露）。
- **终验链**：report-T91（全量 9415P GO）→ T110（2153P）→ T128（468P）→ T141（404P）→ T154（726P 最终 GO）。
- **总报告草稿**：同目录 `WAVE-GH-REPORT-DRAFT.md`（定稿第二稿+六A 终补）。
- **引擎授权册**：同目录 `engine-actions-plan.md`（六预案九步）。
- **AGENTS.md §44 行 / docs/HANDBOOK.md §35.8**：两册台账已带 GO 终填（9d758a5）。

## 5. 测试手册（测试 AI 按此执行）

### 5.0 环境
- 仓库根 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`；venv=`../ChatBot_Runtime/venv/Scripts/python.exe`。
- 一切 pytest 带：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp="../ChatBot_Runtime/cache/<你的名>"`。
- **禁**：启停服务/引擎、真连 9880、发真实消息、`--write`（verify_hashes/catalog 除外且需明知）、git add -A、碰 `.env` 实文件、碰 `ChatBot_Runtime/`（venv 解释器除外）。
- 重启后第一件事：`python scripts/tts_offline_selfcheck.py`（pre_restart 10 项→verify_chatbot_env→语料门，一键透传）。

### 5.1 离线测试族（无需引擎/重启，按域跑）
```
# 摘要链全链（M-64）
../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_media_digest.py tests/test_voice_outbound_contract.py tests/test_tts_media_digest.py tests/test_tts_t127.py tests/test_tts_filename_privacy.py -q -p no:cacheprovider --basetemp="../ChatBot_Runtime/cache/tA"
# 传输层（M-63/M-38/W1）
... tests/test_h_voice_delivery.py tests/test_voice_queue_sim.py tests/test_part_idempotent_resume.py tests/test_result_unknown.py tests/test_tts_outbound_chain.py ...
# 触发词/边界（M-01/M-15/M-16）
... tests/test_tts_hijack_guard.py tests/test_text_boundary_central.py tests/test_text_boundary_wiring.py tests/test_trigger_bidirectional_gate.py tests/test_voice_boundary_central_gate.py ...
# 装载/守望/探针（M-68/M-12/M-13）
... tests/test_runtime_config_loader.py tests/test_pre_restart_check.py tests/test_env_verifier.py tests/test_voice_health_probe.py tests/test_datafix_runtime_paths.py ...
# 契约+预设+语料门（M-35/M-07/M-72/M-30）
... tests/test_tts_contract_layer.py tests/test_tts_presets.py tests/test_tts_corpus_gate.py tests/test_tts_corpus_tools.py tests/test_tts_config_gates.py ...
# hook/出站/体检（M-10/M-06/M-19）
... tests/test_voice_hook_assembly.py tests/test_reviewer_media_visibility.py tests/test_media_contract_v2.py ...
# 全量 TTS 族一键
... tests/test_tts*.py tests/test_media_digest.py tests/test_voice_outbound_contract.py ...
```
预期：全绿；已知 xfail 3 枚=test_tts_corpus_gate.py（语料现状病钉，摘牌等授权链）；test_smoke_config/test_pre_restart 若红先查 T142 在飞归属。

### 5.2 真机窗（需用户在场）
1. 授权执行 engine-actions-plan.md 九步（或逐案裁）。
2. 引擎启动后：`python scripts/tts_offline_selfcheck.py` 全绿 → §6.6.11 30 项（O8/E6/R16）→ 每条语音后 `python scripts/tts_retcode_collect.py --json` 采集（实测⊆{100,1200,1400,1404}=T55 §七闭合证据）。
3. U5 耳听终审：音色=守岸人非底模/括号动作不念/数字英文念法/8 条池逐条。

### 5.3 重点核验点（易错处）
- 繁體触发后**正文原样繁體不简转**；繁體日常句（說的是/說了再見）仍零劫持。
- `(T_T)` 颜文字保留不剥（U-23 既有项）；`50%` 不替换（语序保护）。
- 换 ref 内容（size+mtime 不变）→ 缓存键必须变（T129/T120 内容键锁）。
- 无 digest 请求的 dedupe_key 与旧三元组逐字节一致（兼容双锁 tests/test_part_idempotent_resume.py）。
- bot_tts_api_url 配 169.254.169.254/10.x/整型 IP → 装载期拒。
- verify_chatbot_env 在 `python -O` 下仍有效（零裸 assert）。

## 6. 测试 AI 必须验证的清单（我方声明 vs 你的实测）
1. §2.3 九条行为变更逐条复现。
2. §5.1 各族计数与本表偏差>5% 即上报。
3. 引擎 9880 未启时：`说 你好` → 私聊降级文字「嗓子还没接上…」族、群聊走中央 A-19 短句、零 9880 连接尝试超时堆积。
4. bot_tts_voice_hook_enabled=False（缺省）时：聊天回复出站与 hook 无关（字节级）。
5. T29 台账 50 M 行+17 S 行+30 U 行的终态标注抽样 10 条反查哈希。

## 7. 禁碰与陷阱
- `capabilities/tts.py`、根 `runtime/pipeline.py`、根 `sender/worker.py`=PEP562 垫片（他席退役在飞），**禁回滚禁编辑**。
- `domains/*/data/`=源码包目录（T101 事故教训），不是运行残留，禁清。
- `domains/weather/assets/qx.json`=随包资产（362,774B），禁删。
- 共享仓多会话：git 提交一律 `git commit -m … -- <显式路径>`（pathspec），**禁 amend/rebase 已共享提交**（8e47ed0 事故）。
- 共享台账 progress.md 用追加式（cat >>），勿整文件重写。
- 台账目录 `.superpowers/` 在 .gitignore（不入库是设计）；`.tmp-test/` 已被 607472e 收 ignore。

## 8. 本波 45+ 笔提交速查（git log 可溯）
基线十笔（607472e…e0b0722，M-05 收口）→ 修复五笔（d3a53ea/12f956b/c723904/7c566f7/b13913d）→ 施工批（d6801ab/ce85074/1b2860c/4f3d1e8/6988e46/aaee13b/767f2b5/9a9e099/04c8c9a/6c34858/9f1e81a/194a2ca/7d40d8f/0ad3c1e/1a4200b/21b702c/3f8c234/5ddf704/743505b/6a7573e/4f48be6/d210082/c78951f/2f7469d/2401c5c/6d30c7f/64fff5d/4043103/8d9a149/5606cfe/906ca3a/c3ac342/b605692/097b2e9/606c606/7903797）→ 收尾（9d758a5）。
*他会话穿插笔（83233dd 文案批/2039161/6c6b6a5 webui/995b937 等）不在本波对账内。*
