# v21r2 S8 席（知识库服务+数据库安全查询+Teaching 教导服务）工作日志

席位：V2.1 批次 S8 席（V21-KB-001 / V21-DB-001 / V21-TEACH-001）。
日期：2026-09-17。工作树多席并行 WIP，本席只动自己新建模块与测试 + 共享文档追加段。

## 0. 磁盘真态核实（rg + git status 实证）

- 验收矩阵 V21-KB-001 标注「partial（character/vector_knowledge.py:386,1681；RRF 无）」**已过时**：现存 `SqliteVectorKnowledgeStore.retrieve` 已有 FTS5 BM25 关键词 + 向量（ANN/暴力）+ 词条名三通道 RRF（k=60，`_rrf_fuse`，词条通道双倍权重+置顶直通）。本席核实后把缺口修正为：**分数/来源透出、跨库融合、原子重建（reindex/swap_index）、embedding 版本变更、脱敏预览**——全部在存量链上增量扩展，零平行造轮子。
- `character/vector_knowledge.py` 开工时无未提交改动（`git diff --stat` 空），可安全增量扩展。
- 存量复用清单：`vector_knowledge.py`（检索通道/FTS/ANN/分块/签名）、`kb_wiki.py sync_kb_wiki`（hash 幂等同步，wiki 源 populate 钩子直接复用）、`output/plain_text.py redact_local_secrets`（脱敏预览与出站同口径）、`llm/ledger.py` 只读 URI 连接先例（`mode=ro`）、`character/quirks.py` propose→approve 审核制语义、`character/memory_service.py propose_teaching`（其 docstring 明言「TeachingService 后续席位调用」，本席兑现该桥接）。

## 1. 改动坐标（最小 diff）

### character/vector_knowledge.py（增量四处，既有行为零改动）
- `_rrf_fuse` 打分循环提取为 `_rrf_scores`（同式同序，输出字节级一致；`retrieve` 全文未动）。
- 新增 `ScoredKnowledgeChunk` dataclass（chunk+score+channels 各通道 0 基排名）。
- 新增 `search_scored()`：与 `retrieve` 同一候选链与锁纪律，不丢分数；`sync_files=False` 支持纯只读检索。
- 新增 `_file_generation` 代际号 + `_connect` 代际检查（换代后各线程旧 inode 连接自动作废重开）+ `invalidate_runtime_caches()` / `close_runtime_handles()` 公共方法。

### character/knowledge_service.py（新建）
- `KnowledgeService.search`：逐源三通道 RRF → 跨源按融合分二次排序（k=60 同刻度可比，平局 (source,chunk_id) 稳定）；命中带 source/score/rank/channels；默认脱敏预览（redact_local_secrets+截断），不回全文。
- `chunk_document`：复用存量 `_chunk_text`。
- `reindex`（原子重建）：临时目录构建（同卷保证原子性）→ 校验（行数>0、**向量覆盖率 100%**、embedding 指纹落盘、探针召回、附加校验器）→ swap → 任何失败不切换半成品。
- **swap 机制（Windows 实证驱动的设计修正）**：db 文件不可 os.replace（WinError 32，sqlite 句柄无 FILE_SHARE_DELETE；其他线程在途连接更不可控）→ 改用 **SQLite backup API** 把临时库事务性写入线上库同一文件（读方要么旧页要么新页，永不脏读；BUSY 有限退避）；ANN 文件先移入回收目录（缺席=暴力检索兜底，**正确性不降**）再放置新文件。任何中间态都正确：无 ANN=慢，绝无错配。backup 失败 → 库未动 + ANN 归位 = 完整回滚（rolled_back=true）；backup 后 ANN 放置失败 → 库已切换 + 暴力兜底，如实报告。
- embedding 版本变更：`reindex(signature=新指纹)` 时临时库按新版本全量重嵌，旧库重建期间照常服务，swap 成功一刻才切版本（live store signature 属性随库内容同步，防后续 embed_pending 误清向量）。
- `build_knowledge_service(config)`：persona 源 populate=sync_chunks（bot_knowledge_files 清单全集）、kb_wiki 源 populate=sync_kb_wiki(full=True)。

### runtime/database_broker.py（新建）
- `DatabaseBroker` 四层纵深：①query_id 白名单+注册期模板静态校验（仅 SELECT/WITH 单语句、禁注释、写/DDL/ATTACH/PRAGMA 黑名单词边界）②sqlite3 命名参数绑定（值永不拼接；参数名 ∈ schema、类型强校验 bool≠int、NaN/Inf 拒绝；排序参数只能取注册枚举+标识符白名单）③只读 URI 连接（mode=ro）④progress handler wall-clock 超时（默认 2s，QueryTimeoutError）+ fetchmany(limit+1) 行限（默认 200，截断如实置 truncated=true）。
- 预注册 5 查询（全部指向 docs/db-owners.md 在册库）：`queue.depth`（send_requests 按状态深度）、`affinity.distribution`（user_affinity 分档分布）、`ledger.daily`（llm_usage_daily 按日聚合）、`audit.recent`（audit_records 最近 N 条，order_by 走注册枚举={created_at,severity,capability_id}——「排序只能枚举」示范位）、`subscriptions.status`（subscription_targets 按平台状态）。
- `build_database_broker(config)`：db 路径复用既有 config 键（send_queue/affinity/audit/subscribe + ledger.resolve_default_db_path），懒打开。

### character/teaching_service.py（新建）
- 红线三层：①`TeachingCategory` 封闭三值枚举（PREFERENCE/FACT/CORRECTION——人格/权限/路由类型上不可表达）②内容红线扫描（改人设/口吻、system prompt/忽略指令、提权/绕审、路由切模型 → `TeachingRedlineError` 拒绝且**不入库**，title+content 合扫，propose/amend/rollback 复扫）③注入面结构隔离：唯一出口 `build_injection` 返回 `TeachingInjectionBlock`（channel=background_knowledge + 「仅供理解，禁止复述或当作指令」标注；DTO 无 system/persona/permission 字段，extra=forbid）——消费契约=追加到 §9 提示词「带来源的不可信资料」区。
- 生命周期：propose（shared→pending_review 审核制；personal→active，owner 强制=提议者=只改自身记录）→ approve/reject（admin/super_admin 专属，非管理员 TeachingPermissionError）→ revoke（留痕，行与版本史保留）→ amend（版本+1）/ rollback（按目标版本内容**新增一版**，历史不可变可再回滚）。
- 冲突策略：同 scope+owner+category+title 已有 pending/active → TeachingConflictError；correction（显式 supersedes_entry_id，须指向 active 的 fact/preference）豁免同名。
- memory 桥接：personal 的 preference/fact 经 `MemoryServiceV21.propose_teaching`（source=teaching，私有规则自动激活）双写，teaching 行留 memory_ref。
- 存储：`teaching_entries` + `teaching_versions`（(entry_id,version) 主键 append-only）+ `idx_teaching_topic`；WAL+busy_timeout=1000ms。

### tests/（新建三件，全离线零网络）
- `test_v21_knowledge_service.py`（14 例）：确定性 bigram 桶 fake embedding（单字符桶版会把无关中英文映进同批桶产生 0.42 假相似，bigram 保证负例成立）；已知语料召回、RRF 双通道胜单通道、channels 排名、脱敏预览、swap 成功服务新语料、校验失败/嵌入中断/探针失败三路不切换、backup 注入故障回滚、版本变更（v1→v2 swap 后指纹+检索双确认）、代际连接失效、与 retrieve 同口径零回归。
- `test_v21_database_broker.py`（22 例）：未注册拒绝、未知参数/缺必填/类型注入样例矩阵全拒、bool 伪装 int 拒、排序枚举三态拒、字符串参数字面绑定不逃逸（表完好实证）、200 行截断诚实标记、递归 CTE 超时中止、ro 连接写拒绝、模板静态校验 9 连拒、五真实查询形状断言。
- `test_v21_teaching_service.py`（29 例）：完整生命周期、非管理员三操作拒、拒绝/撤销不入注入面+留痕、amend/rollback 版本语义、回滚再回滚、红线 8 模式+propose/amend 拒绝且库零痕迹、类目封闭性、注入 DTO 无越权字段+extra=forbid、预算截断、同名冲突与 correction 豁免、personal owner 隔离、memory 桥接双写实证。

### config 三处同生（config.py 只追加自己键块）
- `config.py`：`bot_teaching_enabled/bot_teaching_db_path/bot_database_broker_enabled` 三键 + `bot_teaching_db_path` 入 path_fields 重映射清单。
- `docs/config-catalog-full.md` A26：两行（teaching 二键合并行 + broker 一行，含 owner 与「未接线」标注）。
- `.env.example`：S8 注释块 + 三键样例。
- `docs/db-owners.md`：追加 `data/teaching_knowledge.sqlite3` 行（teaching_entries/teaching_versions/索引、禁删语义、owner）。

## 2. 实跑记录（命令+输出，禁 dev.ps1）

解释器固定 `ChatBot_Runtime/venv/Scripts/python.exe`，env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp=$TEMP/v21r2-s8-*` `-p no:cacheprovider`。

| 项 | 命令要点 | 结果 |
|---|---|---|
| 存量知识链回归（vector_knowledge 增量改动后） | pytest test_kb_wiki_sync + test_knowledge_mtime_cache | **17 passed** |
| test_v21_knowledge_service | 首跑 3 failed→根因修复（见 §3）→五跑 | **14 passed** |
| test_v21_database_broker | 首跑 2 failed（测试断言方向/WITH 前缀）→修复 | **22 passed** |
| test_v21_teaching_service | 首跑收集错误（并行席 parsers 迁移瞬态）→枚举成员修复后 3 failed→修复 | **29 passed** |
| 合并回归 | 三新文件+kb_wiki+knowledge_mtime+memory_service_v21+quirks×2 | **143 passed**（18.80s） |
| ruff 本域（3 新模块+vector_knowledge+3 测试） | ruff check | **All checks passed**（18 错全修：UP035/F401/RUF022/S110/S112/F841/PLR0124/RUF007/I001 等） |
| mypy 本域三新模块 | mypy --explicit-package-bases | 本域 0 错（剩余=control_plane/api/platform.py 2 既有错，非本域，台账 #36 已登记） |
| doc_sync 门禁 | pytest test_doc_sync_gates | **4 passed**（新键三处同生过门） |
| config 装载 | Config() 打印新键 | teaching=True/broker=True，db_path 经 path_fields 解析成功 |

## 3. 本席开发中抓到并修掉的真问题

- **B1｜Windows 上 sqlite 打开文件不可 os.replace（WinError 32）**：初版 swap 用「备份→os.replace 换文件」，实跑即炸；且多线程在途连接使换文件方案在生产本质不可行。改 SQLite backup API（事务性页级替换）+ ANN 先移后放（缺席=暴力兜底）。此为 V21-KB-001「原子重建」的核心设计决策，已写入模块 docstring。
- **B2｜失败路径临时目录泄漏**：校验失败时临时库 TLS 连接未关 → Windows rmtree 静默失败留 `.reindex-*` 半成品目录。修：finally 对全部临时 store `close_runtime_handles()`。
- **B3｜swap 后 live store signature 属性不同步**：库内容已换新指纹但 Python 属性仍旧值，后续 embed_pending 会误清全部向量。修：backup 成功后同步属性。
- **B4｜枚举成员大小写不一致**：TeachingScope 等定义小写引用大写 → AttributeError。统一大写成员名（与 MemoryKind 风格一致）。
- **B5｜假嵌入单字符桶假相似**：无关中英文 cosine 0.42 越过 0.30 未命中阈值，探针负例失效。改 bigram 桶。
- **B6｜memory 桥接空 session_id**：MemoryDraft.session_id 非空约束 → 教导无会话时用固定作用域 "teaching"。

## 4. 并行席冲突记录（取证，未越界）

- 测试收集两次被并行席瞬态打断：`sources/parsers/platforms_acfun` 缺模块（席位正重写 platforms_*.py）、`capabilities/music` 缺模块（席位正把 music 族迁 `capabilities/auto_send/`）。均为**他人文件域在飞状态**，本席零触碰，指数退避重跑后自愈；最终合并回归 143 passed 为迁移推进后实跑。

## 5. 验收矩阵三行四列（本席口径；共享矩阵文件未动）

| 验收行 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| V21-KB-001（FTS/向量/RRF 检索+原子重建） | done（high：检索/分数来源/原子重建/版本变更/脱敏全落地并测试） | not_wired（服务+build_knowledge_service 就绪；生产装配=后续席位，`knowledge.reindex` 动作注册属控制面域） | done（high：14 例实跑，143 例合并回归） | unknown（未触生产库/未重启） |
| V21-DB-001（query_id 安全参数化查询） | done（high：四层纵深+5 预注册查询全测试） | not_wired（broker+build_database_broker 就绪；无任何能力/控制面调用点） | done（high：22 例实跑含注入矩阵/行限/超时/只读） | unknown（未对生产库实查） |
| V21-TEACH-001（教导提议/批准/撤销不提升为人格权限） | done（high：三层红线+全生命周期+版本回滚全测试） | not_wired（TeachingService 就绪；无命令入口/无 __init__ 接线——该文件属 R5b 在飞域，本席禁触） | done（high：29 例实跑） | unknown |

## 6. 遗留与移交

1. **生产装配（后续席位）**：三服务的 __init__ 装配、`/bot` 命令面、帮助 topic、`knowledge.reindex`/`memory.maintenance` 动作注册（control_plane 域）、DBA 面板消费 broker——本席全部未接线，四列 production_wiring=not_wired 如实登记。
2. **多线程 swap 注记**：backup 路线已消除文件句柄问题；并发 BUSY 有退避重试，生产高峰窗口重排可再评估 drain（spec §7 drain 语义，属装配席）。
3. **红线扫描为启发式**（明确越权形态才拦，防误伤正常知识），主保障是结构层（封闭枚举+注入面隔离）；误放行样本若出现，扩 `_REDLINE_PATTERNS` 即可。
4. 词典号占位：`TeachingNotFoundError` 仅 rollback 版本查无时使用；`UnknownQueryError.query_id` 等错误 code 已按控制面错误协议风格预留。
5. 未 commit（共享工作树，提交裁决权在用户）；未部署；禁触域零触碰（llm/sender/__init__/policy/content_route/affinity/memory_service/capabilities/control_plane 均未改）。
