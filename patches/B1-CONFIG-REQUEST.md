# B1-CONFIG-REQUEST · 语音合成产物目录的配额缺省（席 B1，2026-10-02）

> 一句话：`bot_tts_cache_max_bytes` / `bot_tts_cache_max_age_days` 两枚**已存在**的键，
> 缺省从 `0`（＝不限制）改成有界值。本席禁写 `config.py`（席位共同硬约束），故按台账
> #68★ 提**精确需求**，点名「需主会话同批落四面 + 同批改动的锁」。**不新增键、不改键名、
> 不动 `bot_tts_cache_enabled`**（那枚缺省本就是 `True`，简报里「缓存开关缺省 0（关）」
> 与现算不符，纠偏见 `patches/B1-TTS-CACHE-OUTTMPL-20261002.md` §1）。

## 1. 需求两枚（键名 / 类型 / 现缺省 → 请求缺省 / 语义 / 消费点）

| env 键 | 字段 | 类型 | 现值 → 请求值 | 语义（`cache_policy.enforce_quota` 口径） | 消费点（按符号名定位；行号会漂 ⇒ 台账 #50★） |
|---|---|---|---|---|---|
| `BOT_TTS_CACHE_MAX_BYTES` | `bot_tts_cache_max_bytes` | `int`（`Field(ge=0)`） | `0` → **`268435456`**（256 MiB） | 目录总字节上限，**最旧先删**；`<=0`＝不限总量 | `domains/media/capabilities/tts.py` 三枚调用路（`capability` / `synthesize_autodub` / `maybe_attach_voice`）→ `synthesize(..., quota_max_bytes=…)` → 落盘后那一腿（本席新加的形态闸 `_quota_bound` 在其前） |
| `BOT_TTS_CACHE_MAX_AGE_DAYS` | `bot_tts_cache_max_age_days` | `int`（`Field(ge=0)`） | `0` → **`30`** | 保鲜期天数，超期即删（与字节档同一条腿、先后有序） | 同上（`quota_max_age_days=`） |

管理员**显式**设 `0` 的语义不变（＝「别动我的缓存」继续被尊重）；`synthesize` 的
`if quota_bytes > 0 or quota_age_days > 0` 那道腿一字未动。

## 2. 阈值不是拍出来的（真实分布分档 @2026-10-02 01:3x 本地，只读取证）

现盘 `ChatBot_Runtime/data/tts_output/`（生产 `BOT_TTS_ENABLED=true`，`BOT_TTS_CACHE_*` 三枚未设、
覆盖册 `config_overrides` 里 TTS 键 **0 行** ⇒ 生效值＝代码缺省）：

- **24 枚 / 30,927,136 B ≈ 29.49 MiB**；单枚 min 105 KiB、median 1.52 MiB、max 2.29 MiB、avg 1.23 MiB
  （`bot_tts_max_audio_bytes` 的 8 MiB 字节顶从未触顶）。
- 时刻分布：09-18 ×1、09-24 ×14、09-25 ×2、09-26 ×3、09-27 ×4 ⇒ 跨 9 日 **2.67 枚/日、3.28 MiB/日**；
  最旧一枚 **14 天**前。
- 分档推论（A 案 256 MiB / 30 日）：
  - 256 MiB ÷ 3.28 MiB/日 ≈ **78 天**自然增长才第一次触线；按峰值日（14 枚 ≈ 18 MiB）算也够 ~14 个峰值日；
  - 256 MiB ÷ 8 MiB（字节顶最坏形态）＝ **≥32 枚**下限 ⇒ 不会出现「刚落一枚就把自己删掉」；
  - 30 日 > 现盘最旧 14 日 ⇒ **落地当天一枚都不删**（现网零行为差，只是从此有界）。
- 同族对照（尺＝`config.py` 现值，本席不重抄清单）：`bot_card_cache_max_bytes` / `bot_meme_cache_max_bytes`
  均 256 MiB、`bot_music_cache_max_bytes` 512 MiB、`bot_download_cache_max_bytes` 2 GiB + 7 日。
  语音产物与卡片/表情同量级 ⇒ A 案取 256 MiB；若主会话要更宽，**B 案＝512 MiB / 60 日**（与 music 同族），
  两案都满足「落地当天零删除」。⚠ 不许自造第三档。

## 3. 四面必须同批（只补一面必红另一面）

1. `plugins/bot_unified_runtime/config.py`（约 :593-594，`bot_tts_cache_*` 段）——两枚 `Field(default=…)` 数值。
2. `domains/chat_reply/runtime/settings.py:598-603`——登记行**文本**（`BOT_TTS_CACHE_MAX_BYTES` / `..._AGE_DAYS`）
   已在册且写的是「读装配期 config、覆盖不可达」，值随 config 走 ⇒ 本批**只核不改**；
   若主会话顺手要收进热改档，那是合并层（`__init__._RUNTIME_HOT_OVERRIDE_FIELDS`）另一档活，别混进本批。
3. `.env.example:1037-1038`——两行数值同步（现值 `0`）。生产 `.env` 本席不碰（禁写面）。
4. `docs/config-catalog-full.md:850`（派生册，**只走生成器 `--write`** + 验收带 `BOT_AUTOSYNC=0`，台账 #72★）。
   另：板块页正文（生成标记之外的手写区）`docs/boards/B06-media-entertainment/tts/synthesis-cache.md:51-53`、
   `tts.md:67-68`、`README.md:119-120` 三处写着「均 0=不限制 / 配额缺省关闭 / 孤儿无人回收」——
   那本就是把这笔债记在账上的地方，改缺省要同批把这三句改掉，否则文档与运行时两说。

## 4. 同批要跟着改的锁（不改就红）

- `tests/test_tts_presets.py::test_config_quota_keys_default_off`——现断言两枚 `== 0`（「U-04 缺省关」）。
- `tests/test_tts_cache_quota_shape_guard.py::test_cache_is_on_by_default_while_the_quota_is_off`
  与 `::test_default_quota_leaves_every_artifact_on_disk`——本席新锁**故意**把「缺省不收盘」钉成债账，
  改缺省即红，红法就是设计目的（逼一次显式改账）。
- 复跑不带红即可（预计不动）：`tests/test_tts_contract_layer.py`（U-04 两格）、
  `tests/test_config_key_registration_ledger.py`（键集合不变 ⇒ 直读维读数不变；**该文件正被别席在飞**，
  改数值别顺手动读点形态）、`tests/test_doc_sync_gates.py::test_config_catalog_*`、
  `tests/test_env_example_gate.py`。

## 5. 风险与两步方案（要主会话裁的点）

- 配额一开，`enforce_quota` 会在每次落盘后 `rglob` 整个产物目录（现盘 24 枚 ⇒ 成本可忽略，与卡片/表情包同形）。
- 「最旧先删」删掉的可能是**发送队列里仍在引用**的那枚产物（part 级幂等 / UNKNOWN 确认 / PARTIAL 断点续发），
  被删后走 M-38 死引用摘段。30 日档远大于任何在飞窗 ⇒ 风险实际落在**字节档触线**那一刻。
  保守方案：**第一步只开 `MAX_AGE_DAYS=30`（`MAX_BYTES` 留 0）**，观察一轮再落字节档。
  本席不在这里代替裁定，只把两案摆齐。
- 本席**没做**且需要裁的另一格：把 `int(getattr(config, "…", 0) or 0)` 改成「读不出键即回落 `Config` 字段缺省」
  （`music.py::_music_cache_quota_bytes` 的 W7 同形）。它会把 6 枚字面 `getattr` 读点重排成 2 枚，
  动的是 `tests/test_config_key_registration_ledger.py` 的**直读维**读数（现账 `1606`、容差 `200`，
  且该文件此刻在别席手里）⇒ 本席按「不碰别人在飞面」停在形态闸那一格，全文见工单 §5。
