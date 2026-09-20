# TTS 统一波总交接（G 契约层 + H 传输层）—— 穷尽版（v2）

> 定稿：2026-09-20 07:0x。HEAD=`9d758a5`（全部工作在 git，重启/断电零丢失）。分支 `v0.0.1-alpha.2`。
> 读者：下一个对接 AI（测试/续建）。本文档自足——不需要读会话史即可接管。
> 深度子系统事实源：`.superpowers/sdd/2026-09-19-unify-audit/`（progress.md=席位动态+裁定全录；report-T29.md=缺陷编号唯一源，M/S/U 三层 134 行已带 2026-09-20 终态标注；report-T2…T154=60+ 份席报；WAVE-GH-REPORT-DRAFT.md=总报告；engine-actions-plan.md=引擎授权册）。

---

# 第一部分：项目与环境（含全部陷阱）

## 1.1 身份
- QQ 聊天机器人「守岸人」（鸣潮角色人格），NoneBot2 + OneBot V11，协议端 **SnowLuma**（WS 127.0.0.1:3001；旧 NapCat 已退役但文档残留其名）。主包 `plugins/bot_unified_runtime/`，v21r2 起域重组为 `domains/` 20 域（根级 `capabilities/`/`runtime/`/`sender/` 等遗留 **PEP562 垫片**=活再导出，指向 domains 真身）。
- 运行数据根 `ChatBot_Runtime/`（venv/SQLite/日志/缓存）；源码树禁 `data/`/`__pycache__`/`*.pyc`/`.pytest_cache`/`.mypy_cache`/`.ruff_cache`（例外：`domains/weather/assets/qx.json` 362,774B 随包资产禁删；`domains/*/data/`=**源码包目录不是运行残留**，禁清——T101 曾误删已恢复）。
- TTS 引擎：GPT-SoVITS-V2Pro，`C:\Software\GPT-SoVITS-V2Pro`，api_v2 默认 127.0.0.1:9880；**当前未运行**（全波离线施工）。

## 1.2 命令环境（每条 pytest 都要带）
```
# 仓库根 = C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot（Git Bash）
../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <tests> -q \
  -p no:cacheprovider --basetemp="../ChatBot_Runtime/cache/<你的名>" \
  # 且环境：PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0
# BOT_AUTOSYNC=0 必须：缺省会自动 --write 重写三个生成物（command-catalog/render_hashes/doc_sync 机器册）→"全绿"变自我实现
```

## 1.3 陷阱清单（每条都有事故在案）
1. **共享仓多会话**：本波与用户其它会话并行。git 提交一律 `git commit -m … -- <显式路径>`（pathspec 形态）——曾两次被共享 index 卷入他席暂存件（8524811 卷入 outbound_gate.py）。**禁 amend/rebase 已共享提交**（8e47ed0→ece7b43 事故：他会话历史改写曾把已提交件从历史带掉、还整文件重写过共享台账 progress.md 丢过我三条记录）。
2. **共享台账 progress.md 用追加式**（`cat >> … << 'EOF'`），勿 Edit 整文件——他会话整文件重写曾丢我三条记录（已补记）。
3. **漏 add 三例同款**：T75(t75 锁)/T65(helpers/__init__) /T129(h_dedupe 锁) 都发生过"代码入库测试件漏 add"——commit 后必查 `git status` 该域 ?? 清零。
4. **席报落根三例**：T58/T110/T121 曾把 report-T*.md 写到仓库根而非台账目录——写报告用绝对台账路径。
5. **PEP562 垫片**：根级旧路径是活再导出非死文件，**禁回滚禁编辑**（他席退役在飞）；monkeypatch 打垫片无效，要打 domains 真身。
6. **domains/*/data/=源码包**（draw_store/tarot 等），T101 误删已恢复——禁清。
7. **控制台 GBK 假乱码**：git 中文输出有时显示乱码，存储实为合法 UTF-8（python `b.decode('utf-8')` 验证法在案）；反之 verify 时走 python 别信控制台。
8. **.env**：真实密钥只在 `.env`；读白名单键走 `config.translate_env_keys(read_env(...))` 装载路径（T21 法），禁整文件入上下文。
9. **引擎目录 C:\Software\GPT-SoVITS-V2Pro**：全波只读；六项改造已写成预案等授权（见 §7），未授权前禁改。
10. **BOT_AUTOSYNC**：跑测试必须 =0，否则生成物自写（见 1.2）。

---

# 第二部分：任务溯源与探索结论（探索了什么）

## 2.1 用户主张与审计判决
用户主张：「上面所有东西都需要经过中央处理的统一指令，再派给各个插件，TTS 同理。」
26+ 审计席以最残酷态度验证，判决：**主张在七个断面只有两个为真**（命令式路由 ✓/出站记账 ✓；内容闸/政策/质检/观测/协议五面全假）。审计产出缺陷总账：**M-01…M-77（77 条）+ S-01…S-17（全仓共性 17 条）+ U-01…U-30（待裁 30 条）**，唯一编号源=report-T29.md。

## 2.2 六个 P0（全部闭环）
| 号 | 一句话 | 闭合提交 |
|---|---|---|
| M-01 | 句首虚词把日常聊天整句劫持进 TTS（201/295 实测） | d3a53ea 虚词剔除 + ff091dc 繁體 16 词 + 8524811 六副本收编 |
| M-02 | 语音文本零内容闸+审核对 audio 失明 | d3a53ea speech_block_reason 直连中央 + 12f956b reviewer 看见媒体文本 |
| M-03 | 语音文本零打码（sk-/盘符/BOT_ 键值进音频） | d3a53ea resolve_speech_text 打码前置（先码后洗，占位符 `<已隐藏>`→`已隐去`） |
| M-04 | 语音段被平台静默摘除却记 SENT（谎报送达） | 743505b 段级记账+绝对路径死引用闸（SnowLuma 语义=T46 复判决推翻 NapCat dropped 假设） |
| M-05 | domains/ 416 真身 0 git 跟踪（一条 clean -fd 全塌） | 607472e…e0b0722 十笔基线 416 件全入库 |
| M-63 | mixed 语音游离 part 级幂等，最坏真投 9 遍 | 194a2ca 段级记账原子投递（9→首轮冻结）+ b605692 dedupe d 段 |

## 2.3 关键探索发现（影深排序）
1. **中央能力协议层 1929 行生产零导入**（F1）——"中央存在但未接管"，现行中央=根 __init__.py 上帝文件（8600+ 行）。
2. **TTS 三入口两不在册**：命令式 `说 X`（RouteKind.TTS 走 pipeline）✓；自动配音=根 init :4718 闭包包装（review 前拦截、零注册零观测）✗；hook 化后=9f1e81a voice_enricher ✓。
3. **引擎契约**：请求 24 键 pydantic 零范围校验；bot 实发 19 键漏 5 死键；WebUI 滑杆域=speed 0.6-1.65/top_k 1-100/top_p 0-1/temp 0-1（T53 权威表）；推理异常→**200+1 秒静音 wav**（T2）；权重缺失**静默回退底模+写回 yaml 永久中毒**（T2/T12）；输出 32000Hz int16 mono。
4. **SnowLuma 换件语义翻转**（T46）：NapCat 坏段=dropped 静默；SnowLuma 坏 record=**throw 整条不发**（fatal）——M-04/M-63 定级据此重判，W1 兜底=保文字非保语音。
5. **退码白名单实集**={403,404,1003,1200,1201,1401,1403,1404}，缺 SnowLuma 实回 1400/100（T46-N1）；真 1200 会挂 bot_unavailable 30 分钟（T97 发现，已终态化）。
6. **触发词劫持率**：T15 实测 201/295=68.1%（语料配比属性；族内 100%/自然语料 14.3%）；六域副本取值互不等；提取器 L-C04 单行委托失明（T68 修）。
7. **语料三源分裂**：.env=订正后权威；引擎 tsv=校对前旧文本（虚至此报/力隙）；照 T03 §5.3 复核法操作会**反向毒化**（T96 门已钉 xfail(strict)）。
8. **观测面结构性缺失**：TTS 出事运维全盲——告警/错误卡/stats 三面零信号（T14）；`/bot status` 零 TTS 行（已接线 863fee6）；pre_restart 零 TTS 项（已补第 10 项 1b2860c）。
9. **装载四套并存**（M-68）：生产 dotenv/smoke 手搓/pre_restart 第三套/verify_chatbot_env 假绿——已收敛唯一入口 6a7573e（351 键三链对拍零差异）。
10. **参数出处 5/10 无据**（M-75/M-76）——preset 表 rationale 列根治；8 硬编码出门参数收编（split_bucket 死意图显式 False）。

## 2.4 探索方法论（复用价值）
- **对抗证伪席**（T19/T34/T56/T62）：每条承重结论派独立席复跑，accept/reject 有据——T62 用 `git archive` 提交树隔离法复跑 RED 9F/1P 与 T57 自报逐字吻合。
- **变异探针内存法**（T5/T81）：源码读入→%TEMP% 字符串替换→exec 回注，零仓库写入验测试证明力。
- **三源对账门**（T96）：权威=.env、tsv=推导副本、反向毒化探针锁歧路。
- **提交树隔离**（T62）：`git archive` 父/本提交全树+%TEMP%+桩重包 init，避开共享树在飞污染。
- **inventory-first 断点继承**（T123→T129）：阵亡席半成品先 git diff 通读判定续用/回滚，不盲目重做。

---

# 第三部分：改造后架构与流程（现在的真实形态）

## 3.1 TTS 全链（改造后，哈希可溯）
```
[入站]
 说 X / 說 X（16 词∪追加，中央件 domains/core/text_boundary.py 唯一判定）
   → RouteKind.TTS（base_router，priority 41，block=True）
   → 门禁 gate（黑白名单/安静时间/限流/确定性抽奖 deterministic_group_reply_lottery）
   → RuntimePipeline(offload 池)
   → 能力层 tts.py：
       resolve_speech_text（先 redact_local_secrets 打码 → 括号动作段剥除(roleplay.strip_action_brackets 共用真相源)
         → 读法词典(8 条活跃+%～关断) → markdown 剥除 → max_chars 截断[0=不限+硬顶2000字/8MiB]
         → 全程 lossy_transform_tags 机读审计）
       → should_voice_reply（六道门+中央四名单 explicit_allowed_for_session 同源）
       → pick_ref_audio（确定性：seed=cache_key 派生，hashlib 指纹 v2）
       → synthesize：POST 9880/tts → _inspect_wav_bytes 结构闸(RIFF/帧>0)
         → 静音三指纹闸(16kHz+恰1s+近全零) → 落盘 tts-{uuid4}.wav
         → media_digest(bytes) → content_sha256 随部件
       → OperationalIssue 族（tts_service_unreachable 可重试/tts_bad_audio/tts_write_failed/tts_no_ref_audio/…）
       → CapabilityResult.audio=[{type:record,file,content_sha256}]
   → review_capability_result（reviewer._collect_scan_text 看见媒体文本）
   → renderer canonicalize_audio_parts（voice→record 归一+第三冻结键）
   → SendQueue（dedupe_key=消息身份∧段类型∧d=content_sha256[:16]，无 digest 逐字节不变）
   → worker 段级记账（mixed 原子投递，超时/断连→全 UNKNOWN→PARTIAL 冻结；退码白名单+1400/100；1200 终态化；W1 首轮文字兜底）
   → onebot data={file} 白名单 → SnowLuma

[自动配音 hook（键开才生效，缺省 False 字节不变）]
 chat 能力 → review 后 → outbound_voice_enricher（voice_enricher.py）
   → 取 review 后 body → resolve_speech_text 同链 → 失败精确挂 issue（根侧零自拼文案）
   → R-16②：群内降级归中央 A-19

[观测]
 落盘点/出站 audit_tags（lossy_transform_tags+audio_sha256[:16]+seed/preset）
 → OperationalIssue → _notify_operational_receipt → alerts 300s 抑制 → 错误卡
 /bot status 语音行 ← voice_health_probe（惰性 TCP ≤2s）
 pre_restart_check 第 10 项 ← check_tts_voice_identity（yaml 语义+sha256 基线册）
```

## 3.2 消息/配置/摘要横切面
- **触发词**：中央件 casefold+繁簡词表登记（不做 s2t）+虚词边界唯一权威；六消费点全走它；`effective_trigger_words()`=内置 16∪追加唯一入口；提取器递归追踪委托（L-C04 修复）。
- **装载**：`scripts/load_runtime_config.py::load_runtime_config(env_files=…)` 唯一入口；pre_restart（值层签名不变）/verify_chatbot_env（F1 位置自证）/smoke（单文件契约保留）三消费方；生产 bot.py:255 真身不替换双层对拍锁。
- **摘要链**：S1 digest.py 唯一真身（全长+1MB 流式）→ S2 tts.py 落盘点 media_digest_file 挂 content_sha256 → S3 canonicalize 第三冻结键（缺省退化）→ S4 dedupe_key d 段（无 digest 逐字节不变）+`-textfb` 内容寻址+textfb_parent 归位 → S5 media_archive 收编。**全链可选缺省退化=兼容性根**。
- **预设表**：`bot_tts_preset` 单键（枚举校验+TTS_PRESET_IDS 一致性门）；20 键全部单源化（第二缺省 27 处删除）；9 数值键 Field 域闸+3 枚举校验器；max_chars 0=不限+硬顶 2000 字/8MiB；split_bucket 死意图显式 False。
- **配置门**：bot_tts_api_url 装载期 loopback 白名单 fail-closed（26 拒绝面探针：元数据/内网段/公网/整型 IP/v6 变体/userinfo/畸形端口）；bot_tts_gptsovits_dir 入 path_fields（绝对透传/相对重定向/空串保持三态）。

## 3.3 观测与自检
- OperationalIssue 族：tts_service_unreachable(重试)/tts_empty_audio(重试)/tts_bad_audio/tts_write_failed/tts_no_ref_audio/tts_service_rejected + missing_file（T100）；blocked_by_policy 有意不挂（防刷屏）。
- 健康探针 voice_health_probe：惰性 TCP（不常驻不代启动=U-17=C 宪条）；300s 同窗不重复挂 issue；voice_status_line 进 /bot status。
- 音色守望：pre_restart 第 10 项（SKIP 不假红/FAIL 五类人话/基线册 tts_voice_baseline.json）。
- 退避真闸：30s 窗/快速失败挂 tts_service_unreachable/真成功清零/快速失败不刷新窗（防永久拉黑）；4xx 确定性拒绝不进窗（T75 失败分类学）；体检失败不入窗。

---

# 第四部分：缺陷全账（问题/漏洞/bug 逐条——已修与未修）

## 4.1 已修缺陷（核心 45+ 条，全带哈希）
### P0 六条
- **M-01 劫持**：虚词剔除（d3a53ea）；提取器 L-C04 委托失明根修（767f2b5，bot.tts 0→11 词）；繁體 5 词登记（ff091dc）；六副本收编（ce85074 T66 五处+8524811 T83 tts 本尊）；棘轮转硬门（T77 双门 0487156/T83 摘标）。
- **M-02 内容闸**：speech_block_reason 直连 assess_public_content+explicit_allowed_for_session fail-closed（d3a53ea）；reviewer 媒体可见（12f956b）；配置错误/政策异常区分双路挂 issue（T56→T61）。
- **M-03 打码**：先码后洗定序（d3a53ea）；占位符 `<已隐藏>` 第二形态补齐（T61）；`<本机路径已隐藏` 残缺入声修（T61）。
- **M-04 谎报送达**：SnowLuma fatal 语义下 worker 段级记账+退码白名单（194a2ca）；绝对路径死引用闸（743505b）。
- **M-05 domains 零跟踪**：416 件全入库（607472e…e0b0722）+qx.json 新家+否定规则。
- **M-63 盲重投**：mixed 原子投递段级记账（194a2ca；9 发→首轮冻结）；dedupe d 段（b605692）。

### P1 二十八条（要点）
M-06 体检闸（7c566f7+T61 静音闸三指纹 16kHz/恰1s/近全零）｜M-07 静音假成功（T61）｜M-08 同句 8 缓存键（T57/T61 seed 派生）｜M-09 退避死代码（T57 真闸）｜M-10 自动配音 review 前拦截（9f1e81a hook）｜M-11 缓存键缺引擎身份（T57 api_url+T61 ref 指纹）｜M-12 音色静默换底模（1b2860c 守望+基线册；引擎半=授权册）｜M-13 失败静默（c723904 OperationalIssue 族+9f1e81a hook 半）｜M-14 念 42% 字无观测（b77b7f4 audit 化）｜M-15 追加变替换（b13913d）｜M-16 大小写/繁體（b13913d+ff091dc）｜M-17 群面名单同源（b77b7f4）｜M-19 出站自由袋（6c34858）｜M-20 测试证明力三洞（7d40d8f+T81 终裁）｜M-32 api_url 零闸（034bcb8）｜M-38 死路径出站（743505b）｜M-39 文件名指纹泄露（1a4200b）｜M-52 重映射漏网（2401c5c）｜M-61 工具链零版本（c78951f）｜M-64 字节零摘要（d823232/c24282a/b605692/c3ac342 全链）｜M-67 体检器假绿（7e2fe36）｜M-68 装载四套（6a7573e）｜M-73 括号被念（5ddf704）｜M-77 读法词典占位（5ddf704 最小集）。

### P2 择优收编
M-30 语料对齐门（097b2e9）｜M-66 文档面（6d30c7f）｜M-45 预案六（T147）/control+Sec-Fetch（等授权）｜M-69 转录防护（T148 repo 副本）。

### 测试与门禁建设
G-4 双机器门（0487156：出站入口 A1-A5+边界谓词 B1-B4，负样本 8 例实弹自检）；G-5 四轮终验（T91 9415P→T110 2153P→T128 468P→T141 404P→T154 726P，全 GO）；语料对齐门（097b2e9 内 5P/3x 现状病钉）；M-20 补锁（7d40d8f 四变异各恰 1F）。

## 4.2 未修/未闭合（13 条，全带归属）
| # | 项 | 为什么没修 | 归属 |
|---|---|---|---|
| 1 | 引擎侧六预案 | 需用户授权（引擎目录禁改铁律） | engine-actions-plan.md 九步等一句 |
| 2 | 语料门 3 xfail 摘牌 | 依赖预案四 tsv 订正 | 授权链 |
| 3 | U-18 防火墙 netsh | 同上（纵深缺口已披露：Sec-Fetch 门只防浏览器 CSRF） | 授权链 |
| 4 | M-37 时长硬拦 | 会误杀正常长回复，等真机时长数据 | 真机窗 U-02 |
| 5 | M-74 语气语义匹配 | U-28 未裁（确定性方差已关） | 待裁 |
| 6 | M-77 全量读法词典 | 最小集已落，全量另波 | 下一波 |
| 7 | M-68 smoke 并集 .env.prod | 行为变更待裁决 | 待裁 |
| 8 | M-40 回复引用语音 | 跨域 P2（ingest/chat） | 独立波 |
| 9 | M-21 chat 注入闸 | 跨域 P1 非 TTS | 独立波 |
| 10 | M-18 NapCat 坐标行 | 真机待证 | 真机窗 |
| 11 | M-26 协议层通电 | RET2b 收口窗（G-4 门已锁死旁支） | 收口波 |
| 12 | 全量四门禁+auto-facts+theme_tokens | 收尾合流轮（theme_tokens DRIFT=他会话面） | 合流波 |
| 13 | U-107-C 完整观测 | 最小面已落 4f48be6 | 已闭（余项待裁） |

## 4.3 已知残留缺陷（如实披露，未修）
- 语料 tsv 反向毒化现状（门钉 xfail(strict)；根治=预案四授权）。
- tts.py:389 已流式化（T127）；:445/446 已收编（T127）；tts.py 无已知残留。
- file_gateway:207 简报前提不成立（原本已流式）——无优化可做（T121 纠偏）。
- `%`/`～` 读法刻意关断（语序/双语义）；`(T_T)`→`(TT)` 为 U-23 既有项。
- 引擎原件 transcribe_refs 仍带毒化缺陷（repo 副本已修+分叉登记）。
- 相对路径死引用透传（T100 C 案：生产恒绝对路径，相对面登记未闭）。
- image 部件死引用回退不在闭合面（W1 事故回归件前提耦合，留专席）。
- 空体不进退避窗无承重（P3 可选）。
- honami L25「力希」疑同族误听=T96 门盲区（语料权威裁定）。

---

# 第五部分：修改全量（45+ 笔提交逐笔账）

## 5.1 基线十笔（M-05 收口）
`607472e` .gitignore 表F → `c40c8e1`/`de7ef71`/`ea41da1`/`07786f4`/`13d2f7d` domains 五批(115+82+95+78+37) → `60453a3` transport 三真身 → `9cf310d` 交接文档+pyproject → `e0b0722` P2a 重演（他会话历史改写事故补救）。

## 5.2 审计修复五笔（前波）
`d3a53ea` M-01/03/语音半M-02 → `12f956b` M-02 中央半 → `c723904` M-13 → `7c566f7` M-06+M-23 → `b13913d` M-15/M-16。

## 5.3 Wave G 施工批
`d6801ab` T57 M-09/M-11 → `ce85074` T59 中央谓词件+70例 → `1b2860c` T60 音色守望+预检10项（含他批8/9项防丢失）→ `4f3d1e8` T63 交接勘误9处 → `6988e46` T70 路由册/命令册 → `9a9e099` **T61 G-2契约层**（预设表/域闸/0=不限/静音闸/seed/缓存v2/配额，+300行）→ `04c8c9a` T76 验收手册30项版 → `6c34858` T80 M-19出站契约 → `9f1e81a` **T73 G-3自动配音接中央**（+1635行根init双态）→ `194a2ca` **T78 Wave H传输层**（段级记账+退码+W1）→ `7d40d8f` T90 M-20四锁 → `0ad3c1e` T102 微同步 → `1a4200b` T101 M-39 → `21b702c` T75锁补录 → `3f8c234` T99 繁體尾巴 → `5ddf704` T104 M-73/M-77 → `743505b` **T100 M-38闭合** → `6a7573e` **T142 M-68闭合** → `4f48be6` T144 观测面 → `d210082` T148 毒化修复 → `c78951f` T106 工具链 → `2f7469d` T107 蓝图 → `2401c5c` T125 M-52 → `6d30c7f` T103 snowluma文档 → `64fff5d` T130 登记节 → `4043103` T124 索引同步 → `8d9a149` T136 手册工具刷新 → `5606cfe` T117 双工具 → `906ca3a` T121 A类收编 → `c3ac342` T116 S5 → `b605692` **T129 S4** → `097b2e9` 语料门+hashes重录 → `606c606` S4锁补录 → `7903797` T160 README+handover → `9d758a5` 两册终填+头注。

## 5.4 每笔的测试证据（要点）
- T57：原生 RED 9F→10P；T62 git archive 隔离复跑逐字吻合。
- T59：继承态 49F 在案+变异探针 14F；132P 零回归。
- T60：RED 14F→41P；真机只读探针 PASS。
- T61：RED 30F/15P→46P；族 397P→T75 后 257P→T127 后 407P。
- T66：RED 6F→500P（含 hijack 62）；T83：211P；T120：403P；T144：415P；T127：407P。
- T142：生产 .env 351 键三链 model_dump 全等；69P+117P。
- T154：七族 726P/0F/3x（3x=语料现状病钉）。

---

# 第六部分：架构决策记录（裁了什么、为什么、错则如何）

| 裁决 | 内容 | 依据 | 错则代价 |
|---|---|---|---|
| G-R1 | 契约层优先，传输层排 H 波 | 六轴中央门先立 | 语音重投风险延后（已闭环） |
| G-R2 | 中央语音预设表（U-27） | 七条缺陷同载体 | — |
| G-R3 | M-35/M-07 升 P0；max_chars 0=不限 | 引擎域值权威 T53 | — |
| G-R4 | git 授权全开（四项） | M-05 拆雷 | — |
| G-R-M1 | 0=不限≠无界，硬顶兜底 | 引擎显存+QQ 物理上限 | 多一条配置 |
| G2-R1 | U-29=A 保 mixed+段级记账 | 无产品形态变化 | — |
| G2-R2 | U-17=C 人工脚本+只读探针 | 不代启动宪条 | — |
| G2-R3 | 硬顶 2000 字/8MiB；语料门挂账方向 | T53 域值+T96 现状钉 | 数值可调 |
| 主代理 C 案（T100） | 绝对路径闭合/相对透传 | 生产恒绝对=100% 覆盖 | 相对面登记未闭 |
| T101 uuid 文件名 | 隐私优先，键内存寻址 | M-39 指纹泄露 | 孤儿靠配额 |
| T148 拒绝不转义 | parse 裸 split 无转义语义 | 结构性成立 | 引擎原件分叉（登记） |
| T144 最小观测 | U-107-C 纯元数据 | 蓝图推荐 | 完整面待裁 |

---

# 第七部分：行为变更报备（9 条，测试预期差异）
见 WAVE-GH-REPORT-DRAFT.md §四全表；速记：①同句恒同音色 ②繁體 16 词触发（繁體日常句零劫持）③括号动作不念出 ④4xx 不进退避窗 ⑤api_url 非 loopback 装载期拒 ⑥scope=all 群面过四名单 ⑦uuid 文件名 ⑧键换代旧 wav 孤儿 ⑨1200 终态化。

---

# 第八部分：测试手册（操作级）

## 8.1 一键自检（重启后第一件事）
```
python scripts/tts_offline_selfcheck.py        # pre_restart 10项 → verify_chatbot_env → 语料门，FAIL透传
python scripts/tts_retcode_collect.py --json   # 真机语音后采集（实测⊆{100,1200,1400,1404}=闭合证据）
```
## 8.2 离线测试族（全部应绿；3 xfail=语料现状钉）
分族命令见 §5.1 模板；总族一键 `pytest tests/test_tts*.py tests/test_media_digest.py tests/test_voice_outbound_contract.py`（基线 415P/3x）。
## 8.3 真机 30 项
docs/acceptance-manual.md §6.6.11（O8 离线/E6 引擎/R16 真机+P-8 前置）；工具=tts_offline_selfcheck+tts_retcode_collect。
## 8.4 抽样反查
T29 台账 134 行终态标注抽 10 条反查哈希（T122/T131 抽查法）；行为变更 9 条逐条复现。

---

# 第九部分：禁碰与流程铁律
1. PEP562 垫片（根 capabilities/*/runtime/*/sender/*）禁回滚禁编辑。
2. `domains/*/data/`=源码包禁清；qx.json 禁删。
3. pathspec 提交（`git commit -m … -- <paths>`）；共享台账追加式；他会话在飞件不卷入（列清单归其席）。
4. 席报写台账目录绝对路径（仓库根三例事故）。
5. commit 后查 `git status` 该域 ?? 清零（漏 add 三例教训）。
6. BOT_AUTOSYNC=0 跑测试；verify_hashes --write 后必 --check 归零。
7. 引擎目录未授权禁改；.env 白名单外禁读。
8. T29 台账终态标注格式=「2026-09-20 终态：」行尾追加，原审计内容零改动。

---

# 第十部分：待用户决策清单（一句话即可解锁）
1. **引擎六预案授权**（engine-actions-plan.md 九步）——解锁语料门摘牌+M-45+M-12 引擎半。
2. **真机窗**（重启+引擎+§6.6.11 30 项+retcode 采集）——解锁 M-37/M-18/dlopen/耳听终审。
3. **M-74 语气语义匹配 b/c 档**——未裁。
4. **M-68 smoke 并集 .env.prod**——行为变更待裁。
5. **M-64 A 类手抄余量**（tts.py 三处 T120 后已收编；file_gateway/meme 已收；余 scripts 四处=维持现状决议）。
6. **M-77 全量读法词典**——下一波或本波追加。
7. **收尾合流轮授权**（全量四门禁+auto-facts --write+theme_tokens 重录+他会话在飞面收口）。
