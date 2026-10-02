# S3 · 现实世界语料册要求（topic 结构与抓取清单）

> 席位：现实知识面波 S3（2026-10-02）。**本件不改 bot 码、不联网**；抓取与灌库归用户/主会话。
> 所有数字＝本席现算，取数口逐条写在行内，可复跑。

## 1. 现场（现算读数）

| 量 | 现算值 | 取数口 |
|---|---|---|
| wiki 知识库文档数 | 162,381 | `ChatBot_Runtime/data/kb_wiki_embeddings.sqlite3` 只读 `COUNT(*) FROM knowledge_docs` |
| chunk 数 | 744,371 | 同上 `knowledge_chunks` |
| chunk 长度 | mean 534 / median 746 / p90 992 / max 1600 字符 | `SELECT LENGTH(content)` 全表 |
| topic 数与构成 | 16 枚，**全部二游**（明日方舟 46,321 … 异环 135），现实世界 topic＝**0** | `GROUP BY topic` |
| 库文件 | 18,670,096,384 字节 | `stat` |
| wiki 检索坑位 | `top_k=4`、`chunk_chars=800` | `.env` 第 187/188 行；缺省值真身 `config.py`（`bot_kb_wiki_top_k/_chunk_chars`） |
| 【知识库】分区预算 | default 档 10,086 字符；group 档 6,646；support 档 10,086；deep_help 档 13,527 | `chat.py` 的 `expandable = budget-560` ∧ `knowledge=0.42` ∧ `.env` 的 `BOT_REPLY_*_CONTEXT_BUDGET`（24576/16384/24576/32768）现算 |
| topic 门槛 | `BOT_KB_WIKI_TOPICS=`（空＝全放） | `plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py` 的 `parse_topics` |

## 2. topic 结构建议（一 topic 一目录，命名与在册 16 枚同形＝中文通名）

| topic 名 | 覆盖 | 语料源（建议优先级） | 目标体量 |
|---|---|---|---|
| `芯片与算力` | GPU/CPU/制程/光刻/算力 | 厂商官方产品页与白皮书 › 维基 › 权威科技媒体 | 3k–8k docs |
| `消费电子` | 手机/笔电/相机/器材评测 | 官方规格页 › 维基条目（**评测类不进**，二手观点噪声高） | 3k–8k |
| `游戏厂商` | 库洛/米哈游/鹰角/叠纸/悠星/深蓝互动等公司条目 | 公司官网「关于/团队」› 维基 › 版号与工商登记页 | 1k–3k |
| `漫展与同人活动` | 萤火虫/CP(COMICUP)/CQ/CD(ComiDay)/世界线/梦乡/BW/CICF/HKACG | **主办方官网**（每届 time/venue/ticket 页）› 维基 › 官方公告号 | 1k–3k |
| `历史人物` | 生卒/履历/代表作 | 维基（含维基文库）› 学术开放库 | 5k–10k |
| `经济与时政` | 宏观指标/政策/机构 | 统计局·央行·海关等**官方发布页** › 维基（新闻类不抓，交给联网腿） | 3k–8k |

口径提醒（与 bot 侧既有红线一致）：`经济与时政` 只入**官方口径**条目；时效类快讯仍走联网，别把库当新闻源。

## 3. 抓取清单（每 topic 逐源）

- 通用要求：与在册爬导协议同形（`manifest.json` 三清单 + `updates.jsonl` + `documents.jsonl`，
  带 `updated_at`/`crawled_at`），doc_id 前缀＝topic 名（`漫展与同人活动/bgm/…`），
  否则 `knowledge_docs.topic` 分组与 topic 白名单都落空。
- 每源三件必写：**入口 URL、页面→条目的判定（标题分节即 chunk）、更新频率**。
- 反爬/凭据：萌百与 B 站侧已有 cookie 链；新站点若需登录，**先中报再动手**，不许把真实 key/cookie 写进任何入库文件（铁律 3）。
- 体量控制：首轮每 topic ≤ 3k docs 起，观察 kb-sync 时长与 ANN 重建成本（在册实测账 `SEAT-S84/S85`）再放量。
- 灌库入口：真身＝`incremental_daily_runner`（日增量）；**别拿 `recrawl_pipeline --stage crawl` 当日常入口**（会一夜全 skip）；判发布只认 `kb_export=OK|FAILED`。

## 4. 「现实 topic 会不会挤掉二游命中」——现算结论

测量法：拿在册库里已有的 5 枚二游 topic 各抽 6 条标题当查询，走 **FTS5/bm25 腿**（`trigram` 分词，
`knowledge_chunks_fts`）取 `top_k=4`，数坑位归属。库文件全程 `mode=ro` + `PRAGMA query_only`。

读数（复跑＝本席探针 `%TEMP%\cb-s3\kb_displacement2.py`）：

- 有效查询 29 条、坑位 91 格；**跨 topic 抢占 = 0 格（0.00%）**；五枚源 topic  own 率均 100%。
- 单 topic 体量差 340 倍（135 ↔ 46,321）仍没出现跨 topic 抢坑 ⇒ 坑位竞争是**同题相似度的竞争**，不是体量的竞争。
- 预算侧不构成约束：wiki 腿满载 4×median 746 ≈ 2,984 字符，default 档预算 10,086 字符 ⇒ 余量 3.4 倍；
  且合并检索按「人格知识在前、wiki 在后」轮询交错裁剪，人格库（含世界观）排在被裁序列的后面。

⇒ **结论（待主会话裁）**：按上表体量（每 topic 1k–10k docs）灌入现实语料，**不会挤掉二游命中**，
也不会挤占【知识库】42% 预算；真正的风险面不在这两处，而是
① 现实条目让「不懂的话题」显得「库里已答」⇒ `decide_web_search` 的 FALLBACK 分支更易被判"已可答"而不联网
（这条要靠**质量**与 topic 白名单分批放，不是靠体量）；
② 我这条测量只覆盖 **FTS/bm25 腿**，向量腿需要嵌入服务（本席禁联网）⇒ 未测。
若要把②补上，需在灌库后拿同批查询走一次 `kb_wiki` 的向量腿实测。

## 5. 本席没做的事（避免误读）

- 没改 `question_intent.py`（不在写面）：`_REAL_WORLD_RE`/`_EXTERNAL_ENTITY_RE` 仍是现实实体判定的另一处欠账，
  需主会话或持该写面的席位补；本席的现实实体只进了 `search_intent` 的 **expo/hardware 新子域**（竖源腿）。
- 没动任何配置开关、没重启、没抓任何页面。
- 没给实体关系册加 config 键（种子随包，缺席即空册），所以三面齐门只涉及既有那枚 `bot_chat_native_tools_enabled`。
