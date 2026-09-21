# 人格库按源配额（per-source quota）— 施工报告

状态：**完成（2026-09-29 接席收尾）**——前任席位落码后死于网络中断，留 5 红 + mypy :1739；本席五红全绿（19/19）、mypy 本文件净、False=逐字节跨版本实证、邻座守卫与相关面 93 passed 全绿。未 commit（共享工作树，提交裁决权在用户）。

## 0. 阵亡席遗产处置

**（本席更正）**：本节原判「阵亡席未留任何配额半成品」**不成立**——盘上 `vector_knowledge.py` 已有完整配额实现（`_source_family`/`_quota_family_cap`/`_quota_persona_reserved`/`_select_within_source_quota`/`_family_of_chunks`/`_fused_ids_for_limit`，:60-169/:1566-1628），`tests/test_knowledge_source_quota.py` 19 例已落盘（5 红 14 绿），:2968 人格 provider 已置 `source_quota_enabled=True`。下方原始记录保留为历史。

原始记录：结论：**阵亡席未留任何配额半成品，从零开工；工作树 M 标记全部是已交付他席的未 commit 改动，一律不扰动。**

- `git status --porcelain` 两文件确为 M：`providers.py`(+5/-1)、`vector_knowledge.py`(+432/-75)。
- 甄别：`git diff | grep -iE "quota|per_source|source_id|配额|保留位|槽位"` **零命中**；`git diff -w` hunk 逐一比对，全部落在 F5 席（ANN 原子发布：`_AnnBuildGate`/attestation/缓存失效）与 kb_wiki 导入路径修复+`logger.exception` 留痕（providers.py，F3/装配席）改动面上。
- `tests/` 无配额相关未跟踪文件；`test_content_parser_quota_throttle.py` 是另一会话的 M 文件（任务书明示勿动），未当遗产、未修改。

## 0b. 本席五条红测试逐条判定（先读后判，实跑诊断）

诊断命令：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests/test_knowledge_source_quota.py -q --basetemp=$TEMP/q5-diag -p no:cacheprovider` → 5 failed/14 passed，与前席记录一致。

| 红测试 | 判定 | 依据 |
|---|---|---|
| test_disabled_quota_reproduces_legacy_rrf_exactly | **测试替身签名错**（非断言错非缺件） | `TypeError: lambda() takes 1 positional but 2 given`：`_stub_channels` 把 `_vector_candidates` 桩成 `(q)`，真实方法本波已扩为 `(q, scores_out=None)` 且 retrieve 恒传第二参——桩不匹配真实契约，行为断言（融合序一致+人格 0 占）不动 |
| test_enabled_quota_reserves_persona_slots | 同上 | 同一 TypeError（:1666） |
| test_pinned_entries_keep_direct_hit_position | 同上 | 同一 TypeError；且桩不回填 scores_out 会让保留位证据门永空（真实现三路径 ANN/numpy/brute 均回填，:1882/:1912/:1860） |
| test_search_scored_shares_quota_chain | 同上 | TypeError @:1740 |
| test_persona_queries_gain_and_encyclopedia_untouched | **实现缺件（证据门用错阈值）** | 实测：人格块**在池内**（RRF rank 7~19/共 20~27）但 4/6 查询 `promotable=N`——门径写成 `cos >= min_cosine_threshold(0.30)`，那是**整库未命中判据**（retrieve :1689 低置信空结果用），与「池内保位」是两个概念；正确门径=池内且有任何余弦重叠（>0）或词汇通道命中，即 :70 契约「仅当候选池中存在 persona 块时生效」。词袋假嵌入下同义改写 cos≈0.05~0.13，0.30 门把设计意图本身锁死（改期望值=迁就实现，违今日规矩，不动测试断言） |

## 1. 代码现状勘察

- 主链路：`retrieve()`（现 :1348-1406）三通道 → `_rrf_fuse(vector_ranked, keyword_ranked, top_k, bonus_ids=entry_ranked)`（词条名通道双倍权重，`_rrf_scores` :504）→ 整段精确词条 `pinned_ids` 直通头部 → `_fetch_chunks` 懒加载。`search_scored()`（:1408）同链不丢分数，供 `KnowledgeService`（v21 服务面，`bot_knowledge_service_enabled` 缺省 False）。
- **关键纠偏**：人格库内部竞争的不是 8 槽——`.env` 实况 `BOT_KNOWLEDGE_TOP_K=5`（config 缺省 4），**8 是跨库合并后的提示块总闸**（`bot_knowledge_max_chunks`，`FileCharacterContextProvider._build_knowledge_chunks` 消费）；`MergedKnowledgeRetriever.retrieve` 轮转（人格流占合并后 1/3/5/7）意味着**人格库内部 rank5 永远进不了提示词**。
- 候选池规模（top_k=5 时）：向量 `max(top_k*4,20)=32`、关键词 `top_k*2=10`、词条名 `top_k*3=15`。RRF 融合只在候选池内排序，配额同样只能在池内保位（见 §3 边界）。
- 改动面收敛依据：`SqliteVectorKnowledgeStore(` 全仓构造点 6 处——`vector_knowledge.py:2622`（人格 provider，**本席可改**）、`kb_wiki.py:575`（禁改只读）、`knowledge_service.py:354/536/565`（不在本席归属）、`smoke.py:2884`（热区外不动）。故配额做成**构造参数（缺省关）+ 人格 provider 装配时显式开**——生产人格路径缺省生效，其余库逐字节不变，不属于「又一个默认关的开关」（效果开关在 provider 装配处即为 ON，非 env 键）。

## 2. 实测：source_id 分布与 th-* 陷阱

生产库 `ChatBot_Runtime/data/knowledge_embeddings.sqlite3` 只读实测（`mode=ro`，零写入，嵌入由补嵌进程在跑、不影响计数）：

- `knowledge_chunks` TOTAL **35479**、独立 source_id **17** 个。
- 分布：战双 24155 / 鸣潮 6647 / th-01…th-12 **12 个独立源共 4274**（单源 327~387）/ 守岸人_核心知识 201 / 守岸人_人格与表达规范 172 / ai-kb-operations-manual 30。**人格本体 373 块，与任务书一致；th-* 确为 12 个独立 source_id，「每源至多 N」陷阱实锤**。
- `chunk_id` 为 16 位 hex（样本 `0000928a…`）；`source_id=path.stem`（`sync_chunks` :994）。
- `.env` `BOT_KNOWLEDGE_FILES` 实况 19 个文件：2 百科 + 2 守岸人 md + 12 th-XX + 1 运维手册——17 源=19 文件里百科 2 文件在库街区分卷所致（24155+6647+4274+373+30=31474+…=35479 ✓ 全对上）。

## 3. 方案形态与粒度裁定

（前席 §3 空缺，本席补全——实测定形，全部依据 §0b 表五条红的诊断数据）

- **族粒度**：`th-01…th-12` 并一族（`on-this-day`，正则 `^th-\d{1,2}$` 全匹配，`th-1x`/`th-013` 不并）；`守岸人*` 两文件并 `persona` 族；其余源各自一族。前席 `_source_family` 原样保留。
- **选择层三段式（纯函数 `_select_within_source_quota`）**：A 融合序填槽（persona 不封顶、其余族 cap=ceil(limit/2)）；B persona 保留位 reserved=min(2,limit//2)（不足则队尾淘汰非 persona 补位）；C 溢出回填保「拿满槽」。本席新增两点：**`hard_cap_families` 参数**（on-this-day 族连溢出回填也不越 cap——12 源并族陷阱的收口，缺省空集=前席纯函数测试语义零改动）与**输出三段序**（cap 内主选 → persona 全部 → 溢出回填；纯融合序会把弱证据 persona 沉到溢出块之后，`MergedKnowledgeRetriever` 轮转下流内第 5 位永远进不了提示词前 8，保留位必须在流内**位置**上成立）。
- **链级三层证据模型（`_fused_ids_for_limit`，本席核心补件）**：LEGIT（词汇通道命中 或 cos ≥ 0.30 整库地板）参与 cap 竞争；WEAK（池内 cos>0 但低地板无词汇，含哈希词袋 md5 桶碰撞伪装块——实测「战双 信号 配置」查询里 th 块 cos=0.146 纯碰撞）只做两件事：persona 保留位候选（追加进选择输入队尾）、兜底溢出回填；零证据块出局。前席把 persona 保位门径误写成 `>= min_cosine_threshold`（整库空结果判据，两概念混用）→ 同义改写场景保留位永锁死；本席实测语料（_TokenEmbedder 词袋）人格块 cos 0.05~0.13 全被挡死、4/6 人格查询零收益，是五条红里第 5 条的真根因。
- **全 WEAK 池 = 逐 id 等于关配额**（融合序截断），纯百科单源查询由 C 段溢出回填保零退化；`source_quota_enabled=False`（kb_wiki/smoke/KnowledgeService 等全部其余构造点）走 `_rrf_fuse` 原路径，§7 有跨版本逐字段实证。
- **接线**：唯一开关点=人格 provider `build_vector_knowledge_provider`（vector_knowledge.py:3041 一带，前席已落 `source_quota_enabled=True`，本席核验不动）；`providers.py` 无需改动（配额在 store 装配面，不在 provider 消费面）。

## 4. 改动清单（文件/行号，本席增量）

| 文件 | 位置 | 改动 |
|---|---|---|
| `plugins/.../character/vector_knowledge.py` | :83-88 | 新增 `_QUOTA_HARD_CAP_FAMILIES = frozenset({_ON_THIS_DAY_FAMILY})` |
| 同上 | `_select_within_source_quota` :103-207 | 新增 `hard_cap_families` 形参（缺省空=前行为）；B 段淘汰补 `counts` 回退；C 段硬顶族不越顶；输出三段序 `_order_key`（persona 保留位钉流内尾部） |
| 同上 | `_fused_ids_for_limit` :1637-1726 | ON 分支重写为 LEGIT/WEAK/零证据三层；WEAK persona 追加输入队尾；链级兜底回填（硬顶族 enforce 轮 + 末轮放开拿满槽）；OFF 分支零改动 |
| 同上 | :1746（原 :1739） | mypy 修复：`vector_scores: dict[str, float] \| None = ...`（search_scored 内，retrieve 侧前席已有注解） |
| `tests/test_knowledge_source_quota.py` | `_stub_channels` | 向量通道桩对齐真实契约 `(query_vector, scores_out=None)` 并回填 scores_out（真实现 ANN/numpy/brute 三路径均回填，:1882/:1912/:1860）；**断言值零改动**；ruff 三件（I001 --fix / C405 / RUF059） |
| 生产库 | **零接触** | 全程未打开 `ChatBot_Runtime/` 下任何 SQLite（连 mode=ro 都不需要，§2 分布数据为前席已录得）；无嵌入/knowledge-sync/ANN 重建触发 |

同文件两笔邻座改动（`sync_chunks` 空清单守卫、`_embed_all_pending` 冷启动预热）本席未碰，各自守卫套件实跑见 §7。

## 5. 验收①：固定查询集前后对比（tmp_path 合成语料 139 块 + 确定性词袋嵌入，12 查询 ≥6 条要求）

| # | 类型 | 查询 | 人格md占槽 前→后 | th 占槽 前→后 | after 明细 |
|---|---|---|---|---|---|
| 1 | 人格向 | 你怎么看鸣潮的剧情 | **0→1** | 0→0 | 鸣潮×4, 人格规范 |
| 2 | 人格向 | 你平时说话的方式是什么样的 | 0→0（人格块 cos=0.0 无证据不入池，诚实不硬塞） | 0→0 | 鸣潮×5（=before） |
| 3 | 人格向 | 你是谁？你的身份是什么 | **0→1** | 0→0 | 鸣潮×4, 核心知识 |
| 4 | 人格向 | 你和漂泊者之间是什么关系 | **0→1** | 0→0 | 鸣潮×4, 核心知识 |
| 5 | 人格向 | 历史上的今天你怎么看 | **0→1** | 1→1 | th, 鸣潮×3, 人格规范 |
| 6 | 人格向 | 今天心情怎么样 | **0→1** | 0→0 | 鸣潮×4, 人格规范 |
| 7 | 百科向 | 鸣潮 忌炎 图鉴 | 0→0 | 0→2 | 鸣潮×3, th×2（cap 生效仍全百科） |
| 8 | 百科向 | 鸣潮剧情 今汐 条目 | 0→1 | 2→2 | th×2, 鸣潮×2, 人格规范 |
| 9 | 百科向 | 战双 万事 构造体 档案 | 0→0 | 0→0 | **逐 id 不变** |
| 10 | 百科向 | 战双帕弥什 信号 配置 | 0→0 | 0→0 | **逐 id 不变**（md5 碰撞噪声 th 被 WEAK 层挡在 cap 外，本席修复点） |
| 11 | 百科向 | 知识库运维 同步 嵌入 | 2→2 | 0→0 | **逐 id 不变** |
| 12 | 百科向 | 历史上的今天 9月7日 大事记 | 0→1 | 5→**3** | th×3, 人格规范, 鸣潮（硬顶 cap 收口 12 源陷阱） |

人格向获益 5/6，人格占位只增不减；百科向逐 id 不变 3/6；th 全查询 ≤ cap(5)=3。端到端投影锁（`MergedKnowledgeRetriever` 轮转后前 8 槽人格数）：`test_merged_prompt_projection` 通过且 improved≥1。

## 6. 验收②：回归锁（百科通道不塌）

- **False=逐字节**：`tests/test_knowledge_source_quota.py::test_disabled_quota_reproduces_legacy_rrf_exactly`（合成链上 = `_rrf_fuse` 直接截断）+ `test_kb_wiki_store_class_default_has_no_quota`（构造点缺省关）+ §7 跨版本等价件（真语料 12 查询 × retrieve/search_scored 逐字段）。
- **True 不塌百科**：语料级锁 `test_persona_queries_gain_and_encyclopedia_untouched`（纯百科单源逐 id 不变 ≥3 + 长度守恒）、`test_th_family_cap_holds_in_corpus`、纯函数溢出锁 `test_single_family_query_overflow_keeps_all_slots`。
- 邻座守卫：`test_knowledge_empty_manifest_wipe_guard` 8 passed、`test_embed_cold_start_guard` 3 passed（本席未过界，§7 实跑）。

## 7. 实跑命令与原样输出

统一前缀（离线、tmp 基棚、禁缓存写源码树）：
`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest <文件> -q --basetemp="$TEMP/<名>" -p no:cacheprovider`（工作目录=仓库根）

```text
tests/test_knowledge_source_quota.py                            → 19 passed in 5.30s
test_ann_atomic_publish(14) + kb_topic_name_contract(10)
  + kb_metadata_probe_window(9) + kb_metadata_probe_bounds(13)
  + embed_cold_start_guard(3) + knowledge_source_quota(19)
  + knowledge_mtime_cache + v21_knowledge_service
  + knowledge_empty_manifest_wipe_guard(8)                    → 93 passed in 19.64s
tests/test_knowledge_empty_manifest_wipe_guard.py               → 8 passed in 3.45s
tests/test_embed_cold_start_guard.py                            → 3 passed in 3.35s

# False=逐字节 跨版本对照件（%TEMP%\q5_equiv.py，可复跑）：
# PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 ../ChatBot_Runtime/venv/Scripts/python.exe -B "$TEMP/q5_equiv.py"
HEAD blob sha256[:16] = 4d4f31fbd1357f7c
queries compared = 14 x (retrieve + search_scored) + 6 default-ctor
EQUIV OK: 8x8 outputs field-identical (chunk_id/source_id/title/content + score/channels)

# 静态门（项目 dev.ps1 同款旗标，作用域本席文件）：
ruff check plugins/.../vector_knowledge.py tests/test_knowledge_source_quota.py → All checks passed!
mypy --cache-dir ../ChatBot_Runtime/cache/mypy --explicit-package-bases \
     --ignore-missing-imports plugins/.../vector_knowledge.py
  → 本文件 0 错误（输出仅存 3 条 domains/emergency_info/service/subscriptions.py 错误，
    属在飞 WIRE 波文件，非本席面；:1739 var-annotated 已消）
```

树卫生自查：`__pycache__`/`data/`/源码树 `.pytest_cache` 零新增；mypy 缓存写 `ChatBot_Runtime/cache/mypy`（该目录 2026-08-28 起即项目 typecheck 门自有缓存位，本次运行仅刷新自有缓存文件，未触碰盘/恢复进程所写运行数据，如实报备）。生产库 `%TEMP%\kb-backfill-backup\recover.log` 在飞全程零接触。

## 8. 主会话这次转述里不准的地方

1. **「死在网络中断前留下了 5 条红测试」的实现部分已落码**——转述没说「盘上已有实现、红是测试替身过期+实现内部证据门缺陷」混合态；照「补完实现」单一预期走会误修。
2. **「49 passed 相关面基线」计数缺项**——四条点名文件实跑 36（14+10+9+3），49 的口径实际含未点名的 `test_kb_metadata_probe_bounds.py`(13)。基线本身全绿、无掉面。
3. **「很可能缺的是 search_scored 那条链的共用、以及置顶直命中位置保持」方向不确**——search_scored 链与置顶位置前席均已接好；真实缺件是 ①五条链测全炸于测试桩签名过期（TypeError，一条断言都还没执行到），②`_fused_ids_for_limit` persona 保位门径误用整库空结果阈值 0.30，③cap 对零/弱证据噪声块无差别放行致百科查询被治残，④th 族缺硬顶（溢出回填穿透 cap），⑤保留位落点按纯融合序沉底、在轮转投影下永远进不了提示词——五个都是实测钉死，前三个任一不修则「置顶位置」根本无从谈起。
4. **`mypy :1739` 行号**在转述时点准确，但 retrieve 侧同型代码（:1663 一带）前席已带注解、无需修——「那个注解」实为一处而非模式性缺漏（小差异，如实记）。
5. 转述未提**旧报告 §0 的「阵亡席未留任何配额半成品」判断已过期**——接手时盘上实现完整度远超该记录，报告若续用旧 §0 会误导后人（本席已在 §0 加更正标注并保留原始记录）。
