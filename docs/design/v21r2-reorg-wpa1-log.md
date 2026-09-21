# v21r2 W-PA1 席施工日志（creation 生成域骨架波）

> 席位：RWPA1（板块重组·W-PA1 creation 骨架波）。施工图：`docs/design/v21r2-reorg-plan.md` §9（字段级契约草案）+ §6（门禁网）+ §10 W-PA1 行。
> 纪律：纯新增零冲突（`domains/creation/**` + 新测试 + 本日志）；禁 git 写操作；固定解释器 ChatBot_Runtime venv；源码树零缓存（PYTHONDONTWRITEBYTECODE=1 / -p no:cacheprovider）。

## 1. 骨架清单（全部新建，零移动零改动既有文件）

```
plugins/bot_unified_runtime/domains/creation/
├── __init__.py            # 唯一入口：CreationCapabilityRegistry 注册面（§9.3 四步接入），reserved docstring
├── _common/
│   ├── __init__.py        # reserved 占位
│   └── contracts.py       # 任务状态机/取消语义/UsageLine 计量/CostAmount/AssetRef/错误目录（共用件）
├── tts/
│   ├── __init__.py        # reserved 占位（现载体 capabilities/tts.py 留 media，归属裁决=W-PA2）
│   └── contracts.py       # TTSJobRequest/ProviderCapabilities/Usage/AssetRecord/OutboundPlan + REST 路由常量
├── image/
│   ├── __init__.py        # reserved 占位（矩阵 L52 零载体）
│   └── contracts.py       # ImageJobRequest/ProviderCapabilities/SafetyCheckHook/AssetRecord/ConfirmToken/DeliveryPlan
└── extensions/
    └── __init__.py        # reserved 占位（§9.3 通配扩展槽）
```

8 个文件全部首行 docstring 匹配 `^reserved:`，全部声明「依赖外部 provider 配置，未实现」。

## 2. 契约要点（§9.1 → DTO 逐条落地）

- **严格基类** `CreationContractBase`：`extra="forbid"`（未支持参数 422 不静默丢弃）+ `allow_inf_nan=False`（拒 NaN/Infinity）。
- **任务状态机**（TTS/绘图共用 `_common` 单一定义，§9.1.2「同 §9.1.1」）：pending→admitted→running→succeeded/failed/cancelled/unknown；四终态无出边；**unknown 无出边=不盲重发**；`cancel_requested` 是 CancelRequest 标记不是状态；取消保留可能已产生费用（扩展 §1 L58）。
- **TTS 参数域**：text≤3000 二选一 approved_reply_id（模型不得自报）；speed 1.0 默认、0.75..1.25 ∩ provider（TTSProviderCapabilities + `speed_in_provider_intersection` 纯函数）；provider/model/voice 禁路径/URL/注入形态；text 禁原始 SSML；输出上限 60s/20MiB（TTSAssetRecord 硬约束回验）。
- **TTS 计费**：characters/audio_seconds/requests 子集；`token_status=measured` 必须 `token_provider_reported`（不伪造 Token）；UsageLine 不变量 value None ⇔ status∈{unknown,not_applicable}；金额 Decimal 禁浮点。
- **TTS 出站**：tag voice 需 native_voice_verified（文件回退不得称原生 voice）；review_approved 与 via_render_transport 钉死必 True（经 render→transport 主链不走旁路）；REST 路由常量静态先于参数；错误目录 422/503/503/429。
- **绘图参数域**：task 三枚举；prompt≤4000/negative≤2000；count 默认 1 最大 2；steps≤50 ∩ provider；size "WxH" 枚举态；assets/mask 只收 asset_id（拒路径/URL/穿越），输入 ≤20MP（AssetRef.pixel_count）；i2i 须 assets、inpaint 须 mask、mask 仅 inpaint。
- **绘图安全**：SafetyCheckHook Protocol（runtime_checkable）+ SafetyCheckResult（失败必带 reason）；`asset_issuable`=Review 闸；minors 等硬红线语义沿用 chat_reply/security 既有实现（实现期接线，本域零实现承诺）。
- **绘图资产/出站**：ImageAssetRecord 钉死 magic_verified/exif_sanitized/review_approved=True（EXIF 清理+magic 校验+Review 不过不出 asset）；默认预览→确认发送（ConfirmToken 绑 actor/target/version/payload_digest，120s TTL、一次消费，时钟由调用方注入纯函数判断）。
- **注册面**（§9.3）：Entry 的 `default_enabled: Literal[False]`、`gate_state: Literal["dormant"]` 钉死（禁冒充已生效）；实例化三道门：未注册→`UnregisteredCapabilityError`；四步未完（step<4 或投影未完成）→`CapabilityGateClosedError`；无工厂→`CapabilityNotImplementedError`（协议≠可用，矩阵 L101）；`manifest_registration_blockers` 如实报距正式登记缺口；默认注册面三条 dormant 条目（creation.tts/image/extensions）与占位目录一一对应（§9.4④）。

## 3. 实施决策记录

- **叶子纯净 vs 共用件单源**：tts/image contracts 相对导入 `.._common.contracts`（状态机/取消/计量单源，§9.1 要求 _common 为共用件）。测试用「fake 顶层包 + 真实目录 __path__」直载，相对导入照常解析且不触达 `plugins.bot_unified_runtime.__init__`（该父包会拉起 nonebot，属装配层现实，与本域叶子纯净断言分离）；真包路径可导入性由子进程探针如实验证（parent_nonebot 字段只记录不遮掩）。
- **EXIF 清理**：落在绘图侧 ImageAssetRecord 硬门（TTS 音频无 EXIF 语义，不伪造字段）。
- **preview/确认流**：确认 token 按 §6 L149 落在 image（TTS 无确认发送流；preview 端点双方都有）。

## 4. 实跑证据（2026-09-18 实测，解释器=ChatBot_Runtime venv，全程 PYTHONDONTWRITEBYTECODE=1 / PYTHONUTF8=1 / BOT_AUTOSYNC=0 / --basetemp=%TEMP%/v21r2-rwpa1 / -p no:cacheprovider）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 新测试 | `python -m pytest tests/test_v21_creation_skeleton.py` | **39 passed**（1.61s；含 5×reserved docstring 参数化、探针×4、DTO 越界×20+、注册表×6、子进程真包探针×1） |
| 关键词扫掠 | `pytest tests -k creation` | 45 passed / 7834 deselected（22.06s，与他席无冲突） |
| 静态门（本波面） | `ruff check plugins/bot_unified_runtime/domains/creation tests/test_v21_creation_skeleton.py` | **All checks passed!**（初跑 24 错已波内清零：19 自动修+5 手工修=TRY004 noqa[pydantic 校验器须 ValueError]/F841/PLW1510 check=False/DTZ001 noqa[naive 是被测拒绝面]/RUF100 注释文本去 "# noqa" 前缀） |
| 静态门（全树对照） | `ruff check plugins tests` | 33 错全在其他席在飞文件（如 test_v21_risk_red_cp_platform.py F401/F841），**本波文件 0 命中** |
| mypy（权威口径） | `python -m mypy --explicit-package-bases --ignore-missing-imports --cache-dir=%TEMP%/... plugins` | 608 文件 24 错：control_plane/api/platform.py×2（台账 #36 既有基线）+ domains/schedule/delivery.py×6 + runtime/capability_protocols.py×16（并行席 WIP）；**domains/creation 0 新增**。注：直跑 `mypy plugins/bot_unified_runtime` 非权威口径（W14 席教训同款 dual-name 假错，已按 W16 席记录换权威 flags） |
| 哈希门 | `python tests/verify_hashes.py --check` | exit 0 |
| 树卫生 | `pytest tests/test_no_source_tree_data_writes.py` | **5 passed**；终态 creation/**+tests 零 `__pycache__`/`*.pyc`，根 .mypy_cache/.ruff_cache（本席初跑非权威 mypy 与 ruff 默认缓存所写）已清除，qx.json 完好 |
| 插件冒烟 | `python -c "import plugins.bot_unified_runtime; ..."`（§6 ⑦） | plugin import OK；creation 真包 import OK（3 dormant 条目 + PEP562 惰性转发可用） |
| runtime-layout | `python scripts/runtime_layout_smoke.py` | **FAIL=既有环境项**：BOT_KNOWLEDGE_FILES 指向的两个外部用户目录百科文件缺失——与本波零交集（纯新增、未动 config/环境） |
| doc_sync | `pytest tests/test_doc_sync_gates.py` | `test_config_catalog_covers_config_fields` FAIL=**bot_schedule_***×7 未登记（RW10 schedule 席在飞 WIP）；其余 42 passed。本波零 config 触碰 |

## 5. 偏差与移交

- 矩阵 L51/L52 四列维持 unknown：本波只落协议面（协议≠可用），activation/waiting external provider 配置。
- `capabilities/tts.py` 未动（W-PA2 归属裁决：推荐 a 案留 media）。
- 契约字段收敛到 `llm/billing_entities.py` 单源属激活期工作（本波有意对齐其不变量，未 import 它——避免拉起插件父包）。
- **四步阶梯语义落地**：Entry 校验器允许 step1(注册) 无契约 DTO（预留占位条目形态），step2(协议) 起 tts/image 必须挂 §9.1 DTO——默认三条 dormant 条目即 step1 形态；初版「一律必须挂 DTO」会在模块导入期炸掉占位注册面，已修正并测试锁定。
- **域根 PEP 562 惰性转发**：TTS/Image 契约名经 `__getattr__` 按需加载，保域根 import 轻负载，且使测试对每个叶子契约模块的直载探针相互独立（根先加载不会吞掉叶子探针）。
- 两处既有红（runtime-layout 环境项 / doc_sync bot_schedule_*）移交责任席，不在本波处置范围。
