# report-T116 — Wave H 摘要层 S5：media_archive 自算 sha256 收编中央件

- 席位：T116｜日期：2026-09-20｜性质：代码施工（唯一代码面=`domains/media/archive/media_archive.py` 最小改动）
- 蓝图：docs/design/media-digest-layer.md §7 S5 行｜中央件：T109 席 `domains/media/digest.py`

## 0. 前提修正（本席开工即发现，未改前提只报事实）

任务简报写「自算 sha256 的第二份手抄位置=domains/media/**capabilities**/media_archive.py」——**实查不成立**：该文件零 hashlib（sha256 仅现于 docstring）。真身=**domains/media/archive/media_archive.py**（蓝图 §2 旁证与 §7 S5 坐标一致）：`:203`（save 归档去重）+ `:289`（save_text 聊天记录去重）。本席按蓝图坐标施工，capabilities 份零改动。

## 1. 等依赖记录

- digest.py 在盘性：开工首轮 `ls` 即见（2026-09-20 04:37，T109 已落盘，2690 字节，接口 `media_digest`/`media_digest_file` 与蓝图 §3.1 逐字一致）——**未触发 sleep 重查**。
- 全包 `digest import` 消费点开工时=0（T109 件尚无消费者）；本席收编后 media_archive 为首个消费点。

## 2. 改动清单（最小面）

`plugins/bot_unified_runtime/domains/media/archive/media_archive.py` 三处：

1. 删 `import hashlib`（收编后无残余引用，grep 实证 exit=1）。
2. 增 `from ..digest import media_digest`（相对两级=domains.media，与包内 `domains/creation/image/contracts.py` 的 `from .._common.contracts` 同惯例；简报的 `from ...digest` 三级在现树解析到 `bot_unified_runtime.domains.digest` 不存在，**三级为简报笔误，已按两级修正**，pytest 实证可解析）。
3. `:203` `hashlib.sha256(data).hexdigest()` → `media_digest(data)`；`:289` `hashlib.sha256(payload).hexdigest()` → `media_digest(payload)`。各附一行注释标注唯一真身。

禁碰面（digest.py/tts.py/tests test_tts_*/根 init/config.py/transport）零触碰；未动 tests/（并行席在飞的 test_media_archive.py import 迁移非本席所为，与本改动正交）。

## 3. 行为等价证明（三重）

1. **源码恒等**：digest.py:39 即 `return hashlib.sha256(data).hexdigest()`——同表达式同算法，sha256 全长 64 hex 小写，无截短。
2. **端到端实跑三方对照**（venv 实跑，data=PNG 魔数+256B 样本经 `MediaArchiveStore.save` 真落盘落库）：stored=direct(hashlib)=central(media_digest)=`90a812851798ef1a9a2bc8d34db02540505499654de9e85c87329b38bec94130`，断言相等通过；文件名 sha8 前缀形态不变（`20260920_044637_90a81285.png`）。归档落库路径哈希值逐字节不变，实证成立。
3. **回归全绿**：`tests/test_media_archive.py`（35 例，含 `test_sha256_dedup` 幂等去重端到端）+ `tests/test_media_digest.py`（T109 S1 锁，含 `media_digest(b"x")==hashlib.sha256(b"x").hexdigest()`）合计 **50 passed / 0 failed**（实跑 2.85s）。

实跑配方：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_media_archive.py tests/test_media_digest.py -q -p no:cacheprovider --basetemp="../ChatBot_Runtime/cache/t116"`

## 4. 静态门与树卫生

- ruff（touched 件）：All checks passed。
- mypy（项目口径 `--explicit-package-bases --ignore-missing-imports`，touched 件+digest.py）：**Success: no issues found in 2 source files**。
- 树卫生：archive/ 目录无 `__pycache__`/`.pyc`；pytest basetemp 落 Runtime/cache/t116；零 data/ 残留。端到端脚本的 TemporaryDirectory 清理 WinError 系 SQLite WAL 句柄在 Windows 的既有现象，断言在其之前已全部通过，非产物。

## 5. 全仓其它自算 sha256 手抄点清单（grep 实证，只列不改）

grep 口径：`hashlib.sha256|hmac…hashlib.sha256` 于 plugins/+scripts/，排除中央件 digest.py 与 tests（测试断言侧重算属验证器非生产手抄）。实跑产出 60+ 行，按媒体摘要层语义分两类：

### A 类——媒体/文件字节面（后续波收编候选，7 处）

| 坐标 | 现状 | 收编口径 |
|---|---|---|
| `domains/media/capabilities/tts.py:389` | `_ref_fingerprint`：ref 文件字节 sha256[:16]（read_bytes 全量） | 蓝图 §2「合成·输入侧」身份，归 S2/S-08 席面（本席禁碰 tts.py）；可换 `media_digest_file` |
| `domains/media/capabilities/tts.py:445,446` | cache preimage/seed/cache_key（文本+指纹再哈希） | 同上，键派生面，属 T61 身份 v2 域 |
| `domains/media/capabilities/tts.py:1326` | 确定性概率桶（seed 文本） | 非（B 类语义，列此仅因同文件） |
| `domains/meme/capabilities/meme.py:348` | 表情服务返回 GIF 字节 sha256[:12] | 媒体字节，可换 `media_digest` |
| `domains/transport/sender/file_gateway.py:207` | `_sha256_of_file`：1MB chunk 流式文件摘要 | 与 `media_digest_file` 语义逐点同构，最佳收编候选 |
| `domains/transport/sender/file_gateway.py:255` | `_stage_bytes`：内存 bytes 一次性摘要 | 可换 `media_digest` |
| `scripts/fetch_mermaid_js.py:57`、`scripts/render_card_samples.py:1066`、`scripts/sync_persona_source.py:99`、`scripts/pre_restart_check.py:717` | 资产/文件完整性校验 | 可选 `media_digest_file`（脚本侧，低优先） |

### B 类——非媒体字节面（文本/令牌/种子/HMAC，不属媒体摘要层，不收编，留域内）

- **control_plane/**（9 处）：actions.py:196,208,258（确认令牌哈希）、auth.py:48、config_store.py:131（敏感值指纹）、llm_admin.py:42,177、workspaces.py:272,313,323、platform.py:257、metrics.py:168（HMAC）。
- **chat_reply/**：poke.py:38,122（确定性概率桶）、affinity_replay.py:454、persona_service.py:116、billing_service.py:104、policy/gate.py:116、prompt_audit.py:73。
- **core/search/search_service.py**：776,782,957,1050（缓存键/引文 id）+ 988,996（cursor HMAC）。
- **divination/**：draw_store.py:129,239,269,282,299,301、tarot.py:264、render_projection.py:51、tarot_draw.py:100、fortune.py:116,156,170,188,194（占卜种子/HMAC，安全敏感，禁并轨）。
- **finance/stocks.py:155**（查询身份）、**music/data/music_normalization.py:33**。
- **ops/**：monitor/intent_telemetry.py:57、repair/service.py:777（文本合成键）。
- **schedule/**：timetable.py:133,196、service/schedule_rrule.py:178、service/schedule_service.py:586（payload id）。
- **transport/**：mail/mail_bridge.py:259（邮件内容去重，文本）、sender/worker.py:638（part JSON 摘要——蓝图 §2 row 6 明确保留字符串摘要语义）、sender/outbound_gate.py:256。
- **meme/reactions/engine.py:303,634**（反应种子/HMAC）；**scripts/webui_mock_server.py:90,108**（mock 会话 HMAC）。

## 6. 结论

S5 收编完成：media_archive 归档去重两处手抄消灭，中央件获得首个生产消费点，行为逐字节等价（50 passed+三方实跑对照），ruff/mypy 净。后续波建议从 file_gateway 双点（A 类最佳候选）续收。
