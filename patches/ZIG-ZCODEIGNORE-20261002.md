# 席 ZIG 工单：`.zcodeignore` 来历取证（2026-10-02 下午窗，只读席）

## ① git 态
- `git log --all -- .zcodeignore`＝**零历史**（从未 tracked）。
- `git status --porcelain`＝`?? .zcodeignore`（未跟踪新文件）。
- 4639 字节 / 158 行；mtime 2026-10-02 14:55:14 +0800；同窗存在 `.zcode/plans/`（ZCode 工具目录）。

## ② 内容概要（三段结构）
- **第 1-130 行 ≡ `.gitignore` 全文逐字同步**（`diff --strip-trailing-cr` 实测仅差行尾继承；.gitignore mtime 10-01 15:51 早于本件）。内容＝Python 缓存/venv/.env 密钥/运行数据(data/,*.sqlite,*.log)/研究第三方源码树/OS 噪声/会话产物，含全部否定组保护（sources/data/qx.json、domains/*/data/、seat-s84/85 豁免）。
- **第 131-132 行**＝同步分隔标记「===== ↑ 以上同步自 .gitignore（『从 .gitignore 同步』只重写以上部分）=====",自证生成机制。
- **第 133-158 行**＝ZCode 默认排除规则（.git/.hg/.svn/node_modules/playwright-report/cdk.out 等 26 条通用件）+ 尾注「自定义规则请写在本行下方，不会被同步/恢复改动」。行尾为 LF（同步段为 CRLF）＝工具进程写入的物证。

## ③ 可疑条目点名
**无**。未新增任何 .gitignore 之外的规则；`personas/`、`tests/`、源码均未被忽略；否定组反而原样保留了 qx.json / domains data / seat-s84-85 三处资产解挡。

## ④ 裁定素材（不代裁）
- **入批 E（工具配置件）论据**：纯 ZCode 工具生成（类比 .gitignore 的扫描范围版）；无独立内容、无密钥值；与 .gitignore 语义完全一致；不入库则 AI 扫描面配置随机器漂移。
- **禁入（本地工具私有态）论据**：本项目 `.gitignore` 明文将 `.claude/ .codex/ .grok/` 定性「Local agent tool configs (workspace-local, never commit)」——`.zcodeignore` 同族（ZCode 工具私有配置），按先例应 workspace-local；且 133 行起的默认段会随 ZCode 版本漂移，入库即引入第三份需同步的 ignore 面（与规则 10「计数/清单漂移」同型风险）。
- 中性：它是无锚根级文件，`SEAT-S*.md` 式误吞风险不适用于它本身。

## ⑤ 未尽
- 写入者身份（哪席/会话）无直接物证；14:55 窗口他席活动未交叉比对（超出本席权限范围）。
- `.zcode/plans/` 内容未读（非本席工单范围）。
