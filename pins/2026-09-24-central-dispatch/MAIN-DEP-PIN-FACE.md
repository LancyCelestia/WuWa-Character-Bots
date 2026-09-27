# MAIN-DEP-PIN-FACE — 「适配」这一半的地基：23 枚依赖只有 1 枚精确钉，且已有 8 枚漂出下界

主代理亲跑（只读；不装包、不改 `pyproject`），2026-09-25T14:59Z。
动机＝第四条主线点名「**插件**」是一类要各建库的对象，而它的"统筹版本/更新/适配"完全由依赖声明面决定。
S634（lock 处置案）与 S639（每库 `pyproject` 草案）都要这张表当地基，此前**没人把"实际装的是哪版"和"声明的下界"并排看过**。

## 取数口（含一次我自己的假零，照实记）
- 第一发我用字符串切块读 `pyproject.toml`，把 `dependencies` 切成 **0 枚**——因为 `]` 出现在 `nonebot2[fastapi]` 里，
  切片在第一枚可选组括号处就断了。**教训：TOML 必须用 TOML 解析器**（改 `tomllib` 后得 23 枚）。
- 实装版本经 `importlib.metadata.version()` 从**生产 venv** 读（子进程带 `-B`，不写缓存进源码树）。

## 今值（23 枚声明依赖）
| 面 | 枚数 |
|---|---|
| 精确钉 `==` | **1**（`nonebot-adapter-telegram==0.1.0b20`） |
| 带**上界** | **1**（`mcp>=1.0.0,<2.0.0`） |
| 只有下界 `>=` | **21** |
| 实装**已漂出**声明下界 | **8** |
| 其中跨**主版本** | **2**（见下） |
| `pip check` | **No broken requirements found**（今天不冲突） |

🔴 两枚跨主版本的漂移：
- `numpy >=1.26` → 实装 **2.5.2**（1.x→2.x 是生态级破坏性升级，而它同时是 `faiss-cpu` 的底座）
- `yt-dlp >=2024.03.10` → 实装 **2026.8.19**（日历式主版本，跨两年）
另六枚已漂出下界：`alconna 0.62.0→0.62.1`、`asyncpg 0.30→0.31.0`、`faiss-cpu 1.8→1.15.0`、
`jinja2 3.1→3.1.6`、`qrcode 8.0→8.2`、`mcp 1.0.0→1.29.0`。

## 为什么这件事属于「每类一库」而不是运维杂事
1. **今天没有 lock file**（`uv.lock`/`poetry.lock`/`requirements.txt` 现算 0）。⇒ 上面那 8 枚漂移**不是有人决定升级**，
   是"某次装包自然取到新版"。这就是"适配"不可统筹的机制形态。
2. **拆库会把这件事放大 10 倍**：现在是一张扁平依赖表；按 S639 每库自带 `pyproject` 后，
   同一枚依赖会被多库各自声明（`numpy` 会被 `media`/`vision`/`core/search` 同时声明），
   版本口径没有顶层唯一真身 ⇒ 漂移从 8 枚变成 8×N 枚，且**没有一处能一次看清**。
   ⇒ 这条要给 S639/S634 提个硬要求：**每库声明必须从顶层派生，不许各库自由填**。
3. 与 E-9 的关系：E-9 管"我们自己的库版本住哪"，本件管"**上游依赖版本住哪**"。
   两者都缺唯一真身，但**不能合并成一个决定**——`VERSION` 文件解决前者，lock/约束文件解决后者。

## 建议（编号并入 S634 的三案，不另立待裁）
- **立即可做、零风险**：把本件的取数口固化成一条只读普查（声明 vs 实装 vs 下界，报漂移枚数），
  挂在既有生成物体检旁，**只报不改**——这样"漂了几枚"从 archaeology 变成日常读数。
- 结构性修法仍归 S634 三案（`uv.lock`／`pip-tools` 编译 lock／每库 pyproject ＋顶层约束），
  本件提供的是**它必须解释的现状数字**：`1 枚精确钉 / 1 枚有上界 / 8 枚已漂 / 2 枚跨主版本 / 零 lock / pip check 干净`。
- ⚠ 边界（不夸大）：`pip check` 干净 ⇒ 今天**没有**已知不兼容；numpy 2.x 与 faiss-cpu 的兼容"是否真安全"
  **未由我实测**（禁在并发窗跑重负载），要判得单开一席跑向量检索回归。

## 复跑
```bash
cd "C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot"
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 "../ChatBot_Runtime/venv/Scripts/python.exe" - <<'PY'
import tomllib, re, json, subprocess
rows = tomllib.load(open("pyproject.toml","rb"))["project"]["dependencies"]
def sp(s):
    m = re.match(r"([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$", s.strip()); return m.group(1), m.group(3).strip()
names = sorted({sp(x)[0] for x in rows})
v = r"../ChatBot_Runtime/venv/Scripts/python.exe"
out = subprocess.run([v,"-B","-c","import json\nfrom importlib.metadata import version,PackageNotFoundError\n"
    + "names=%r\no={}\nfor n in names:\n    try: o[n]=version(n)\n    except PackageNotFoundError: o[n]=None\nprint(json.dumps(o))" % names],
    capture_output=True, text=True)
inst = json.loads(out.stdout.strip())
for s in rows:
    n, spec = sp(s); print("%-30s %-18s 实装 %s" % (n, spec, inst.get(n)))
PY
```
