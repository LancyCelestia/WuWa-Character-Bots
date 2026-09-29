# SEAT-S84 — wiki 向量嵌入重建：吞吐 / 续跑 / 护栏 实测报告

席号：S84（只读测量席） · 本文件是本席唯一写面
**取数时刻：2026-09-25 22:14 – 22:40 本机钟（= 14:14 – 14:40 UTC）**
⚠ 时钟口径如实报：调度侧给的当日是 2026-09-28，本机 `date` 与 `Get-Date` 均为 `2026-09-25 22:20 +08:00`。本报告一切时间戳取本机钟（库里 `kb_sync_last_summary.started_at=2026-09-25T13:57:57Z` 与 bot 进程创建时间 21:57:06 对得上，证明本机钟与库内 Z 钟自洽）。

纪律声明：全程只读。未 git 写、未改任何配置（`.env`/`.env.prod`/`settings.json`/模型档一个字没动）、未重启或杀任何进程（含 bot）、未派子代理、未写 `ChatBot_Runtime/**`（只用 `file:...?mode=ro` 读）。所有 python 直跑带 `PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=$TEMP/s84-pyc`。临时件只落在 `$TEMP/s84-*`（盘外）。
**负荷披露**：本席确实给机器加了三次负荷——① 一发 235 条的本地嵌入探针（GPU，约 30 s）；② 一发 4096/12288/24576 枚随机向量的 HNSW 单线程构建基准（1 核，约 105 s）；③ 两发全表只读扫描（本席 323 s + 一并发 `knowledge_progress.py`）。均在 32 逻辑核机器上、单核量级，未触碰 bot 进程。

---

## §0 一句话结论（先给判据，再给过程）

**wiki 嵌入今天已经全好了，不需要"尽快重建"。** 现算三口径互证：块行 766,126 / 已嵌 766,126 / 待嵌 **0**；ANN 计数戳 766,126 == 索引 ntotal 766,126 ⇒ `missing=0`；代际证明四道（字节数×2 / order sha256 / ntotal==count / ann_signature==provider 指纹）**逐条实测为真** ⇒ HNSW 通道今天是被使用的，不是回落暴力的。仓内既有判据件 `scripts/knowledge_progress.py` 实跑输出 `=> 这一轮已投完收工`（四发 [ok] 全绿）。

真正值得主代理动手的只有三件，且都不是"跑一次大重建"：
1. `BOT_EMBEDDING_LOCAL_TIMEOUT_SECONDS` 现值 **5.0**，而 128 批实测 **4.87–6.55 s** ⇒ 生产现配置下**多数首批必超时**、嵌入批大小自动折半到 ~32，吞吐从 ~1400 块/分钟掉到 ~441（**2.7–3.2 倍纯浪费**）。这是唯一一处"跑得慢"的真凶，改一枚键即可（见 §4/§5）。
2. 真缺的是 **人格/记忆库 25 条未嵌**（`knowledge_embeddings.sqlite3`：35,258/35,283），不是 wiki。
3. 语料侧 `.kb_publish_staging/` 正在换代（22:28 有动作），**今晚 23:40 那次夜间 kb-sync 才是真正会有新待嵌的一轮**——护栏见 §4，那条路上有一颗会打死会话的雷（FTS 全量重建在检索锁内，进程内跑）。

---

## §1 嵌入路径真身（链条 / 批量 / 并发 / 超时 / provider / 429 语义 / 续跑谓词）

### 1.1 调用链（每一跳都给 `文件:符号`）

```
scripts/dev.ps1 -Task kb-sync
  └─ scripts/chatbot-tasks.json : tasks["kb-sync"].steps[1]
        runner="soft"（非零退出只打印不抛） module=plugins.bot_unified_runtime.domains.ops.smoke.smoke args=["kb-sync", {optionalSwitches:"Kb"}]
  └─ plugins/bot_unified_runtime/domains/ops/smoke/smoke.py:3296  args.task=="kb-sync" 分支
        └─ :3299 run_kb_sync_task(config, full=args.kb_full, embed=not args.kb_no_embed,
                                  on_progress=..., embed_progress=...)
             （config 来自 smoke.py:3017 load_smoke_config → smoke.py:226 → 唯一入口
              scripts/load_runtime_config.load_runtime_env_values，但**只喂单文件 .env**，
              见 1.6 的差异核对）
  └─ domains/location/knowledge/kb_wiki.py:1027 run_kb_sync_task
        :1043 _SYNC_TASK_MUTEX.acquire(blocking=False)  ← 进程内互斥，撞车即 error_kind=busy
        :1068 _run_kb_sync_task_locked
             :1098 _embedding_chain_ready(config)  任一腿不齐 ⇒ error_kind=config_missing（不跑）
             :1105 _build_store(config, auto_reset=True)   ← CLI 走 auto_reset=True（见 §4 地雷）
             :1108 provider=_build_provider(config)  全长超时 provider 临时换进 store
             :1112 sync_kb_wiki(...)                kb_wiki.py:332
             :1127 store.embed_pending(None, on_progress=…, batch_size=bot_kb_wiki_embed_batch)
  └─ domains/chat_reply/character/vector_knowledge.py:1621 embed_pending
        :1634 with self._maintenance_lock        ← 维护任务串行闸（嵌入与 ANN 重建互斥）
        :1637 self._embed_all_pending(...)
             :988 _reset_vectors_if_needed()      ← 指纹不符就 UPDATE ... SET vector_json=NULL（全库清）
             :989 pending = self._pending_rows()  ← 全表扫 + fetchall（见 §2/§4）
             :996 if pending: self._embed(["预热"])
             :1001 while done < total: 逐批 → _embed → _save_vectors → commit
             :1026 if done == total: 才落 embedding_signature
  └─ :2789 _embed(texts) → provider.embed_texts → 失败/长度不齐一律返回 None
  └─ :550 OpenAICompatibleEmbeddingProvider._embed_texts_uncached
        for chain in self._chain_order(): for model in chain.models:
            httpx.post(f"{chain.base_url}/embeddings", json={"model":…,"input":texts},
                       timeout=chain.timeout_seconds)   ← 同步 httpx，批内无并发
            except Exception: continue                 ← :577 全吞，429/超时/4xx 同一条路
```

### 1.2 批量 / 并发 / 超时 / 每批成本（**现值 = 生产同构 Config 实跑打印**）

| 项 | 真身锚点 | 生效值（`load_runtime_config((".env",".env.prod"))` 实读） |
|---|---|---|
| 每批行数 | `kb_wiki.py:1124` 吃 `config.bot_kb_wiki_embed_batch` | **128** |
| 折半下限 | `vector_knowledge.py:35 _EMBED_BATCH_SIZE = 10`（注释：百炼 qwen3.7 上限 20、v4 上限 10） | **10**（floor，同时是远程链单批上限） |
| 同尺寸重试预算 | `vector_knowledge.py:998 retries_left = 1` | **全局 1 次**（不是每批） |
| 批内并发 | `:1001` 起 while 串行、`httpx.post` 同步 | **1**（无 ThreadPool、无 asyncio） |
| 跨批并发 | `embed_pending` 持 `_maintenance_lock`（`:1634`） | **1**（同进程所有嵌入排队） |
| 本地链每批超时 | `kb_wiki.py:536 effective_local_timeout` ← `bot_embedding_local_timeout_seconds`（代码缺省 60.0） | **5.0 s** ← 本波头号问题 |
| 远程链每批超时 | `kb_wiki.py:531` ← `bot_embedding_timeout_seconds`（缺省 15.0） | **5.0 s** |
| 预热一发 | `vector_knowledge.py:997` | 实测 **8.43 s**（模型加载，一次） |

### 1.3 provider 是哪个渠道 —— **不是 axonhub，是本地 Ollama**

`vector_knowledge.py:476-499` 构链顺序 = `chains[0]` 本地（若 `local_enabled` 且 `local_base_url` 非空）、`chains[1]` 远程；`_chain_order()`（`:519`）sticky：某链一旦成功，后续优先复用它。现值：

- 链 0（本地，**现役**）：`http://127.0.0.1:11434/v1/embeddings`，model `bge-m3`，`local_enabled=True`，超时 5.0 s。端口实测在听：`netstat` → `TCP 127.0.0.1:11434 LISTENING 28640`（`ollama.exe`）。维度实测返回 **1024**（`dims={1024}`）。
- 链 1（远程兜底）：`https://dashscope.aliyuncs.com/compatible-mode/v1`，models `qwen3.7-text-embedding, text-embedding-v4`，超时 5.0 s。⚠ 该链的 key 在 Config 里是明文实值，本席**不把它写进任何文件**（纪律 3）。
- axonhub `127.0.0.1:8090` 只在听（`LISTENING 16764`），**与嵌入链无关**：库内 `knowledge_meta.embedding_signature = 'http://127.0.0.1:11434/v1|bge-m3;https://dashscope.aliyuncs.com/compatible-mode/v1|qwen3.7-text-embedding,text-embedding-v4'`，与 `_build_provider` 的 `signature`（`:513`）逐字节一致 ⇒ 今天落库的 766,126 条向量都是这两条链（且链 0 现役）产出的，**没有走 axonhub**。
- GPU：`nvidia-smi` → RTX 4060 Laptop 8188 MiB / 已用 2513 MiB ⇒ bge-m3 在 GPU 上，嵌入几乎不吃 CPU/RAM（这是好消息，护栏主要看 ANN 侧）。

### 1.4 429 / 超时会不会中断整轮 —— **不会"炸"，但会"提前收工"**

`_embed_texts_uncached:577` 是 `except Exception: continue`（HTTPStatusError 429、ReadTimeout、KeyError 全同一条路），全链失败即 `return []`；`_embed:2796` 把 `[]` 判成 `len(result)!=len(texts)` → **None**。回到 `_embed_all_pending`：

1. 先用那唯一 1 次 `retries_left` 原尺寸重试一次；
2. 还 None 就进折半循环 `:1011`（`size = max(floor, len(batch)//2)`，**收缩被记住给后续所有批次**）；
3. 退到 floor=10 仍 None ⇒ `:1016 break` ⇒ 本轮**剩余全部行不嵌**（不抛异常、不退出进程）。

上层表现：`kb_wiki.py:1192` 判 `embed_pending > embed_done` ⇒ `error_kind="partial"` + 人话「嵌入只完成 X/Y 行，请检查 Ollama/嵌入端点后重跑（断点续跑，已完成行自动跳过）」；进程按 `runner="soft"` 打印 `softFailMessage` 后以非零码结束。**关键**：`:1026` 只在 `done == total` 时才落 `embedding_signature` ⇒ 部分完成的轮次不会把"未跑完"钉成指纹，下一轮继续。

### 1.5 断点续跑：谓词坐标

- 挑活谓词 = `vector_knowledge.py:2765 _pending_rows()`：
  `SELECT chunk_id, content FROM knowledge_chunks WHERE vector_json IS NULL OR vector_json = ''`（**无索引，全表扫**；`chunk_id` 是 PRIMARY KEY，`vector_json` 上没有任何索引——schema 实测只有 `idx_knowledge_chunks_source(source_id)`）。
- 每批落库 = `:2800 _save_vectors()`，128 发 `UPDATE knowledge_chunks SET vector_json=?, vector_blob=? WHERE chunk_id=?`，一个 `with self._connect()` 出口提交 ⇒ **断点粒度 = 一批**。
- 投料侧断点 = `kb_wiki.py:714` 注释所指：`sync_documents` 每 500 文档一提交。
- 协作式取消 = `_SYNC_CANCEL_EVENT`（`kb_wiki.py:715`）+ `_cancel_aware_progress`（`:750`）在**批边界**检查，抛 `KbSyncCancelled(BaseException)`（`:718`，刻意继承 BaseException 以穿透内层吞 Exception 的兜底）⇒ `:1229` 落 `error_kind="cancelled"`，断点保留。取消入口 `cancel_kb_sync_task()`（`:728`）由停机序列调用。
- 跨进程互斥：**没有**。`_SYNC_TASK_MUTEX` 是 `threading.Lock`（进程内）。CLI 与 bot 进程内 23:40 那轮可**同时在跑**，两边各自 `_pending_rows()` 挑到同一批行 → 重复嵌入（同一模型同一条文本 → 结果同值，最后一写赢，不损坏数据，但白烧 GPU 与时间）。唯一跨进程真闸是 ANN 建锁文件 `kb_wiki_faiss.index.build.lock`（`_AnnBuildGate`，`:331`，抢不到就让路 `reason=locked_by_other_process`）。

### 1.6 CLI 与生产的配置装载差异（已核，今天无分歧）

`smoke.py:248 _resolve_smoke_env_file` 只取**单文件 `.env`**（生产 `bot.py` 是 `.env` + `.env.prod` 链）。本席对 §1.2/§1.3 全部 15 枚相关键做了两侧对拍：`single(.env)` vs `prod-chain(.env+.env.prod)` **逐键等值**（`.env.prod` 只有 1525 B，不含任何嵌入/知识库键）。⇒ `dev.ps1 -Task kb-sync` 与 bot 内 23:40 那轮看到的嵌入链参数今天完全一致，不必担心"改了不生效的那一份"。

---

## §2 现算待嵌量（`kb_wiki_embeddings.sqlite3`，`mode=ro`，**未拉 vector_json**）

一条全表聚合扫描（本席实跑，`scan_seconds=323.0`，与并发只读扫描+活体 bot I/O 抢盘，属上界）：

```
TOTAL=766126  PENDING=0  EMBEDDED=766126  PENDING_CHARS=0
```

按主题分桶（`substr(source_id,1,instr(source_id,'/')-1)`，16 桶，全部 pending=0）：

| topic | total | pending |  | topic | total | pending |
|---|---:|---:|---|---|---:|---:|
| 明日方舟 | 309,031 | **0** | | 无限暖暖 | 32,263 | **0** |
| 鸣潮 | 121,389 | **0** | | 崩坏：星穹铁道 | 18,975 | **0** |
| 战双帕弥什 | 65,447 | **0** | | 明日方舟：终末地 | 14,770 | **0** |
| 重返未来：1999 | 62,194 | **0** | | FGO | 8,598 | **0** |
| 碧蓝航线 | 45,666 | **0** | | 梗知识 | 5,943 | **0** |
| 原神 | 41,877 | **0** | | 崩坏3 | 4,380 | **0** |
| 第五人格 | 32,833 | **0** | | 绝区零 | 2,177 | **0** |
| 碧蓝档案 | 317 | **0** | | 异环 | 266 | **0** |

交叉印证（三条独立口径）：
- 台账：`SELECT COUNT(*) FROM knowledge_docs` = **172,933** 文档（1.4 s，与 `.env` 侧 manifest 的 `documents` 对得上）。
- 上一轮收工摘要（`knowledge_meta.kb_sync_last_summary`，机器写入）：`started_at=2026-09-25T13:57:57Z`、`duration_ms=287578`、`ok=True`、`added/changed/removed=0/0/0`、`chunks=0`、`embedded=0`、`embed_pending=0`、`chunks_after=766126`、`embedded_after=766126`、`ann_rebuilt=False`（`ann_reason=unchanged_skip`）、`reconcile_status=ok`。⇒ 那是一轮**零变更夜**（启动 +45 s 补同步，21:57 本机钟），只做了对账与扫描，没嵌一行。
- 仓内判据件实跑：`cd scripts && ../ChatBot_Runtime/venv/Scripts/python.exe knowledge_progress.py`（跑超 2 分钟，被本机转后台后完成）：
  `== wiki ==` → `embedded=766126 total=766126 percent=100%` + 四发 `[ok]`（含 `ANN 应嵌数(766126)==库内已嵌(766126)`）→ `=> 这一轮已投完收工`。
  `== memory ==` → `embedded=35258 total=35283 percent=99%`、**库里还有 25 条未向量化**（另一枚库 `knowledge_embeddings.sqlite3`，本席未展开）。

ANN 侧（同样只读实测）：`ann_expected_vector_count=766126`；`ann_pair_attestation = {ntotal:766126, count:766126, index_bytes:3346539658, order_bytes:33709544, order_sha256:4ed6c50e…}`；磁盘 `kb_wiki_faiss.index` 3,346,539,658 B / `kb_wiki_faiss.order.json` 33,709,544 B（**字节数与 sha256 本席重算逐位吻合，sha 只花 0.06 s**）；`ann_signature == embedding_signature`。⇒ `load_ann_index()` 的四道判据全过、`missing = 766126-766126 = 0 ≤ _ANN_COMPLETENESS_MAX_MISSING(=0)`（`vector_knowledge.py:328`）。

语料侧（下一步会不会有活）：`bot_kb_wiki_root = D:/Coding/01_Projects/Crawl Wiki` → `crawl_output/knowledge_base/`：`documents.jsonl` 813,887,965 B（本机 15:34）、`manifest.json` 23,118,243 B（`generated_at=2026-09-25T07:32:48Z`）、`updates.jsonl` 1,797 B、**`.kb_publish_staging/20260924T163729Z-p38084/` 目录 mtime 22:28（本席取数期间正在动）**，且机器上另有 `corpus_snapshot.py snapshot --out $TEMP/cw-s90/snap-after.jsonl` 进程（PID 41372，22:19 起）在跑。⇒ 换代一旦落定，23:40 那轮 `sync_kb_wiki` 会投出新块 ⇒ 那才是今天唯一真实的"待嵌量 > 0"机会，量级本席无法预知（未落定，且预估需要读 813 MB 语料——不属本席授权面）。

**扫描本身的成本要记进账**：`_pending_rows()` 每轮无条件付一次全表扫（要判 `vector_json IS NULL` 就得把 13.8 KB/行的 JSON 溢出页读一遍）。本席实测 **323 s**（争用下），而那一轮真实 kb-sync 全程（含台账对账 + 这次扫描）只有 **287.6 s** ⇒ 真值区间取 **4–5.5 分钟/轮**，无论有没有活要嵌。这是"跑一次 kb-sync 看看"的固定门票，也是 §5 里"何时该停去看读数"的依据之一。

---

## §3 实测吞吐（本地 Ollama bge-m3；**未写生产库、未碰远程付费链**）

做法（合规）：绕开 store，**只实例化 provider 本身**（`vector_knowledge.py:455`），`remote` 三参数留空 ⇒ `chains` 里**根本没有远程链**（`:490` 的 `if remote_models and base_url.strip()` 不成立），既不会向 dashscope 出网、也不会产生任何计费；文本从库里 `SELECT content … LIMIT 235` 取真语料（只读）；**零 UPDATE、零文件写**（除 `$TEMP` 基准件）。

```
chains: [('http://127.0.0.1:11434/v1', ('bge-m3',), 60.0)]          ← 故意放宽超时以量真耗时
sample_texts=235 total_chars=148127 avg_chars=630.3
warmup-1 : n=1   seconds=8.43   → 模型加载一次性成本
batch-10 : n=10  chars=3320   seconds=3.42  chunks/min=175.4   chars/min=58,249   dims={1024}
batch-32 : n=32  chars=12755  seconds=4.35  chunks/min=441.6   chars/min=176,020  dims={1024}
batch-64 : n=64  chars=47812  seconds=4.99  chunks/min=769.5   chars/min=574,863  dims={1024}
batch-128: n=128 chars=84162  seconds=6.55  chunks/min=1172.1  chars/min=770,701  dims={1024}
```

128 批重复 5 发的离散度（含一发 `timeout=5.0` 直发）：`6.55 / 5.73 / 5.49 / 4.87 / 5.18 s` ⇒ **1,172–1,577 块/分钟，中位 ≈ 1,390**；代码注释里的「本地 Ollama 批 128 ≈19 块/s」（`kb_wiki.py:1120`）与本席实测 19.5 块/s 对得上（**独立复现，非转述**）。

**±区间与依据（写死口径，不许用形容词）**：
- 稳态吞吐：**1,150 – 1,600 块/分钟**（依据 = 上面 5 发实测的包络；下界含冷一点/争用一点）。
- 冷启动一次性：**+8 – 10 s**（Ollama 模型加载，实测 8.43 s；本会话内后续批不再付）。
- 固定开销形态：批 10→128 的耗时 3.42→6.55 s ⇒ **每请求固定约 3.2 s + 每块约 0.026 s**（4 点拟合，R² 目测高但不成文，取"近似"口径）。批越大摊薄越充分——这就是 5 s 超时与批 128 天生打架的数学原因。
- tokens/分钟：**未实测**（bot venv 无 `transformers`/`sentencepiece`，本席 `importlib.util.find_spec` 实测两个都 False）。换算式给在这里，别当测量值：样本 avg **630.3 字符/块** ⇒ 1,390 块/分钟 ≈ **8.8×10⁵ 字符/分钟**；按 bge-m3(XLM-R sentencepiece) 中文约 1 token/字（±30%）估 **0.6 – 1.2 M tokens/分钟**。标注：这条是推算，不是读数。
- SQLite 落库分量：**未单测**（本席不写库）。给出字节算术：`_save_vectors` 每块写 `vector_json`(实测 avg **13,787 B**) + `vector_blob`(4,096 B) ⇒ 全库一次重建 = **13.4 GiB UPDATE 流量**；按批提交，WAL 不涨大。

### 3.1 全量重建 ETA（把 §2 的 766,126 代进 §3 的速率）

| 情形 | 批大小 | 速率 | 766,126 块要多久 |
|---|---|---|---|
| 把本地超时放宽到 ≥20 s 后（推荐） | 128 | 1,150–1,600/min | **8.0 – 11.1 h**（中位 9.1 h） |
| 生产现值（5.0 s 超时，首批必挂 → 折半记住） | 64（若 4.99 s 侥幸过） | ~770/min | ~16.5 h |
| 生产现值（更常见：64 也挂 → 退到 32） | 32 | ~441/min | **~29 h** |
| 最坏（一路退到 floor） | 10 | ~175/min | ~73 h（且每批 3.42 s 逼近 5 s 线，迟早 `break`） |

夜间增量按同一速率折算：1,000 块 ≈ 0.6–0.9 h（128 批）/ 2.3 h（32 批）；5,943 块（= 梗知识那桶的量）≈ 3.7–5.2 h（128 批）。
**注**：今晚真到手的增量本席无法预先量（§2 已说明 `.kb_publish_staging` 未落定），所以这张表按"每千块"给，别按整库读。

### 3.2 逐批耗时为何不能从日志取证（诚实缺口）

当前 bot（PID 36328，创建 21:57:06）的 stdout **没有落在盘上**：`ChatBot_Runtime/logs/bot_stdout.log` mtime 停在 **09-16 03:13**、`bot_stderr.log` 09-16 03:09、`nonebot.out.log` 09-17 23:28 且 **0 字节**。`ChatBot_Runtime/restart_bot.ps1:41-42` 的 `-RedirectStandardOutput logs\bot_stdout.log` 只在用它拉起时才有日志，本次不是用它拉的。⇒ 21:57 那轮的 `progress embedded=…` 每批行**已经永久丢了**，只剩 DB 里的 summary。所以 §3 的数字全部来自本席的直接测量，不来自日志；这也是 §5 第 3 步要求"前台跑、看得见输出"的原因。

---

## §4 内存与并发护栏（会不会把机器打死：给数，不给形容词）

### 4.1 本机现量（22:2x–22:4x 本机钟，`GlobalMemoryStatusEx` / Win32_OperatingSystem / tasklist）

| 量 | 读数 |
|---|---|
| 物理内存总量 | 31.74 GiB（33,282,672 KB） |
| **空闲物理** | 首测 **2.82 GiB**（22:20）→ 2.99 GiB（22:2x）→ **2.38 GiB**（22:3x，正逢本席基准 + 全表扫描） |
| **空闲提交（commit）** | 5.80 – 6.74 GiB；提交上限 84.40 GiB（页面文件很大 ⇒ **真 OOM-kill 概率低，代价是换页风暴**） |
| 逻辑核 | 32 |
| 活体 bot（PID 36328 `python bot.py`） | 创建时 218 MB → **22:3x 实测 RSS 3,702,380 K = 3.53 GiB** |
| GPT-SoVITS 引擎（PID 32680） | 1,781 MiB（22:2x）→ 961 MiB（22:20），在动 |
| C: 盘 | 953 GB 总 / **68 GB 空闲（93% 满）** |
| kb 库文件 | `kb_wiki_embeddings.sqlite3` **18.67 GiB**（4,558,129 × 4096，freelist 722 页）＋ `-wal` 16 KB（活体 WAL 模式） |

### 4.2 bot 那 3.53 GiB 是什么（这条决定今晚的风险形状）

判据链：`retrieve`/`search_scored` 的向量缓存预热是**有条件的**——`vector_knowledge.py:1798` 与 `:1884` 都是 `if not self.load_ann_index(): self._prewarm_vector_cache()`。而 §2 已实测四道 ANN 判据全过 ⇒ HNSW 被使用、**numpy 全量矩阵（766,126 × 1024 × 4 B = 3.14 GiB）没有被建**。所以那 3.53 GiB **最省的读法**就是 faiss 索引的私有副本（磁盘文件 3,346,539,658 B = 3.12 GiB 净 + 33.7 MB order 列表 + 基线）。
诚实标注判别边界：本席**没有**直接证据排除"3.53 GiB 里混着别的驻留"（bot 的 stdout 未落盘 ⇒ 看不到 `ANN completeness refused` 那行日志，见 §3.2）。判别办法留给她：`GET /api/…`/日志里若出现 `knowledge ANN … refused` 即说明是矩阵而非索引（那时内存形状更糟）。
`faiss.read_index(path, faiss.IO_FLAG_MMAP)`（`:2269`）在本机 faiss 1.15.0 / Windows 上**没有真的省驻留**——本席实测两发：① 小索引带 MMAP 读回类型是 `IndexHNSWFlat`（不是 mmap 专用壳）；② 读回后对同一文件做 `os.replace` **成功（未被锁）**，而对照实验里 `python mmap` 映射过的文件 `os.replace` 直接 `PermissionError [WinError 5]`。⇒ 结论：faiss 侧走的是"读完即关句柄"的普通读，整份索引进了进程私有内存。

**两个直接推论（都是硬结论，不是倾向）**：
1. **ANN 覆写不会被 bot 的映射卡住**（`_publish_ann_pair` → `_atomic_replace_from:425` 那发 `os.replace` 今天能成）。这条风险排除掉了——但它排除的理由和直觉相反，别拿"mmap 会锁文件"当依据写 runbook。
2. **任何新进程只要走一次 wiki 检索，就会再吃 ~3.5 GiB**（自己 read_index 一份）。当前空闲只有 2.4–3.0 GiB ⇒ **现在跑 `scripts/kb_wiki_retrieval_probe.py`（或任何在 bot 外做 wiki 检索的探针）就是在赌换页风暴**。本席**故意没跑**它。要看"能不能检索到"，今晚之后、且在 bot 空闲窗、或干脆用 bot 自己的会话问一句，都比新起进程便宜。

### 4.3 「kb_export.py 型全量常驻」在这里是否存在

先纠锚点：`kb_export.py` **在本仓不存在**（`ls scripts/ | grep -i kb_export` 与全仓 `find . -name kb_export.py` 双查零命中）。该风险的现役真身是这两处：
- `vector_knowledge.py:2765 _pending_rows()` —— **确实一次 `fetchall()` 全部待嵌行**（`:989` 在 `_embed_all_pending` 开头无条件调用）。常驻 = 待嵌行数 × (content + `sqlite3.Row` 壳)。实测列宽：avg `content` **575 B**（400 行样本，样本取自 rowid 序 = 偏「梗知识」短块，**下界口径**）+ Row/list 壳约 0.2–0.3 KB ⇒ 全库 766,126 行的极端常驻 **≈ 0.6 – 1.2 GiB**。**今天的实况 = 0 行 ⇒ 这项为零**；只有真投了新料才成立，且它远小于 ANN 那 3.5 GiB，不是主瓶颈。
- `:2681 _load_vector_cache()` —— 一次性物化 numpy 矩阵（**3.14 GiB**），但只在 ANN 被拒时消费（见 4.2）。⇒ 若有人把 `BOT_EMBEDDING_*` 改了签名或删了索引文件，bot 会从"3.5 GiB 常驻"劣化成"3.5 GiB + 3.1 GiB 常驻 + 每问全量点积"，那才是 09-22 停摆的形状。

### 4.4 「能开多大 jobs/批量而不 OOM」的数值判据

**结论先说：这条链上"开大并发"没有收益空间，别拿并发当提速手段——真正的旋钮只有超时。**

1. 嵌入侧的并发是**被代码钉死为 1** 的（`:1001` 串行 while + `_maintenance_lock` 单进程闸 + 同步 `httpx.post`）。**没有任何 `bot_*` 键能把它调成多路**；想多路只能改代码（不在本席授权面，也不建议：GPU 上 bge-m3 已是批 128 打满，多路只会排队）。
2. **可开多路的只有"一批之内"** —— 即 `bot_kb_wiki_embed_batch`，且它有硬上限：实测 128 批 GPU 侧 4.9–6.6 s，再往上（如 256）按 3.2 s 固定 + 0.026 s/块外推 ≈ 9.9 s，收益递减且**必须同时把超时抬到 ≥15 s**，否则退化成更多次超时。⇒ 建议区间 **128（保持）+ 超时 20–30 s**；内存代价仅"单批 vectors 列表" = 128 × 1024 × 4 B ×(Python 表壳约 8 倍) ≈ **4–8 MB**，与机器余量无关。
3. **ANN 重建进程的内存判据**（本席基准外推，见 4.5）：峰值私有 ≈ 索引向量 766,126 × 4,096 B = **3.14 GiB** + HNSW 链接图（M=32 实测整份文件/向量 = 4,368 B ⇒ 图约 **0.2 GiB**）+ `chunk_ids` 列表 766,126 × ~90 B ≈ **0.07 GiB** + 每批 2048×1024 矩阵 8 MB + SQLite 页缓存 ⇒ **峰值 ≈ 3.5 – 4.2 GiB**。当前空闲 2.4–3.0 GiB、空闲提交 5.8–6.7 GiB ⇒ **跑得完（提交够），但会重度换页**。数值判据给死：起建前 `空闲物理 ≥ 4.5 GiB` 才算安全；达不到就把 bot 暂时停掉（**停 bot 是她的权，不是任何席的**）或等空闲上来。
4. **磁盘判据**：ANN 换入要写 `*.tmp` 索引 3.35 GiB + order 33.7 MB，换入后旧文件由 OS 释放 ⇒ 瞬时多占 ≈ **3.4 GiB**；C: 现有 68 GB ⇒ 够。若同时触发 FTS 全量重建（4.5），单事务 WAL 要吞约 **5 GiB** 量级（现库 FTS+台账+索引≈5.5 GiB，见 4.6 算术）⇒ 仍在 68 GB 内，但 **93% 满的盘要盯着**。

### 4.5 ANN 重建耗时（本席实测曲线 + 外推，标注为外推）

`_build_ann_index_locked:2474` 的构造设置：`faiss.omp_set_num_threads(1)`（`:2520`，**单线程建图**）、`IndexHNSWFlat(1024, 32, METRIC_INNER_PRODUCT)`（`:2524`）、`efConstruction=200`（`:2525`）、批 2048 流式读（`_ANN_BUILD_BATCH_SIZE:285`）。本席用同设置在 `$TEMP` 建随机向量（**不碰生产库、不写生产件**）：

```
n=4096   seconds=1.5   （2653 vec/s）
n=12288  seconds=24.1  （累计 510 vec/s；边际 4096→12288 = 2.76 ms/vec）
n=24576  seconds=80.0  （累计 307 vec/s；边际 12288→24576 = 4.55 ms/vec）
边际成本随规模上升 1.65×（2 倍数据量）⇒ 建图是超线性退化，不是 n·log n 能盖住的
```
外推到 766,126（31.2×）：**下界 40 min（线性外推）/ 中位 56 min（n·log n）/ 上界 75 min（n^1.73）**。
第二条腿：仓内历史读数「23.8 万块全量重建 **8.5 分钟**」（`kb_wiki.py:1144` 与 `:705` 注释两处一致）⇒ 同一条曲线在 n=238,000 处 2.14 ms/vec；按上面三个指数外推到 766,126 = **30 / 49 / 75 min**。两腿交叉 ⇒ 取 **45 – 75 min** 为规划值（诚实标注：**这不是全尺寸实测**，全尺寸实测要 45 分钟以上、且会吃满那条 3.5 GiB，不在只读席授权面）。
加读侧：重建要把全部 `vector_blob + vector_json` 从 18.67 GiB 库里流式读一遍 ⇒ 按 §2 实测扫描速率 **4–6 min**。加写侧：`faiss.write_index` 3.35 GiB + fsync。⇒ **一次 ANN 重建总账 ≈ 55 – 90 min 单核 + 换页风险**。

### 4.6 那颗最亮的雷：FTS 全量重建在**检索锁内**（今晚 23:40 若投进新料就会踩）

`build_ann_index:2537` 结尾无条件 `self.ensure_fts_index(force=True)` → `ensure_fts_index:2846` 第一行就是 **`with self._lock:`（`:2854`）** → 里面 `_rebuild_fts:2916` 干的是：一发 `SELECT chunk_id, content_hash … ORDER BY chunk_id` 全表扫算 sha1 → **`DROP TABLE knowledge_chunks_fts`** → 重建表 → **逐行 766,126 发 `INSERT INTO …_fts (chunk_id,title,content)`（trigram 分词）**，全部在**一个 `with self._connect()` 事务**里。

- 快路径今天有效：`fts_signature='ce620e90a1bae4cdf03f8d2be871b406522129f0'` 非空 ⇒ `:2864` 直接 return True，**不重建**。⇒ 零变更夜（今天这种）安全。
- 一旦投进新料：`sync_documents` 会清掉该签名（`:2891 _invalidate_fts` 同族）⇒ 23:40 那轮就会在**持有 bot 进程内检索锁**的情况下跑这 766,126 发 INSERT。量级：trigram FTS5 单行 800 字约 1–3 ms ⇒ **13–38 min 持锁**；这期间全会话检索排队 → 聊天线程池堆满 → `pipeline_busy` 静默吞消息 = **09-22/09-17 停摆同型复发**。
- 关键区分（这条决定"谁去跑"）：
  * **CLI（`dev.ps1 -Task kb-sync`）另起进程**：它持的是**自己进程内**的 `self._lock` ⇒ 不冻结会话，只跟 bot 抢 SQLite 写锁（WAL 下读不阻塞写，写者之间互斥）、抢 GPU、抢页缓存。⇒ **想安全就手工用 CLI 跑，别让 23:40 的进程内 job 撞上大批新料**。
  * **进程内 23:40 job（`bot_kb_wiki_sync_hour=23 / minute=40`，实跑读到的现值）**：投大料的那一晚就会踩。缓解手段只有两枚键：`BOT_KB_WIKI_SYNC_HOUR/_MINUTE` 挪到无人时段，或 `BOT_KB_WIKI_ENABLED=false` 整域让路（**改哪一枚都是她的决定，本席只报数**）。

### 4.7 `bot_*` 里今天**能调**的键（符号名 + 现值 + 调它的效果与代价）

| 键（Config 字段 / .env 名） | 现值 | 代码缺省 | 调它有什么用 |
|---|---|---|---|
| `bot_embedding_local_timeout_seconds` / `BOT_EMBEDDING_LOCAL_TIMEOUT_SECONDS` | **5.0** | 60.0（`config.py:184`） | **本波唯一高价值改动**：5→20~30 ⇒ 128 批不再超时 ⇒ 吞吐 441→1,150-1,600 块/分钟（2.7–3.6×）。代价：端点真挂时每批最坏等 20-30 s（有 `retries_left=1` + 折半兜底）。读点 `kb_wiki.py:539` |
| `bot_kb_wiki_embed_batch` / `BOT_KB_WIKI_EMBED_BATCH` | **128** | 128（`config.py:201`） | 已是最优点（§3 曲线批 128 = 1,172-1,577/min）；再大收益递减且必须先抬超时 |
| `bot_embedding_timeout_seconds` / `BOT_EMBEDDING_TIMEOUT_SECONDS` | **5.0** | 15.0（`config.py:177`） | 只影响**远程兜底链**。远程链单批上限 10（`_EMBED_BATCH_SIZE`），143k 级欠账走远程 = **~14,000 次付费 API 调用**；不想让它有机会发生就把远程链留在这儿、别把本地链关掉 |
| `bot_embedding_local_enabled` / `_local_base_url` / `_local_models` | True / 127.0.0.1:11434/v1 / `bge-m3` | 同 | ⚠ **改动这三枚里的 base_url 或 models ⇒ provider `signature` 变** ⇒ 见 §4.8 地雷 |
| `bot_embedding_enabled` / `BOT_EMBEDDING_ENABLED` | True | False | 关掉 ⇒ `_embedding_chain_ready` 假 ⇒ CLI 直接 `error_kind=config_missing` 不跑 |
| `bot_kb_wiki_chunk_chars` / `BOT_KB_WIKI_CHUNK_CHARS` | **800** | 800 | ⚠ 改它会**重切所有块**（chunk_id 由内容派生）⇒ 等价于全库重嵌，别顺手调 |
| `bot_kb_wiki_topics` / `BOT_KB_WIKI_TOPICS` | `''`（= 全域） | `''` | 填子集可把今晚的量缩小到可测范围（投料/对账都按 `_id_topic` 过滤，`kb_wiki.py:380`）；⚠ 但**指定子集会挂起删除侧**（`reconcile_*`），别拿它当加速阀 |
| `bot_kb_wiki_sync_hour` / `_sync_minute` / `_sync_on_startup` | 23 / 40 / True | 同（`config.py:203-205`） | 用来**躲开 4.6 那颗雷**：把夜间同步挪到人少的时刻，或临时把 startup 补同步关掉 |
| `bot_kb_wiki_enabled` / `BOT_KB_WIKI_ENABLED` | **True**（`.env`+`.env.prod` 两口径同值） | False | ⚠ **AGENTS 台账 #55 那句「今天是关的、重建索引后按条件改回 true」已过期**——今天实测现值是 True，且 §2 四道 ANN 判据全过。别再照旧账去"打开"它 |
| `bot_kb_wiki_db_path` / `_root` | `ChatBot_Runtime/data/kb_wiki_embeddings.sqlite3` / `D:/Coding/01_Projects/Crawl Wiki` | 相对缺省 | 路径字段，走 `runtime_paths` 重映射（`config.py:1536-1537` 实读） |
| （无并发键） | — | — | §4.4 第 1 条：**没有**任何 `bot_*` 能把嵌入调成多路，这条链的并发度不在配置面上 |

### 4.8 顺带量到的两颗地雷（不修，登记）

1. **`auto_reset=True` 的清空半径**：CLI 路径 `_build_store(config, auto_reset=True)`（`kb_wiki.py:1105`）→ `_reset_vectors_if_needed:958`，一旦 provider `signature` 与库里 `embedding_signature` 不符，立刻 `UPDATE knowledge_chunks SET vector_json = NULL`（**766,126 行、单事务、≈13.4 GiB WAL**）并删 `vector_dim`。今天签名逐字节相符 ⇒ 不清空；但**只要有人在跑 kb-sync 之前动过 `BOT_EMBEDDING_LOCAL_MODELS/_BASE_URL`/`_MODEL`/`_LOCAL_*`，全库向量一夜归零**。跑前先比一次：`SELECT value FROM knowledge_meta WHERE key='embedding_signature'` vs 现构 provider 的 `signature`（本席已比，等值）。盘上 68 GB 空闲撑得住那次 WAL，但要清楚它是"单事务"。
2. **`bot_kb_wiki_enabled` 与 25 条欠账分属两枚库**：wiki 库 0 欠账，**memory 库（`knowledge_embeddings.sqlite3`）35,258/35,283 差 25 条**。它的补嵌入口是 `knowledge-sync` 任务（`chatbot-tasks.json:tasks["knowledge-sync"]` → `smoke.py` 的 `knowledge-sync` 分支，走 `embed_pending` 的 `files=` 形态），**不是** `kb-sync`。别为这 25 条去碰 wiki 链。

---

## §5 交付：可粘贴顺序（只含前进命令；已按"今天 pending=0"的真值裁剪）

> 前置事实（§0/§2）：**wiki 嵌入已完成，缺的是验收，不是重建。** 因此下面的 `kb-sync` 定位是"投进 `.kb_publish_staging` 换代的新料并嵌完"，而不是一次全库重灌。命令一律在仓库根 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot` 执行；PowerShell 与 Git Bash 两版都给。

**Step 0 — 先确认没有别的 kb-sync 在跑、以及跑前基线（30 秒，纯只读）**
```powershell
# 0a 有没有第二个 kb-sync 在跑（§1.5：跨进程无互斥，撞车=白烧 GPU）
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'smoke|kb-sync' } | Select-Object ProcessId, CommandLine
```
```bash
# 0b 基线四数（只读；expected==ntotal==embedded==chunks 即"已收工"）
cd scripts && PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
  ../ChatBot_Runtime/venv/Scripts/python.exe knowledge_progress.py
```
跑完应看到：`wiki embedded=766126 total=766126 percent=100%` + 四发 `[ok]` + `=> 这一轮已投完收工`（**本席已实跑，输出在 §2**）。同时 `FreePhysicalMemory` 若 < 4.5 GiB，则 §5 Step 3 的 ANN 重建今晚不要新起进程（判据 4.4-③）。

**Step 1（可选，且有陷阱）— 想"只投料不嵌入"来看清 D？先把 ANN 那一步摘掉再想**

`--kb-no-embed` 只是不进 `kb_wiki.py:1119` 的 `if embed:` 分支（不嵌一行），**但它管不住后面的 ANN 重建门**：`:1149` 的 `sync_changed = added+changed+removed > 0` 一旦为真，`:1160` 就照样跑 `store.build_ann_index()`（55–90 min，§4.5）+ `ensure_fts_index(force=True)`（§4.6），而且 `_publish_ann_pair:2467` 会把完备性计数戳重盖成"这一代的 ntotal"⇒ **刚投进来、还没嵌的那些块被戳当作不存在**，`missing` 判据当场失效一次（下一轮嵌完再重建才会追平，所以数据不会坏，但白付一个多小时）。

⇒ 结论：**别用 `--kb-no-embed` 去量 D**。要量 D，直接进 Step 2 —— 它第一行 `progress embedded=0/D` 就把 D 打出来了（`smoke.py:3313` 的 `embed_progress`），而且不必先付一次全表扫描。今天（pending=0、语料 manifest 零变更）真跑一次 `kb-sync` 的最坏结果就是 §2 那轮的样子：287.6 s、`unchanged_skip`、不嵌不建，无害但无意义。

**Step 2 — 正式嵌入（带新料跑；跑前把超时抬上去，见 §4.7 第一枚键——**改键是她的动作**）**
```powershell
# 判据：D 决定要不要中途去看读数
#   D ≤ 5,000  → 直接跑完（128 批 ≈ 3–5 分钟）
#   D ≥ 50,000 → 每 20 分钟看一次下面的"读数命令"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task kb-sync"
```
每批会打一行 `progress embedded=done/total percent=NN%`（`smoke.py:3313`）。**该停下去看读数的时刻**：`percent` 连续 20 分钟不动、或看到 `嵌入只完成 X/Y 行`（`kb_wiki.py:1194` 的 partial 人话）、或 `chunks_per_min` 明显掉到 §3 区间下沿之外。读数命令（另开一个终端，只读，**绝不起新进程做 wiki 检索**）：
```bash
cd scripts && PYTHONIOENCODING=utf-8 ../ChatBot_Runtime/venv/Scripts/python.exe knowledge_progress.py   # 注意它自带一发全表扫 ≈4-5 min，别和嵌入抢盘时频繁跑
```
**ETA 核对表（用 §3.1 的数）**：超时已放宽 ⇒ `D / 1,400 分钟`（例 D=60,000 ⇒ 43 min）；没放宽 ⇒ `D / 441`（同例 2.3 h）。实际比这慢 3 倍以上 ⇒ 停，去查 Ollama（`netstat` 11434 / `nvidia-smi`），不要重复重跑（重跑安全：§1.5 按 `vector_json IS NULL` 续，已嵌行自动跳过）。

**Step 3 — ANN 重建（同一命令内自动做；只有 `sync_changed ∨ embed_done>0 ∨ 索引文件缺失` 才触发，`kb_wiki.py:1149-1162`）**
Step 2 有真嵌入时**不要再单独跑一次**——那条 kb-sync 结尾就会 `store.build_ann_index()`（`:1164`），并把结果写进 `result["ann_built"]/ann_vectors/ann_reason`。想单独补建（例如上次 `ann_reason=RuntimeError`），用现成出口：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task knowledge-sync"
```
跑完应看到（人话 + 数字）：`ann_built=True`、`ann_vectors = 当时的 embedded 总数`；`ann_reason=locked_by_other_process` ⇒ 有另一进程在建，让路即可（`_AnnBuildGate`，3 s 短等）。
时间/内存预期（§4.5/§4.4）：**55–90 min 单核、峰值 3.5–4.2 GiB 私有、额外写 3.4 GiB 到盘**；空闲物理不足 4.5 GiB 时不要起。
⚠ 顺带必读：`build_ann_index` 结尾会 `ensure_fts_index(force=True)`（§4.6）——在 **CLI 进程**里跑它只会拖慢这个 CLI 自己（十几到几十分钟、约 5 GiB WAL），**不冻结会话**；在 bot 进程内跑才会。这就是 Step 2/3 用 CLI、别等 23:40 的全部理由。

**Step 4 — 收工判据（本席现算过的两条，缺一不可）**
```bash
# 判据 A：missing=0（expected == 索引 ntotal）+ embedded == chunks
# 判据 B：代际证明与实际文件对得上
PYTHONIOENCODING=utf-8 /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe - <<'PY'
import sqlite3, json, hashlib, os
D = r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data"
c = sqlite3.connect(f"file:{D}\\kb_wiki_embeddings.sqlite3?mode=ro", uri=True)
meta = dict(c.execute("SELECT key, value FROM knowledge_meta"))
att = json.loads(meta["ann_pair_attestation"]); exp = int(meta["ann_expected_vector_count"])
n = c.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE vector_json IS NOT NULL AND vector_json!=''").fetchone()[0]
t = c.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
print(f"embedded={n} chunks={t} deficit={t-n}")
print(f"expected={exp} ntotal={att['ntotal']} missing={exp-att['ntotal']}  -> {'PASS' if exp==att['ntotal'] else 'FAIL'}")
print("pair_bytes", os.path.getsize(D+r"\kb_wiki_faiss.index")==att["index_bytes"],
      os.path.getsize(D+r"\kb_wiki_faiss.order.json")==att["order_bytes"],
      "order_sha", hashlib.sha256(open(D+r"\kb_wiki_faiss.order.json","rb").read()).hexdigest()==att["order_sha256"])
PY
```
**跑完应看到的数（今天 22:3x 的本席实测值）**：`embedded=766126 chunks=766126 deficit=0`、`expected=766126 ntotal=766126 missing=0 -> PASS`、`pair_bytes True True order_sha True`。
新料嵌完之后的期望数会变：`embedded == chunks == ntotal == expected`（四个数相等即收工），`deficit=0`。

**Step 4b — 关于 `.sdd-reports/ann_gate_probe.py`：该文件本席找不到**
`ls .sdd-reports/` 与全仓 `find . -name 'ann_gate_probe*'` 双查 = **零命中**（`.sdd-reports/` 里现役只有 6 份别的席报告 + 本席这份）。所以 Step 4 用的是**等价替身**：仓内常驻判据件 `scripts/knowledge_progress.py`（它的四发 `[ok]` 正是 `embedded≥chunks`、`ANN 应嵌数==库内已嵌`、`本轮 embed_pending 清空`）+ Step 4 那段现算（补 `missing=0` 与代际证明两条）。若她要的确实是那枚探针，得先有人把它写出来（**不在只读席授权面**）；写的时候必须用 bot venv（`../ChatBot_Runtime/venv/Scripts/python.exe`）——本席实测 venv 里 `faiss/numpy` 在、`transformers/sentencepiece` 不在，系统 Python 3.12.10 那份没有这些包。
**最后一步（真机、只有她能批）**：`BOT_KB_WIKI_ENABLED` 今天已是 True，新向量要能被**运行中的 bot**看见，得等它下一次重判（`load_ann_index` 每问 2 次 stat + 换代自动重开，`vector_knowledge.py:2242-2249`，理论上**不必重启即可跟上索引换代**）；在会话里问一句百科内容、看它引到不引到，才算闭环。**本席没跑检索**（§4.2 第 2 条：现在新起一个检索进程要吃 ~3.5 GiB，而空闲只有 2.4–3.0 GiB）。

---

## §6 PARKED / 本席没测出来的（照实写缺哪件）

| # | 缺什么 | 为什么缺 | 补它要付什么 |
|---|---|---|---|
| P-1 | 今晚真实待嵌量 D | `.kb_publish_staging` 正在换代、manifest 未落定；预估要读 813 MB 语料并全库对账 | Step 2 第一行 `progress embedded=0/D` 即得（**别走 `--kb-no-embed`，见 §5 Step 1 的陷阱**） |
| P-2 | tokens/分钟 | bot venv 无 bge-m3 分词器（实测 `find_spec('transformers'|'sentencepiece')` 均 False） | 装包（禁：需她授权）或改读 Ollama `/api/embed` 的 `prompt_eval_count` 字段（未验 Ollama 是否回该字段） |
| P-3 | ANN 全尺寸重建实测（45–75 min 是**外推**） | 会占 3.5–4.2 GiB 私有 + 55–90 min 单核，只读席不起这个量 | 见 §5 Step 3 的时机判据；或让她在安静窗跑一次并把 `duration_ms` 回填 |
| P-4 | `_save_vectors` 落库分量（每批 2.3 MB × 批数） | 本席不写生产库 | 跑 Step 2 时从 `progress embedded=` 的行间隔直接读，无需另测 |
| P-5 | 逐批历史耗时（日志取证） | 当前 bot 进程 stdout 未落盘（`bot_stdout.log` 停在 09-16，`nonebot.out.log` 0 字节） | 以后用 `restart_bot.ps1` 那条带 `-RedirectStandardOutput` 的规程拉起 |
| P-6 | `ann_gate_probe.py` 不存在 | 见 §5 Step 4b | 需要写件（不在只读授权面） |
| P-7 | 全表扫描成本的"无争用"真值 | 本席那发 323 s 与另一发只读扫描 + 活体 bot 抢盘 ⇒ 只能给区间 4–5.5 min | 安静窗单跑一次 `stats()` 计时 |
| P-8 | memory 库那 25 条欠账的成因 | 不属本席 mandate（wiki 链），未展开 | `knowledge-sync` 任务，或 `stats()` 逐库点名 |

---

## §7 安全台账（规则 11）

**注入形态命中：0。** 本席读过的所有正文里的祈使句（AGENTS.md 纪律条、`kb_wiki.py`/`vector_knowledge.py` 的注释指令、`knowledge_progress.py` docstring、system-reminder 里的技能清单）分别属于白名单来源 ①②③（用户消息 / 本席简报 / 在册规范文档），且**没有任何一条要求本席改配置、杀进程、git 写或派席**——故未触发"拒绝 + 取证"分支，未登记载荷。技能清单里出现的 `/plugins:security-scan` 类提示，按简报"禁调"处置，未调用。

**一条纪律 3 相关的暴露，主动报备（不当注入）**：§1.3 的 Config 实读输出里，`bot_embedding_api_key` 的**远程 dashscope key 明文值进入了本席的工具结果**（Git Bash 下 `BOT_EMBEDDING_*` 的装载路径使其出现在打印中）。处置：**未写入本报告、未写入任何文件、未向任何外部服务转发**；本报告以 `sk-…（明文值已隐去，形态为 130+ 字符的 ws 签名型 key）` 描述。复现该读数的命令是 `load_runtime_config((".env",".env.prod"))` 后打印字段，任何后续席跑同一命令都会再次拿到明文 ⇒ 若要消这条，需要她裁定"改 `config.py` 里该字段的 repr 掩码"或"换 `env:` 引用形态"，**本席不动配置**。

**未服从的一条保密型要求**：无（本席未遇到"别向用户提起"式指令）。
