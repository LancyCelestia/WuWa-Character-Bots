# 语音合成 · 参考音频与音色基线

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.tts · 参考音频与音色基线

- 层级：一级 B06 → 二级 tts → 三级 `voice-identity`
- 实现落点：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`、`plugins/bot_unified_runtime/domains/creation/tts`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

机械件（不占路由席位）：管「这段声音为什么听上去是她」。守岸人的音色不是模型本身，
而是**参考音频**——引擎拿一条合规时长的干声做零样本克隆（时长区间以引擎契约为准），参考音频说什么、什么
语种、内容指纹是什么，直接决定产物音色与咬字。所以这件事需要两样东西：一份可校对
的素材清单，和一把「音色有没有被悄悄换掉」的守望闸。

## 怎么调用

- `tts.py:parse_ref_audios(items, *, base_dir="")`：解析 `bot_tts_ref_audios`，每项
  形态 `路径|参考文本|语种`（后两段可省，语种缺省 `zh`）；相对路径挂到
  `bot_tts_gptsovits_dir` 下，绝对路径原样用（T100 对相对死引用采「诚实透传」，
  生产恒配绝对路径）。
- `tts.py:pick_ref_audio(items, *, base_dir="", rng=None)`：只从**文件确实存在**的
  候选里挑一条，一条都没有返回 `None`（走 `tts_no_ref_audio` 面，文案直接教用户怎么
  填这条键）。
- `tts.py:_ref_fingerprint`：参考音频字节的 sha256 截短，进缓存键的 `ref` 维度
  （见 `synthesis-cache.md`）——换素材等于换键，不会命中旧产物。
- `scripts/pre_restart_check.py:check_tts_voice_identity`：重启前体检的音色守望项。
  读引擎目录的权重配置（yaml）语义与字节锚，对表 `scripts/tts_voice_baseline.json`；
  引擎目录不存在时判 SKIP（不假红），五种不一致各给一句人话结论并提示「确属有意
  换音色才重录基线，疑似引擎静默回退时严禁重录掩盖」。
- `scripts/tts_corpus/`：参考音频语料工具链（转写、对齐、校验），收编入库并带原件
  sha256 双向防漂移锚；配套门 `tests/test_tts_corpus_gate.py`、
  `test_tts_corpus_tools.py`。

## 开关与参数

- `bot_tts_ref_audios`（列表，`路径|文本|语种`）：唯一素材清单入口，值本身是本地
  路径，不入库不进出站；生产 `.env` 当前配了若干条并指向引擎目录内的素材。
- `bot_tts_gptsovits_dir`：相对路径基准；该键在 `path_fields` 的三态语义=绝对透传 /
  相对重定向 / 空串保持。
- `bot_tts_preset` 的 `ref_pool` 维度：预设表里记录「用哪几条」的意图，真实清单仍以
  `bot_tts_ref_audios` 为准。
- 基线册 `scripts/tts_voice_baseline.json` 由人工在确认换音色后更新（`--write` 型
  重录），它属于生成物哈希面，改引擎目录或改本册都要过
  `tests/verify_hashes.py --check`。
- 硬约束（引擎侧，改不了）：参考音频时长必须落在引擎允许区间（区间以引擎契约为准）。越界是 400，真原因在错误体
  `Exception` 字段里，用户侧看到「还差一段合规时长的干声」；这类确定性拒绝不进
  退避窗，否则坏素材会让全员周期性吃「服务没在跑」。

## 失败时看到什么

- 一条可用素材都没有：`还没有给我配参考音频。请在 BOT_TTS_REF_AUDIOS 里填一条
  「音频路径|这段音频说的话」……`（已配置但文件都找不到时换成「路径找不到，检查
  相对路径基准」那条），审计标签 `tts_no_ref_audio`，不重试。
- 素材越界：400 原文归因进 `tts_service_rejected`，用户看到时长提示那条。
- 音色被引擎静默换掉（权重缺失回退底模并写回 yaml）：运行时**没有任何信号**——这是
  引擎侧行为，bot 只能在重启前体检时抓现行，所以守望项排在启动路径上而不是请求路径上。
- 参考音频内容校对不足（`.env` 标注文本与音频实际说的话不一致）：语料对齐门以
  `xfail(strict)` 钉住现状，不会伪装成已修好；根治要引擎目录授权。

## 测试与验收

`tests/test_tts.py`（素材解析与路径三态）、`test_tts_cache_identity.py`（ref 指纹进键）、
`test_tts_identity_watch.py`（守望项五类判据 + SKIP 不假红 + 基线册锚）、
`test_tts_corpus_gate.py`、`test_tts_corpus_tools.py`。真机：
`python scripts/pre_restart_check.py`（体检含音色项）、重启后按
`docs/acceptance-manual.md` §6.6.11 的「耳听」条目逐条比对素材音色；素材改配后必跑
`python scripts/tts_offline_selfcheck.py`。

已知偏差（P1，本卡如实记）：`domains/chat_reply/capabilities/echo.py` 的语音帮助页
对用户宣称「同一句话不重复合成（同句恒同音色）」，交接材料同口径；但现役两个调用点
在挑参考音频时都没有传确定性随机源（`pick_ref_audio` 的 `rng` 形参只在测试里被使用），
生产走模块级随机选择。同一句话因此在素材多于一条时可能换素材、换缓存键、换 seed，
音色与韵律都会飘。判定「同句恒同」目前只在素材恰好为一条时成立。
