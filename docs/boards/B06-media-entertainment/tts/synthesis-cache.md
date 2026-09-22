# 语音合成 · 缓存键与落盘命名

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.tts · 缓存键与落盘命名

- 层级：一级 B06 → 二级 tts → 三级 `synthesis-cache`
- 实现落点：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`、`plugins/bot_unified_runtime/domains/creation/tts`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

机械件（不占路由席位）：决定「这句话是否还需要再合成一次」以及「合成出来的文件
叫什么」。旧实现两条都不成立：缓存键只由文本与采样参数拼出，换了引擎、换了参考
音频、换了预设都照样命中旧产物（同句八个键互相打架、异句又彼此串味）；落盘名直接
用内容指纹，等于把「哪句话被念过」永久写在磁盘文件名上，可离线字典反推。

现在的口径：缓存身份四维（引擎、素材、预设、正文），seed 由同一份 preimage 派生，
盘上名随机化，键与文件名彻底解耦。

## 怎么调用

- `tts.py:_cache_identity(text, ref, params, *, api_url, preset_id, identity_version)`：
  唯一算法。preimage = 对 `{identity_version, engine, ref, preset, text}` 做
  canonical JSON（`sort_keys`、保留非 ASCII），返回 `(cache_key, seed)`：
  - `engine` 维度：`api_url` 做 `rstrip("/")` 归一，尾斜杠不算换了引擎；
  - `ref` 维度：绝对路径 + `_ref_fingerprint`（素材字节 sha256 截短）+ 参考文本 + 语种；
  - `preset` 维度：预设 id + 生效参数快照，换预设=换键空间；
  - `identity_version`：键空间代号（`tts_presets.IDENTITY_VERSION`），换代自增让旧键
    整体变冷，不做迁移；
  - `seed = sha256(preimage) 前 8 位转 int`（旧的 `seed=-1` 每请求随机重播种已废除），
    `cache_key = sha256(preimage + "|" + SEED_RULE_VERSION) 前 20 位`，规则版本入键
    防跨规则碰撞。
- `tts.py:derive_seed`：seed 的唯一派生口，审计标签与请求体共用，保证「记录的和发的」
  是同一个数。
- `tts.py:_lookup_cache` / `_store_cache`：进程内 LRU（容量 `_CACHE_LRU_CAP`），
  命中前先验文件还在，不在则踢掉条目。
- `tts.py:synthesize` 落盘点：文件名 `tts-<uuid4hex>.wav`（M-39），写完立刻在同一处
  调 `domains/media/digest.py:media_digest` 算产物字节摘要，随音频部件带出
  `content_sha256`。
- `domains/transport/sender/worker.py` 与 `domains/chat_reply/runtime/pipeline.py`：
  消费侧——摘要进 `record` 部件第三冻结键、进段级幂等键的 `d=` 段；没有摘要的请求
  键**逐字节不变**（缺省退化是整个设计的兼容性根）。摘要不回写缓存键，不构成换代。

## 开关与参数

- `bot_tts_cache_enabled`（True）：关掉即每请求真打引擎。
- `bot_tts_preset`：换值等于换键空间（预设参数进 preimage）。
- `bot_tts_api_url`：换端口/换实例同样换键。
- `bot_tts_cache_max_bytes` / `bot_tts_cache_max_age_days`（均 0=不限制）：落盘后
  顺接中央 `enforce_quota`（最旧先删），缺省关——语音产物目录定性为**可再生
  缓存**而非档案（U-04 裁定 a 案），但配额没开的时候它就是个只会长的大目录。
- `bot_tts_output_dir`（产物目录，缺省路径以 `config.py` 该字段为准）：必须经 `scripts/runtime_paths.py`
  重映射，漏登会写进源码树。

## 失败时看到什么

- 缓存里记着的路径已被删：当作未命中重合成，不报错，也不留陈旧条目。
- 产物体检不过：不落盘、不入缓存（毒件一旦入缓存会在进程存活期反复复放）。
- 落盘失败（`OSError` 与非法路径 `ValueError` 同捕）：`音频落盘失败：<异常类型>`，
  挂 `tts_write_failed`，且**不清零退避**——写不下去不算成功。
- 摘要算不出（文件读不到等）：诚实降级，部件不带 `content_sha256`，出站键退化为
  现状三元组形态，不伪造摘要。
- 换预设/换引擎/键空间换代后：用户无感，只是首批句子会重新合成一次。

## 测试与验收

`tests/test_tts_cache_identity.py`（四维任一项变化必换键、尾斜杠不换键、seed 与
cache_key 同源）、`test_tts_filename_privacy.py`（盘上名不含内容指纹、不含正文）、
`test_tts_media_digest.py` 与 `test_media_digest.py`（落盘点摘要与文件字节恒等、
流式与一次性等值、读不到返 None）、`test_tts_outbound_chain.py` +
`test_voice_outbound_contract.py`（`record` 部件三冻结键、非法摘要剥离留痕、
无摘要请求 dedupe_key 逐字节不变）、`test_voice_queue_sim.py`（段级幂等重放）。
`tests/test_tts_t127.py` 覆盖哈希派生收编进中央件后的恒等性。
