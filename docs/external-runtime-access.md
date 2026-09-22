# 外部运行时访问与工作区边界

## 结论

**现在机器人可以访问工作区外的数据，但机器人不是通过阅读 Markdown 来找到这些数据。**
真正生效的入口是：

1. `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\.env` 和 `.env.prod`；
2. `plugins\bot_unified_runtime\config.py` 对 `data/...` 的统一解析；
3. `bot.py` 的启动初始化；
4. `scripts\dev.ps1` 的固定工作目录与外部虚拟环境；
5. NoneBot localstore 的外置目录设置。

Markdown（本文件、`WORKSPACE_GUIDE.md`、`README.md`）是给人和 AI 的操作边界说明，不是机器人的运行时配置。

## 数据流

```text
源码 ChatBot\\
  ├─ .env / .env.prod
  ├─ bot.py + plugins/
  └─ scripts/dev.ps1
       │ 读取并解析路径
       ▼
外部 ChatBot_Runtime\\
  ├─ data\\knowledge_embeddings.sqlite3       向量库
  ├─ data\\knowledge_faiss.index              FAISS 索引
  ├─ data\\wuwa_memory.sqlite3               机器人记忆
  ├─ data\\wuwa_history.sqlite3              对话历史
  ├─ data\\nonebot\\                         NoneBot 插件数据
  ├─ data\\downloads\\ / cards\\ / meme_library\\媒体与缓存
  ├─ config\\                                  第三方插件配置
  ├─ cache\\                                   Ruff/mypy/localstore 缓存
  └─ venv\\                                    Python 运行环境
```

### 机器人如何引用

- `BOT_RUNTIME_DATA_DIR` 指向 `ChatBot_Runtime\data`。
- 配置中写作 `data/xxx` 的数据库、日志、下载、卡片和订阅路径，会由 `Config._resolve_runtime_data_paths()` 转成外部绝对路径。
- `BOT_PERSONA_FILES` 和 `BOT_KNOWLEDGE_FILES` 支持绝对路径，因此库街区百科可以留在外部，守岸人活动人格可以留在源码或 Runtime。
- 卡片 SVG 由 `BOT_CARD_ASSET_DIR` 或 `ChatBot_Runtime\card_render_assets` 自动发现。
- `nonebot-plugin-localstore` 使用 `.env.prod` 中的外部 `LOCALSTORE_*_DIR`，所以不会因 CWD 把数据写回 `ChatBot\cache`、`ChatBot\config` 或 `ChatBot\data`。
- 启动崩溃日志在 NoneBot 初始化后绑定同一个外部 Runtime data 目录；不会因 `bot.py` 过早安装崩溃钩子而回流源码目录。

## Codex/AI 如何避免扫描

### 正确做法

在 Codex 中关闭当前外层容器工作区，只打开：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
```

打开后根目录应直接看到 `bot.py`、`plugins\`、`scripts\`、`personas\` 和 `pyproject.toml`。

### 不要打开

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive
```

`.gitignore` 只能影响 Git 跟踪，**不能可靠地限制 AI 上下文扫描**。限制扫描的决定性措施是工作区根目录只选源码子目录。

## 启动、调试与恢复

所有命令都从源码目录执行：

```powershell
Set-Location 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task runtime-layout"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task config-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task readiness-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task startup-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task run"
```

请注意上面的 `runtime-layout` 是最关键的外部边界检查；它只读目录和配置，不打开数据库内容，不调用 LLM，不连接 QQ/SnowLuma。受限终端优先使用上面的 `-Command "& .\scripts\dev.ps1 -Task ..."` 写法；如果独立 PowerShell 环境支持 `-File`，也可以使用旧的等价写法。

如果检查失败，优先修正 `.env`/`.env.prod`，不要把 Runtime 目录复制回源码工作区。

## 维护脚本

以下脚本的默认数据库和输出目录已经改为读取 `BOT_RUNTIME_DATA_DIR`：

- `scripts\knowledge_progress.py`
- `scripts\kb_wiki_retrieval_probe.py`
- `scripts\knowledge_bench.py`
- `scripts\import_meme_packs.py`

`knowledge_progress.py` 一次报两个向量库（`memory`=角色记忆库、`wiki`=百科接货库），只读打开，
可以在 kb-sync 跑动中随时看。wiki 侧的**收工判据不是行数**：投料阶段块行就已全部落库，
"库内 100% 带向量"既可能是投完也可能是还没开嵌。真正的四条判据（摘要 `ok`/`error_kind`、
本轮 `embedded >= embed_pending`、`embedded_after >= 块行数`、`ann_expected_vector_count == embedded_after`）
由脚本自己打勾，语义锁在 `tests\test_knowledge_progress_settled_gate.py`。
注意摘要里的 `embed_pending` 是**本轮投料数（分母）**，不是"还剩多少"。
值守/等待类脚本**必须带基线** `--since <ISO>`：库里的摘要只有一枚、永远反映**上一次跑完的那轮**，
不带基线时"已投完收工"会在本轮还没开跑时就先绿一次（2026-09-22 实犯，值守脚本第一轮即自行退出）。
带基线后本轮未开始时打 `=> 本轮未开始`，两例锁在同一测试件里。

表情包导入脚本写入数据库的文件路径也使用绝对路径，避免数据库位于 Runtime 时，后续清理操作错误地把相对路径解释到源码目录。

## 语音工具链（语料与自检）

TTS 语料工具链的代码真身与产物真身都在引擎目录 `C:\Software\GPT-SoVITS-V2Pro`（仓外，不属本工作区）。本仓库只保存版本保护副本与登记台账；执行永远发生在引擎侧，仓内副本零业务引用。

### 四支工具的收编副本

引擎 `tools\` 下四支语料工具已逐字节收编入 `scripts\tts_corpus\`。每支头部带溯源块（原路径/原件 sha256/收编日期/已知缺陷指针），原件仍是唯一执行真身，副本只用于版本保护与取证；已知缺陷原样保留不修，修 bug 另波。

| 副本（scripts\tts_corpus\） | 原路径（引擎 tools\） | 原件 sha256 |
|---|---|---|
| scan_durations.py | scan_durations.py | d1ea0870b054aea4769ad30897c7e1dcd57996d6e25c2ca793980ed273e6bf8b |
| pick_refs.py | pick_refs.py | 0ed14796c763e2c0236b5e2a9b1e95cb9c3da2a836a67ccb8a876358128e5e9f |
| make_listening_checklist.py | make_listening_checklist.py | 076c5c64eda4da160f5449dc7d7b43d8a022ff6acd8ba6aa63e7515773b402f8 |
| transcribe_refs.py | asr\transcribe_refs.py | 7d2e8962483ed6f7adcc58519d20856612ba878e5d5a6cd709540bed1d944306 |

副本与原件的一致性由冒烟门 `tests\test_tts_corpus_tools.py` 锚定（2026-09-20 实跑 18 passed）：副本尾部与引擎原件各自对溯源块登记的 sha256 做逐字节断言，任何一侧改动都会被漂移门拦下；引擎目录缺失时按 SKIP 语义跳过，不假红。注意 `pick_refs.py` 与 `make_listening_checklist.py` 是顶层执行脚本（import 即按硬编码绝对路径写引擎 refs\），结构上禁止在本工作区 import。

### 引擎侧产物登记（只登记不收编）

以下 13 件产物真身在引擎 `refs\` 目录，仓库不保存副本，仅登记 sha256 供换机或重录语料后对表。**这些哈希不在 CI 内**（`verify_hashes.py` 结构上锚不了仓外文件），**换机或重录语料后本表需要重录**。

| 产物（GPT-SoVITS-V2Pro\refs\） | sha256 前 16 | 大小 | 备注 |
|---|---|---|---|
| corpus_durations.csv | 05362a75a3e1c71f | 86716B | 490 行含 2 簇重复，291/118 虚增（真实 289/117） |
| listening_checklist.md | 20e94300aa5016bb | 3168B | 生成物内嵌手写矛盾数字 |
| shorekeeper_refs_asr.tsv | 5970949be196be5d | 2345B | 粘贴块 9 条含 32kHz 杂散件 |
| honami_lines_asr.tsv | d99be28d5290bd3c | 4237B | 无粘贴块=非同版本产出，不可归因 |
| shorekeeper_ref_01.wav | 783c66eb1fb541ee | 463404B | 32kHz 杂散件，勿扩进选片池 |
| shorekeeper_ref_01.flac | 1c8617dc464abd3d | 385420B | 手工第一条，源=剧情/main_honami_2_8_2_43_9.flac（哈希可溯） |
| shorekeeper_ref_02..08.flac（7 件） | 7ad26b5c/bdda2432/21dde323/307ff5ab/cb1dc751/cedc24d8/3fda0f1d | 195586~394815B | pick_refs 产出，7/7 与宣称源逐字节相同 |

### 与自检工具的分工

- `scripts\verify_chatbot_env.py`（已入仓，T87 重建）：手动快查工具——改完 `.env` 后秒级离线核对 bot 侧配置面（生产 pydantic Config 装载语义 + TTS 段深查），不是重启门。
- `scripts\pre_restart_check.py`（重启前置预检 10 项）：第 10 项「音色守望」守引擎面（tts_infer.yaml/权重/sha256 身份对表，基线册 `scripts\tts_voice_baseline.json`）。
- `tests\test_tts_corpus_tools.py`（冒烟门）：只守语料工具收编副本与引擎原件的逐字节一致，随全量测试（`dev.ps1 -Task test`）运行。

三者零重叠：配置面归 verify_chatbot_env，引擎面归 pre_restart_check，语料工具版本面归冒烟门。

## 归档与恢复

归档固定写入：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\
```

归档包不属于当前 AI 工作区。只有在明确恢复某个测试或历史文件时，才临时解压到源码目录；验证完成后再次移出。运行中的 SQLite、FAISS、记忆、Cookie 和 NoneBot data 不要直接压缩后继续运行，也不要直接删除。

## 快速故障判断

| 现象 | 首先检查 |
|---|---|
| 源码目录重新出现 `data/`、`config/` 或 `cache/` 文件 | `LOCALSTORE_USE_CWD=false`，以及 `LOCALSTORE_*_DIR` 是否仍指向 Runtime |
| 知识检索为空 | `BOT_RUNTIME_DATA_DIR`、向量 SQLite、FAISS 索引和 `BOT_KNOWLEDGE_FILES` |
| 人格缺失 | `BOT_PERSONA_FILES` 是否全部存在，文件是否仍在原位置 |
| 卡片图标缺失 | `ChatBot_Runtime\card_render_assets\` 是否存在，或设置 `BOT_CARD_ASSET_DIR` |
| AI 上下文又变大 | Codex 是否重新打开了外层 `ChatBot` 容器，而不是源码子目录 |
| 运行后出现 `__pycache__` | 使用 `scripts\dev.ps1`；直接调用 Python 前设置 `PYTHONDONTWRITEBYTECODE=1` |

## 验收标准

下列命令全部通过，才可以认为“外部数据访问引导”有效：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 runtime-layout
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docs-check
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 plugin-check
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 config-smoke
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 readiness-smoke
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 startup-smoke
```

这些检查不等同于真实平台联调；真实 SnowLuma/QQ 连接仍需在用户明确要求时单独验证。
