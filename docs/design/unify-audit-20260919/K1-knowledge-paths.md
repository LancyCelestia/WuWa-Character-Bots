# K1 台账 — BOT_KNOWLEDGE_FILES 外部知识文件缺失调查（2026-09-19，只读席）

## 结论一句话
**两份「库街区百科」都在，没有被删**：整个 `AI智能体有关材料` 目录被移动（非改名/清空）到
`C:\Users\LancyCelestia\Documents\Documents\AI提示词与人格\AI智能体有关材料\`，属 09-18/19 用户把 Documents 重新分类归档的一波操作（`Documents\Documents\` 下出现 AI提示词与人格/书籍/游戏笔记/… 等分类目录，mtime 集中在 2026-09-18 01:59–04:32）。

## 1. 旧路径现状
- `C:\Users\LancyCelestia\Documents\AI智能体有关材料\` —— **不存在**（ls 实测 No such file or directory）。
- 旧 `Documents` 顶层现在只剩分类壳（Adobe/Codex/MyWorkspace/Documents(嵌套)/Tencent Files/…），原中文资料目录整体进了嵌套 `Documents\Documents\<分类>\`。

## 2. 搜索结果（限定 roots：Documents / Desktop / Downloads / OneDrive / 项目树；未扫全 C 盘）
- `find -iname "*库街区百科*"` 命中仅 4 个文件，全部在新位置；Desktop/Downloads 零命中；**OneDrive 目录不存在**（未参与搜索）。项目树（在 Documents 下，已被扫描覆盖）无副本。
- 新位置整个 `鸣潮 AI智能体有关材料\` 共 21 个文件全部随迁（含 守岸人 系列人格文档、明日方舟/绝区零/碧蓝档案/FGO 等其他 wiki、以及 `鸣潮库街区百科v1.md`/`v2.md` 两个未配置的旧版本）。兄弟子目录 `神椿\`、`紫罗兰永恒花园 AI智能体有关材料\`、`超时空辉夜姬\` 也在同一新父目录下——**整目录完整搬移，无拆散**。

## 3. 目标文件证据
基准目录 `C:\Users\LancyCelestia\Documents\Documents\AI提示词与人格\AI智能体有关材料\鸣潮 AI智能体有关材料\`：

| 文件 | 字节数 | mtime | 首行核验 |
|---|---|---|---|
| `鸣潮库街区百科.md` | 9,109,889 | 2026-08-23 21:57:29 +0800 | `# 鸣潮`＋`## 目录`（共鸣者62/武器119/声骸175…），与库街区百科导出格式一致 |
| `战双帕弥什库街区百科.md` | 38,442,219 | 2026-08-23 21:57:33 +0800 | `# 战双帕弥什`＋`## 目录`（机体图鉴83/意识手册105…），同款 |

内容确认为同一文档（.md 自身 mtime 停留在 8 月，移动不改文件 mtime；移动痕迹=新父目录 mtime 2026-09-18/19）。

## 4. 配置面（未读 `.env` 内容，来源=config.py/.env.example/config-catalog/离线脚本判存）
- 声明：`plugins/bot_unified_runtime/config.py` L124 `bot_knowledge_files: list[str] = []`；解析器 L1152-1163（`file_list` 族，mode="before"，接受 JSON 数组字符串或 `;` 分隔，见 `docs/config-catalog-full.md` §13）；L1143-1149 对 `bot_persona_files/bot_knowledge_files/bot_trend_files/bot_glossary_files` 逐项做 runtime_paths 重映射（仅相对 `data/` 前缀会被重定向，绝对路径原样通过——本例是绝对路径，重映射不背锅）。
- 生产值规模：**`BOT_KNOWLEDGE_FILES` 在 .env 中实为 17 项**（非 .env.example 的 4 项样例规模），其中**恰好 2 项缺失=本报两条**，其余 15 项判存在好。样例前 2 项与 .env.example L241 一致（旧路径）。
- 门实现：`scripts/runtime_layout_smoke.py` L64-73——经 `runtime_paths._dotenv_value` 直读 .env 键值，JSON/分号切分后逐项 `is_file()`，只报缺失路径名不打密钥。离线复跑（`BOT_AUTOSYNC=0`）**exit=1，且这两条是全部 FAIL**，无其他环境面失败。
- 同族连带核查（只报计数/存在性，不印值）：
  - `BOT_PERSONA_FILES`：1 项，0 缺失（Runtime 人格副本好）；
  - `BOT_TREND_FILES` / `BOT_GLOSSARY_FILES`：空列表；
  - `BOT_KB_WIKI_ROOT`：已设置且存在；
  - `BOT_KNOWLEDGE_DB_PATH`：已设置（相对 data/，实际落 Runtime）——`ChatBot_Runtime\data\knowledge_embeddings.sqlite3`（949,612,544 B）与 `knowledge_faiss.index`（154,377,854 B）均在，smoke 的 required runtime file 检查也过。
  - **结论：断的只有这 2 条路径，不是整块漂移。**

## 5. 给主会话/主人的最小修复（二选一，K1 席不动手）
**方案 A（推荐，顺应用户搬家意图）——改 `.env` 的 `BOT_KNOWLEDGE_FILES` 中 2 项**，前缀替换：
- 旧：`C:\Users\LancyCelestia\Documents\AI智能体有关材料\鸣潮 AI智能体有关材料\{鸣潮库街区百科.md|战双帕弥什库街区百科.md}`
- 新：`C:\Users\LancyCelestia\Documents\Documents\AI提示词与人格\AI智能体有关材料\鸣潮 AI智能体有关材料\{同上两文件名}`
保持该键原有分隔风格（JSON 数组或 `;`，逐项看 .env 现写法的 JSON 数组内转义）。其余 15 项零接触。**注意路径含空格（`鸣潮 AI智能体有关材料`），别在 shell 里裸拼。**
**方案 B（若主人更想让配置不动）**：由她把 `AI智能体有关材料` 移回 `Documents\` 顶层——但她在做分类归档，预计选 A。**两个方案都改不了 `.env.example` L241 的旧样例路径**，那只是文档样例，是否顺带更正由主会话/COMMITLIST 口径定。
改后需**重启 bot** 生效（铁律 1），重启后 layout 门应转绿。

## 6. 后续注意事项（非本席裁决）
- `vector_knowledge.py` `sync_chunks`：`chunk_id = sha1(path:index:content)`（L853-855）把**全路径**编码进块 id，而 `source_id = path.stem`、清理台账也按 stem。路径改后下次同步会对这两份文档（合计 ~47.5 MB 文本、600 字/块≈8 万块量级）**整批插入 vector_json=NULL 的新行并重嵌入**，且**旧路径行不会自动删除**（stem 仍在清单里→不触发精确删除），存在检索重复/膨胀风险。缓解选项：接受重嵌成本、或按 path 前缀清旧行、或与既有 B5 kb_drift「重建与否待裁」合并处理（AGENTS #42 ⑤）。
- 若 embedding 关闭走顺序取块回退（`BOT_KNOWLEDGE_MAX_CHUNKS`），无重嵌成本，只有检索语义变化。
- `personas/shorekeeper/knowledge/守岸人_核心知识.md` 等同块后两项在树内，好。

## 7. 席位卫生（可复核）
- 本席唯一写入 = 本文件。**零 .env/personas/config.py 编辑，零 move/copy/delete/rename，零 git 写操作，零 pytest/npm。**
- Python 均带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1`（smoke 复跑按其设计只读）。
- 实跑证据：`runtime_layout_smoke` 离线复跑 exit=1、输出仅上述 2 条（存 `%TEMP%/k1_smoke.txt`）；git 基线 926 条脏项（他席在飞，与本席零交集）→ 终态增量 3 行=本席 1 行（本文件）+ 他席并发 2 行（见下实录），`__pycache__/*.pyc/pytest_cache/ruff_cache/mypy_cache` 计数 0（基线与终态皆 0）。

### 终态实录（写盘后复跑 porcelain diff，基线 926 行 → 终态 929 行）
```
>  M scripts/webui_acceptance.py                     ← 他席（前端在飞会话）并发改动，非本席
> ?? docs/design/unify-audit-20260919/K1-knowledge-paths.md   ← 本席唯一写入（本文件）
> ?? webui/src/lib/labels.ts                         ← 他席（前端在飞会话）并发改动，非本席
```
`__pycache__/*.pyc/pytest_cache/ruff_cache/mypy_cache/data/` 污染计数 = **0**（基线与终态皆 0）。qx.json 等随包资产未触碰。
