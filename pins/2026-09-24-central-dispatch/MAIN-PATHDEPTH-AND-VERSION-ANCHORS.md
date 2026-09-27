# MAIN-PATHDEPTH-AND-VERSION-ANCHORS — 建库前必修的两面：版本真身不唯一 · 仓内路径靠目录深度反推

主代理亲跑（只读；UTC 2026-09-25T13:23Z）。两件事都是**搬文件进独立仓的瞬间就会坏**、
但此前所有席位与我自己都没摆进代价里的东西。复跑命令见 §5。

---

## §1 「统筹版本号」的地基：仓根版本今天有 **5 枚真身、两套互相矛盾的值**

| # | 位置 | 值 | 谁读它 |
|---|---|---|---|
| V-1 | `pyproject.toml:3` `version` | **`0.1.0`** | 打包/安装元数据（`importlib.metadata`）；无人在运行期读 |
| V-2 | git tag（全仓仅 1 枚，**annotated**） | **`v0.0.1-alpha.2`** | 无人读；`NEVER_PIN` 里"无 annotated tag"这条今天**不成立**（有 1 枚） |
| V-3 | 分支名 | `v0.0.1-alpha.2` | 文档/交接散文当版本号用 |
| V-4 | 运行期 `_git_build_info()`（`domains/ops/monitor/error_report.py:536`） | `短哈希 + 提交日期`，取不到写 `unknown` | **诊断卡的「版本构建」栏** |
| V-5 | 板块声明源 `domains/core/board_taxonomy.py::TAXONOMY_VERSION` | **`'1.0'`** | 板块文档门 |

**四笔要账**：
1. **仓根没有单一版本真身**：V-1 与 V-2/V-3 是两套不同值（`0.1.0` vs `0.0.1-alpha.2`），且都无机器门管它们一致。
2. 🔴 **V-1 的值正是 S549/S594 定义的占位版之一**（`NEVER_PIN` 含 `0.0.0`/**`0.1.0`**/无 annotated tag）
   ⇒ **workspace 根自己带着一个"禁止钉住"的占位版本号**。十库的 `pins` 若钉"仓根版本"，钉的是个空壳。
   这解释了 S604 现算的 `bot_version` **九词全 0 命中**：不是忘了写，是**没有可信值可写**。
3. **零 lock file**：仓内无 `uv.lock`/`poetry.lock`/`requirements.txt`（现算 0 命中）。
   ⇒ 「适配」目前只靠 `pyproject.toml` 的区间（如 `nonebot-adapter-onebot>=2.4.6`），
   全仓唯一精确钉是 `nonebot-adapter-telegram==0.1.0b20`。**上游升级会静默进生产**，这条与拆库无关但同属"统筹"该管的面。
4. **V-4 用 `parents[5]` 反推仓根**（见 §2）——即"运行期版本号"这件事本身已经踩在深度耦合上。

---

## §2 🔴 27 枚 `Path(__file__).resolve().parents[N]`：搬进独立仓 ⇒ 语义**静默改变**

现算（AST 扫 `plugins/**`，只数 `__file__` 起链的 `parents[...]` 下标）：

| 深度 N | 处数 | 典型含义 |
|---|---|---|
| 2 | 2 | 到包根（`config.py:1506`、根 `__init__.py:2192`） |
| 3 | 9 | 到仓根／上三层（`control_plane/*`、`llm_engine/ledger.py:95`、`divination/store/draw_store.py:167` 等） |
| 4 | 5 | 到仓根（`link_parse/parsers/*` 数枚） |
| 5 | 11 | 到仓根（`domains/chat_reply/character/*`、**`ops/monitor/error_report.py:545`** 等） |
| **合计** | **27** | 全部假设"我从这里往上 N 层就是某个固定目录" |

**为什么会静默坏**：`parents[N]` 数的是**磁盘层级**。文件一旦从
`<repo>/plugins/bot_unified_runtime/domains/x/y/z.py` 搬进 `<lib-repo>/src/x/y/z.py`（层级少 2 层），
同一个 `parents[5]` 会指到**仓外某处**或不存在的路径。而这批代码的写法一律是
`if (repo_root / ".git").exists()` 才用、否则 **`info = "unknown"`**／回退缺省目录
⇒ **不抛异常、不报警、门禁也抓不到**：诊断卡的构建信息变成 `unknown`、数据目录悄悄换地方。
（`error_report.py:542-546` 就是逐字的 fail-soft 形态。）

**牵连面点名（六枚找 `.git`/`repo_root` 的件）**：
`runtime/capability_protocols.py`（**中央在册表自己**）、`ops/monitor/error_report.py`、
`ops/repair/service.py`、`ops/sync_drift/service.py`、`ops/sync_drift/__init__.py`、
`link_parse/parsers/platforms_github.py`（这个是业务用 GitHub API，不是仓根耦合，逐枚区分）。

**中央件也不能幸免**：被当作"统一路径口"的 `scripts/runtime_paths.py:PROJECT_ROOT`
自身就是 `Path(__file__).resolve().parents[1]` ⇒ 「都走中央口」今天**不等于**深度安全，
中央口自己得先改成可由环境变量／显式参数定根。

⇒ 这条直接进 §十五/§十六 的"步骤 0"：建库前要有**一条禁 `parents[N]` 越包界的常驻门**＋
一个把"仓根／包根／运行数据根"三个概念分开的显式解析口。

---

## §3 建议判据（不落码，供裁；措辞即可粘贴级）
- **G-V1｜版本单真身**：仓根版本只准住在**一处**（推荐 `pyproject.toml`），其余四枚要么由它派生、要么显式改名不叫 version；
  门＝读四处、断言相等或断言"已声明为派生"；**缺省禁 `0.0.0`/`0.1.0`/`1.0`（占位族）**，命中即红。
- **G-V2｜禁越包界深度**：AST 门，`Path(__file__)...parents[k]` 中 `k > 本文件到其所属库根的层差` 即红；
  白名单只准走显式解析口。今值 27 枚 ⇒ **落门必红**，需 approvals 通道带证据与到期日（项目已有该机制）。
- **G-V3｜每库自带版本**：新建库时 `SCHEMA_VERSION`/`CONTRACT_VERSION`（V3 两枚允许名）＋库版本文件
  必须由 §1 的 G-V1 同一条门管，禁各库自创第三种命名（这正是 S597/S611 在收的口）。

---

## §4 新增待裁 **E-9**：仓根版本真身定在哪（三案，推荐乙）
- 甲｜以 `pyproject.toml:version` 为唯一真身，把 tag/分支名当"发布事件"不当版本；
  代价＝现值 `0.1.0` 是占位族，必须先把它改成真值（她裁）。
- **乙（推荐）｜单一真身＝一个新增 `VERSION` 文件（仓根），`pyproject.toml` 与文档均由生成器投影**，
  且值域禁占位（G-V1）；理由＝十库各建仓后，`pyproject.toml` 会变成**每库一份**，
  把"仓根版本"钉在打包元数据上会让"根版本"随第一张库搬走而丢失语义。
- 丙｜维持现状（五处并存）＋只加一条"禁新增第六处"的门 ⇒ 现有矛盾常驻，`pins` 依旧无锚。

**与既有待裁的关系**：E-9 定完才能定 `pins.pinned_version` 的真值来源（S604/S612），
也才能定 S605 §2.1 的"两本账互不背书"里哪一本是权威。**顺序建议：E-7／E-8 → E-9 → S612 落分母。**

---

## §5 复跑（只读，三条）
```bash
cd "/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
git tag -n99 && git for-each-ref --format='%(refname:short) %(objecttype)' refs/tags
grep -n '^version' pyproject.toml ; ls uv.lock poetry.lock requirements.txt 2>&1
PYTHONDONTWRITEBYTECODE=1 "../ChatBot_Runtime/venv/Scripts/python.exe" - <<'PY'
import ast, os
for dp, dn, fn in os.walk("plugins"):
    dn[:] = [x for x in dn if x != "__pycache__"]
    for f in fn:
        if not f.endswith(".py"): continue
        p = os.path.join(dp, f).replace(os.sep, "/")
        try: t = ast.parse(open(p, encoding="utf-8").read())
        except Exception: continue
        for n in ast.walk(t):
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) \
               and n.value.attr == "parents" and "__file__" in ast.unparse(n):
                print(p, n.lineno, ast.unparse(n)[:60])
PY
```
