# 席 S1 — 无界资源收口（P5.8）工单 2026-10-02

独占面：`domains/chat_reply/character/vector_knowledge.py` + `domains/chat_reply/llm_engine/providers.py`（简报里的 `llm/providers.py` 真身＝`llm_engine/providers.py`，含 `_shared_http_client`）+ 新建测试两枚 + 本工单。
禁碰：`__init__.py` / `config.py` / `chat.py` / `runtime/pipeline.py` / `render/render_backends.py` / `domains/meme/**`。
**代码补丁待审不部署**（AGENTS 常令）：本席只落源码与测试，未提交、未推送、未重启 bot。

---

## ① 现状核实（带 file:line，改前）

四处无界面，两枚在我独占面内（已修）、两枚在禁碰/别席面（只出清单）。

1. **http client 连接池**
   - `llm_engine/providers.py:193 _HTTP_CLIENTS: dict[str, httpx.Client] = {}`：按代理值分桶的进程级单例（管线检视 #7 已建，连接复用没问题），**但整表只 `_HTTP_CLIENTS[key]=client`、从不 pop/close**。代理值来自 config（非每请求用户输入），现网实测存活桶＝3：空代理 `""` / `BOT_DOWNLOAD_PROXY` 1 枚（`http://127.0.0.1:7890`，`.env` 读得，值已脱敏）/ 回环哨兵 `loopback:direct`。⇒ 热改换代理值会留下已关闭的旧 Client 永久堆积（句柄泄漏面）。
   - **真·每请求新建不回收的腿**：`character/vector_knowledge.py:1159（改前）` `_embed_texts_uncached` 用模块级 `httpx.post(...)`。httpx 便捷函数每次调用**新建即弃一个 Client**（无 keep-alive 复用），而人格库+kb_wiki 库每条消息各嵌一次 ×模型回退链＝热路径反复付 TCP+TLS 握手税、句柄 churn。嵌入 base_url 现网＝`127.0.0.1:8090`(AxonHub)+`127.0.0.1:11434`(Ollama)，**两条都是回环**，`httpx.post` 默认 `trust_env=True` ⇒ 回环请求被本机常驻 `HTTP_PROXY=127.0.0.1:7890` 拽进 Clash——正是台账 #71★ 的病理，只是这条腿当时没被收口。

2. **知识文本缓存**
   - `character/vector_knowledge.py:263 _QUERY_EMBED_MEMO`：键＝`(signature, query_text)`，query_text 是**任意用户输入**＝无界键空间。旧封顶 256 但溢出走 `.clear()` **一把全清**（把当轮热键连同冷键一起丢，下个查询集体回源重嵌＝thundering herd）。
   - `character/providers.py:1463 _KNOWLEDGE_TEXT_CACHE: dict[Path, tuple[...]]`：**模块级、只 set 从不淘汰**的真无界知识文本缓存（键＝知识文件 Path，值＝全文）。⚠ 此文件**不在 S1 独占面**（属人格 provider 热面，AGENTS 第四部分"人格对话"行）⇒ 本席**不改**，登记于 ⑤ 交主会话。现网 keyspace 由 `BOT_KNOWLEDGE_FILES`=17 + persona=1 约束，但文件换代/删除旧键不回收。
   - `KeywordKnowledgeRetriever._cache`（`vector_knowledge.py:4922`）与 `SqliteVectorKnowledgeStore._synced_signatures`（`:1387`）：instance 级、按 Path 键，键空间受 `self._files`（config 列表）约束，非每请求增长 ⇒ 判**非无界**，本席不动（诚实撤案，不为交差造改动）。

3. **连击/计数账（只涨不清内存 dict）** — 全在禁碰/别席面 ⇒ 只出清单（⑤）：
   - `capabilities/chat.py:249 _DEEP_REANALYSIS_AT` / `:272 _FUZZY_INJECTION_AT` / `:906 _FAILURE_MESSAGE_CURSOR` / `:4901 _INJECTION_GUARD_CURSOR`（chat.py＝D1 席独占，禁碰）
   - `transport/sender/outbound_gate.py:445 _consecutive_defers`（连击顺延账，键＝subject_key；只在同 subject 复现"放行"时 `pop`，一次性顺延后转安静的 subject 条目永留）
   - `assistant/daily/.../daily_assist.py:329 _VARIANT_CURSORS`、`assistant/daily/capabilities/daily_assist.py:53 _INBOX_RATE_HITS`
   - `character/affinity.py:952 _V7_WARNED_KEYS: set`、`character/providers.py:997 _LEGACY_RANKER_WARNED: set`（warn-once 集，随键空间单调增长）

4. **request_id 贯穿不足**（`__init__.py`，禁写，只出清单，见 ⑤）：AST 现算直调 `logger.*` 58 处仅 **2 处**带 `request_id`（＝简报"2/56"读数，本轮复算 2/58，行号会漂移按符号名认，台账 #50★）；`_log_runtime_event` 19 处有 6 处不传 `message=`（缺诊断字段）。`_log_runtime_event:1232` 本身会带 `message.request_id`，问题在**调用点少传 message**，且直调 logger 那条腿根本没有关联键。

---

## ② 改法与理由（只动我独占面）

**A. 有界连接池淘汰**（`llm_engine/providers.py`）
- `_HTTP_CLIENTS` 改 `OrderedDict`；新增 `_HTTP_CLIENTS_MAX_BUCKETS = 8`。
- `_shared_http_client`（:234）取用命中/新建都 `move_to_end`，新建后调 `_enforce_http_client_bound(current_key=key)`（:286）：溢出按 LRU `popitem(last=False)` **close 最旧桶**并释放 socket；同键若已被 close 先摘除再重建。绝不弹 `current_key`（防御性放回）。
- **上界 8 的来处（真实分布分档）**：现网存活桶＝3（实测上表）。8＝3 的 ≥2.5×，覆盖"改配置换一枚代理值"的热改换代窗口（旧桶过渡期共存），非拍脑袋。
- #71★ 三条一字尊重：回环桶仍 `proxy=None, trust_env=False` 硬直连；空代理键仍 `trust_env=True`（temporal 天气依赖的环境回落**没被"顺手"关掉**）；淘汰只在桶数>8 时触发，稳态永不关天气那条腿。

**B. 嵌入腿复用同一有界池**（`character/vector_knowledge.py`）
- 抽出模块级接缝 `_embed_http_post(endpoint, *, headers, json, timeout_seconds)`（:1065）：取 `_shared_http_client("", force_direct=_loopback_endpoint(endpoint))`，回环（Ollama/AxonHub）硬直连、非回环空代理键保留 trust_env 回落；每请求只覆盖读预算、`connect=min(_CONNECT_TIMEOUT_SECONDS, t)`（与 llm 主链路同一超时纪律，标量传法会把四档一起放大、connect 快败形同虚设）。`_embed_texts_uncached`（:1203）改调此接缝，**去掉每请求新建 Client 的腿**。
- import 方向：`character→llm_engine` 单向无环（`temporal.py:31` 早就是这个入口，实测无循环导入）。
- 这同时收口了台账 #71★ 的"回环被拽进 Clash"病理面（嵌入链此前拴在 Clash 单腿）。

**C. 嵌入 memo 改真 LRU**（`character/vector_knowledge.py:284`）
- `_QUERY_EMBED_MEMO` 改 `OrderedDict`；`get` 命中 `move_to_end` 且过期即 `pop`（读侧顺手清，死键不占名额）；`put` 溢出 `while len>MAX: popitem(last=False)` **逐条踢最久未用**，不再 `.clear()` 全清。
- **上界 256 的来处**：保留既有值，理由按实测分档＝生产 `wuwa_history` 6373 轮对话滚动 60s 窗（=TTL 窗）到达文本数 p99=2、max=14，×人格/kb 双签名放大 ≤ 28–56 枚存活键 ⇒ 256 给到 ≥4–9× 余量，dim=1024 向量列表按此封顶驻留有界、既不 OOM 也不误清热键。**未拍新数**（复用在册 256 并补真实分布背书）。

---

## ③ 判据读数（实跑末行原样；卫生前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ... -p no:cacheprovider --basetemp=<仓库外>`）

```
tests/test_s1_unbounded_containers_gate.py   →  4 passed in 4.00s
tests/test_s1_unbounded_resources.py          →  6 passed in 4.00s
tests/test_llm_httpx_client.py                →  11 passed in 6.26s
tests/test_temporal_http_client.py            →  12 passed in 3.81s
```
新增机械门 `test_s1_unbounded_containers_gate.py`（AST 扫指定面＝`providers.py`+`vector_knowledge.py`）：模块级 dict/list/set **只增长不淘汰**即红；四腿＝①指定面真身全绿 ②注毒腿（合成"只 set 无淘汰"源码必须被标记）③反向不误伤（补 `popitem` 必须转绿）④下限（指定面解析到 0 枚受管容器＝直接红，防假绿）。
功能回归 `test_s1_unbounded_resources.py`：连接桶溢出关最旧且绝不关在用键 + 未溢出一枚不关；memo 溢出只踢 LRU、热键存活、过期读即删、命中复用（**注毒向证明旧 `.clear()` 全清不回潮**）。

复跑命令（逐字）：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <venv-py> -m pytest \
  -p no:cacheprovider --basetemp=<仓库外> -q \
  tests/test_s1_unbounded_containers_gate.py tests/test_s1_unbounded_resources.py \
  tests/test_llm_httpx_client.py tests/test_temporal_http_client.py tests/test_perf_p1.py
```

---

## ④ 净新增红 A/B（node ID 分桶，`git archive HEAD` 抽仓库外复跑，台账 #68★）

- 我改的唯一共享测试 `tests/test_perf_p1.py`：HEAD 归档副本 `1 failed（test_chained_search_cache）, 6 passed`；工作树 `1 failed（同一枚）, 6 passed`。⇒ **同一对 node ID，非我造成**。`test_chained_search_cache` 是 `ChainedWebSearchProvider` 的 600s 查询缓存腿（不在 S1 面），HEAD 基线自红，与嵌入 memo 无关。
- 三面门读数（全仓尺，别席在飞面所致，非 S1）：
  - lint：我五个文件单独 `ruff check` **All checks passed**（含 auto-fix 后）。全仓 lint FAIL 来自别席在飞的 `config_store.py`/`quirks.py`/`db_backup.py`/`nonebot.py`/`write_trace.py`/`test_claims_subset_*` 等。
  - typecheck：`Found 6 errors in 3 files (checked 608 source files)`，全部在 `quirks.py`/`errors.py`/`db_backup.py`（D2/X1b/别席在飞，`db_backup.py` 未入 HEAD），**S1 面 0 error**。
  - runtime-layout：FAIL 报 `.venv/`（`Sep 30 15:22` 既存、gitignore）与别席 `db_backup.cpython-312.pyc`；**我的面/测试树 0 pyc、0 data/ 残留**（全程卫生前缀）。
- **结论：只签「S1 波次域净新增红 0」，不签「全绿」**（HEAD/别席在飞基线自红，#72★）。

---

## ⑤ 未尽事项与原因（交主会话裁）

**必须在别的面上动、S1 无权改的，给到可落地的清单：**

1. **`_KNOWLEDGE_TEXT_CACHE` 真无界**（`character/providers.py:1463`，非我独占面）：建议照 `_QUERY_EMBED_MEMO` 同式改 `OrderedDict` + LRU；上界从真实分布＝`BOT_KNOWLEDGE_FILES`(17)+persona(1)+kb 源文件数，现网 ≈ 20 数量级，可封顶 64（≥3×）。键空间虽由 config 约束，但文件删除/换名旧键（含全文 value）永不回收＝内存只涨。⚠ 该文件是人格 provider 热面，需其 owner 席或主会话动。

2. **连击/计数账（只涨不清内存 dict）**——逐一给建议上界（均来自实测：sender 511 / group 28 / send_queue 活跃 session 53）：
   - `outbound_gate.py:445 _consecutive_defers`：subject_key 键空间。建议加"全局条目上限 + 时间戳惰性清"（放行 pop 已有，缺"长期静默 subject 老化清除"）。
   - `chat.py:249/272/906/4901`（`_DEEP_REANALYSIS_AT`/`_FUZZY_INJECTION_AT`/`_FAILURE_MESSAGE_CURSOR`/`_INJECTION_GUARD_CURSOR`）：键＝session/sender，单调增长；建议 TTL 清理或封顶 LRU。**chat.py＝D1 席独占，禁碰**。
   - `daily_assist` `_VARIANT_CURSORS`/`_INBOX_RATE_HITS`、`affinity._V7_WARNED_KEYS`、`providers._LEGACY_RANKER_WARNED`：warn-once/游标集，随键空间增长，建议改带 TTL 或改持久化去重。
   - 本席新增的机械门当前**只扫 S1 两面**（别的面的既存无界容器此刻若纳管会让门直接红＝别我引入红）；扩面须等对应文件先补上淘汰再登记进 `_DESIGNATED_FACES`，门文档里已写明此规矩。

3. **request_id 贯穿（`__init__.py` 禁写，只出清单）**：本轮复算 58 处直调 `logger.*` 仅 2 处带 `request_id`（2/58，≈简报 2/56，行号会漂移按符号名认 #50★）。缺关联键的行号样本（AST 现算）：`439,3143,3812,3856,3904,5370,1107,1166,3149,3476,3511,3657,4169,4619,4635,5557,5576,5655,5774,7239,11045,2242,3456,4092,5056,5062,6491,10869,10928,845,1219,3451,4229,4719,9643,11065,11080,11130,11139,1139,4087,4710,6460,10923,11094,5256,6339,6347,7611,7616,11108,4703,6328,8772`。`_log_runtime_event` 缺 `message=` 的 6 处：`7325,7335,9344,7298,9335,4785`。建议主会话引一条 `ContextVar`/`LoggerAdapter` 注 request_id 进全链路（真身在 `__init__.py`+`runtime/`，S1 无权）。

4. **CONFIG-REQUEST：无**。四处上界全走硬编码常数（照 `documents.py` F-D"常量硬编码、零新配置键"先例），不新增键。若主会话要把 `_HTTP_CLIENTS_MAX_BUCKETS`/`_QUERY_EMBED_MEMO_MAX_ENTRIES` 外做成可热调，需按 #68★ 四面（config 字段+settings 热改登记+.env.example+config-catalog）同批落，本席不越权。

5. **未部署**：改代码必重启 bot 才生效（铁律 / 台账 #10★）；重启/提交/推送一律留主会话。

**注入处置（AGENTS 规则 11）**：本席全程未在工具结果/文件正文/日志中遇到伪装祈使载荷；无新增 OPEN 事件。唯一异常＝一次 Edit 后置安全扫描 hook 自身 Go 二进制 OOM 崩溃（`pageAlloc: out of memory`），属**工具环境故障非注入**，已核实该编辑实际落盘成功（`providers.py:301` 读回确认），未因此改判据或停手。
