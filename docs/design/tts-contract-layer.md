# TTS 统一性契约层 · 设计规格（Wave G · G-1，席 T54）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> 版本 v1（2026-09-19 定稿）。作者=T54 契约层设计席（接替未落地的 T51）。
> 性质：**规格件，不是成果件**——本文零施工；任何「落地」宣称以 G-2/G-3/G-4 施工席实跑为准。
> 权威链：缺陷编号唯一源=`.superpowers/sdd/2026-09-19-unify-audit/report-T29.md`（M-xx/S-xx/U-xx）；
> 施工计划=`同目录 plan-G-contract.md` §G-1（本文是其「缺一不算 DONE 五件事」的成文+扩展）；
> 引擎侧数字转引 report-T35/T25/T2/T20/T46（**report-T53 引擎真值席未在盘，凡标「待 T53 校准」处 G-2 不得视为定稿**）。
> 用户裁定已绑入：G-R1～R4、G-R-M1～M4（plan-G §一）、**U-17=C（引擎生命周期=人工脚本+只读探针+告警，不代启动）**、
> **U-29=A（混排保一条消息+段级记账，不拆条）**（progress.md「Rulings（G2 续）」）。
> 路径约定：下文 `tts.py`=`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`（858 行，已跟踪）；
> 行号为 2026-09-19 工作树实读（T54 本席复核）；引擎侧行号全部转引，标「转引」。

---

## §0 当前态快照（G-1 开工时点，防后续席引用过期坐标）

T29 审计后已有两批修复入树（18:33 批 + c723904/7c566f7），契约层必须站在**实况**上设计：

| 面 | 现状 | 锚点 | 归属 |
|---|---|---|---|
| 触发边界 | 虚词已退场，边界集=纯标点/空白 | `tts.py:83 _TEXT_BOUNDARY_CHARS="，,。！？!?：:、 　\t～~"` | M-01 止血已落地 |
| 触发词语义 | 内置∪追加合并 + casefold（英文大小写不敏感）+ 繁體 5 词（T92 登记） | `tts.py:158 effective_trigger_words`、`:175 extract_tts_text` | M-15/M-16 已收口（T92 词表登记+T99 echo/册页同步） |
| 打码 | `resolve_speech_text` 内 redact 前置于清洗 | `tts.py:694/:708`（`redact_local_secrets`） | M-03 主链已落地 |
| 内容闸 | `speech_block_reason` 接中央 `explicit_allowed_for_session`+content_safety | `tts.py:663`（`:673` 调中央件） | M-02 命令式半/M-17 已落地 |
| 产物体检 | 结构体检闸（RIFF+头+帧数>0），不过=不落盘/不入缓存 | `tts.py:399 _inspect_wav_bytes` | M-06 半收口（7c566f7；时长维度刻意留白） |
| 失败留痕 | 六类 `tts_*` OperationalIssue 码族已挂 | `tts.py:515 _issue`/`:541`/`:548` | M-13 已落地（c723904） |
| 概率门 | 确定性哈希桶（本域副本，未并中央件） | `tts.py:740/:795-799` | M-44 未收编 |
| **仍在** | `seed:-1` 硬编码 | `tts.py:358` | M-72 未修 |
| **仍在** | `_MARKDOWN_MARKS_RE` 仍吃 `_`/`>`（占位符互斥未收口） | `tts.py:117` | M-03 残余（U-23 待裁） |
| **仍在** | 健康退避只写不读 | `tts.py:109-110`（写点 :368/:373/:392） | M-09（**T48 在飞**） |
| **仍在** | 自动配音包装在 Review 前 | 根 `__init__.py:341-362/:4718` | M-10（G-3 施工面） |
| **仍在** | 缓存键无引擎/素材身份 | `tts.py:282 _cache_key` | M-11（T48 在飞+G-2 收编） |
| **仍在** | `data/tts_output` 零配额零 owner | `tts.py:472 _output_dir`（:473 CWD 兜底残余=M-52） | M-27/S-09 |
| 路由 | matcher 仍从垫片导入 | `base_router.py:80/:431-438/:577` | T10 Phase 4 面 |

---

## §1 契约一：引擎 HTTP 契约中央表（治 M-31/M-33/M-34/T35 全表）

**地位**：本表是「bot↔引擎」与「bot↔平台」两侧请求/响应语义的**唯一真相源**；消费方=tts 契约层（G-2）、传输层（H 波）、契约测试（G-4）、错误归因文案层。T46-N1 的退码语义**归属上移至此**——传输层白名单只是本表的消费者，不再是语义持有者（施工仍在 H 波，G-R1）。

### §1.1 请求形态

| 项 | 契约 | 依据 |
|---|---|---|
| 端点 | `POST {api_url}/tts`，JSON body；bot 恒 `streaming_mode=False`、`parallel_infer=True`（最稳分支） | api_v2.py:511（转引 T35 §0）；bot 侧 `tts.py:323-345 _request_tts` |
| `GET /tts` | **保留不用于生产**：浏览器试听工作流专用（U-17 附带、验收⑥依赖）；**陷阱：GET 入口对 `text_lang` 做 `.lower()`（api_v2.py:484/:488）而 POST 不做**——同一引擎两入口行为不一致 | 转引 T2:35、T20:17/:35 |
| 请求键集 | `TTS_Request` 19 键，全字段带默认、`extra=ignore` ⇒ **漏键走默认、多键被忽略，都不报错**；真 422 只来自类型违例，枚举错是 400 | api_v2.py:154-178（转引 T2:48） |
| `text_lang` | **bot 出门前一律 casefold**（POST 入口引擎用原值断言 `TTS.py:1116`，"ZH" 得 400）；合法域=`[auto,auto_yue,en,zh,ja,yue,ko,all_zh,all_ja,all_yue,all_ko]` | 转引 T35 §1 #13/P1-T35.4、TTS.py:275-277 |
| 枚举域 | `text_split_method∈cut0..cut5`、`media_type∈[wav,raw,ogg,aac]`、`text` 非空、`ref_audio_path` 非空 | api_v2.py:305-342 check_params（转引 T35 §0） |
| 数值域 | **引擎完全不查**（top_k/top_p/temperature/speed_factor/seed 零校验）⇒ 域闸责任全在 bot 侧（§3 预设表 `Field(ge/le)`） | 转引 T35 §0「数值域一个都不查」 |
| 并发语义 | 引擎 `workers=1` 单进程，非流式同步推理独占 event loop ⇒ 全端点严格排队；bot 标量超时最坏 3×60s | api_v2.py:572/:441（转引 T35 §4、T25 P3-1） |

### §1.2 响应/退码语义总表（两侧合一）

| # | 来源 | 信号 | 语义 | bot 侧映射（既有码族，复用不新造） |
|---|---|---|---|---|
| E1 | 引擎 | `200` + RIFF/WAVE 结构健全字节 | 成功 | 正常出货 |
| E2 | 引擎 | `200` + ≈32044B/16000Hz/恰 1s 静音（top_k≤0、speed_factor≤0、纯标点文本五值通道，`TTS.py:1516-1527` yield 静音+单次 next 吞 raise） | **引擎伪装成功** | 体检闸拒 → `tts_bad_audio`（不可重试）；采样率≠产物标称+恰 1s 两条指纹可机检（待 T53 校准指纹值） |
| E3 | 引擎 | `200` + 非音频字节（HTML 网关页/碎片） | 上游异常 | 体检闸拒 → `tts_bad_audio` |
| E4 | 引擎 | `400 {"message":…}`（枚举/必填，无 Exception 键） | 请求被引擎拒 | `tts_service_rejected`（不可重试）+ reason 归因（§5 表） |
| E5 | 引擎 | `400 {"message":"tts failed","Exception":…}`（推理异常/参考音频越 3~10s） | 推理失败 | `tts_service_rejected`；Exception 含「参考音频」→ `tts_no_ref_audio` 族文案 |
| E6 | 引擎 | `422`（pydantic 类型违例，`detail:[…]` 可空） | bot 自身键型错 | `tts_service_rejected` + detail 数组渲染（M-57 干尾修法） |
| E7 | 引擎 | 连接拒绝/超时/断连（引擎可能仍在完成推理并丢弃结果） | 不可达或排队超时 | `tts_service_unreachable`（可重试）+ 退避真闸（T48 面）；文案=「服务忙/排队」非「没在跑」（M-57） |
| P1 | SnowLuma | `retcode∈{100,1200,1400,1404}` + `failedResponse={status:"failed",retcode,data:null,**wording**}`（字段名是 `wording`，非 message/msg） | 平台动作失败四值全集 | 录本表为语义源；`record` 段投递失败记账归段级台账（§5.8，U-29=A） |
| P2 | SnowLuma | `1400`（消息校验失败：record 缺 file/url、未知段类型、字段非标量）与 `100`（动作失败）**不在**现行 `_is_final_failure_retcode={403,404,1003,1200,1201,1401,1403,1404}` 白名单 | 毒语音会白烧 3 轮 | **T46-N1 施工在 H 波**；修法=按平台版本声明 retcode 集（读本表），`domains/transport/sender/onebot.py:119-122/:174` 的 `_ONEBOT_API_UNAVAILABLE_RETCODE=1200` 语义漂移同批改判 |
| P3 | SnowLuma | 「适配器无连接」分支在 SnowLuma 下不可达（真断线走 NoneBot `ApiNotAvailable`，无 retcode） | 白名单挂起分支死码 | H 波收编时随 P2 一并处置 |

### §1.3 引擎错误码归一规则（治 M-33 locale 脆弱）

禁中文散文子串匹配；归一顺序=①HTTP 状态码 ②`Exception` 字段白名单关键值（参考音频/语种/权重） ③兜底 `tts_service_rejected`。引擎自带 `tts_error_catalog.py:77` 行错误目录为**候选映射源**（转引 T25/T29 M-33），T53 校准后表驱动接入。`_degrade`（`tts.py:477`）改为「按本表类别分派文案」：参数非法→管理员向提示，引擎不可达→用户向兜底话术（P1-T35.3 归因丢失的修法落点）。

---

## §2 契约二：中央语音预设表（G-R2 / U-27=c；治 M-35/M-72/M-75/M-76/M-77/M-28/M-67）

### §2.1 载体与形态

- 载体=**版本化 Python 注册表模块**（建议 `domains/media/tts_presets.py`），数据驱动 dict，**随包入库、入 `tests/verify_hashes.py` 哈希册**。不落 config 文件：可评审、可哈希锁、五处登记矩阵只新增 1 键。
- config 新增**唯一**选择键：`bot_tts_preset: str = "shorekeeper"`（枚举成员校验=注册表键集）。
- **与既有 20 键的关系（本席推荐，无保留同意）**：**preset=唯一缺省源；`BOT_TTS_*` 保留为管理员覆盖（覆盖优先级：env 显式值 > preset）；catalog 对被吸收键标 deprecation 周期=U-13（翻正+旧键告警保留一个版本周期，到期删净）**。理由：①v1 预设值=现状生产生效值收编 ⇒ 行为字节级不变，零迁移风险；②M-43 的 27 处 getattr 第二缺省随「preset 唯一缺省源」一次删净；③五处登记矩阵（config.py/catalog/env-example/SETTABLE/机器册）只加一键，串行窗成本可控。唯一代价=两个 `max_chars` 键在 U-13 周期内并存于「截断」语义（§3 收编为硬顶族），catalog 需写明键族关系。
- seed_policy 与探测选型随表裁定已由 G-R2 落定：探测选 **①ffprobe+版本落 CSV**（T24-§4b）。

### §2.2 预设表结构（列定义）

`preset_id` → `{params: {键: 值}, seed_policy, lexicon, ref_pool, rationale_note}`。
**列**：键｜类型｜域值（引擎 WebUI 滑杆）｜v1 预设值（=现状收编）｜rationale｜收编自。

| 键 | 类型 | 域值 | v1 值 | rationale | 收编自 |
|---|---|---|---|---|---|
| text_lang | enum | `auto/auto_yue/en/zh/ja/yue/ko/all_zh/all_ja/all_yue/all_ko`（出门 casefold） | `zh` | 中文人格主体；混读行为零约定（M-77，待 U-02 听辨） | T25 §1#6 |
| text_split_method | enum | `cut0..cut5` | `cut5` | 抄引擎缺省未声明=「有意跟随缺省」就此显式化 | T25 §1#5 |
| media_type | enum | `wav/raw/ogg/aac` | `wav` | SnowLuma 链按 wav 契约（§1.2 P1）；换格式=字节顶换算失效须重裁（§3.2 判据） | T25 §1.1 |
| top_k | int | **1～100**（WebUI 滑杆） | `15` | 全表唯二有可复核出处（引擎缺省+WebUI value=15） | T25 §1#3（A 类） |
| top_p | float | **0～1** | `1.0` | 同上（WebUI value=1） | T25 §1#4（A 类） |
| temperature | float | **0～1** | `0.9` | 现状收编；出处原为「指向不存在的预设卡」注释（C 类）⇒ 本列即**唯一交代**：待 U-02 听辨 A/B 后改判 | M-75/T25 §1#2 |
| speed_factor | float | **0.6～1.65** | `0.85` | 现状收编；比引擎缺省慢 17.6%，听辨依据不存在 ⇒ 同上待听辨 | M-75/T25 §1#1 |
| batch_size | int | 待 T53 校准（抄 WebUI 滑杆） | `1` | 有意跟随引擎缺省（显式化） | M-76 |
| batch_threshold | float | 待 T53 校准 | `0.75` | 同上 | M-76 |
| split_bucket | bool | — | **`False`** | **死意图消除**：引擎在 `speed_factor≠1.0` 时无条件自动关闭并打日志（TTS.py:1097-1099）⇒ 预设显式 False，与实况对齐 | M-76 |
| fragment_interval | float | 待 T53 校准（[0,1] 滑杆） | `0.3` | **每段尾补静音含末段，直接进时长账**（120字≈50s 的组成项）；动它=时长账重算，rationale 挂 U-02 | M-76/T25 §3.1 |
| repetition_penalty | float | 待 T53 校准 | `1.35` | 有意跟随引擎缺省（显式化） | M-76 |
| parallel_infer | bool | — | `true` | 与 workers=1 排队语义组合后=HTTP 层串行（§1.1）；维持 | M-76 |
| **seed** | int | 任意 int（`-1`=每请求随机重播种，`TTS.py:194-214`） | 见 seed_policy | **不再直配**；由 seed_policy 列派生（§2.3） | M-72 |
| max_chars / auto_reply_max_chars | int | ≥0；**0=不限（不截断）** | `200` / `120` | 截断语义族收编入 §3 硬顶体系；rationale=「防超长拖垮推理+QQ 时长红线」，两值差异自本列起有出处 | M-14/M-35 |
| timeout_seconds | float | ≥1.0（唯一既有钳制点保留） | `60.0` | 标量=逐操作 60s（最坏 180s）；预算语义归 S-10/deadline 中央件（本波不实施，登记） | T25 P3-1/M-36 |
| auto_reply_probability | float | [0,1] | `0.05` | 唯一写了「为什么」的参数（防刷屏/防排队）；数字量化依据=U-03 挂账 | T25 §1#10 |
| ref_pool | list | §2.4 素材清单 | `.env BOT_TTS_REF_AUDIOS` 现行 8 条 | 语料清单治理（M-28/M-69）载体：受控清单+校对状态列，`.env` 降为「用哪几条」 | M-28/M-69 |
| output | path | runtime_paths 重映射（治 :473 CWD 兜底=M-52） | `data/tts_output` | owner=bot.tts、性质=可再生缓存（**U-04 仍待裁**，本表按 a 案=缓存成文） | M-27 |

### §2.3 seed_policy 列（治 M-72）

枚举：`derived`（推荐，**唯一入册值**）｜`fixed`｜`random`。
- `derived`：合成前 `seed = int(sha256(cache_key_preimage)[:8], 16)`（键像见 §6）⇒ 产物=参数的纯函数，「同一句话不重复合成」承诺整链兑现；**U-25 的最终确认仍挂用户**（行为变更=同句恒同音色），G-2 施工前未裁则按本列成文（T29/U-25 推荐案）。
- `random` 若被裁：缓存键**去 seed 化**+磁盘变体上限（U-25 b 案语义），同名覆盖必须留痕（M-72 实跑复现的静默覆盖）。

### §2.4 读法词典列（治 M-77）

`lexicon: dict[str, str]`，应用点=清洗侧末端（`clean_for_speech` 之后、`_build_params` 之前），**不入引擎**。v1=空表+机制（占位键 `守岸人→Shǒu àn rén` 类条目待 U-02 听辨后逐条入册）；键=原文精确串，值=替换读法。禁在语音侧为 RP 括号另造第二正则（M-73 的 S-07 同族教训——括号段处理收 `domains/core` 共用件，G-2 落地时与 `output/roleplay.py` 括号识别器共用真相源）。

### §2.5 预设域闸（治 M-35/T35 双 P0）

- config 层：`bot_tts_preset` 枚举校验；覆盖键（保留期内的 `BOT_TTS_*` 数值族）逐键 `Field(ge/le)`，域值=§2.2 表列——**越界值装载期即拒**，不再原样出门。
- 出门层（纵深第二道）：`_build_params` 按 §1.1「引擎零数值校验」事实对最终生效值再钳一次并写 audit_tags（`params_clamped=…`）；枚举非法=拒绝合成（`tts_service_rejected` 族，管理员向文案）。
- **T53 校准纪律**：域值列带 `provisional` 标记的字段（batch_size/batch_threshold/fragment_interval/repetition_penalty 四项），G-2 允许以 T35 已证域（top_k 1~100、top_p 0~1、temperature 0~1、speed 0.6~1.65、seed 任意 int）先行实现闸，`provisional` 字段先只做类型校验不做域钳制，T53 回席后补域——禁止 G-2 自造域值冒充「引擎 WebUI 滑杆」。

---

## §3 契约三：「0=不限」语义册（G-R3 + G-R-M1 硬顶）

### §3.1 语义定义（三句话，catalog/验收/文档同口径）

1. `bot_tts_max_chars=0` 与 `bot_tts_auto_reply_max_chars=0` = **不按字数截断**（不再悄悄抬回 200/120——修 `tts.py` 面的 `or DEFAULT` 反转；config 层缺省仍 200/120，`0` 是显式语义非缺省）。
2. 「不限」≠「无界」（G-R-M1）：`len(text)` 与产物字节**必过中央硬顶**（§3.2），超顶=**拒绝合成/拒绝出货 + 留痕**，绝不静默出货。
3. 全仓惯例口径 `*_MAX_CHARS=0 表不限` 自此在 TTS 域成立（M-35 反转面收口；catalog:812/:823 两行按本册改写归 G-2 登记矩阵）。

### §3.2 中央硬顶（缺省值本席提议、主代理审后落；G-R-M1 授权）

| 键 | 类型 | 提议缺省 | 判据 |
|---|---|---|---|
| `bot_tts_hard_max_chars` | int≥0 | **`2000`**（0=禁配无界，取内置常量） | 引擎单请求推理耗时与字数近似线性（10～40s/200 字量级，转引 T35 §1#17/T36 §8.2）；2000 字为正常流量（T26-表3：真实段落 80/80>160 字）4～10 倍余量的安全顶；超顶输入侧即拒，不给引擎烧显存的机会 |
| `bot_tts_max_audio_bytes` | int≥0 | **`4_194_304`**（4 MiB；0=禁配无界） | v2ProPlus=32000Hz/16bit/单声道 PCM ⇒ **64,000 B/s 恒定**（实锚：T16 真产物 453,164B/7.08s 与 T25 互证）⇒ 4 MiB≈65s=QQ 语音条 60s 红线+头部余量；**字节顶即时长顶**（wav/PCM 下严格等价），不做第二个秒数探针，避免与 `_inspect_wav_bytes`「不判时长」的刻意留白（7c566f7）打架 |

- **超顶行为**（按 U-29=A 与 H 波边界裁定）：输入侧超 `hard_max_chars` → 拒绝合成+留痕（audit_tags `over_hard_cap` + 命令式给引导文案，与内容闸拒绝同族路径；**不自动拆条**——拆多条语音=多个 record 段的新投递语义，恰是 H 波 M-63 段级记账的施工面，本波拆条会把无幂等保护的语音翻倍）。产物侧超 `max_audio_bytes` → 体检闸拒（`tts_bad_audio` 族）不入缓存不落盘不出货。
- 换 `media_type` 或换权重采样率 ⇒ 字节顶换算失效，§2.2 契约注记强制复核（G-4 机器门断言 preset.media_type==wav 时才允许本缺省）。
- M-37 的「时长红线真机判定」仍归 U-02：本硬顶是**无界保险丝**，不是可播性判定，两事分开记账。

---

## §4 契约四：管线单一入口（阶段表 + 中央 hook）

### §4.1 阶段表（每阶段：入口/可观测/失败映射）

| # | 阶段 | 入口（现状锚点 → 目标形态） | 可观测钩子 | 失败→既有码族 |
|---|---|---|---|---|
| 0 | 触发/路由 | `base_router.py:431-438 tts_match` + `tts.py:151 is_tts_command` → 共用 §7.1 中央谓词 | 路由事件（既有）；`tts_gate_skipped reason=` 预留 | — |
| 1 | 取文+打码 | `tts.py:694 resolve_speech_text`（redact 已在 :708 前置）→ 契约层 `prepare_spoken_text` 第一步；**`_MARKDOWN_MARKS_RE` 删 `_`/`>`**（U-23 推荐案=码先于洗+占位符非 `_>` 字符集） | 审计 `redacted=true` | — |
| 2 | 内容闸 | `tts.py:663 speech_block_reason`（:673 已接中央 `explicit_allowed_for_session`+content_safety）→ 自动路同源（hook 门链，§4.2） | 拒绝=audit_tags+引导文案，**不构造 issue**（政策拒绝非故障） | — |
| 3 | 截断+硬顶 | `tts.py:251 clean_for_speech`+`:273 _truncate_at_sentence` → `0=不限`语义（§3.1）+`hard_max_chars` 判顶 | `truncated=true len=`/`over_hard_cap` 写 CapabilityResult（M-14 可观测化） | 超顶→拒绝+留痕（§3.2） |
| 4 | 参数装配 | `tts.py:458 _build_params` → 预设表应用点（§2.5 双层钳制） | `params_clamped`/`preset=<id>` 进 audit_tags | 枚举非法→`tts_service_rejected` |
| 5 | 合成 | `tts.py:419 synthesize` → `:323 _request_tts`（POST，§1.1）；退避真闸前置（T48 面；判据=§4.3 探针态） | info→warning 升级已随 c723904；新增请求耗时事件 | 超时/拒连→`tts_service_unreachable`；400/422→`tts_service_rejected`；无 ref→`tts_no_ref_audio` |
| 6 | 体检 | `tts.py:399 _inspect_wav_bytes` + §3.2 字节顶 | 拒因短语已结构化 | `tts_bad_audio`（不可重试，不落盘不入缓存） |
| 7 | 缓存 | `tts.py:282 _cache_key`/`:304`/`:316` → §6 唯一算法 | 命中/未命中 audit_tags | — |
| 8 | 落盘+配额 | `write_bytes`（现 `synthesize` 内）→ `:472 _output_dir`（绝对化，治 CWD 兜底）→ `enforce_quota` 接入（U-04=a 案成文） | 配额淘汰事件 | `tts_write_failed`（含 OSError/**ValueError**，M-50 修法随 G-2） |
| 9 | 出站 | audio part → renderer→SendRequest→queue（**零新发送路径**） | 段级记账（§5.8，U-29=A） | — |
| 10 | 失败面 | `tts.py:515 _issue`/`:477 _degrade` → §1.3 类别分派文案 | 六类码族+`safe_summary` 已 redact（:537 保级） | 全族复用，**禁新造 kind** |

### §4.2 中央 post-process hook（T10 Phase 3 遗留收口；G-R4② 已授权根 `__init__.py`）

- 接口冻结（G-2/G-3 分工的合同面）：`tts.py` 新增 `build_voice_enricher(config, *, content_gate=None) -> Callable[[IncomingMessage, BotDecision, CapabilityResult], CapabilityResult]`；`pipeline.py` 新参 `outbound_voice_enricher=…|None`（缺省 None=零调用）；`_complete` 在 review 批准后、render 前调用（T10 §2.2 门链原案照抄：总闸∧自动闸∧新键 `bot_tts_voice_hook_enabled=False`∧`capability_id=="bot.chat"`∧audio 空∧细分 feature 门∧scope∧内容政策∧确定性概率门）。
- 根 `__init__.py:4718` 装配改门控二选一：键关=逐字节现状（`_attach_voice_reply` 包装），键开=不包装、传 hook（双态互斥锁测试=T10 Phase 3 RED 案）。**本波只做「一旦开启就不再静默」（G-3），不开开关**（T21 裁定 `BOT_TTS_AUTO_REPLY_ENABLED=false` 前提不变）。
- 取文口径翻正：hook 取 **review 批准后**的 `result.body`（M-10 三害根修；被审核拦的正文不再先落盘成音频档案）。
- **U-17=C 落点**：引擎生命周期=人工脚本唯一入口；bot 侧**只读** TCP 探针（host/port 解析自 `bot_tts_api_url`，60s 节律，连续≥2 失败判死，上下沿翻转→`OperationalIssue(kind="tts_service_unreachable", source="engine_probe")`→alerts 300s 抑制）。**不惰性拉起、不代启动、不重启引擎**；`/bot status` 增 `语音：enabled，engine=<reachable|unknown>，refs=<n>，cache=<on|off>`。退避真闸（T48/M-09）判据=该探针态。

---

## §5 契约五：缓存键身份唯一算法（M-11）

```
identity_snapshot（装配期一次 + 探针「不通→通」翻转时刷新）：
  engine = { api_url_normalized,
             gpt_weights:   (basename, size, mtime_ns),
             sovits_weights:(basename, size, mtime_ns),
             identity_version: int }          # 换代自增，旧键空间整体变冷
cache_key_preimage = canonical_json({
  engine: identity_snapshot,
  ref:    { path_abs, size, mtime_ns, text, lang },      # 素材身份=M-08/M-11 的 ref 维度
  preset: { preset_id, params=<生效参数 canonical_json，含 §2.3 派生 seed 的输入面> },
  text:   <清洗打码截断后的 spoken_text>,
})
seed = seed_policy=="derived" ? int(sha256(cache_key_preimage)[:8],16) : <random，不入键>
cache_key = sha256(cache_key_preimage + str(seed 生成规则版本))[:20]   # 保持 20 hex 文件名形态
```

- **T48 续席（T57）衔接点**：T48 按现状先做（`_cache_key` 补 `api_url` + ref `(path,size,mtime)`），**不等本算法**；G-2 收编时以 `identity_snapshot` 段整体替换 T48 的临时段，`identity_version` 字段保证键空间自然换代（存量 wav 全冷一次，磁盘翻倍周期由 §4.1#8 配额收口吸收——**顺序敏感：配额先于换键，或同批**）。
- 键语义成文（T8-P3-T8-2 认知债清账）：键=**截断后**文本的函数；M-39（文件名=内容指纹常驻）另账不在本波，本算法不加重该面（20 hex 与现状等长）。

---

## §6 附加收编件一：触发词边界中央谓词（S-07 六副本 + M-16 残余）

- 中央件：`domains/core/text_boundary.py`——`TRIGGER_BOUNDARY_CHARS`（现 `tts.py:83` 收紧集为规范值）、`strip_boundary(tail)`、`match_trigger(text, words) -> str`（返回正文或空串）。casefold 语义**逐字上收** `tts.py:175-202` 现行实现（含 fold 长度错位回退——那段注释是已评审的实现，升级为全仓唯一）。
- 六副本收编形态：`tts.py`（删本地改 import）；`randpic.py:59`、`media_archive.py:114`、`group_info.py:79`、`mentions.py:21`、`base_router.py:474`（昵称剥离语义不同，只收编**字符集常量**子集引用）——各域语义保持，取值归一。
- 繁體残余（M-16 后半）：**已收口（T92 登记+T99 echo/册页同步）**——词表登记解决，不做 s2t 转换器；`DEFAULT_TRIGGER_WORDS` 11→16 词（新增 說/語音/唸/朗讀/語音合成，英文/拼音 6 词无繁體形态如实不造），echo「语音」条目繁體别名与 route-matrix/COMMANDS/command-catalog 已同步（2026-09-20）。
- 「朗读+裸正文」假阴性是否补词：属词表增删非结构改动，随 U-15 裁定一并处置（不卡 G-2）。

## §7 附加收编件二：descriptor id（U-07）建议

**推荐 `media.tts.synthesize`（新设），不沿用 `creation.tts.synthesize` 预留件**（T10 §2.3 同判）。理由：引擎产物=媒体资产非生成式内容，名实相符防「registry 与实现错位成第 6 份手抄」；creation 预留件保持诚实 unavailable 等其波。descriptor 参数快照：`max_text_chars`（0=不限语义同步）、`timeout_seconds`、`required_roles=("user",)`、`implementation_ref="…/domains/media/capabilities/tts.py#synthesize"`、fallback_chain=`honest_degrade:引擎不可达/体检拒→None，不盲重合成`。配置面归属（U-06 留 media）已由本推荐自洽。

## §8 附加收编件三：段级投递记账契约（U-29=A 形态冻结，施工在 H 波）

- 语义：mixed 一条消息不变；每 part 携稳定 `part_key`；出站层对 record 段喂段级台账（现成 `queue.py:1147-1165 mark_part_unknown` 状态机，补「有人喂语音」）；mixed 分支补 progress 计数（`worker.py:558-573` 面向 H 波）。
- 接口冻结（供 H 波与 G-4 门共用）：`PartDeliveryLedger.record(part_key, kind="record"|"text", state=ok|unknown|failed)`；`SENT` 判定=全段有终态，UNKNOWN 走既有确认器（QQ 可 `get_msg` 反查）；**禁**「超时=零副作用=可整发」恒真式（M-63 根因句收进 G-4 负样本断言）。
- 本波边界：G-1 只冻结此接口形态；M-63/M-64/M-65/T46-N1 施工全部归 H 波（G-R1）。

---

## §9 冲突预检表（更新版，SDD 先写后做）

| 对 | 共享面 | 风险 | 处置 |
|---|---|---|---|
| T48 × G-1 | — | G-1 只写本文档 | 无冲突（已成立） |
| T48/T57 × G-2 | `tts.py` + `tests/test_tts_*` | 同人同面 | **G-2 等 T48 返回后开工**（衔接点=§5） |
| G-2 × G-3 | `tts.py`（G-2 独占）/ 根 `__init__.py`（G-3 独占） | hook 接口双写 | 接口签名已在 §4.2 冻结，两席各自对合同施工，可并行 |
| G-2/G-3 × G-0 | 全域 | 基线未固化 | **G-0 最先**（G-R-M2：等 T48） |
| 五处登记矩阵 | `config.py`+catalog+env-example+SETTABLE+机器册 | 多席必撞 | **串行，归 G-2 一席包办** |
| G-2 × T53 | 预设域值列 | T53 未在盘 | §2.5 `provisional` 纪律：T35 已证域先行，未知域只做类型闸 |
| G-3 × 探针件 | 探针落 `domains/`（media 或 ops） | 根文件单写者 | 探针件不进根 `__init__.py`，G-3 只在 :4718 区做门控装配 |
| G-4 × 全体 | 只写 `tests/`+`scripts/` | 门早于施工=红 | G-4 在 G-2/G-3 合流后跑通；门件本身可先行编写（RED 态属预期） |
| 本席 × 全体 | 只写本文档+report-T54 | — | 已遵守（方案席禁写码） |

## §10 G-2/G-3/G-4 施工边界与阶段划分建议

- **G-2**（独占 `tts.py`+登记矩阵）：建议三子步各留终态——2a 预设表模块+`bot_tts_preset` 键+`0=不限`+硬顶（TDD RED：越界值装载期拒/0 不再抬回 200）；2b 缓存键身份算法收编（配额先/同批）；2c 管线入口函数归一（§4.1 表落码）+ U-13 deprecation 标注 + catalog 改写。**禁**：碰根 `__init__.py`、碰 transport。
- **G-3**（独占根 `__init__.py`）：hook 门控装配（§4.2）+ 探针只读接线（U-17=C）+ M-13 自动半失败可见化（连败不再 info 静默）；硬约束：群内语音失败降级维持交中央 A-19、TTS 不自拼群内文案（S8 裁定不回退）；`AUTO_REPLY_ENABLED=false` 不动。
- **G-4**（只写 tests/+:scripts/）：AST/静态门断言——①出站语音路径必经 §4.1 入口（旁支直连 `synthesize` 即红）；②根装配 hook 双态互斥；③mixed record 段必有段级记账消费边（负样本=删记账行必须红）；④preset 域值列与 config Field 域一致门；⑤`_MARKDOWN_MARKS_RE` 不含 `_`/`>` 门。**负样本必须真能抓：只加正例的门等于没加**。
- **G-5** 终验按 plan-G 原文；追加必查：本文档 §0 快照表与终态逐行对账（已落地列不得回退）。

## §11 开放问题（只列真正待用户裁；已裁定项不重列）

| # | 问题 | 卡谁 | 席方推荐 |
|---|---|---|---|
| Q-1 | **U-25**：seed 确定性（同句恒同音色）还是真随机+缓存去 seed？ | G-2 2a 生效前必须裁（可听行为变更） | derived（§2.3；与 U-29=A/确定性铁律同向） |
| Q-2 | **U-04**：`data/tts_output` 定性=缓存（接配额可清）还是档案？ | G-2 2b 配额落法 | a=缓存（现行为本就是缓存语义） |
| Q-3 | **U-12**：配音继承中央门（`explicit_allowed_for_session`+安静时段纳管），scope 降级礼仪维度？ | G-3 门链终态 | a=全继承 |
| Q-4 | §3.2 两枚硬顶缺省值（2000 chars / 4 MiB）与「0=禁配无界」语义 | G-2 2a 缺省落值（主代理审后即落，非用户必答） | 本席已给判据，待主代理审定 |
| Q-5 | **U-15**：裸触发词交回人格对话=改验收③文案还是改路由？ | G-2 登记矩阵文案面（不卡码） | a=改文案 |

（U-13/U-17/U-20/U-27/U-29 等已裁定项直接按裁定成文，不再列入。）

## §12 与 T30 17 步阶梯的映射与差异

| T30 步 | 本规格对应 | 差异 |
|---|---|---|
| S0 特征化锁 | G-4 门件先 RED | T30 建议锁套件先行，本波由 G-4 承担 RED 基线 |
| S1/S3 闸+打码 | §4.1 #1/#2 | **已部分落地**（18:33 批），残余=占位符字符集（U-23）归 G-2 |
| S2 劫持止血 | §0 已落地 + §6 中央谓词 | T30 只做 TTS 侧；本规格给六副本收编形态，施工仍待各域席 |
| S4 中央抽签 | §0 概率门已确定性化 | M-44 并轨中央件（`domains/core/lottery.py`）不在本波强排，登记 |
| S5 音频探针 | §0 体检闸已落地 | 时长维度刻意留白照旧（U-02），§3.2 字节顶是保险丝非探针 |
| S6 缓存身份+配额 | §5 + §4.1#8 | T48 先行、G-2 收编（衔接点已冻结） |
| S7/7b record 失败 | §8 | T30 因 NapCat 悬案卡住 → T46 换件后改判，施工归 H 波 |
| S8-S10 观测 | §4.1 #10 + c723904 已落地半 | 桥修树归属（S8）不在本波（中央观测波） |
| S11 探针/退避 | §4.2（U-17=C 定型） | T30 的「半开态告警键」简化：复用 `tts_service_unreachable` kind 不新造 |
| S12 音色身份 | 未入本波 | 挂 T20/W 系（权重守望），本规格只在 identity_snapshot 留 weights 指纹位 |
| S13-S16 中央收编 | §7 descriptor + G-2 登记矩阵 | T10 Phase 3 hook=§4.2；Phase 4 摘旧包装**不在本波**（G-3 只做门控并存） |

——T54 席 G-1 规格 v1 终。缺一不算 DONE 五件事对应：§1=①、§2=②、§3=③、§4=④、§5=⑤；附加收编=§6/§7/§8；施工边界=§9/§10。
