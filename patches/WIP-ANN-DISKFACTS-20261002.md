# WIP-ANN-DISKFACTS-20261002（取证席 WIP · 只读盘面）

> 2026-10-02 下午窗 · 只读取证（Runtime 侧 ls/stat/ro 连接，零写零进程零 git）。
> 路径更正：运行根在 `...\MyWorkspace\ChatBot\ChatBot_Runtime\`（ChatBot 工作区的**兄弟目录**，非工作区内）。
> 席 WIP 取证时刻 ≈ 2026-10-02 18:2x（本机本地时）。

## ① `.wip` 尸块下落与机理

`ls -la ChatBot_Runtime/data/ | grep -i wip` → **零行**。同目录 `find . -maxdepth 1 -name ".*" -type f` → 零隐藏件；`*.part` / `*.tmp` → 零。**大小库的 `.wip` 全都不在盘。**

**机理（代码核实，vector_knowledge.py）**：`.wip` 与 publish 的 `.tmp` **不同族**——
- publish 暂存＝`{live_name}.{pid}.{tid}.tmp`（:3310-3312），写完 `_atomic_replace_from` ×2 换入线上对（:3320-3321），**publish 从不触碰 `.wip`**。
- `.wip`＝断点续传检查点族：`_ANN_WIP_PREFIX = ".wip-"`（:555），贴各自线上件同目录（`_ann_wip_paths` :2767-2778），经 `.part` 原子换入（:3392-3403）。
- **消失点（判 pinned）**：`_build_ann_index_locked` 内 publish 成功后**当场删三件套**——:3810-3819「发布成功 ⇒ 检查点三件套完成使命，当场删除」→ `_clear_ann_checkpoint()`（:3438-3454：unlink 两枚 `.wip` + glob 扫同前缀 `*.part`）。次级消失点＝`_try_resume_ann_checkpoint` 无行清扫（孤儿 `.wip`，:3443/:3488 注释）。
- 主库属主 `kb_wiki.py` 直接复用 `SqliteVectorKnowledgeStore`（kb_wiki.py:53-55/665），同一套 `.wip`/checkpoint/publish 机理。
- **PEND 假说修正**：「publish 换入消费了同目录 tmp」不成立——换入消费的是 publish 自己的 `.tmp`；`.wip` 尸块是**被 publish 成功后的 `_clear_ann_checkpoint` 删除**（或被无行清扫带走），非被换入消费。

## ② 小库索引对（knowledge_embeddings 族，ls 原样）

```
-rw-r--r-- 1 197121  1268076544 Oct  2 17:46 knowledge_embeddings.sqlite3   （nlink=2，硬链接对件见④附注）
-rw-r--r-- 1 197121      589824 Oct  2 16:33 knowledge_embeddings.sqlite3-shm
-rw-r--1 197121   289458872 Oct  2 17:52 knowledge_embeddings.sqlite3-wal
-rw-r--r-- 1 197121   45731838 Oct  2 17:52 knowledge_faiss.index
-rw-r--r-- 1 197121          0 Sep 20 14:02 knowledge_faiss.index.build.lock
-rw-r--r-- 1 197121    1552056 Oct  2 17:52 knowledge_faiss.order.json
```
（无 manifest 件、无 wip 件；上列 `-rw-r--1` 系抄录排版，原样为 `-rw-r--r--`。）

ro 查 `knowledge_meta`（mode=ro URI 实跑）：
- `embedding_signature` == `ann_signature` == `http://127.0.0.1:8090/v1|bge-m3;http://127.0.0.1:8090/v1|qwen-3.7-text-embedding,text-embedding-v4`（两签名一致）。
- `ann_pair_attestation` = `{index_bytes:45731838, order_bytes:1552056, order_sha256:6bf6af75…f46c5, ntotal:35274, count:35274, embed_generation:3530}`——**attestation 两 bytes 与线上件逐字节吻合**（45,731,838 / 1,552,056）。
- `ann_expected_vector_count` = 35274；`ann_embed_generation` = 3530。**小库对齐、代际自洽、publish 完整。**

## ③ 主库 `.wip` 两枚（09-30 尸块 81MB/2.8MB）

**已不在盘**（① grep 零行覆盖）。现状与时间线：
```
-rw-r--r-- 1 197121 964813546 Oct  2 16:24 kb_wiki_faiss.index
-rw-r--r-- 1 197121   32752324 Oct  2 16:24 kb_wiki_faiss.order.json
-rw-r--r-- 1 197121          0 Sep 20 06:43 kb_wiki_faiss.index.build.lock
-rw-r--r-- 1 197121 18670096384 Oct  1 00:12 kb_wiki_embeddings.sqlite3
-rw-r--r-- 1 197121      32768 Oct  2 04:44 kb_wiki_embeddings.sqlite3-shm
-rw-r--r-- 1 197121     127752 Oct  2 16:24 kb_wiki_embeddings.sqlite3-wal
```
ro 查主库 meta：两签名互同（同上小库）；`ann_pair_attestation` = `{index_bytes:964813546, order_bytes:32752324, order_sha256:dfad6d76…c94b, ntotal:744371, count:744371, embed_generation:68}`；`ann_expected_vector_count`=744371；`ann_embed_generation`=68——attestation 与线上件逐字节吻合 ⇒ **主库最近一次成功 publish = 10-02 16:24**。
- 消失时点边界：[09-30 登记在盘 → 10-02 取证已无]。机理绑定「某次成功 publish 当场清理」；最后一次＝10-02 16:24（主库）/ 10-02 17:52（小库 publish 后三件套同样即删）。**09-30→10-02 16:24 之间若还有更早的成功 publish，则消失更早**——runtime_events.log（10-02 11:18 起卷）与 supervisor.log 均无 ANN 重建行，精确到分＝unknown，不裁。
- 日志旁证：`logs/bot_stdout.log` 末写 10-01 19:49、`nonebot.out.log` 0 字节（09-17 起）、`data/runtime_events.log` 今日在写但零 ANN/faiss/索引行；supervisor.log 显示 bot 现行进程 10-02 04:43:38 拉起（此前 10-01 17:50、10-02 00:43/04:19/04:22 多次拉起）。

## ④ 备份区旁证

```
$ ls ChatBot_Runtime/backups/sqlite
（无输出——目录不存在）
$ ls ChatBot_Runtime/backups/
env.bak-20260911-212550 / env.bak-20260911-213617
runtime_settings_shorekeeper.json.bak-20260911-{212550,213617,214302,215101}
wuwa_history.sqlite3.bak-20260911-195705
```
`backups/` 在（仅 09-11 一批 .bak），**`backups/sqlite` 子目录不存在**——db_backup 挪家后的默认根尚未被创建。本席只 ls 未建。

**硬链接附注**：`fsutil hardlink list data\knowledge_embeddings.sqlite3` → 对件在 `C:\Users\LancyCelestia\AppData\Local\qoder-m2-02\ChatBot_Runtime\data\knowledge_embeddings.sqlite3`（qoder 运行副本，台账 #70 同族）。小库 db 与 qoder 副本共享存储，一侧原位写入对侧可见。

## ⑤ 一句话结论

**尸块账该记「已被覆写消化」**：两枚 09-30 主库 `.wip` 尸块与全数 `.wip`/`.part`/`.tmp` 均已不在盘，机理＝ANN 成功 publish（主库 10-02 16:24、小库 10-02 17:52，attestation 与线上件逐字节吻合）当场触发 `_clear_ann_checkpoint` 删三件套——「publish 换入消费 tmp」假说修正为「publish 成功后清理」，盘面无待裁尸块。
