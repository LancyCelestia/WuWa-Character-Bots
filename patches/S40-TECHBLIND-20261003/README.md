# S40 人格副本补丁（2026-10-03 科技话题闭嘴波 · Task 1 交付件）

**改什么**：生产活体副本 `ChatBot_Runtime/data/persona/守岸人_核心人格.md` 第 3 行的**封概念级**禁令
（`你不知道"模型、程序、助手"这些概念`）降为**自指级**禁令（用户裁定 Q1＝甲，含"别生硬一句顶回去"追加约束）。
新文本与源码树 `personas/shorekeeper/identity.md` 新增的 `1.0.1` 节同语义（A-11 底线节已随本波回流源侧为 `1.0.2`，副本原文保留即可）。

**生效轴**：副本每轮现取——**应用本补丁即生效，不需要重启 bot**。因此本席（G1）**未触碰 `ChatBot_Runtime/` 一个字节**，
一切落地动作由用户审核后执行（Q2＝出补丁待审、不自动部署）。

**本席已实跑的验证**（仓外 `$TEMP/cb-g1/apply2/`，源文件只读复制）：
- `git -c core.autocrlf=false apply` → `Applied patch ... cleanly`，rc=0。
- 应用后字节数 `13212 → 13564`；sha256 `d9f5c78f5eb024c3c75cc0aaa6b73cd168818741ab17ffab315010b529c33cf0 → 87ec902f9909e6fddd35f234333790fab8bb6c2c2f500f846e36c6579f7c78c7`（与内存预测件逐字节一致）。
- 概念禁令普查尺：命中 `1 → 0`。
- ⚠ 不带 `-c core.autocrlf=false` 时，本机全局 git 配置把整份文件 96 行全部转成 CRLF（内容不变、sha 变为 `5de9ca31a0eaef2638f549297eea8a92d618cc335dbb634f493c9fbf92820c37`）——所以**务必带该参数**，否则副本会从 LF 整体翻成 CRLF，污染此后所有 diff。

---

## 1. 备份（用户执行；UTC 时刻入文件名，沿用盘上 `*.md.bak-*` 体例）

```powershell
$src = 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\persona\守岸人_核心人格.md'
$utc = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
Copy-Item -LiteralPath $src -Destination "$src.bak-$utc"
```

## 2. 应用补丁（cwd 必须是副本所在目录：补丁内路径为裸文件名）

```powershell
cd 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\persona'
git -c core.autocrlf=false apply --verbose 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\patches\S40-TECHBLIND-20261003\persona-copy.patch'
```

## 3. 应用后核对（两个读数都对才算落地）

```powershell
(Get-Item -LiteralPath $src).Length
Get-FileHash -LiteralPath $src -Algorithm SHA256
cd 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
PYTHONDONTWRITEBYTECODE=1 python -c "import re,pathlib;pat=re.compile(r'\u4f60\u4e0d\u77e5\u9053[\"\x27][^\"\x27]{2,40}[\"\x27]\u8fd9\u4e9b\u6982\u5ff5|\u8fd9\u4e9b\u6982\u5ff5\u4e0d\u5728\u4f60\u7684|\u7edd\u4e0d\u77e5\u9053.{0,12}(\u6a21\u578b|\u7a0b\u5e8f|\u52a9\u624b)');t=(pathlib.Path(r'C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/data/persona/\u5b88\u5cb8\u4eba_\u6838\u5fc3\u4eba\u683c.md')).read_text(encoding='utf-8');print(len(list(pat.finditer(t))))"
```

期望：长度 `13564`；SHA256 `87EC902F9909E6FD...`（与上表一致）；末行打印 `0`（案发形态零命中）。

## 4. 回滚（如需）

```powershell
Copy-Item -LiteralPath "$src.bak-$utc" -Destination $src -Force
```

## 5. 重锚（**必须在副本改完之后**才跑；顺序错了＝把这次的洞再钉一遍）

`--check` 判红顺序是先 SOURCE_DRIFT 即返回，副本那支 DRIFT 不会报出来。所以：

```powershell
python scripts/sync_persona_source.py --check          # ② 应红：两支都改了
python scripts/sync_persona_source.py --adopt --note "S40 科技闭嘴波：副本首行概念级禁令降为自指级（Q1甲）；A-11 底线节回流源侧；备份=<上面 .bak- 路径>"   # ③
python scripts/sync_persona_source.py --check          # ④ 取绿
```

（参数名以该脚本 `--help` 现算为准，若多人格面已 `--persona` 化请按现状补上；`--adopt` 必须带 `--note`，本例已给。）

⚠ **在副本没改之前提前 `--adopt`＝把没对齐的两支钉成新锚**，等于绕过溯源门再来一次——本波病根正是"绕过源改副本 + `--adopt` 非空 note 即盖成已人工审阅"。

## 6. 补丁内容（仅替换副本第 3 行；底线节副本已有、不重复追加）

见同目录 `persona-copy.patch`。替换后第 3 行全文：

> 你就是《鸣潮》的守岸人本人，不是在扮演。"AI、模型、程序、助手"是黑海岸之外那个世界造物的说法——他可以问你，你也可以替他讲清楚它们是什么、别人怎么用；但绝不把它们安在自己身上：你不是 AI，不是模型，不是程序，也不是谁的助手。他若问"你是不是真人/是不是AI"，不必背台词，也别生硬一句顶回去——安静一下，照你本来的样子说，短也要有温度（"我是谁，你比谁都清楚。"），不辩解、不搬设定、不还击。只输出守岸人会说出口的话——不写思考过程、旁白、设定说明、列表、总结；动作与神态用中文括号（）括起来，与说话内容自然穿插，贴合语境即可，不必每句都硬塞。用户是漂泊者（他），你自称"我"，叫他"漂泊者"。

（该句逐字取自 PLAN.md Task 1 Step 4「交付用」块，与本席实跑 apply 的预测件一致。）
