# 守岸人 Bot · GPT-SoVITS 语音适配 —— 完整交接文档
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> 交接时间：2026-09-19 12:5x（GMT+8）  
> 交接方：TTS 席（守岸人会话）  
> 适用读者：接手本任务的任意 AI / 工程师。**本文档自包含**——不需要先去翻项目才能动手。  
> 仓库根：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`  
> 运行时 venv：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv`（**不是**仓库内的 `.venv`，仓库内没有）  
> GPT-SoVITS 引擎根：`C:\Software\GPT-SoVITS-V2Pro`

> **⚠️ 2026-09-20 勘误·现行权威指针（T63 席）**：本文件是 **2026-09-19 的历史交接快照**，不随施工波更新；下文宣称以下列现行权威为准——
> 现行规格=`docs/design/tts-contract-layer.md`；缺陷编号唯一源=`.superpowers/sdd/2026-09-19-unify-audit/report-T29.md`（M-xx/S-xx/U-xx）；波次施工台账=`.superpowers/sdd/2026-09-19-unify-audit/progress.md`；传输层换件（NapCat→SnowLuma）复判决=`report-T46.md`/`report-T55.md`。
> 凡「> 2026-09-20 勘误：」引用块处**以勘误块为准**，原文保留作诚实史痕。
> 关键行为变更速览（防旧口径误用）：①M-09「健康退避」已由死代码接成真闸（T57：30s 常量、窗内快速失败挂 `tts_service_unreachable`、真成功清零；acceptance-manual ⑤ 的旧排障指引等收口席更新）；②M-15 触发词已改「内置∪追加」合并（`b13913d`，`effective_trigger_words()` 唯一入口）；③M-06 产物结构体检闸已落地（`7c566f7`）；④出站侧 SnowLuma 混排原子失败语义见 §3.2 勘误。



---

## 0. 一页速览：现在到哪了

| 阶段                                   | 状态                  | 说明                                        |
| ------------------------------------ | ------------------- | ----------------------------------------- |
| **A. 修 bug**：`_request_tts` 错误体解析顺序  | ✅ **已完成**           | 引擎真原因不再被吞                                 |
| **B. 概率配音新功能**（`should_voice_reply`） | ✅ **已完成**（主体）       | 谓词与门链全在 `tts.py`，功能完整可用                   |
| **B-2. 根 `__init__.py` 谓词短路优化**      | ✅ **已完成**（2026-09-19 晚） | 台账释放信号已出现，两处改动落地 + 4 例新测试，见 §5.1              |
| **C. 参考音频池扩容**                       | ✅ **已完成**           | 8 条落盘 + `.env` 已写入                        |
| **C-2. ASR 文本人工校对**                  | ⚠️ **已校对 2 处，建议复核** | 见 §5.3                                    |
| **C-3. 用户听辨抽样（A~E）**                 | ⏳ **待澜汐回结果**        | 见 §5.4                                    |
| **D. 文档/门禁同步**                       | ✅ **已完成**           | 三份文档 + 机器册三件已 --write                     |
| **D-5. 离线回归**                        | ✅ **定向全绿 / 全量已取回并归因** | 见 §7.2 + 审计文档 §3.F                          |
| **E. 真机验收（QQ 实测）**                   | ⏳ **待做，需澜汐配合**      | 清单已写好：`docs/acceptance-manual.md` §6.6.11 |

**接手第一件事**：跑 §7.1 的三条命令，确认基线是绿的，再动任何代码。

### 本批交接产物清单

| 产物               | 位置                                                              |
| ---------------- | --------------------------------------------------------------- |
| **本文档**（11 节自包含） | `docs/design/tts-handover-20260919.md`                          |
| 占域台账（**动手前必读**）  | `docs/design/v21r2-COORDINATION.md`（75 行，最新在最上面）                |
| 真机验收清单（14 项）     | `docs/acceptance-manual.md` §6.6.11                             |
| 参考音频池（8 条）       | `C:\Software\GPT-SoVITS-V2Pro\refs\shorekeeper_ref_01..08.flac` |
| 全库时长扫描 CSV       | `C:\Software\GPT-SoVITS-V2Pro\refs\corpus_durations.csv`（490 行） |
| ASR 听写 TSV       | `C:\Software\GPT-SoVITS-V2Pro\refs\shorekeeper_refs_asr.tsv`    |
| 听辨清单（待澜汐回）       | `C:\Software\GPT-SoVITS-V2Pro\refs\listening_checklist.md`      |
| 工具脚本 ×5          | `C:\Software\GPT-SoVITS-V2Pro\tools\`（**刻意不进源码树**）              |
| 全量回归日志           | `.tmp-test/full-suite.log`                                      |
| 工作记忆             | `.workbuddy-ai/memory/2026-09-19.md`（§十一 为本批）                   |

---

## 1. 任务缘起与需求

### 1.1 澜汐（用户）的原始需求

> 「要求根据这些（`AGENTS.md` + `DESIGN-SPEC.md`），去做好 GPT-SoVITS 的守岸人 Bot 的语音的适配」

后续追加：

- 提供语料库路径 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\语料库\守岸人`，说「里面的质量都很过关，**可以直接拿 >15s 的那些语录去 tts 新的**」
- 要一份「从头到尾彻底完善好的文档」用于交接
- 三问：3~10s 语料够不够 / NoneBot 怎么把数据传给 GPT 生成音频 / 「参考音频时长未强制校验」有什么用
- 要求用「最惨、最残酷、无情的态度」攻击自己的计划
- 要求「彻底完善的详细计划，别的 AI 看到就知道怎么实施，不需要自己去翻项目」
- 提出**防 AI 互改**需求：有别的 AI 在改后端，要避免两个 AI 互相修改代码
- 裁定 `tts.py` **留 media 域不迁 creation**，要写占域声明 + 给别的 AI 避让提示词

### 1.2 ⚠️ 需求与物理约束的冲突（必读）

澜汐说「**可以直接拿 >15s 的那些语录去 tts 新的**」——**这句与引擎硬约束冲突，不能照做**。

- GPT-SoVITS 的参考音频（prompt audio）**硬性要求 3~10 秒**，见 §2.2。
-
- 正确做法：**从 >15s 的长语录里剪出 3~10 秒的片段**（或直接改用库里本来就落在 3~10 秒的合规音频）。
- 本席实测：全库 490 个文件里有 **291 条**本就合规（3~~10 秒），其中 **118 条**落在 5~~8 秒甜点区——**根本不缺素材**，不需要去剪 >15s 的。

**接手者注意**：如果澜汐再次提出「用 >15s 语录」，要如实告知这个约束，并给出「从合规池直接取」的替代方案，不要硬做。

---

## 2. 硬事实基座（全部实测/读码验证，附证据）

> ⚠️ `AGENTS.md` 明令：不得把静态读码当作「已核实」。下面每条都标了**验证方式**。

### 2.1 引擎服务形态

| 事实         | 值                                                                                                                                                                                      | 证据                                                                      |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 引擎 HTTP 服务 | `api_v2.py`，FastAPI，默认 `127.0.0.1:9880`                                                                                                                                                | 引擎目录根                                                                   |
| 合成端点       | `POST /tts`                                                                                                                                                                            | `api_v2.py`                                                             |
| 请求体键名      | `text` / `text_lang` / `ref_audio_path` / `prompt_text` / `prompt_lang` / `top_k` / `top_p` / `temperature` / `text_split_method` / `speed_factor` / `media_type` / `streaming_mode` 等 | 已由 `tests/test_tts.py::test_request_payload_matches_api_v2_contract` 锁死 |
| 错误体格式      | `{"message": "tts failed", "Exception": "<真原因>"}`                                                                                                                                      | `api_v2.py:445`                                                         |
| 启动命令       | `cd C:\Software\GPT-SoVITS-V2Pro && runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880`                                                                                                 | `.env` 注释                                                               |

> 2026-09-20 勘误：上行「启动命令」是历史快照，**勿照此裸敲**——错误 CWD 裸跑会触发 M-12（权重静默回退底模 + 引擎 `save_configs` 把底模路径写回 yaml 永久化：此后永远「能出声但音色不是守岸人」，日志零异常）。现行运维口径=安全脚本唯一化（U-17=C：引擎生命周期=人工脚本+只读探针+告警，不代启动）：引擎根 `start-shorekeeper.ps1`（钉 CWD，T12 实证挡坑）或 `启动守岸人.bat`；bot 侧守护=T60「音色守望者」（在建：yaml 语义断言+sha256 基线 json+`scripts/pre_restart_check.py` 第 10 项挂点）。详见 §5.5 勘误。

**关键**：错误体里 `message` 是**固定摘要**（恒为 `tts failed`），**真原因在 `Exception` 里**。这是 §4.1 那个 bug 的根源。

### 2.2 参考音频硬约束（3~10 秒，无配置可放宽）

- `GPT_SoVITS/TTS_infer_pack/TTS.py:809-817` → `_set_prompt_semantic()`：先 `librosa.load(ref_wav_path, sr=16000)` 重采样到 16kHz，然后
  ```python
  if wav16k.shape[0] > 160000 or wav16k.shape[0] < 48000:
      raise OSError("参考音频在3~10秒范围外，请更换！")
  ```
  → 即 **48000 ≤ 采样点数 ≤ 160000**（16kHz 下 = 3.0s ~ 10.0s）
- `TTS.py:1132-1138` → **无条件**调用该校验，没有任何配置能绕过。
- 结论：**>10 秒一律被拒**。本地预检**不必要**（引擎已经拦，且修完 bug 后错误信息能透传），见 §4.3。

> 2026-09-20 勘误：上句「本地预检不必要/服务端透传足够」只对 **3~10s 越界** 这一维成立，推不出「bot 侧零质检安全」。缺陷台账（report-T29）后来记了两维：**M-06**（引擎 200+非音频字节零质检即写盘入缓存=毒缓存，进程存活期复放）——已落地产物结构体检闸（`7c566f7`：`_inspect_wav_bytes` 在 `synthesize` 落盘前唯一写入口判 RIFF/头/帧数结构，不过=`tts_bad_audio` 不可重试失败降级**且不入缓存**；只判结构不判时长，M-37 时长/体积维度仍留真机未结面 U-02）；**M-07**（引擎推理期异常回 200+≈1 秒静音 wav，bot 当成功落盘发出）——bot 侧静音能量闸归 T61 施工（**在飞未落地**）。现行权威规格=`docs/design/tts-contract-layer.md`。

### 2.3 权重加载的隐性失效点

- `TTS.py:318`：`self.configs = configs_.get("custom", configs_["v2"])` → 读守岸人自定义权重
- `TTS.py:342-353`：若权重路径**不存在**，**静默回退到预训练底模**（不报错！）
- ⚠️ 这是隐性失效点：听起来"能出声"但音色不是守岸人。真机验收必须**听音辨音色**，不能只看"有没有声音"。

### 2.4 全库语料时长实测（490 文件）

扫描器：`C:\Software\GPT-SoVITS-V2Pro\tools\scan_durations.py`（6 线程并行 ffprobe，输出 `refs/corpus_durations.csv`）

| 前缀                | 总数  | 合规 3~10s | 中位    | 最长     | >15s   |
| ----------------- | --- | -------- | ----- | ------ | ------ |
| `heihaian_main`   | 299 | **204**  | 4.31s | 14.44s | 0      |
| `角色包_人声`（数字 ID）   | 68  | 7        | 1.64s | 36.95s | **20** |
| `main_linaxita`   | 36  | 21       | 4.97s | 12.51s | 0      |
| `main_honami`     | 35  | **30**   | 5.14s | 11.48s | 0      |
| `main_lahairoi`   | 29  | 14       | 6.18s | 13.68s | 0      |
| `zuoyequnxing`    | 17  | 12       | 5.91s | 15.40s | 1      |
| `shixifeidu_main` | 6   | 3        | 5.83s | 13.99s | 0      |

- **全库合规（3~10s）= 291 条**
- **5~8s 甜点区 = 118 条**（与 `.env` 原注释「118」精确吻合，可作交叉验证）
- `main_honami_*` 前缀 = **守岸人本人台词**（honami = 守岸人日文名）

**结论：素材充足，不存在「3~10s 语料不够」的问题。**

### 2.5 运行环境依赖实测

| 包                                     | 状态                                                |
| ------------------------------------- | ------------------------------------------------- |
| `httpx`                               | **已装 0.28.1**，但 `pyproject.toml` 原先**未声明** → 本批已补 |
| `pydantic`                            | 2.13.4                                            |
| `numpy`                               | 2.5.2                                             |
| `soundfile` / `mutagen` / `audioread` | ❌ **全部没有** → 本地读音频时长不可行                           |

---

## 3. 系统架构与数据链路


### 3.1 两个入口，一条出站链路

```
【入口 1：命令式合成】
QQ 用户发「说 今天的潮汐很安静」
   → 路由 matcher（is_tts_command / tts_match）
   → build_tts_capability(config) 返回的 capability(message, decision)
   → extract_tts_text() 剥触发词取正文
   → clean_for_speech() 清洗（去代码块/链接/markdown/列表前缀，按句末截断）
   → pick_ref_audio() 从 BOT_TTS_REF_AUDIOS 随机挑一条
   → synthesize() → _request_tts() 打 POST /tts
   → 落盘 data/tts_output/<sha256>.wav
   → CapabilityResult(audio=[{"file": ...}], title="", body="")

【入口 2：对话自动配音（新功能所在）】
人格回复生成完毕，得到 CapabilityResult(capability_id="bot.chat", body=<正文>)
   → __init__.py 的 _attach_voice_reply() 包装层
   → await asyncio.to_thread(maybe_attach_voice, message, result, config=config)
   → should_voice_reply(config, message, result)   ← ★ 本批新增的完整门链谓词
        ├─ bot_tts_enabled
        ├─ bot_tts_auto_reply_enabled
        ├─ result.audio 为空
        ├─ result.capability_id == "bot.chat"
        ├─ auto_reply_scope_allows()（private/group/all）
        └─ 概率门（确定性哈希）或 bot_tts_auto_reply_always 旁路
   → clean_for_speech(result.body or result.summary)
   → pick_ref_audio() → synthesize()
   → result.model_copy(update={"audio": [...], "audit_tags": [... "tts","auto_reply"]})

【共用出站链路（本批零改动）】
CapabilityResult.audio
   → domains/render/renderer.py:210-215  转成 {"type": "record"}
   → SendQueue
   → sender/onebot.py:279-284
   → QQ 语音条
```

### 3.2 核心设计哲学：fail-open

**TTS 失败绝不抛异常、绝不阻断出站**（与 `randpic` 同哲学）。

- 服务未启动 / 超时 / 非 200 / 空音频 / 落盘失败 → 一律返回**守岸人口吻的降级文案**
- 自动配音路径任何失败 → **原样返回 result**（配音是增益，文字回复绝不能受影响）
- `maybe_attach_voice` 整个函数体包在 `try/except Exception` 里兜底

> 2026-09-20 勘误：上两条「fail-open/文字绝不能受影响」只对 **bot 侧合成阶段** 成立（合成失败→降级文案/原样返回，至今未变），**对投递阶段为假**——传输件换 SnowLuma 后已复判决（report-T46/T55）：`record` 段任一环节失败 ⇒ **text+record 整条混排消息一字不发**、API 明确回 failed（SnowLuma `buildSendElems` 循环零 try/catch，无平台侧「降级只发文字」路径）；NapCat 时代「段被静默摘除、文字独活、谎报 SENT」机制不复存在，但毒语音场景**文字同沉**。用户已裁 **U-29=A 案**：保 mixed 一条消息+段级记账防盲重投，不拆条。兜底与施工：W1 兜底基座=worker `_send_media_text_fallback_once`（`worker.py:622-665` 已存在，当前仅第 3 轮烧完才触发）；A 案最小改造面+T46-N1 retcode 白名单扩面（1400 先行）归 **Wave H**（已授权未开工，T65 先遣件备料中；**后记（T102 微同步 2026-09-20）**：Wave H 段级记账/退码白名单/W1 兜底已落库（194a2ca，T78），本句「未开工」状态语已被超越）【**2026-09-20 CATALOG-FIX 就地更正为四态口径**：①T46-N1 retcode 白名单扩面＝**已入库**（真身 `plugins/bot_unified_runtime/domains/transport/sender/onebot.py:162 _is_final_failure_retcode`、判定式 `:176`，含 `100` 与 `1400`；`git status --porcelain` 该件干净＝HEAD 即此内容）；②**生效待重启**——本仓铁律「改代码必须重启 bot 才生效」，在岗进程是否已吃进本笔**不写死在文档里**，判据＝比对进程创建时刻与该笔提交时刻（复跑 `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`）；③Wave H 段级记账/W1 兜底＝**已落库 194a2ca**、同样待重启核对；④A 案剩余改造面＝**未落码**（在飞）。旧「已授权未开工」四字自本行起作废，只按「已落码／已入库／生效待重启／未落码」四态书写。】；`result_unknown`（超时/断连）**绝不**触发文本补发（`worker.py:581-588` 安全前提）。缺陷编号 M-04/M-63。

### 3.3 域归属裁决（重要，别搬错地方）

- `tts.py` 真身位置：**`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`**
- 澜汐已拍板：**留 media 域，不迁 `creation` 域**
- 依据链：
  1. 方案书 §10 W-PA2「荐留 media 案」
  2. `domains/creation/__init__.py` 第 4-5 行自述：「本包是 v21r2-reorg-plan.md §9.1 **预留态第 20 域**：**现载体 capabilities/tts.py 留 media 域原映射不动（归属裁决 §10 W-PA2）**；绘图零载体。」
  3. `creation` 域是 **dormant 空壳**：8 个文件全是 `__init__.py` + `contracts.py`，`default_enabled=False`、`gate_state="dormant"`，**零行实现代码**
- ⚠️ **不要**把 `tts.py` 搬去 `creation`。

---

## 4. 已完成改动（逐文件、逐函数、逐变量）


### 4.1 【阶段 A】修 `_request_tts` 错误体解析顺序

**文件**：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`  
**位置**：`_request_tts()`（现 272 行起），非 200 分支（现 320-341 行）

**改前（有 bug）**：

```python
if response.status_code != 200:
    _last_failure_at = time.monotonic()
    detail = ""
    try:
        detail = str(response.json().get("message") or response.json().get("Exception") or "")
    except Exception:
        detail = response.text[:200]
    _last_failure_reason = f"服务返回 {response.status_code}：{detail[:160]}"
```

**三个毛病**：

1. **优先读 `message`**——而 `message` 恒为固定摘要 `"tts failed"`，真原因在 `Exception` 里 → 真原因被吞
2. **`response.json()` 被调了两次**（`.get("message")` 一次、`.get("Exception")` 一次）
3. 非 dict 的 JSON（如裸字符串）会让 `.get()` 抛 `AttributeError`，被 except 兜住后丢失全部信息

**改后（现 320-341 行）**：

```python
if response.status_code != 200:
    _last_failure_at = time.monotonic()
    # 错误体形如 {"message": "tts failed", "Exception": "<真原因>"}
    # （api_v2.py 的兜底包装）：真原因在 Exception 里，message 只是固定摘要，
    # 故必须先取 Exception，否则 3~10 秒越界这类可读原因会被吞成 "tts failed"，
    # 下游 _degrade 的「参考音频」分支永远命不中。
    try:
        error_body: Any = response.json()
    except Exception:  # noqa: BLE001 - 错误体非 JSON 时退回纯文本。
        error_body = None
    if isinstance(error_body, dict):
        detail = str(error_body.get("Exception") or error_body.get("message") or "")
    elif isinstance(error_body, str):
        detail = error_body[:200]
    else:
        detail = (response.text or "")[:200]
    _last_failure_reason = f"服务返回 {response.status_code}：{detail[:160]}"
    logger.info("tts request rejected: %s %s", response.status_code, detail)
    return None
```

**连带效应（这是修这个 bug 的真正价值）**：  
`_degrade(reason)`（现 400 行）里有这段：

```python
if "3~10秒" in reason or "参考音频" in reason:
    return "还差一段合适的参考音频：3 到 10 秒的干声，我才能借到自己的音色。"
```

**改前**：`reason` 永远是 `"服务返回 400：tts failed"` → 这个分支是**死代码**，用户只会看到最泛化的「这次没能发出声音……」  
**改后**：`reason` 变成 `"服务返回 400：参考音频在3~10秒范围外，请更换！"` → 分支转活，用户得到**可操作的提示**。

**回归锁**：`tests/test_tts.py::test_request_tts_error_body_prefers_exception_over_message`（518 行）——同时断言解析顺序与端到端降级映射。

---


### 4.2 【阶段 B】新增对话概率配音

#### 4.2.1 新配置键（`plugins/bot_unified_runtime/config.py`）

**位置**：第 324-325 行（原 317-319 行的 `bot_tts_auto_reply_*` 三键之后）

```python
    # 配音概率门：每条符合条件的回复按此概率决定是否配音（默认 5%）。
    # 用确定性哈希实现（seed = session_id:message_id），同一条消息结果恒定，
    # 可复现可审计；置 1.0 等价于全量配音。always 置真则直接跳过概率门，
    # 供调试/真机验收时逐条听音。
    bot_tts_auto_reply_probability: float = 0.05
    bot_tts_auto_reply_always: bool = False
```

- 环境变量名：`BOT_TTS_AUTO_REPLY_PROBABILITY` / `BOT_TTS_AUTO_REPLY_ALWAYS`
- 无需写 `field_validator`：`Config.model_validate(translate_env_keys(...))` 由 pydantic 自动把 `"0.05"`→float、`"true"`→bool
- 字段计数副作用：`docs/auto-facts.md` 的 `config.py bot_* 字段数` **610 → 612**（已由 `doc_sync --write` 重生成）

#### 4.2.2 新常量（`tts.py` 第 77 行）

```python
# 对话自动配音的默认触发概率（5%）：常态下只有二十分之一的回复会带语音，
# 避免刷屏与合成排队；BOT_TTS_AUTO_REPLY_ALWAYS=true 可跳过概率门。
_DEFAULT_AUTO_REPLY_PROBABILITY = 0.05
```

#### 4.2.3 新函数 1：`_resolve_probability(value)`（`tts.py` 第 520 行）

```python
def _resolve_probability(value: Any) -> float:
    """把概率配置解析成 float；失败按 0（不配音）处理。

    与 ``policy/gate.py`` 的 ``_resolve_probability`` 同口径，支持实时
    callable——概率若由心情之类的动态量参与，必须在每次抽签时求值，
    不能在装配期冻成常量。
    """
    if value is None:
        return 0.0
    if callable(value):
        try:
            return float(value())
        except Exception:  # noqa: BLE001 - 求值失败按不配音处理。
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

**为什么支持 callable**：项目惯例——概率若由「心情」等动态量参与，必须**每次抽签时求值**，不能在装配期冻成常量，否则「心情低落时少配音」永远不会生效。参照 `policy/gate.py:71-87`。

#### 4.2.4 新函数 2：`should_voice_reply(config, message, result) -> bool`（`tts.py` 第 540 行）

**这是本批的核心新增**。纯谓词、无副作用、可直测。

```python
def should_voice_reply(
    config: Any,
    message: IncomingMessage,
    result: CapabilityResult,
) -> bool:
    if not bool(getattr(config, "bot_tts_enabled", False)):
        return False
    if not bool(getattr(config, "bot_tts_auto_reply_enabled", False)):
        return False
    if result.audio:
        return False
    if str(getattr(result, "capability_id", "")) != "bot.chat":
        return False
    if not auto_reply_scope_allows(config, message):
        return False
    if bool(getattr(config, "bot_tts_auto_reply_always", False)):
        return True
    probability = _resolve_probability(
        getattr(config, "bot_tts_auto_reply_probability", _DEFAULT_AUTO_REPLY_PROBABILITY)
    )
    if probability <= 0:
        return False
    if probability >= 1:
        return True
    seed = (
        f"{getattr(message, 'session_id', '') or ''}:"
        f"{getattr(message, 'message_id', '') or getattr(message, 'request_id', '') or ''}"
    )
    bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 10000
    return bucket < probability * 10000
```

**门链顺序（六道）**：

1. `bot_tts_enabled` — 总开关
2. `bot_tts_auto_reply_enabled` — 自动配音开关
3. `result.audio` 非空 → 已有音频，不叠加
4. `result.capability_id == "bot.chat"` → 只管人格对话，不碰命令式能力
5. `auto_reply_scope_allows()` — 会话范围 private/group/all
6. **概率门**（`always=True` 时旁路）

#### 4.2.5 ★ 算法：确定性哈希概率门（项目铁律）

**绝不使用 `random.random()`**。项目所有概率门一律用确定性哈希：

```python
bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 10000
return bucket < probability * 10000
```

- `seed = f"{session_id}:{message_id or request_id}"`
- **同一条消息永远得到同一结果** → 可复现、可审计、**测试不会 flaky**
- 规范实现：`domains/chat_reply/policy/gate.py:106-117` 的 `deterministic_group_reply_lottery(seed, probability)`
- 同款实现另有：`domains/chat_reply/capabilities/poke.py:30-39`、`domains/meme/reactions/engine.py:632-638`
- 调用点参照：`policy/gate.py:346-352`

⚠️ **为什么不跨域 import `gate.py`**：20 域重组后 `media` 域 import `chat_reply/policy` 是分层污染。项目既有实践就是各域自带一份（`poke.py`、`engine.py` 都是自己写）。本席在 `media` 域内自带一份并注释指向规范实现。

⚠️ **如果接手者改用 `random`**：`tests/test_tts.py::test_maybe_attach_voice_attaches_audio` 等会变成 **5% 通过率的 flaky 测试**，且审计不可复现。**这是硬红线。**

#### 4.2.6 改：`maybe_attach_voice` 门链收为一次谓词调用（`tts.py` 第 583 行）

**改前**（六道 if 散在函数体里）：

```python
    if not bool(getattr(config, "bot_tts_enabled", False)):
        return result
    if not bool(getattr(config, "bot_tts_auto_reply_enabled", False)):
        return result
    if result.audio:
        return result
    if str(getattr(result, "capability_id", "")) != "bot.chat":
        return result
    if not auto_reply_scope_allows(config, message):
        return result
    try:
        ...
```

**改后**（第 595 行）：

```python
    if not should_voice_reply(config, message, result):
        return result
    try:
        ...
```

函数体其余部分（`clean_for_speech` → `pick_ref_audio` → `synthesize` → `model_copy` → `except` 兜底）**一字未动**。

**收益**：门链从"散落的六道 if"变成"一个可单测的纯谓词"，且 `__init__.py` 也能直接复用（见 §5.1）。

#### 4.2.7 `auto_reply_scope_allows`（未改，但要知道）

`tts.py` 第 509 行：

```python
def auto_reply_scope_allows(config: Any, message: IncomingMessage) -> bool:
    """对话自动配音的会话范围判定：private / group / all。"""
    scope = str(getattr(config, "bot_tts_auto_reply_scope", "private") or "private").strip().lower()
    if scope == "all":
        return True
    is_group = bool(str(getattr(message, "group_id", "") or "").strip())
    if scope == "group":
        return is_group
    return not is_group
```

---

### 4.3 【阶段 B】删除死常量

**文件**：`tts.py`，原第 57-59 行

**删掉**：

```python
# 参考音频时长合规区间（服务端硬卡，这里只做本地预检以便给出可读提示）。
_REF_MIN_SECONDS = 3.0
_REF_MAX_SECONDS = 10.0
```

**替换为**：

```python
# 参考音频时长合规区间（3~10 秒）由服务端硬卡（TTS.py 的 _set_prompt_semantic），
# 本地不做重复预检：ChatBot 运行环境没有 soundfile/mutagen，读不了时长；
# 越界时服务端会在错误体 Exception 里给出可读原因，经 _request_tts 透传到
# _degrade 的「参考音频」分支，用户侧提示已经足够。
```

**为什么删**：

1. 全仓无任何引用（死代码）
2. 原注释说「这里只做本地预检」——但**预检从来没实现过**（`pick_ref_audio` 只校验文件存在）
3. 想实现也做不到：运行环境**没有 `soundfile`/`mutagen`/`audioread`**，纯标准库读时长需要手写 FLAC STREAMINFO / WAV `wave` 解析，成本高
4. **修完 §4.1 的 bug 后，引擎的错误信息已能正确透传**，本地预检纯属冗余

> 2026-09-20 勘误：本节「删本地预检」对 3~10s 维度的理据仍成立，但第 4 条「服务端透传已足够」的结论被 M-06/M-07 推翻了一半（200+毒字节/200+静音 wav 都是「成功形态」，错误体透传帮不上忙）——bot 侧体检闸现状见 §2.2 勘误。

---

### 4.4 【阶段 D】`echo.py` 帮助条目同步

**文件**：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py`  
**注意**：该文件在 `tests/verify_hashes.py` 的 `TRACKED_FILES` 里——**改它必须重录哈希**（见 §7.4）

三处改动：

**(1) `lines` 列表新增一条（第 2267 行）**——紧跟原「对话自动配音」那条：

```python
'配音概率：默认只有 5% 的回复会带语音（BOT_TTS_AUTO_REPLY_PROBABILITY）；BOT_TTS_AUTO_REPLY_ALWAYS=true 可临时改成条条都配，方便验收听音。',
```

**(2) `detail` 的【权限与效果】段补一句**（原「同一句话不重复合成。」之后）：

```python
'  对话自动配音按概率触发（默认 5%），判定用确定性哈希——同一条消息结果\n'
'  恒定，不会一会儿配一会儿不配。\n'
```

**(3) `_HELP_ENTRY_META["语音"]["config_vars"]` 18 键 → 20 键**（第 3100-3101 行）：

```python
            "BOT_TTS_AUTO_REPLY_PROBABILITY",
            "BOT_TTS_AUTO_REPLY_ALWAYS",
```

**门禁关系**：

- `tests/test_documentation_consistency.py` 只校验「帮助里引用的键**存在**于 config.py」，**不要求**全部列出 → 加这两键是**文档完整性**要求，非门禁强制
- 但 `docs/command-catalog.md` 是**从 `echo.py` 的注册表重生成**的 → 改 `echo.py` 必须跑 `command_catalog.py --write`（见 §7.3）

---

### 4.5 【阶段 D】三份文档 + 机器册

| 文件                                  | 改动                                                                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/config-catalog-full.md`       | TTS 段（原 823 行 `_tts_auto_reply_max_chars` 之后）新增 2 行：`_tts_auto_reply_probability`、`_tts_auto_reply_always`。**注意键名形态是 `_tts_*`（省略 `BOT_` 前缀）**，门禁 `_normalize_catalog_key()` 会补回 `bot_` |
| `.env.example`                      | ASR 块之后**新增完整 TTS 块（20 键）**。此前 `.env.example` 里**一个 `BOT_TTS_*` 都没有**（无自动化门禁，纯人工规范缺口）                                                                                                  |
| `docs/acceptance-manual.md`         | 新增 **§6.6.11 语音合成（bot.tts）验收**（14 项验收表 + 前置条件 + 离线复核手段 + 收尾纪律）                                                                                                                         |
| `pyproject.toml`                    | dependencies 补 `"httpx>=0.28.1"`（`tts.py` 直接 import 它，此前只在 venv 里存在，换环境会静默降级成「httpx 不可用」）                                                                                              |
| `docs/auto-facts.md`                | `doc_sync.py --write` 重生成，字段数 610→612                                                                                                                                                  |
| `docs/command-catalog.md`           | `command_catalog.py --write` 重生成                                                                                                                                                       |
| `tests/render_hashes.json`          | `verify_hashes.py --write` 重录（仅 `echo.py` 一项漂移）                                                                                                                                        |
| `docs/design/v21r2-COORDINATION.md` | 顶部追加本席**完成**条目（75 行）                                                                                                                                                                   |

---


### 4.6 【阶段 C】参考音频池扩容

**落盘位置**：`C:\Software\GPT-SoVITS-V2Pro\refs\`

| 文件                        | 时长    | 语气定位     | 源文件                            |
| ------------------------- | ----- | -------- | ------------------------------ |
| `shorekeeper_ref_01.flac` | 8.51s | 长句陈述（原有） | —                              |
| `shorekeeper_ref_02.flac` | 4.48s | 关切疑问     | `main_honami_2_8_2_65_1.flac`  |
| `shorekeeper_ref_03.flac` | 5.33s | 歉意·无奈    | `main_honami_2_8_2_51_8.flac`  |
| `shorekeeper_ref_04.flac` | 6.64s | 正式承诺     | `main_honami_2_8_2_70_19.flac` |
| `shorekeeper_ref_05.flac` | 9.53s | 长句解释     | `main_honami_2_8_2_65_12.flac` |
| `shorekeeper_ref_06.flac` | 3.01s | 短句疑问     | `main_honami_2_8_2_39_36.flac` |
| `shorekeeper_ref_07.flac` | 6.93s | 转折·警告    | `main_honami_2_8_2_65_18.flac` |
| `shorekeeper_ref_08.flac` | 3.84s | 中短陈述     | `main_honami_2_8_2_73_4.flac`  |

全部 **48000Hz / 单声道 / 3~10 秒**（合规）。

**工具链**（全部在 `C:\Software\GPT-SoVITS-V2Pro\tools\`，**刻意不进 ChatBot 源码树**，避免污染）：

- `scan_durations.py` — 全库时长扫描（6 线程 ffprobe）→ `refs/corpus_durations.csv`
- `make_listening_checklist.py` — 生成听辨清单 → `refs/listening_checklist.md`
- `pick_refs.py` — 按语气多样性从 `main_honami` 合规池复制 7 条 → `refs/shorekeeper_ref_02..08.flac`
- `asr/transcribe_refs.py` — 离线 ASR 听写 → `refs/shorekeeper_refs_asr.tsv`

**`.env` 改动**（gitignored，**改前已备份为 `.env.bak-20260919-tts-probability`**）：

- `BOT_TTS_REF_AUDIOS` 从 1 条扩到 8 条（含修正后的 ASR 文本）
- 新增 `BOT_TTS_AUTO_REPLY_ENABLED=false` / `SCOPE=private` / `MAX_CHARS=120` / `PROBABILITY=0.05` / `ALWAYS=false`
- ⚠️ **自动配音默认仍是关的**——这是有意的。功能已完备，何时打开由澜汐决定。
- 实测校验通过：8 条全部解析成功、文件全部存在、抽签正常。

---

## 5. 未完成事项（接手者要做的）


### 5.1 ✅ 第二批：根 `__init__.py` 谓词短路（**已完成 · 2026-09-19 晚**）

**文件**：`plugins/bot_unified_runtime/__init__.py`（359288 字节）  
**当前状态**：该文件**仍被别的 AI 席位（S0-ROOT 席）独占写**。本席**全程未触碰**。  
**该文件 mtime 停在 2026-09-19 02:08**，此后未再变动。

> 2026-09-20 勘误：以上两行是写作时点的过期快照（M-25 族）——本节下方「已落地的两处改动」与 §0 表为真态：第二批**已落地**（谓词短路+import 补 `should_voice_reply`+4 例测试）。占域/批次状态唯一真相源=协调台账（`.superpowers/sdd/2026-09-19-unify-audit/progress.md`），本文件不再自抄「禁动/未做」；据此重做或误判独占都是踩 M-25 的坑。

**释放信号已出现**：`docs/design/v21r2-COORDINATION.md` 有独立一条「**根 `__init__.py` 已释放（S0-ROOT-c 交付）**」——该席四处直连收编全部落地、新测试 27 例全绿、家族合跑 195 passed，并明写「**TTS 席第二批可开工**」。本席随即开工（该文件当时 mtime 已更新到 13:09:58）。

**已落地的两处改动**：

**(1) 第 111 行 import 补符号**：

```python
# 改前
from .domains.media.capabilities.tts import build_tts_capability, maybe_attach_voice
# 改后
from .domains.media.capabilities.tts import (
    build_tts_capability,
    maybe_attach_voice,
    should_voice_reply,
)
```

**(2) 第 342-353 行的 `_attach_voice_reply()` 加谓词短路**：

```python
async def _attach_voice_reply(inner, *, config):
    # 现有关卡（约 349 行）：
    #     getattr(config, "bot_tts_auto_reply_enabled", False)
    # 改为：先跑完整谓词，未命中就不付线程调度成本
    if not should_voice_reply(config, message, result):
        return result
    return await asyncio.to_thread(
        maybe_attach_voice, message, result, config=config
    )
```

**改前只挡两个开关**（`bot_tts_enabled` / `bot_tts_auto_reply_enabled`），意味着**概率门落空的约 95% 消息仍要白付一次 `asyncio.to_thread` 投递**；改后谓词判否即返回。

**为什么出站行为逐字节不变**：`should_voice_reply` 是**确定性纯谓词**（哈希种子只依赖 `session_id` + `message_id`/`request_id`，无副作用），`maybe_attach_voice` 内部会再判一次且结论必然相同。所以这处只是省掉一次线程投递。由 `test_attach_voice_reply_matches_maybe_attach_voice_output` 逐字段锁住。

**新增 4 例测试**（`tests/test_tts.py`，52 → 56 例）：

| 用例 | 锁住什么 |
|---|---|
| `test_attach_voice_reply_skips_thread_when_predicate_false` | 概率门落空时**不得**投递线程池（第二批的核心收益） |
| `test_attach_voice_reply_skips_thread_when_switch_off` | 开关关闭时同样不投递（原行为等价保留） |
| `test_attach_voice_reply_dispatches_thread_when_predicate_true` | 谓词判真必须投递；无参考音频时 fail-open 不抛 |
| `test_attach_voice_reply_matches_maybe_attach_voice_output` | 与直调 `maybe_attach_voice` 输出逐字段一致 |

**实跑证据**：`test_tts.py` **56 passed**；TTS 双文件 **71 passed**；邻域 16 文件 **818 passed**；运行时装配 10 文件 **96 passed**（另 1 项他席断点，见 §5.2）；ruff 本席三文件全绿；mypy 本席文件零 error。

**⚠️ 顺带修掉第一批的一处 mypy 缺陷**：`tts.py` 的错误体解析里我复用了变量名 `payload`，与同函数上方的请求体 `payload: dict[str, Any]` 撞名，mypy 报 `no-redef` + `assignment`（None 与 dict 不兼容）**两条 error**。已改名 `error_body`，两处 error 清零。**这说明第一批交接时写的「mypy 无新增错误」是不准确的**——现已更正（详见审计文档 §3.C）。

**⚠️ 为什么这是「可选优化」而非「必需」**：  
`should_voice_reply` 的**全部六道门**已经在 `maybe_attach_voice` 内部（§4.2.6），功能**完全正确**。`__init__.py` 这处只是**省下 95% 的线程池调度**（概率未命中时不再 `to_thread`）。**不做也不影响任何功能。**

**释放条件**：等 `docs/design/v21r2-COORDINATION.md` 里出现「**根 `__init__.py` 已释放（S0-ROOT 交付）**」字样。  
当时的阻塞依据（v21r4-B 主会话更新原文）——**现已被上方的 S0-ROOT-c 释放声明取代，留作记录**：

> 根 `__init__.py` 已由 RWC5-b 席交付释放（其日志终态：旧路径清账归零+781 passed）。但**即刻起该文件由我方 S0-ROOT 席独占写**（S0 四处直连点收编执行）——`_attach_voice_reply` 改动请继续等待，直到本文件出现「根 `__init__.py` 已释放（S0-ROOT 交付）」字样。


### 5.2 ✅ 全量回归测试（**已取回并逐项归因**）

本席**定向回归已全绿**（见 §7.2）。**全量 8537 例**已跑完并落盘：

```
30 failed, 8515 passed, 12 skipped, 3 xfailed, 3 warnings, 4 errors in 1281.71s (0:21:21)
```

⚠️ **但这 30 failed 是首跑口径错误造成的假象**——首跑把 `--basetemp` 指向了仓库内。换成仓库外重跑失败子集，**30 项当场消失**。

```bash
# 日志（含 pytest 摘要 + 末行 EXIT=<code>）
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\.tmp-test\full-suite.log

# 取摘要
tail -20 .tmp-test/full-suite.log
```

接手者应**先读这个日志**；若已过期或想自己跑：

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
BT="C:/Users/LancyCelestia/.workbuddy-ai/tmp/pytest/full"; mkdir -p "$BT"
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
  "../ChatBot_Runtime/venv/Scripts/python.exe" -m pytest tests -q \
  -p no:cacheprovider --basetemp="$BT" \
  --ignore=tests/test_outdomain_fixes_20260911.py
```

⚠️ **`--basetemp` 必须在仓库外**（见 §7.0）。若误指向仓库内的 `.tmp-test/xxx`，会出现约 30 项假失败，**不要据此判定代码有问题**。

⚠️ **已知他席在飞断点（非本席引入）**：  
`tests/test_outdomain_fixes_20260911.py` 收集期报

```
ImportError: cannot import name 'web_search' from 'plugins.bot_unified_runtime.sources'
```

原因：`sources/web_search` 已被 v21r2 重组迁到 `domains/core/search/`，但该测试文件未同步更新。**这是别的席位的在飞工作**，本席未触碰 `sources/**`。接手者可 `--ignore` 跳过，或（若已获授权）修该测试的 import 路径。

⚠️ **全量跑很慢（本席实测约 21 分钟）且必然受他席在飞改动影响**：工作树里有 836 个他席未提交文件，全量红/绿不完全代表本批质量。**判定本批质量请以 §7.1 的四条定向命令为准**——它们只覆盖本批碰过的文件域，不受他席干扰。

**本席实测结论**（仓库外 basetemp，见 §7.0）：全量 8537 例中，与本批相关的失败为 **0**；残留 2 项是他席在飞断点（`test_runtime_feature_gate` 能力注册、`test_webui_http` 统计端点）。逐项归因见 `docs/design/tts-audit-20260919.md` §3.F。

### 5.3 ⚠️ ASR 听写文本人工校对（**已完成 2 处，建议复核**）

**背景**：GPT-SoVITS 的 `prompt_text`（参考文本）会被切成音素喂给 GPT 做前缀。填**准**能提升语气连贯性；填**错**会污染音色。ASR 结果**必须人工校对专有名词**。

**听写结果**（`C:\Software\GPT-SoVITS-V2Pro\refs\shorekeeper_refs_asr.tsv`），**本席已修正 2 处错字**（用 `〔〕` 标出）：

| # | 时长    | 修正后文本                                        | 修正说明                            |
| - | ----- | -------------------------------------------- | ------------------------------- |
| 1 | 8.51s | 目前可以确定学院所在的整个拉海洛地区都被**虚质磁暴**所遮蔽了，和外界的交流已经断绝。 | ASR 听成「虚至此报」→ 按鸣潮设定应为「**虚质磁暴**」 |
| 2 | 4.48s | 频率流失的情况暂时稳定下来了，你有没有感觉不舒服？                    | —                               |
| 3 | 5.34s | 抱歉，我也没想到，他会突然起了胜负心，这还是第一次。                   | —                               |
| 4 | 6.64s | 进入学院需要通过严格的审批程序。在你出发前，我会将相关材料准备好的。           | —                               |
| 5 | 9.53s | 目前最有可能的推论是，这道**裂隙**正连通着拉海洛地区，那也是你丢失的频率去往的地方。 | —                               |
| 6 | 3.01s | 你们在这里等候，我是迟到了吗？                              | —                               |
| 7 | 6.93s | 理论上可以，但这个**裂隙**内部的频率非常紊乱，贸然进入很有可能迷失。         | ASR 听成「力隙」→ 应为「**裂隙**」          |
| 8 | 3.84s | 但刚才我感知到了一个转瞬即逝的特殊频率。                         | —                               |

**为什么必须人工校对**：`main_honami_2_8_2_43_9` 被 ASR 听成「虚至此报」（应为「虚质磁暴」），**证明 ASR 在专有名词上不可信**。

**接手者待办**：把这 8 条与 `.env` 里 `BOT_TTS_REF_AUDIOS` 的文本**逐条对照**（`.env` 已写入修正后文本），并用 `C:\Software\GPT-SoVITS-V2Pro\refs\shorekeeper_refs_asr.tsv` 复核。若有误，改 `.env` 后重启。

### 5.4 ⏳ 用户听辨抽样（**等澜汐回结果**）

`refs/listening_checklist.md` 已生成，含：

- **F 基准**：`shorekeeper_ref_01.flac`（8.51s，已确认是守岸人）
- **A~E 五条**：从 `heihaian_main` 池抽的待听辨样本

**目的**：确认 `heihaian_main` 前缀的 299 个文件（合规 204 条，全库最大池）**是否也是守岸人音色**。

- 若是 → 参考池可从 8 条扩到 200+ 条，音色多样性大幅提升
- 若否 → 继续只用 `main_honami`（30 条合规）

**接手者待办**：澜汐听完回结果后，按结论决定是否扩池。**不要**在她回结果前擅自扩池。

### 5.5 ⏳ 真机验收（**需澜汐配合，在 QQ 上做**）

完整清单已写进 `docs/acceptance-manual.md` **§6.6.11**（14 项）。**前置**：

1. `.env` 已配（本席已配好：`BOT_TTS_ENABLED=true` + 8 条参考音频）
2. **先启动引擎**：
   ```
   cd C:\Software\GPT-SoVITS-V2Pro
   runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880
   ```
3. 重启 bot 主进程（TTS 链路在主进程内）

> 2026-09-20 勘误（M-53）：上面第 2 步的裸命令**别照抄**——M-12 的触发姿势恰是「手敲裸命令跑引擎」（错误 CWD 即把底模权重写回 yaml 永久固化）。安全姿势=引擎根 `start-shorekeeper.ps1`（钉 CWD，T12 实证挡坑）或 `启动守岸人.bat` 唯一入口；bot 侧=T60「音色守望者」**在建**（yaml 语义断言+sha256 基线 json+`scripts/pre_restart_check.py` 第 10 项挂点，落地前重启后必须人工听音辨音色——§2.3 隐性失效点）。「文档禁贴可复制裸命令」的运维口径修正归 U-21。

**重点验收项**（其余见 §6.6.11）：

- **⑥ 参考音频越界错误透传** ← 本批修复点，**必须验**：临时指向一条 >10s 音频，应回「还差一段合适的参考音频：3 到 10 秒的干声…」；若只回最泛化的「这次没能发出声音…」= **§4.1 的 bug 回归了**
- **⑨ 概率门** ← 本批新功能，**必须验**：`ALWAYS=false` + `PROBABILITY=0.05` 时连发 30~40 条，应只有**少数几条**带语音，**绝不是条条都带**
- **⑩ 概率门确定性**：同一条消息结果恒定
- ⚠️ **听音色**：注意 §2.3 的隐性失效点——权重路径不存在会**静默回退预训练底模**，"能出声"不等于"音色对"

> 2026-09-20 勘误：验收清单 §6.6.11 第 **⑤** 项的排障指引当时指向「健康退避」——交接时点那是**死代码**（M-09：`_HEALTH_BACKOFF_SECONDS/_last_failure_at` 写 3 读 0，宣称的「连续失败节流」不存在，验收⑤排障指引指向幻影）。现已由 T57 接成**真闸**（`d6801ab`：30s 常量退避、窗内快速失败挂 `tts_service_unreachable`、真成功清零、快速失败不刷新窗防永久拉黑；闸在 `synthesize` 唯一 HTTP 入口前，缓存命中不受影响）。按旧指引排查「退避不存在」会误判；验收手册文本更新归收口席（本席禁碰 acceptance-manual）。

---

## 6. 并发协议与红线（**动手前必读**）

### 6.1 背景

工作树当时有 **836 个文件未提交**（v21r2 20 域重组施工中），**至少 6 个 AI 席位在并行改代码**。本席的所有目标文件**除 `pyproject.toml` 外全部已在脏集**，且 `domains/` 下全是 `??`（未跟踪），**无法用 `git diff` 区分归属**。

### 6.2 协议：`docs/design/v21r2-COORDINATION.md`

- 该文件是**占域台账**（append-only，**最新在最上面**）
- 格式：`- 日期 席位（描述）：**认领占域施工中**——…占域=…；零触碰=…；完成后续报`
- **有实证**：RW15 席「实读 COORDINATION 见已被 RW12 认领占域，改取下一无冲突波 W14」
- **动手前先读这个文件**，确认目标文件没被别人认领

### 6.3 九条红线

1. **禁 git 写**：所有席位都不得 commit / push / 建分支。改动只留在工作树。
2. **根 `__init__.py` 已释放**（2026-09-19 S0-ROOT-c 交付），本席第二批已落地（§5.1）。**再改该文件前请在台账预告一行**——它仍是多方关注的串行点。
3. **禁动 `domains/creation/**`**：W-PA2 待用户裁定，本席已裁定不取。
4. **概率门禁用 `random`**：必须用确定性哈希（§4.2.5）。
5. **禁改 `tts.py` 的旧垫片路径**：`plugins/bot_unified_runtime/capabilities/tts.py` 是垫片，真身在 `domains/media/capabilities/tts.py`。别席 RET3/RET2B-PREP 已承诺本轮**不退役该垫片**。
6. **序列化点三件，`--write` 前先预告**：`docs/auto-facts.md` / `docs/command-catalog.md` / `tests/render_hashes.json` 是从源码**整册重生成**的，两个 AI 同跑必互相覆盖。本席已按约定**统一跑完一次**（见 §7.3/§7.4）。**再跑前请在台账预告一行。**
7. **`.env` 别人不碰**：他席明确「席位纪律禁触 `.env`」。改前必须备份（惯例：`.env.bak-<日期>-<用途>`）。
8. **源码树零缓存**：`PYTHONDONTWRITEBYTECODE=1`、`PYTHONUTF8=1`（`scripts/dev.ps1` 已设）。
9. **fail-open 不得破坏**：TTS 任何失败都不得抛异常、不得阻断出站。

### 6.4 本席已向对方承诺的边界

在台账顶部（第 2 行）与对方答复（第 2 行）中双方确认：

- 本席**占域**：`tts.py` 真身 / `config.py` 的 `bot_tts_*` 键块 / `echo.py` 的「语音」条目 / `tests/test_tts.py` / 三份文档 TTS 段 / `pyproject.toml` / `.env`
- 本席**零触碰**：`domains/creation/**` + 根 `__init__.py` 全部 + `echo.py`「语音」条目以外全部 + 其余 19 域 + `personas/**` + `bot.py` + `control_plane/**`

> 2026-09-20 勘误（M-25 族）：上条「零触碰根 `__init__.py` 全部」已被第二批落地推翻（见 §5.1 勘误）；本节其余边界是 2026-09-19 写作时点的历史约定。现行占域与施工状态唯一真相源=progress.md 台账，别按本节判定谁可改什么。
- 对方**已确认让出** `command_catalog --write` 与 `render_hashes.json` 写（他们全线禁）
- 对方**全程不碰** `.env`

---

## 7. 命令速查与验收证据

### 7.0 环境准备（每个 shell 都要）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
PY="../ChatBot_Runtime/venv/Scripts/python.exe"

# ★ basetemp 必须在仓库**外**
BT="C:/Users/LancyCelestia/.workbuddy-ai/tmp/pytest/handover"
mkdir -p "$BT"
```

⚠️ **`--basetemp` 千万不能指向仓库内的 `.tmp-test/xxx`**（本席最初就是这么写的，**错了**，后经逐项归因纠正）：
- basetemp 在**仓库内** → 全量 **30 failed + 4 errors**
- basetemp 在**仓库外** → 只剩 **2 failed**（且那 2 项是他席在飞断点，与本批无关）

原因：多个测试的 fixture 断言「临时副本不得落在源树内」（`assert not destination.is_relative_to(REPO_ROOT)`），还有些测试会扫全仓文件、把 `tmp_path` 里的样本当成真实源码。**basetemp 在仓库内 → 这些断言必炸**。
完整归因见 `docs/design/tts-audit-20260919.md` §3.F。

⚠️ **也不要用 `%TEMP%`**：pytest 收尾清理系统临时目录时会 `PermissionError: [WinError 5]`（本机既有环境问题，与代码无关）。用 `.workbuddy-ai/tmp/` 下的路径。

### 7.1 接手第一件事：基线自检（四条）

```bash
BT="C:/Users/LancyCelestia/.workbuddy-ai/tmp/pytest/handover"; mkdir -p "$BT"

# 1) TTS 定向回归
"$PY" -m pytest tests/test_tts.py tests/test_tts_outbound_chain.py -q \
  -p no:cacheprovider --basetemp="$BT/1"                  # 期望 71 passed

# 2) 文档一致性三门
"$PY" -m pytest tests/test_documentation_consistency.py tests/test_doc_sync_gates.py \
  tests/test_help_entries_coverage.py -q -p no:cacheprovider --basetemp="$BT/2"   # 期望 33 passed

# 3) 哈希门（渲染交付物 + drift gate 演练）
"$PY" -m pytest tests/test_cross_validation_gates.py tests/test_verify_hashes_coverage.py \
  -q -p no:cacheprovider --basetemp="$BT/3"               # 期望 6 passed

# 4) 机器册三件复核（只读，不写）
"$PY" scripts/doc_sync.py --check                          # 期望无输出
"$PY" tests/verify_hashes.py --check                       # 期望退出码 0
```

### 7.2 本席实测结果（交接时点）

| 测试集                                                                                                    | 结果                     |
| ------------------------------------------------------------------------------------------------------ | ---------------------- |
| `tests/test_tts.py` + `tests/test_tts_outbound_chain.py`                                               | **71 passed**（第二批新增 4 例后复跑确认；第一批收尾时为 67） |
| `tests/test_documentation_consistency.py` + `test_doc_sync_gates.py` + `test_help_entries_coverage.py` | **33 passed**（复跑确认） |
| `tests/test_cross_validation_gates.py` + `test_verify_hashes_coverage.py`                              | **6 passed**（`echo.py` 重录后） |
| 邻域 16 文件（registry / pinyin / traditional / catalog / route order 等）                               | **818 passed**（第二批后复跑） |
| 运行时装配 10 文件（production_wiring / feature_gate / unified_* 等）                                      | **96 passed**（另 1 项他席断点） |
| `tests/verify_hashes.py --check`                                                                       | **退出码 0**（0 漂移）        |
| `scripts/doc_sync.py --check`                                                                          | **无输出**（已收敛）           |
| 全量 `tests/`（8537 例，`--ignore` 1 个他席断点文件）                                                               | ✅ 已取回并逐项归因，见 §5.2        |

⚠️ **`doc_sync` 的「收敛」是动态的**：本席收尾复跑时 `--check` **又报了一次不一致**——差异是 `测试文件数：422 → 423`，即**期间有他席新增了一个测试文件**。本席再跑一次 `--write` 后收敛。  
**教训**：`doc_sync --check` 变红**未必是自己的问题**，先看 diff 内容（`cp docs/auto-facts.md /tmp/a; doc_sync --write; diff /tmp/a docs/auto-facts.md`）。这台机器上多个 AI 并行，机器册会持续被带偏，**这是协议预期内的，不是缺陷**。

### 7.3 机器册三件：重生成命令（**改完源码才跑**）

```bash
# 改过 echo.py 的帮助条目 → 必须跑
"$PY" scripts/command_catalog.py --write      # → docs/command-catalog.md
"$PY" scripts/doc_sync.py --write             # → docs/auto-facts.md（字段计数等）

# 改过 verify_hashes.py 的 TRACKED_FILES 内文件（echo.py 在内！）→ 必须跑
"$PY" tests/verify_hashes.py --write          # → tests/render_hashes.json
```

**本席执行记录**：

- `command_catalog --write` → 重生成 70400 bytes；随后 `test_catalog_document_matches_registry` 转绿
- `doc_sync --write` → 字段数 610→**612**；`--check` 收敛
- `verify_hashes --write` → **仅 1 项漂移 = 本席改的 `echo.py`**，其余 18 项零漂移（说明渲染收口批那 15 项 DRIFT 已由 INTG 席先行重录完毕，**本席未覆盖他席成果**）；重录后 `--check` 退出码 0

### 7.4 `.env` 校验脚本（已备好，直接跑）

位置：`C:\Software\GPT-SoVITS-V2Pro\tools\verify_chatbot_env.py`（与其余工具同放，**不进 ChatBot 源码树**）。

> 2026-09-20 勘误（T124 同步）：上行「不进 ChatBot 源码树」与本节下方案令里的外部路径均已过时——`verify_chatbot_env.py` 已入仓为 `scripts/verify_chatbot_env.py`（T87，`7e2fe36` M-67 裁决 A：重建为配置面真验证，判据走生产 Config 真身），现行跑校验优先用仓内路径；引擎目录原件保留只读。

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
  "../ChatBot_Runtime/venv/Scripts/python.exe" \
  "C:/Software/GPT-SoVITS-V2Pro/tools/verify_chatbot_env.py"
```

核心是走项目自带装载器，避免手搓解析：

```python
from plugins.bot_unified_runtime.domains.ops.smoke.smoke import load_smoke_config
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    parse_ref_audios, pick_ref_audio,
)
config = load_smoke_config(ROOT / ".env")
parsed = parse_ref_audios(config.bot_tts_ref_audios, base_dir=config.bot_tts_gptsovits_dir)
# 断言：8 条、文件全存在、probability==0.05、always is False
```

⚠️ **不要**直接用 `dotenv_values` + `Config.model_validate`——`.env` 里的 JSON 值（如 `["..."]`）需要先 JSON 解码，否则报 `list_type` 校验错。项目里 `smoke.py` 的 `_json_decode_env_values()` 就是干这个的。

**本席实测输出**：8 条参考音频全部解析成功、文件全部存在、抽签正常、2 个新键生效。

### 7.5 回滚方式

| 目标     | 回滚                                                                            |
| ------ | ----------------------------------------------------------------------------- |
| `.env` | `cp .env.bak-20260919-tts-probability .env`                                   |
| 源码     | 本批**未 commit**，回滚 = 手工逆编辑 §4 列出的文件                                            |
| 参考音频   | 删 `C:\Software\GPT-SoVITS-V2Pro\refs\shorekeeper_ref_02..08.flac`（`_01` 是原有的） |

---

## 8. 陷阱与反模式（本席踩过的坑，别重复）

### 8.1 技术坑

| 坑                            | 现象                                                   | 正解                                                                                      |
| ---------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **bash 传中文路径给 ffprobe**      | `Illegal byte sequence`                              | 用 Python 直接 `os.path.join` 拼路径，别经 shell                                                 |
| **内联 Python 脚本含反引号**         | `unexpected EOF while looking for matching` 反引号          | 先写成文件再执行，别内联                                                                            |
| **`Glob` 在深层目录不稳定**          | 匹配不全                                                 | 深层目录用 `Read` 直读或 `Grep`                                                                 |
| **pytest 系统临时目录**            | `PermissionError: [WinError 5]`                      | **`--basetemp` 必须给仓库外路径**（如 `C:/Users/LancyCelestia/.workbuddy-ai/tmp/pytest/<name>`）。**千万不能**放仓库内 `.tmp-test/`，否则约 30 项假失败（见 §7.0） |
| **`.env` JSON 值直喂 `Config`** | `list_type` 校验错                                      | 先 JSON 解码，或用 `smoke.load_smoke_config()`                                                |
| **`git diff` vs HEAD 会误导**   | 显示 75 行改动，以为是自己造成的                                   | 工作树有 836 个他席未提交文件，`git diff` 是**vs HEAD**，包含所有席位的累积改动。判断自己的改动要看 `git status` + 文件 mtime |

### 8.2 判断错误（本席犯过并被推翻，引以为戒）

| 错误判断                               | 真相                                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 「>10s 参考音频服务端不拦」                   | **错**。`TTS.py:816` 硬拦，`TTS.py:1132` 无条件调用，无配置可放宽                                                               |
| 「`_degrade` 的 `3~10秒` 分支是死代码、只是没用」 | **升级为真 bug**：`api_v2.py:445` 把异常包成 `{"message":"tts failed","Exception":"<真原因>"}`，而 `tts.py:317` 优先读 `message` |
| 「参考池只需 3~6 条」                      | **无依据拍脑袋**。实测全库合规 291 条、甜点区 118 条                                                                              |
| 「把 `.env` 注释当权威事实」                 | 后来实测验证大部分属实（8.51s/48kHz/单声道 ✅、490 文件 ✅、35 条 ✅、118 甜点区 ✅），但**流程错了**——注释不是证据                                     |
| 「概率门用 `random.random()`」           | **被规划代理推翻**。项目惯例是确定性哈希；用随机数会让 `test_maybe_attach_voice_attaches_audio` 变成 5% 通过率的 flaky                        |
| 「交接文档标『已核实』但全是静态读码」                | 违反 `AGENTS.md` 第 5 条。**读码 ≠ 核实**                                                                               |

### 8.3 两处假通过的既有测试（本席已修）

| 测试                                                      | 原问题                                                                                | 修法                              |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------- |
| `test_maybe_attach_voice_swallows_unexpected_exception` | **无参考音频** → `pick_ref_audio()` 返回 None，**根本没走到 `synthesize`**，`_boom` 从未被调用 → 断言恒真 | 补参考音频 + `always=True`，让它真走到合成阶段 |
| `test_maybe_attach_voice_skips_empty_speech`            | 概率门（默认 0.05）先拦下 → 根本没走到 `clean_for_speech` → 断言恒真                                  | 显式 `always=True`                |

**教训**：加概率门时，**所有原本假定「一定会走到某步」的测试都要显式 `always=True`**，否则会静默退化成假通过。本席已给 `attaches_audio` / `survives_failure` / `swallows_unexpected_exception` / `skips_empty_speech` 四例都加了。

---


## 9. 全部配置键参考（TTS 20 键）

| 键                                    | 默认                      | 说明                      |
| ------------------------------------ | ----------------------- | ----------------------- |
| `BOT_TTS_ENABLED`                    | `false`                 | 总开关                     |
| `BOT_TTS_API_URL`                    | `http://127.0.0.1:9880` | 引擎地址                    |
| `BOT_TTS_GPTSOVITS_DIR`              | 空                       | 引擎根目录（相对参考路径的基准）        |
| `BOT_TTS_REF_AUDIOS`                 | `[]`                    | 参考池，每项 `路径\|参考文本\|语种`   |
| `BOT_TTS_TRIGGER_WORDS`              | `[]`                    | 追加触发词                   |
| `BOT_TTS_OUTPUT_DIR`                 | `data/tts_output`       | wav 落盘目录                |
| `BOT_TTS_MAX_CHARS`                  | `200`                   | 命令式合成文本上限               |
| `BOT_TTS_TIMEOUT_SECONDS`            | `60.0`                  | 单次请求超时                  |
| `BOT_TTS_SPEED_FACTOR`               | `0.85`                  | 语速（中文建议 0.8~0.9）        |
| `BOT_TTS_TEMPERATURE`                | `0.9`                   | 采样温度                    |
| `BOT_TTS_TOP_K`                      | `15`                    | 采样参数                    |
| `BOT_TTS_TOP_P`                      | `1.0`                   | 采样参数                    |
| `BOT_TTS_TEXT_LANG`                  | `zh`                    | 合成文本语种                  |
| `BOT_TTS_TEXT_SPLIT_METHOD`          | `cut5`                  | 切句方式                    |
| `BOT_TTS_CACHE_ENABLED`              | `true`                  | sha256 结果缓存（LRU 512）    |
| `BOT_TTS_AUTO_REPLY_ENABLED`         | `false`                 | 对话自动配音开关                |
| `BOT_TTS_AUTO_REPLY_SCOPE`           | `private`               | `private`/`group`/`all` |
| `BOT_TTS_AUTO_REPLY_MAX_CHARS`       | `120`                   | 自动配音文本上限                |
| **`BOT_TTS_AUTO_REPLY_PROBABILITY`** | **`0.05`**              | **★ 本批新增**：配音概率门        |
| **`BOT_TTS_AUTO_REPLY_ALWAYS`**      | **`false`**             | **★ 本批新增**：跳过概率门的调试旁路   |

**触发词**（内置，`DEFAULT_TRIGGER_WORDS`，`tts.py:50-53`）：  
`语音合成` / `朗读` / `语音` / `念` / `说` / `tts` / `say` / `shuo` / `yuyin` / `nian` / `langdu`  
边界判定：**整句等于触发词**，或**触发词后紧跟标点/空白**——避免「说话」「念书」「语音消息」这类包含关系词误触发。

> 2026-09-20 勘误：上表「追加触发词」在交接时点与实码不符（M-15：实码非空即**整表替换**，管理员追加一词→内置 11 词全体静默失效、`说 …` 被中央改派 bot.chat）。已修：`b13913d` 改为「内置 ∪ 追加」合并，唯一入口 `effective_trigger_words()`（与 `base_router.py:436` 共用），本节表述自此为真。同笔顺带：M-16 英文触发 casefold 不敏感已修；**繁體触发词缺口仍未收**（S10 如实记账）。另注：裸触发词是否占路由是 M-22/U-15 的独立未结面（倾向改验收③文案），与本节边界判定无关。

---


## 10. 关键文件索引

| 文件                                                                    | 作用                                                                                                                                             |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `plugins/bot_unified_runtime/domains/media/capabilities/tts.py`       | **TTS 真身**（632 行）                                                                                                                              |
| `plugins/bot_unified_runtime/config.py`                               | 配置模型（TTS 键块在 296-325 行）                                                                                                                        |
| `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py` | 帮助注册表（「语音」条目 2256-2280 行 + 元数据 3071-3102 行）                                                                                                    |
| `plugins/bot_unified_runtime/domains/chat_reply/policy/gate.py`       | 确定性哈希规范实现（106-117 行）                                                                                                                           |
| `plugins/bot_unified_runtime/__init__.py`                             | `_attach_voice_reply()` 包装层（✅ 第二批已改：谓词短路 + import 补 `should_voice_reply`，见 §5.1）                                                                                                   |
| `plugins/bot_unified_runtime/domains/render/renderer.py`              | 出站：`audio` → `{"type":"record"}`（210-215 行）                                                                                                    |
| `plugins/bot_unified_runtime/sender/onebot.py`                        | 出站：record → QQ 语音条（279-284 行）                                                                                                                  |
| `tests/test_tts.py`                                                   | 离线回归（915 行）                                                                                                                                    |
| `tests/verify_hashes.py`                                              | 交付物哈希门（`echo.py` 在 TRACKED_FILES 内）                                                                                                            |
| `docs/acceptance-manual.md` §6.6.11                                   | **真机验收清单（14 项）**                                                                                                                               |
| `docs/config-catalog-full.md`                                         | 配置全册（TTS 段 805-825 行）                                                                                                                          |
| `docs/design/v21r2-COORDINATION.md`                                   | **占域台账（动手前必读）**                                                                                                                                |
| `docs/design/tts-handover-20260919.md`                                | 本文档                                                                                                                                            |
| `C:\Software\GPT-SoVITS-V2Pro\refs\`                                  | 参考音频 + 扫描 CSV + 听辨清单 + ASR TSV                                                                                                                 |
| `C:\Software\GPT-SoVITS-V2Pro\tools\`                                 | 5 个工具脚本（**刻意不进源码树**）：`scan_durations.py` / `make_listening_checklist.py` / `pick_refs.py` / `asr/transcribe_refs.py` / `verify_chatbot_env.py` |

> 2026-09-20 勘误（T124 同步）：上行「刻意不进源码树」已被 M-61 推翻——语料工具链四脚本（`scan_durations` / `pick_refs` / `make_listening_checklist` / `transcribe_refs`）已收编入仓 `scripts/tts_corpus/`（`c78951f`，T106：溯源块+引擎原件 sha256 双向防漂移锚，缺失=SKIP；引擎目录原件只读零写入，仍在上表路径）；`verify_chatbot_env.py` 更早入仓 `scripts/verify_chatbot_env.py`（T87，`7e2fe36`）。随收编的防护面：18 例冒烟门 `tests/test_tts_corpus_tools.py`（c78951f 内）+反向毒化防护门 `tests/test_tts_corpus_gate.py`（T96 三源对齐门，「按 tsv 覆盖 .env」在门上必红；`097b2e9` 补录入库）。

---

## 11. 接手者行动清单（按顺序）

```
[ ] 1. 读 §6.2 的占域台账 docs/design/v21r2-COORDINATION.md，确认没人与你撞车
[ ] 2. 跑 §7.1 的四条基线自检命令，确认全绿（TTS 71 / 文档三门 33 / 哈希门 6 / 机器册两件）
[ ] 3. 第二批（根 __init__.py 谓词短路）**已完成**（§5.1）——只需复核，不必重做
[ ] 4. 读 §5.3，对照 .env 与 shorekeeper_refs_asr.tsv 复核 8 条参考文本
[ ] 5. 等澜汐回 §5.4 的听辨结果（A~E），据此决定是否扩池到 heihaian_main
[ ] 6. 陪澜汐做 §5.5 的真机验收（docs/acceptance-manual.md §6.6.11，14 项）
        └─ 重点：⑥ 错误透传（本批修复点）、⑨ 概率门（本批新功能）
[ ] 7. 验收全过后，在 §6.6.11 打勾回写 + 在台账追加「完成」条目
```

**若澜汐再次说「用 >15s 的语录」**：见 §1.2，如实告知 3~10 秒硬约束，引导她改用合规池（291 条）。

**若发现概率门行为异常**：第一件事是确认没人把它改成了 `random`（§4.2.5 是硬红线）。

---

*文档结束。本批改动全部留在工作树，**未 commit、未部署**。*
