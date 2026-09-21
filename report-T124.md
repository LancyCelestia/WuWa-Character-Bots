# report-T124 — Wave G 文档索引与旧表述同步席

- 席位：T124｜日期：2026-09-20｜性质：纯文档同步（零代码、零 git 写、零子代理、零启停）
- 写入面：`docs/README.md`（3 处）、`docs/design/tts-handover-20260919.md`（2 处勘误块）、本报告。禁碰面（AGENTS/HANDBOOK/acceptance-manual/tts-contract-layer/media-digest-layer/echo.py/tests/根 init）零触碰。

## 1. docs/README.md 索引补登（3 项）

1. **架构规格表**新增两行（追加在 webui-pages2-spec 行后）：
   - `design/tts-contract-layer.md`：TTS 统一性契约层设计规格（Wave G·G-1/T54），六面现行锚点+目标契约，标注**规格件零施工**。
   - `design/media-digest-layer.md`：中央媒体摘要层蓝图（Wave H 预研·T107），音频字节零摘要/M-64 未闭半现状图+中央件方案，标注**方案件零施工**。
2. **搭建与运维表** `snowluma-setup.md` 行（该文档此前已登记，非本次新增行）：定位语补「§6 语音出站与 silk 转码——TTS 语音出站的单点依赖面」（与文档 §6 标题「语音出站与 silk 转码（M-66 依赖面）」对表一致）。

## 2. tts-handover-20260919.md 旧表述勘误（沿用「> 2026-09-20 勘误：」块惯例，T102 先例）

- **§7.4（原 :851，连带 :857 方令外部路径，同节一块勘误覆盖）**：「不进 ChatBot 源码树」→ `verify_chatbot_env.py` 已入仓 `scripts/verify_chatbot_env.py`（T87，`7e2fe36`），现行优先用仓内路径；引擎目录原件保留只读。
- **§10 关键文件索引（原 :974 表行后）**：「刻意不进源码树」→ 语料工具链四脚本已收编 `scripts/tts_corpus/`（`c78951f`，T106：溯源块+原件 sha256 双向防漂移锚，缺失=SKIP）；`verify_chatbot_env.py` 已入仓（T87）；防护面=18 例冒烟门 `tests/test_tts_corpus_tools.py`（c78951f 内）+反向毒化防护门 `tests/test_tts_corpus_gate.py`（T96 三源对齐门，`097b2e9` 补录入库）。

## 3. 证据（全部实查，verified）

- `git show --stat c78951f`：chore(tts) 语料工具链收编入仓 4 脚本+test_tts_corpus_tools.py 640 insertions（T106·M-61·Wave G）。
- `git ls-files`：`tests/test_tts_corpus_gate.py`、`tests/test_tts_corpus_tools.py` 均已跟踪（gate 由 `097b2e9` T96 漏 add 补录）。
- `git log --oneline -1 -- scripts/verify_chatbot_env.py` → `7e2fe36`（T87）。
- `progress.md:797` T106 台账与勘误措辞逐项对表一致（四脚本名/双向锚/缺失=SKIP/verify_chatbot_env 不重复收编 T87 已入仓）。
- 工作树两目标文件本有他席未提交改动（README 的 V2.1 段、handover :198 CATALOG-FIX 块），本席仅追加未回退，动前已读最新态。

## 4. 自查结果

- **无矛盾**：handover 全文 grep `tts_corpus|c78951f|收编`，既有命中（:572/:626）均为根 `__init__` S0-ROOT 语境，与本勘误无关；本席 2 块是 corpus 唯一提及，与 T106/T99（echo/册页同步，未涉域）/T102（其块未动）零冲突。
- **索引对表**：docs/README.md 77 条链接全解析，死链 0（脚本实跑）；本次 3 项目标文档全登记。
- **树卫生**：无 `__pycache__`/`*.pyc`/stray 文件产生（python 直跑均带 PYTHONDONTWRITEBYTECODE=1）。

## 5. 移交收口的范围外发现（未动，不扩权）

1. 同款旧表述残留两处：handover **:47**（§0 表，已被文首 T63「历史交接快照」总勘误覆盖，无需单修）与 **:545**（§工具链节「刻意不进 ChatBot 源码树」，**无勘误覆盖**，建议收口席补一块或由 T124 后续席处理）。
2. `docs/design/tts-handover-20260919.md` 与 `docs/design/tts-audit-20260919.md` 本身未入 docs/README 索引（grep 零命中）；本席按任务清单只登 3 项，是否补登归收口裁决。
3. docs/design/ 下 audit-20260920-unify-U*（U1-U24 族）/emergency-info-* 等大量本波文件亦未索引——量大，归收口统一裁量，本席不越界。
