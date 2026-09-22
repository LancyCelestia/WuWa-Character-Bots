# 语音合成 · 引擎契约与参数域

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.tts · 引擎契约与参数域

- 层级：一级 B06 → 二级 tts → 三级 `engine-contract`
- 实现落点：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`、`plugins/bot_unified_runtime/domains/creation/tts`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

机械件（不占路由席位）：把「bot 与 GPT-SoVITS 引擎之间到底怎么说话」收成一个唯一
真相源，把「哪些参数能填、填到多大」收进一张表。规格文字在
`docs/design/tts-contract-layer.md`，落码真身在
`domains/media/tts_presets.py`（预设表 + 常量）与
`domains/media/capabilities/tts.py`（应用点）。

要治的三件事：引擎对数值参数**完全不校验**（越界值照收不误，责任全在 bot 侧）；
引擎 `TTS_Request` 全字段带默认且 `extra=ignore`（漏键走默认、多键被忽略，都不报错，
所以「请求看起来发对了」不等于发对了）；参数出处曾经五条无据（抄 WebUI 却没写为什么）。

## 怎么调用

- `tts_presets.PRESET_REGISTRY` / `resolve_preset`：预设表与选择口，
  `TtsPreset` 携 `params`（采样六项）、`engine_params`（八个原硬编码项）、`lexicon`、
  `seed_policy`、`rationale`。选择键 `bot_tts_preset`，未知 id 回缺省
  `DEFAULT_PRESET_ID`。
- `tts_presets.ENGINE_PARAM_DOMAINS`：数值域登记表；`HARD_MAX_CHARS_FALLBACK`（2000）
  与 `MAX_AUDIO_BYTES_FALLBACK`（字节数以该件常量为准）是「0=禁配无界」时的内置兜底。
- `tts.py:_build_params`：装配优先级 = config 显式值 > 预设缺省，无第二真值；
  `text_lang` 出门前 casefold。
- `tts.py:_build_request_payload`：`POST /tts` 请求体的唯一构造口，bot 恒
  `streaming_mode=False`、`parallel_infer=True`。
- `tts.py:_output_dir`：落盘目录三态（绝对透传 / 空串走 `runtime_path` 重映射 / 相对
  按 `bot_tts_gptsovits_dir` 基准）。
- 消费方（禁另建第二处）：`domains/render/renderer.py:canonicalize_audio_parts`
  （`record` 部件冻结键）、`domains/transport/sender/onebot.py:_is_final_failure_retcode`
  （平台退码语义的**唯一**事实源，本卡只登记它存在，不抄名单）。

参数域（引擎 WebUI 滑杆实测域，越界装载期即拒）：`speed_factor` 0.6–1.65、
`top_k` 1–100、`top_p` 0–1、`temperature` 0–1、`repetition_penalty` 0–2、
`fragment_interval` 0.01–1、`batch_size` 1–200。产物形态：32000Hz、int16、单声道
PCM（wav 下字节恒 64000 B/s，故字节顶等价时长顶）。枚举域：`text_lang`
（`auto/auto_yue/en/zh/ja/yue/ko/all_zh/all_ja/all_yue/all_ko`）、`text_split_method`
（`cut0..cut5`）、`media_type`（`wav/raw/ogg/aac`）。

引擎侧硬约束（事实，不可绕）：`workers=1` 单进程，非流式同步推理独占事件循环，
全端点严格排队；参考音频时长必须落在引擎允许区间（区间以引擎契约为准），越界返回 400 且真原因在错误体的
`Exception` 字段（不看该字段就会把可读原因吞成 `tts failed`）；权重文件缺失时引擎
会**静默回退底模并写回 yaml**；`GET /tts` 与 `POST /tts` 对 `text_lang` 处理不一致
（GET 会 lower，POST 不会），生产只用 POST。

## 开关与参数

- `bot_tts_preset`（`shorekeeper`，枚举校验）；被预设吸收的 `bot_tts_*` 数值键保留为
  管理员覆盖，覆盖优先级 env 显式值 > 预设。
- `bot_tts_max_chars`（200）与 `bot_tts_auto_reply_max_chars`（120）：`0` = 不按字数
  截断，且**不再被悄悄抬回缺省**；「不限」不等于「无界」，必过下面两枚硬顶。
- `bot_tts_hard_max_chars`、`bot_tts_max_audio_bytes`（两者的缺省值以 `config.py` 为准；旧提议值已
  被审落上调，判据是旧提议上限会先于默认预设档的正常产物拒发，与「预设收编即现状、
  字节级不变」自相矛盾）。
- `bot_tts_timeout_seconds`（60，`ge=1.0`）：标量超时是逐操作语义，最坏可叠到三倍。
- `bot_tts_text_lang`/`bot_tts_text_split_method`：枚举覆盖位。
- 热更性与逐键域以 `docs/config-catalog-full.md` 为准；预设表本身入
  `tests/verify_hashes.py` 哈希册，改表必重录。

## 失败时看到什么

契约层把失败分成三桶，桶决定后续行为（详见 `backoff-and-commit.md`）：

- 引擎不可达 / 超时：`tts_service_unreachable`（可重试，进退避窗）。文案诚实写
  「服务忙或在排队」，因为引擎单进程排队时连接也会拖到超时，不能一概说「没在跑」。
- 引擎拒绝（400/422）：`tts_service_rejected`（不可重试，不进窗）。参数非法走管理员向
  提示，参考音频越界走「还差一段合规时长干声」的用户向提示。
- 引擎伪装成功（200 + 约一秒静音）：`tts_bad_audio`，**进窗**——这是「引擎活着却
  持续生产垃圾」的部署类故障形态。

## 测试与验收

`tests/test_tts_presets.py`（表结构与一致性门：`bot_tts_preset` 枚举成员 = 注册表键集）、
`test_tts_contract_layer.py`（0=不限不被抬回、超硬顶拒发、钳制域）、
`test_tts_config_gates.py`（`bot_tts_api_url` loopback 白名单拒绝面探针：元数据服务、
内网段、公网、整型 IP、v6 变体、userinfo、畸形端口）、`test_tts_audio_gate.py`
（结构体检与静音三指纹，正常产物零误杀）、`test_voice_outbound_contract.py`
（出站部件冻结键）。`tests/test_rendering_contract.py` 与
`tests/test_doc_sync_gates.py` 覆盖文档/生成物一致面。
