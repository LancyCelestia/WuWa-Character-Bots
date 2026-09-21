# S10 席日志 — 媒体/文件/搜索能力协议化（v21r2 批次）

> 合同：`backend-v2-implementation-guide.md` §11 L252/L254/§13 S10 行 + `backend-v2-product-extensions.md` §6 + 验收矩阵 V21-MEDIA-001/002、V21-FILE-001/002、V21-SEARCH-001/002、V21-TTS-001、V21-IMAGE-001。
> 纪律：全离线（零真实网络）、PYTHONDONTWRITEBYTECODE=1、BOT_AUTOSYNC=0、`--basetemp=%TEMP%/v21r2-s10`、禁 dev.ps1、禁 git 写、禁再派代理、domains/creation 只引用不改动。

## 一、盘点（rg 实证，复用面清单——禁平行造轮子）

### media 族既有实现（全部包装不重写）
| 能力 | 既有载体（canonical，reorg W11 后） | 配置/健康探测信号 | 现状口径 |
|---|---|---|---|
| 图片识别 | `domains/media/ingest/vision_describe.py#describe_images`（provider=build_vision_provider，注册表空→None 诚实） | `bot_vision_enabled`/`bot_vision_model_registry` | 矩阵 partial；协议 implementation=unknown → 本席补 |
| OCR | **无独立 OCR 引擎**（矩阵 L47 实证「OCR 无」）；唯一近似=VLM 文字转写 | 同 vision | 诚实 degraded（VLM 代位）/not_configured |
| 动漫角色 IP | `domains/media/search/sauce_search.py#search_saucenao_ex`（no_key/http_error/无结果三态已分） | `bot_saucenao_api_key`（env:SAUCENAO_API_KEY） | 配了 key=available，没配=not_configured |
| 语音识别（record 段） | `domains/media/ingest/transcribe.py#transcribe_audio`+`build_asr_provider` | `bot_asr_enabled`/`bot_asr_model_registry` | 矩阵说 ASR 无是旧证据（transcribe 已落），按现状登记 |
| 音频转文字 | 同上（audio_source 通用入口，http 拉取限 20MB） | 同上 | 同上 |
| 视频识别 | `domains/media/ingest/video_understanding.py#build_video_brief`（字幕+抽帧+音轨+元数据四路融合） | `bot_video_understanding_enabled` 等 | partial→协议化 |
| 字幕 | video_understanding（CC 字幕轨，`bot_video_skip_asr_with_subtitle`） | 同上 | 字幕缺失=空+诚实说明 |
| 抽帧 | `vision_describe._extract_video_frames`（经 video pipeline 调用） | `bot_video_max_frames`（默认 6/深挖 16；§11 目标 8/24） | 上限进 descriptor limits |
| 媒体归档 | `domains/media/capabilities/media_archive.py#build_media_archive_capability` | `bot_media_archive_*`（min_role 默认 super_admin） | 本席只登记描述符+权限门，不重接 handler 内部 |
| SSRF 护栏 | `domains/files/sources/downloader.py#check_download_url`（协议面拒绝内网/保留地址）+`sources/parsers/ssrf_guard.py#guard_user_url/check_fetch_landing` | — | **沿用不绕过**：URL 输入在包装层先过 check_download_url |

### files 族既有实现
| 能力 | 载体 | 现状 |
|---|---|---|
| Word(.docx) | `domains/files/sources/file_reader.py#read_supported_file`（python-docx 段落） | 可用 |
| PPT(.ppt/.pptx) | 同上（pptx 逐页；**.ppt 旧格式诚实 parser_unavailable**，V2.1 风险 8） | pptx 可用/ppt 诚实降级 |
| Excel(.xlsx/.xls) | 同上（openpyxl 只读；**.xls OLE2 诚实 parser_unavailable**） | 同上 |
| PDF | 同上（pypdf 文本；扫描件 OCR 无——如实 metadata） | 可用（文本层） |
| 代码 | 同上 `_CODE_EXTS` 26 扩展名纯文本+不执行 | 可用 |
| Markdown | 同上 `_TEXT_EXTS` | 可用 |
| LaTeX | **.tex 不在 _TEXT_EXTS → 落 unknown**（缺口）；本席补 `.tex` 进文本集（LaTeX 源=纯文本，诚实 text 路，零执行） | 本席最小补 |
| 代码资产生成 | 同上 `build_generated_file`（只许 txt/md/代码、py 语法门、2MiB、原子写、禁冒充 Office/PDF） | V21-FILE-002 域内侧 |

### search 族既有实现
| 面 | 载体 | 现状 |
|---|---|---|
| 九源协议核心 | `sources/search_service.py`（W7 席）：SOURCE_REGISTRY 九源+general、authorize/plan/normalize/dedupe/rank、预算（总 12s/单源 6s/并发 2）、缓存键含 owner、fetch_reference 只收 citation_id 且过 ssrf_guard | **离线核心已落**；provider 生产装配未接 |
| 通用引擎链 | `sources/web_search.py#build_web_search_provider`（tavily 主链+you/langsearch 回退；DDG/Bing 无 key 可用；disabled→Null provider 诚实） | `bot_web_search_enabled` 默认 false |
| ACG 竖源 | `sources/acg_search.py`+`search_intent.py`（SEARCH 席 09-17 刚落） | `bot_search_acg_*` 默认关 |
| 九源状态 | **无逐源状态面**（矩阵 L53：xhs/YT/X/LinuxDo 缺） | 本席补：每源 available/not_configured/degraded/unknown 诚实口径 |

### TTS/绘图（对接点就位，实现体等 provider）
- 现载体 TTS：`domains/media/capabilities/tts.py`（GPT-SoVITS，`bot_tts_*`，归属裁决=§10 W-PA2 不属本席）；目标归宿 `domains/creation/tts/`（§9.1 reserved，W-PA1 骨架+`_common/contracts.py` 契约草案已落盘）。
- 绘图：**零现载体**（矩阵 L52）；`domains/creation/image/` reserved 骨架已落盘。
- 本席动作：creation.tts / creation.image 两条 CapabilityDescriptor 指向 creation 域契约路径（`domains/creation/tts|image`+`_common/contracts.py`），limits 按指南 §11（TTS text≤3000/speed 0.75..1.25/60s/20MiB；绘图 prompt≤4000/negative≤2000/count≤2/输入≤20MP）；**无 handler 注册→invoke 诚实 unavailable(not_wired)**，不冒充可用；domains/creation 一字不动。

## 二、设计与计划

1. **`plugins/bot_unified_runtime/runtime/capability_protocols.py`**（新建，任务指定位置）：
   - `CapabilityHealth`（unknown/not_configured/available/degraded/disabled）+ `InvocationStatus`（ok/fallback_ok/denied/timeout/limit_exceeded/not_configured/unavailable/failed/degraded）；
   - `CapabilityDescriptor`（frozen dataclass，风格对齐 `runtime/feature_catalog.py` 的 FeatureDescriptor）：capability_id/family/title/input_protocol/output_protocol/required_roles/timeout_seconds/limits/limit_fields/fallback_chain/implementation_ref/config_keys/health_probe/notes；
   - 注册面：`register_descriptor/descriptor_by_id/iter_descriptors`，默认注册=媒体 8+文件 8+搜索 4+creation 2；
   - 健康探测：`register_health_probe(name, fn(config)->CapabilityHealth)`+`compute_health(descriptor, config)`——配了 key/registry=available、没配=not_configured，**禁假成功**；
   - 统一调用面 `CapabilityInvoker.invoke(request)`：描述符解析→权限门（policy.roles.ROLE_ORDER 交集，blocked 永不在授权集）→limit_fields 载荷限额→handler 查找（无 handler=unavailable not_wired）→工作线程+future.result(timeout) 超时→异常走 fallback_chain（终态 honest_degrade:* → degraded 诚实降级）→审计钩子（fail-open）；
   - 完整性校验 `validate_registry()`：id 唯一/族合法/roles⊆ROLE_ORDER\\blocked/timeout∈(0,600]/limits 非负 int/limit_fields 引用存在/fallback 非空/implementation_ref 文件存在/health_probe 已注册——测试断言 []。
2. **处理器适配**（同模块，懒 import 既有实现）：media/files/search 逐能力包装；URL 输入统一先 `check_download_url`；文件路径读取只在 handler 内 `Path` 解析+存在性判断，不做新安全语义（沿用既有护栏）。
3. **九源状态面** `search_source_status(config, providers=None)`：SOURCE_REGISTRY 逐行→`SearchSourceStatus`（requires_authorized_provider 且无注册 provider→not_configured；general 链可达（web enabled）→available；否则 not_configured；github 私库 scope 无凭据→note 诚实；B站/YT 字幕=unknown）。禁假 available。
4. **`domains/files/sources/file_reader.py`**：`_TEXT_EXTS` 增 `.tex`（唯一代码改动，LaTeX=文本读取）。
5. **测试 `tests/test_v21_s10_protocols.py`**（全离线）：描述符完整性/权限门（archive 非超管 denied）/超时（sleep handler）/限额（超 max_chars 拒）/降级链（异常→fallback→fallback_ok；无 fallback→failed；honest_degrade→degraded）/九源状态诚实性（空配置无 available；xhs/cnki 恒 not_configured）/协议调用面 mock 实调（fake handler 注入+真实 files.read.code/markdown/tex tmp 文件+真实 docx/xlsx/pdf 最小样本）/creation 对接点（invoke→unavailable，ref 路径在盘）。
6. 受影响存量回归：file_reader 相关（test_group_files/file 相关）、search_service_v21、media_archive、tts——按 git 域就近选。

## 三、落地清单（全部未 commit，工作树多席共享）

| 交付 | 文件 | 说明 |
|---|---|---|
| 协议模块（新） | `plugins/bot_unified_runtime/runtime/capability_protocols.py` | CapabilityDescriptor（22 条默认注册：media 8+files 8+search 4+creation 2）+ CapabilityHealth/InvocationStatus 词汇 + CapabilityRegistry/Handler/Fallback/HealthProbe/AuditHook 注册表 + CapabilityInvoker（权限门→限额→超时→降级链→审计，fail-open）+ validate_registry 完整性门 + search_source_status 九源状态面 + default_invoker 惰性单例；实现体全部懒 import 既有链（vision_describe/transcribe/video_understanding/sauce_search/file_reader/web_search/acg_search/search_service），SSRF 沿用 check_download_url/guard_user_url 不绕过 |
| LaTeX 读取（改） | `plugins/bot_unified_runtime/domains/files/sources/file_reader.py` | `_TEXT_EXTS` 增 `.tex`（纯文本路，不编译不执行）——唯一对既有实现的行为增量 |
| 测试（新） | `tests/test_v21_s10_protocols.py` | 60 例全离线：描述符完整性/健康态诚实性/权限门（blocked 拒+admin 门+handler 未执行实证）/超时/载荷限额（max_images/max_chars/max_frames）/降级链三态（fallback_ok/honest degrade=degraded/降级失败=failed 不冒充）/async 桥接/审计钩子 fail-open/files 族真实文件实调（.py/.md/.tex/.docx/.xlsx/伪 OLE2 .ppt/.xls/伪 .pdf）/media 族 not_configured+SSRF 拒绝分支/search 族 fake provider 实调+引用取回授权门+SSRF 拒/九源状态诚实性（禁假 available；xhs/cnki 无授权 provider 恒 not_configured）/creation 对接点 unavailable |
| 日志（新） | `docs/design/v21r2-s10-log.md` | 本文件 |

**禁触面确认**：domains/creation 零改动（只引用 `tts/__init__.py`、`image/__init__.py`、`_common/contracts.py`）；domains/render、chat_reply、subscribe、control_plane、capabilities/chat.py、llm/model_router、`__init__.py`、transport 均未动。

## 四、实跑证据（全部 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0，venv 固定解释器，--basetemp=%TEMP%/v21r2-s10，禁 dev.ps1）

1. **新测试**：`pytest tests/test_v21_s10_protocols.py` → **59 passed, 1 skipped**（skip=importorskip('pypdf')：本 venv 未装 pypdf，诚实跳过；该分支由新增 `test_pdf_parser_unavailable_degrades_honestly` 以真实行为覆盖——伪最小 .pdf → DEGRADED parser_unavailable）。
2. **相邻回归合并跑**：`pytest tests/test_v21_s10_protocols.py tests/test_v21_risk_red_tz_and_files.py tests/test_phase0_3_features.py tests/test_runtime_subfeatures.py tests/test_search_service_v21.py tests/test_asr_transcribe.py tests/test_media_archive.py` → **240 passed, 2 skipped**（skip 同为 pypdf importorskip 族；file_reader 消费方/W7 search 协议/ASR/媒体归档零回归）。
3. **Ruff**：三文件 `ruff check` → **All checks passed**。
4. **Mypy**（dev.ps1 同参：--explicit-package-bases --ignore-missing-imports）：两文件 **0 新增错误**；存量 2 错均在 `control_plane/api/platform.py`（AGENTS.md 台账 #36 已记录的既有项，与本席零交集）。
5. **树卫生**：源码树无 `__pycache__`/`.pytest_cache`/`*.pyc`/`data/` 残留（find 实证零命中）；临时产物全在 %TEMP%/v21r2-s10。
6. 过程记录：期间共享工作树被并行 reorg 波一度打断包 import（message_context→新 contracts 迁移中间态），轮询等待恢复后完成上述实跑；未触碰该波次任何文件。

## 五、验收矩阵涉线行四列状态（本席口径，记于自己日志）

| 行 | 状态 | 测试 | live | 实现 |
|---|---|---|---|---|
| V21-MEDIA-001 | partial→**partial（协议面 closed：8 描述符+受控调用面+权限/限额/降级；OCR=VLM 代位诚实 degraded）** | tests/test_v21_s10_protocols.py（离线） | unknown（未联网实测） | runtime/capability_protocols.py#_handle_media_*；实现体 domains/media/ingest |
| V21-MEDIA-002 | partial→**partial（ASR/视频/字幕/抽帧四能力协议化；抽帧上限 24/产物临时路径）** | 同上 | unknown | 同上（video_understanding/transcribe 包装） |
| V21-FILE-001 | partial→**partial（7 读通道+artifact 生成协议化；.ppt/.xls 诚实 parser_unavailable 锁死；.tex 补文本路；pypdf 缺=PDF 诚实降级）** | 同上 | 同上 | domains/files/sources/file_reader.py 包装 |
| V21-FILE-002 | partial（域内侧补充：build_generated_file 入协议面 admin 门+禁冒充 Office 实测） | 同上 | 同上 | 同上；transport/FileGateway 侧未动 |
| V21-SEARCH-001 | partial→**partial（九源逐源状态面 closed：配了=available/没配=not_configured/授权源不冒充；引用取回授权门+SSRF）** | 同上 | unknown（九源真实访问未实测，fixture 口径） | sources/search_service.py（W7）包装 |
| V21-SEARCH-002 | partial（沿用不绕过：check_download_url+guard_user_url 在协议面 URL 入口强制；rebinding 深防仍留后续） | 同上 | unknown | domains/files/sources/downloader.py#check_download_url |
| V21-TTS-001 | unknown→**partial（协议对接点就位：descriptor+limits 按 §11 L256；invoke=unavailable 不假成功；实现体等 provider/归属裁决 §10 W-PA2）** | 同上（unavailable 分支） | blocked（无 provider） | domains/creation/tts/__init__.py（引用不改动） |
| V21-IMAGE-001 | unknown→**partial（协议对接点就位：descriptor+limits 按 §11 L258；零现载体如实登记）** | 同上 | blocked（无 provider） | domains/creation/image/__init__.py（引用不改动） |

## 六、遗留与移交

1. **REST 化留后续**：协议面未接 control_plane（S9 收官面保持稳定；任务书注明「协议 REST 化留后续」）。
2. **媒体归档未纳 descriptor**：`build_media_archive_capability` 是 chat 链 handler 形态（需 send 口依赖），直接包装会造第二装配路径——留接线席按其现有装配复用，本席不平行造轮子。
3. **抽帧产物 asset 化**：`media.video.frame_extract` 产出进程内临时路径（descriptor notes 已声明）；对外 asset_id 化（§11 L254）留 asset 注册表面。
4. **九源 live 实测**：状态面是配置诚实口径；九平台真实可达性/字幕能力=unknown，待白名单真机验收。
5. **TTS/绘图激活**：等 provider 配置+creation 激活波（RWPA1 契约在飞）；届时 handler 按 CreationJobState 状态机实现，descriptor limits 已按 §11 预置。
6. **pypdf 未安装**：本 venv PDF 文本提取整类走 parser_unavailable 诚实降级；装 pypdf 即自动升级为可用（描述符/测试两侧已兼容两态）。

