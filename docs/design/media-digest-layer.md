# 中央媒体摘要层蓝图（S-08 / Wave H 预研 · 席位 T107）

> 日期：2026-09-20 ｜ 席位：T107（S-08 中央媒体摘要层蓝图席，方案件**零施工**）
> 状态：DONE（全只读取证；唯一写入=本件+report-T107.md；零 git 写、零子代理、零代码改动、零启停）
> 取证基线：当前工作树真身（读码）+ report-T97/T78/T61/T80/T29 交叉对账。取证时刻 2026-09-20（树在多席在飞，行号为读码锚点、随树漂移以符号为准）。
> 审计原意链：plan.md §2-D4（函数级重复实现→本应中央化的 helper）→ T29 M-64 收口点「出站键规约=消息身份∧段类型∧段内容摘要（**摘要由中央媒体层产**）」→ T29 S-08「音频介质质检/归一中央件缺位」→ T97 终态核验 M-64 半闭（生成身份维度闭/字节摘要维度未闭）。

---

## 1. 问题定义（M-64 未闭半的精确边界）

T97 已核验：T78 段级键把音频「生成身份」纳入（part canonical JSON 含 file 路径），但——

1. **音频字节零摘要**：时长/体积/内容 digest 不入任何键；出站键对「发出去的字节是什么」结构性失明。
2. **T101（M-39 uuid 化）切断了 T97 判定的前提**：段级键的「身份维度已闭」论证依赖 `路径=cache_key.wav`（身份变更⇒新路径⇒新键）。现树落盘名已改 `tts-{uuid4}.hex}.wav`（tts.py `synthesize` 落盘点，`uuid.uuid4().hex`），路径与内容身份的确定映射**已断**——段级键退化为「路径身份」（单行内稳定，跨行无内容语义）。字节摘要维度因此从「补强」升格为「唯一内容身份来源」。
3. **pipeline dedupe_key 仍三元组**：`pipeline.py` SendRequest 构造点 `f"{capability_id}:{session_id}:{message_id or request_id}"`，零内容维度。
4. **`-textfb` 子请求游离原台账**：`worker.py` `_send_media_text_fallback_once` 内 `request_id=f"{rid}-textfb"`、`dedupe_key=f"{原key}:textfb"` 独立成行，「恰好一次」靠「终态行不被认领」间接性质维持（T29 M-64 该半句未动）。

## 2. 现状图：音频字节从合成到出站的六个流经点

| # | 流经点 | 坐标（锚点） | 身份/摘要现状 |
|---|---|---|---|
| 1 | 合成·输入侧 | `domains/media/capabilities/tts.py` `_ref_fingerprint`（ref 字节 sha256[:16]，每次全量）+ `_cache_identity`（preimage=identity_version+api_url+ref 指纹+text+preset 参数 → seed=sha256[:8]、cache_key=sha256[:20]） | **有 sha256，但全是请求/素材身份**（ref 输入字节+文本参数），非产物字节 |
| 2 | 合成·产物字节 | 同文件 `_inspect_wav_bytes`（RIFF/WAVE 魔数+头可解析+帧数>0+静音指纹三同中）→ 字节顶校验 → `target.write_bytes(audio)`（落盘名 `tts-{uuid4}.wav`，T101）→ `_store_cache(key, target)`（内存 key→path） | **零哈希**。结构体检不产出任何可复用身份；uuid 化后盘上名零内容信息 |
| 3 | 能力出口 | tts.py 两处 audio 构造 `{"file": str(path), "review_text": speech}`（record 缺省类型，T80 对表锚 `:1067`/`:1422` 形态） | 路径引用+审查文本；无 digest 无 duration/bytes |
| 4 | pipeline 去重 | `domains/chat_reply/runtime/pipeline.py` SendRequest `dedupe_key=(f"{capability_id}:{session_id}:{message_id or request_id}")` | 三元组，零内容（M-64 原样） |
| 5 | 渲染收口 | `domains/render/renderer.py` `canonicalize_audio_parts`（T80 件）：record 出站部件**恰两键** `{"type":"record","file":…}`；`_AUDIO_PLAYABILITY_KEYS={"duration","bytes"}` 校验后**剥离不上段**；未登记键=stray 剥离留痕 | **digest 若能力侧带来会被当 stray 键剥离**（现契约无该键位）；渲染路径零文件 IO |
| 6 | 传输·段级键与出站 | `domains/transport/sender/worker.py` `_mixed_part_identity`（part canonical JSON，sort_keys）→ `_payload_digest`（sha256(串)[:16]）→ queue `send_request_parts.payload_digest`（part_key=`{request_id}:{index}`）；`domains/transport/sender/onebot.py` `_segment_from_mixed_part` record 分支 data 白名单**恰 `{"file"}`**、`_resolve_local_file_ref` 透传（T100 在飞） | 段级摘要=**part JSON 串的摘要**（含路径、不含字节）；出站段构造天然忽略额外部件键；出站前零字节校验 |

旁证（中央件缺位实证）：`grep -rn "sha256" domains/media/` 仅三处——tts.py（ref 输入指纹+cache preimage）、`domains/media/archive/media_archive.py`（归档去重自算 `hashlib.sha256(data).hexdigest()`，**第二份独立手抄**，D4 审计原意的现行实例）；`media_digest`/`content_digest` 全 domains/ 零命中。**中央摘要真身不存在。**

## 3. 目标形态

### 3.1 中央件（唯一真身）

新文件 `domains/media/digest.py`（归 media 域，与 S-08 质检/归一层同址预留；零包内依赖、纯函数）：

```python
def media_digest(data: bytes) -> str:
    """媒体字节内容摘要唯一算法：sha256 全长 64 hex 小写。"""

def media_digest_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str | None:
    """流式摘要（1MB chunk 迭代 hashlib.update，O(1) 内存）。
    读不到/OSError → None（调用方决定降级语义，本件不吞）。"""
```

规约三条：
- **单一算法**：sha256 全长小写 hex；截短是**消费侧**决定（键内截短见 §3.3），算法本身不截短（全局去重/跨库对账可互查）。
- **单一入口**：全仓媒体字节哈希只准经此件（media_archive 的归档去重收编为消费点，另立批次不在本层最小面）；禁再造 `hashlib.sha256(media_bytes)` 手抄（D4 原意）。
- **不裁决可播性**：本件只答「字节是什么」，「字节能不能播」仍归 `_inspect_wav_bytes` 族（S-08 质检闸另席）；两件同域不同责，禁合并成上帝件。

### 3.2 键规约（出站键 = 消息身份 ∧ 段类型 ∧ 内容摘要）

| 键 | 现状 | 目标 |
|---|---|---|
| pipeline `dedupe_key` | `cap:session:msg` | `cap:session:msg` **∧** `d=<各 record 部件 digest 截短按序拼接的 sha256[:16]>`（无 record 部件/无 digest 的请求 key **逐字节不变**——向后兼容硬约束）；多 record 部件时 d 段=对「部件 digest 有序列表」再摘要（防拼接歧义） |
| queue part `payload_digest` | sha256(part canonical JSON)[:16]（含路径） | 自动含内容维度——digest 上 part 后 `_mixed_part_identity` **零改码**纳入（canonical JSON sort_keys 稳定） |
| part 冻结形态 | `{"type":"record","file":…}` 恰两键 | record 族**恰三键**：新增 `content_sha256`（64 hex 小写；非法=剥离+anomalies 留痕、部件保命，与 duration/bytes 同待遇）。music/file 族两键不变（无本地字节，digest 允许缺省=诚实降级） |

### 3.3 落点（消费点唯一）

**`canonicalize_audio_parts` 是唯一消费点**（T80 已把它立为渲染收口咽喉，键语义只准在此定）：

1. 能力侧（合成时）把 digest 免费挂上：tts.py 落盘点 `target.write_bytes(audio)` 同点 `media_digest(audio)`（bytes 已在内存，零读盘）→ audio item 增 `"content_sha256": digest`。
2. canonicalize 校验 `content_sha256`（`^[0-9a-f]{64}$`）→ 合法上 part（第三冻结键）、非法剥离留痕 → 向下流经 worker 段级键（自动）、onebot 段构造（data 白名单天然忽略，**传输层零改动**）。
3. pipeline SendRequest 构造点从 rendered parts 提取 record 部件 digest → 组 d 段（§3.2）。缺 digest 的部件参与 d 段时用 `"-"` 占位（保持 key 确定性）。
4. **canonicalize 不做兜底补算**（渲染路径零同步 IO，推荐案）；`media_digest_file` 留给后续质检席/审计侧按需消费（U-107-B 开放问题）。

## 4. 与 T61 缓存键 v2 的职责切分（出站摘要 ≠ 合成侧键）

| | 合成侧（T61/T57 身份 v2） | 出站侧（本层） |
|---|---|---|
| 答的问题 | 「**要合成什么**」（text+ref 内容指纹+engine+preset 参数的 preimage） | 「**发出去的字节是什么**」（产物真相） |
| 消费点 | 缓存命中（进程内 LRU+盘上同名复用）、确定性 seed 派生 | 段级幂等键、pipeline 去重、审计/毒件追溯 |
| 确定性含义 | 同身份⇒同键（键空间 IDENTITY_VERSION=2） | 同字节⇒同摘要；同身份⇒同字节是**期望非保证**（引擎升级/权重回退即漂移）——摘要恰是漂移的取证器 |
| 交互纪律 | 出站摘要**不回写**缓存键：不构成键空间换代、零缓存失效、`cache_key` 生成算法零改动 | 摘要可进 `audit_tags`（`audio_sha256=<截短>`，观测面增量，U-107-C） |

T101 uuid 化后两键已彻底解耦（路径既非请求身份也非内容身份）；本层补上的是「内容→键」这条断链，而非替代任何一侧。

## 5. `-textfb` 游离面的本层解法

坐标：`worker.py` `_send_media_text_fallback_once`（`request_id=f"{rid}-textfb"`、`dedupe_key=f"{原key}:textfb"`）。

- 键语义升级：`dedupe_key` 改 `f"{原key}:textfb:{_payload_digest(text)[:16]}"`——「同父+同降级文本」内容寻址，重放同文本天然幂等；「恰好一次」从「终态行不被认领」间接性质升格为键语义（原行终态判定逻辑零改动，仍 best-effort 一次）。
- 台账归位：fallback_request `audit_tags` 追加 `textfb_parent=<原行 audio digest 截短或 "-" >`——子请求与原行经摘要链可互查，游离面闭合。
- 兼容：存量在飞行 key 无新段不冲突；文本降级属媒体终败 rare path，无热路径成本。

## 6. 成本 / 风险 / 兼容

| 项 | 评估 |
|---|---|
| 「双哈希」开销 | **伪问题**：合成侧现只对 ref 输入与 preimage 文本哈希，产物字节从未哈希过——不存在可复用的一次。新增成本=落盘点对内存 bytes 一次 sha256（`bot_tts_max_audio_bytes` 顶 8MB → <10ms，相对秒级合成可忽略，与 `_ref_fingerprint` 注释同一论证）。worker 侧 part JSON 摘要已有，增量=64 字符。无第二次读盘。 |
| 大文件流式 | 合成路径 bytes 全量在内存（现状如此，本层不新增内存）；`media_digest_file` 用 1MB chunk 流式，供未来非内存面（质检/归档）使用。 |
| part 幂等族兼容 | part_key 结构不变；payload_digest 值变（含 digest 的 JSON）但「同请求重复计划同键」性质保持（digest 是部件稳定成分）。存量在飞 request_json 无 digest → 键退化现状，新旧行不互撞（可选键、缺省退化是本层全部兼容性的根）。 |
| 契约棘轮 | T80「恰两键」锁（`tests/test_voice_outbound_contract.py` `test_free_bag_keys_stripped_to_canonical_record_shape` 族）会红——按 T78 棘轮翻转先例改写断言（两键→record 族恰三键），翻转记录入报告。 |
| onebot/传输层 | 零改动（data 白名单 `{file}` 天然忽略第三键；`_resolve_local_file_ref` 不涉）。TG 分支认 {record,voice} 同样零感知。 |
| 残余边界（本层不解决，如实登记） | ①file/music 族无 digest（键退化现状）；②同路径不同字节残余面：uuid 化后合成侧不再同名覆盖，但**外部手改 wav 文件**仍不触发任何键变化（读盘比对属质检席 U-107-B）；③`-textfb` 的 request_id 前缀仍非内容寻址（dedupe_key 已内容寻址即够，request_id 保持行唯一性职责）。 |

## 7. 施工坐标与 RED 建议（每阶段一条，先行失败测试）

| 阶段 | 施工面 | 坐标 | RED（先行失败测试） |
|---|---|---|---|
| S1 中央件 | 新增 `domains/media/digest.py` | `media_digest`/`media_digest_file` 两函数+docstring 规约 | 新件 `tests/test_media_digest.py`：`media_digest(b"x")==hashlib.sha256(b"x").hexdigest()`、流式与一次性等值、缺文件返 None——现树 ImportError 红 |
| S2 合成侧挂摘要 | `domains/media/capabilities/tts.py` 落盘点+两处 audio 构造 | `write_bytes` 同点算 digest；`[{"file":…,"review_text":…,"content_sha256":digest}]`（两处同改） | 断言能力返回 `audio[0]["content_sha256"]` 为 64 hex 且==落盘文件字节摘要——现树 KeyError 红 |
| S3 渲染冻结键 | `domains/render/renderer.py` `canonicalize_audio_parts`+常量区 | `content_sha256` 入冻结键集（record 族第三键）；格式门+剥离留痕；T80 棘轮翻转 | `test_voice_outbound_contract.py` 新例：合法 digest 输入→part 恰三键；非法 digest 剥离+anomalies 留痕——现树被当 stray 剥离，断言红 |
| S4 键扩展 | `pipeline.py` SendRequest dedupe_key 构造点；`worker.py` `-textfb` 两键+audit_tags | d 段组装（§3.2）；`textfb:<digest8>`；`textfb_parent` | ①带 digest 的 rendered → dedupe_key 含 d 段、无 audio 请求 key 逐字节不变（兼容锁）；②同路径不同 digest 两 part → `_payload_digest(_mixed_part_identity(part))` 不同——现树同路径同键，红 |
| S5（独立后续，不属本层最小面） | media_archive 归档去重收编 + 质检闸（S-08 全量） | `domains/media/archive/media_archive.py:203` 换调 `media_digest` | 归档入库行的 sha256 与 `media_digest(bytes)` 恒等——现树两算法并列，等值门红 |

施工序：S1→S2→S3 串行（键位依赖），S4 依赖 S3；全阶段零新 config 键、零行为变更面（除键值内容）、缺省退化路径逐字节现状。禁碰面提示：queue.py（part 族零改动）、onebot.py（零改动）、`.env`/config。

## 8. 开放问题（需用户裁决，共 3 项）

- **U-107-A digest 截短口径**：part 上挂全长 64 hex（推荐：审计与全局去重可互查），dedupe_key/textfb 键内截短 [:16]——若用户偏好键内全长请裁。
- **U-107-B canonicalize 是否兜底补算**：能力侧未挂 digest 时渲染入口读盘补算（同步 IO 入渲染路径）vs 缺省退化无 d 段（推荐，零 IO）——补算会改「无 digest 请求 key 不变」的兼容承诺，须裁。
- **U-107-C audit_tags 观测面**：`audio_sha256=<截短>` 是否随 S2 顺带挂（行为变更需波末报备）vs 只留键面零观测增量（最小面）。

## 9. 证据口径

读码锚点（2026-09-20 工作树）：tts.py `_ref_fingerprint`/`_cache_identity`/`_inspect_wav_bytes`/落盘 `tts-{uuid4}.wav`/audio 构造两处；pipeline.py SendRequest dedupe_key 构造；renderer.py `canonicalize_audio_parts`+`_AUDIO_PLAYABILITY_KEYS`；worker.py `_mixed_part_identity`/`_payload_digest`/`-textfb` 构造；queue.py `send_request_parts` 表结构+`_part_key`；onebot.py `_segment_from_mixed_part`/`_resolve_local_file_ref`；media_archive.py sha256 自算。转述项（T78/T80/T97/T61 报告结论）均已标注出处；「digest 全 domains/ 零命中」「sha256 仅三处」为 grep 实跑。
