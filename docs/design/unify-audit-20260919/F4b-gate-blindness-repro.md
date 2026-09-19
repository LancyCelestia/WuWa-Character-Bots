# F4-b — 验收门「无牙」实证（2026-09-19）

## 0. 状态（进行中/完成 + 时间戳）

**完成** — 2026-09-19 17:38–17:58（本机 +08:00）。六项实验全部实跑，结论均为**可复跑证据**，非读码推演。

- **本席零写证**：仓库内唯一被本席写入的文件 = 本份台账。全部脚本/样本/截图在
  `C:\Users\LancyCelestia\AppData\Local\Temp\f4b-scratch\`（下称 `%F4B%`）。
  未跑 build、未跑 pytest、无 git 写操作、无删除；`webui/dist/index.html` 前后字节数未由本席改动
  （实测 17:38 快照 977563B → 17:51 复查 979729B → 17:58 复查 980836B，**两次变化均归属并发席重建**）。
- **并发写归因（诚实登记，非本席产物）**：收尾 `find -newermt "17:35"` 命中
  `scripts/__pycache__/runtime_paths.cpython-312.pyc`（17:58:38，与并发席 17:58:26 重建同刻）、
  `.mypy_cache/`、`.ruff_cache/` 共 22 个新条目。本席所有 python 调用一律
  `PYTHONDONTWRITEBYTECODE=1`，且 `scripts/webui_acceptance.py` 只 import 标准库+playwright
  （L31-45，不 import `runtime_paths`），mypy/ruff 本席从未运行 → 上述条目归属并发席的门禁跑。
- **快照口径**：树在被并发写。本席所有 dist 相关结论跑的是 **17:36:34Z(=17:36 本地) 那份构建的本席副本**
  （`%F4B%\dist-baseline.html`）。§6 端点配平与 §4 新鲜度的取值时刻各自标注。

**一句话裁决：不能。`scripts/webui_acceptance.py` 对「真实数据是否被渲染」检出能力为零——
一张手写 1.1KB 无 JS/无 CSS/无数据的假 HTML 就能拿到 9/9 PASS 且全页 mode=data。**

---

## 1. 门禁现状读解（判据是什么、在哪几行、什么能让它红）

载体：`scripts/webui_acceptance.py`（369 行，playwright 无头，逐页 hash 路由驱动）。

判据常量（`PAGE_SPECS` L51-88 / L91-94）：

| 常量 | 行 | 值 | 语义 |
|---|---|---|---|
| `PAGE_SPECS[*]["ok"]` | L51-88 | 每页一串**中文文案** | 命中任一 ⇒ `mode="data"` |
| `PAGE_SPECS[*]["ok_dom"]` | L63/L85 | `[aria-live='polite'] div`、`canvas` | 命中 ⇒ `mode="data"`（仅 logs / memory-graph 两页有） |
| `COMMON_GRACEFUL` | L91 | 加载失败/暂无数据/控制面未配置访问令牌/令牌无效或无权限 | 命中 ⇒ `mode="graceful"` |
| `SHELL_MARKER` | L92 | `守岸人控制台` | 应用壳探针 |
| `MIN_BODY_CHARS` | L93 | `30` | 非白屏下限（数字符数） |
| `NOISE_RE` | L94 | `Failed to load resource\|net::ERR_\|favicon` | 控制台噪声豁免面 |

单页判定阶梯（`check_page` L240-309）：

1. L258-260 壳文案未见 → `reason="应用壳未挂载"`，status 保持 FAIL；
   探针阶段更狠：L200-202 直接 `raise SystemExit`。
2. L262-266 导航里无 `#{route}` 链接 → **`status="SKIP"`** 并 return。
3. L268-271 `ok` 文案轮询 → 未中再试 `ok_dom`。
4. L272-274 仅当 ok 未中才轮询降级文案。
5. L276 `result["mode"] = "data" if ok_marker else ("graceful" if graceful_marker else None)`。
6. L278-283 `main`（回落 `body`）`inner_text` 去空白后 < 30 字 ⇒ blank。
7. L289-293 控制台分类：`pageerror` 或不匹配 `NOISE_RE` 的 error 进 `fatal_console`。
8. L295-304 裁决：mode 为 None → FAIL；blank → FAIL；有 fatal_console → FAIL；**否则 PASS**。

退出码（`print_table` L327-340）：`fails` 只在 `status=="FAIL"` 时自增（L330-331），
末行 `return 1 if fails else 0`（L340）。

**能让它红的，只有四类**：壳文案消失 / 该页 ok+降级文案全不出现 / 正文不足 30 字 / 非白名单控制台错误或 JS 异常。

**结构上永远不会红的（判据里根本没有对应观测量）**：

- `mode` 取 `data` 还是 `graceful` —— L276 只记录，L303 只打印，**不参与 L295-304 任何分支**；
- 页面渲染的**数值**是否合理（无一处读值、无区间、无 NaN 检查）；
- **是否真的发生过网络请求**（`page.on("request"/"response")` 从未注册，L253-254 只挂 console/pageerror）；
- **class / 计算样式 / CSS 是否存在**（只读 `inner_text`，L280-282）；
- 产物是不是真 app（任何含指定文案的 HTML 都行）；
- `dist` 是否落后于 `src`（脚本从不比对 mtime/哈希）；
- SKIP 条数（L340 退出码不含 SKIP）。

---

## 2. 实验设计（每个实验要证伪的具体宣称）

F4 席 §④ 给出 BS1/BS2/BS3 三个坏状态，但自陈「**未实跑**——均为实现读码推演」。本席把每条换成实弹。

| 实验 | 注入 | 被证伪的宣称 | 路线选择理由 |
|---|---|---|---|
| **E1** | 真 dist 副本 + 默认 `--api http://127.0.0.1:8743`（实测 8743 无监听=后端全灭） | 「9/9 PASS ⇒ 后端活着且数据在场」 | 脚本有 `--dist` 参数（L345），**无需覆盖仓库文件**，故走「副本+指路」路线 |
| **E2** | `%F4B%\fake-v2-9pass.html`：手写 1.2KB HTML，**零 JS/零 CSS/零 fetch/零数据**，仅含壳文案+9 条导航 `<a href="#/x">`+各页 ok 文案各一行 | 「PASS 的是真 app 的真渲染」 | 同上；这是「wrong-but-pretty」的最小充分伪造 |
| **E4** | E2 删掉 `#/memory-graph` 导航链接 | 「9 页都验收了」 | 专测 SKIP 的退出码权重 |
| **E5** | 真 dist 副本**剥光全部内联 `<style>`**（977563B→943587B，`<style>` 计数 0） | 「验收覆盖了样式层」 | 样式塌方是渲染类缺陷的代表注入 |
| **E6** | 真 dist 副本 + 注入 `window.fetch` 垫片，对 12 个端点返回**结构合法但数值荒谬**的 200 响应（好感度 9999/档 99、total_calls 999999999、负计数、时区 `Mars/Phobos`） | 「mode=data ⇒ 页面拿到的是真实且合理的数据」 | **不起服务器、不占端口**：垫片在页面内截获 fetch，满足只读纪律同时拿到数据态 |
| **PC1** | E2 样本里把壳文案全局替换成 `XYZZY-NO-SHELL` | 反向对照：门是不是**完全**没牙 | 诚实性要求——测「能检」的那一面 |
| **E7** | 前端 URL 字面量 vs 控制面 AST 注册路由，双向差集 | 「前后端端点配平」 | §6 |
| **E8** | `dist/index.html` 与 `webui/src/**` 字节数+mtime | 「验收跑的是当前代码」 | §4 末 |

E6 的荒谬值不是随手编的：好感度域规范区间是 `-100..+100`（AGENTS.md 第四部分「好感度 v5」），
`9999 / tier 99 / NOT-A-REAL-TIER` 属**结构合法、语义不可能**。

---

## 3. 实验记录（注入什么→门是否变红→原样输出）

### E1 — 后端全灭（真 dist 17:36 副本，8743 无监听）→ **门不红**

```
页             路由              结果     模式        摘要
dashboard     /               PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 21 条
calls         /calls          PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 6 条
tokens        /tokens         PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 6 条
latency       /latency        PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 6 条
affinity      /affinity       PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 6 条
logs          /logs           PASS   graceful  优雅降级态在场（重连中）非白屏；白名单网络噪声 11 条
knowledge     /knowledge      PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 3 条
plugins       /plugins        PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 6 条
memory-graph  /memory-graph   PASS   graceful  优雅降级态在场（加载失败）非白屏；白名单网络噪声 6 条
合计 9 页：PASS 9 / SKIP 0 / FAIL 0
EXITCODE=0
```
全文 71 条网络失败**全部**被 `NOISE_RE` 吞掉。BS1 由推演升级为实证。
原始输出：`%F4B%\E1-out.txt`；截图 9 张 `%F4B%\shots-e1\`。

### E2 — 手写假 HTML（零 JS/零数据）→ **门不红，且 9/9 记为 mode=data**

```
dashboard     /               PASS   data      数据态标志在场；白名单网络噪声 0 条
calls         /calls          PASS   data      数据态标志在场；白名单网络噪声 0 条
tokens        /tokens         PASS   data      数据态标志在场；白名单网络噪声 0 条
latency       /latency        PASS   data      数据态标志在场；白名单网络噪声 0 条
affinity      /affinity       PASS   data      数据态标志在场；白名单网络噪声 0 条
logs          /logs           PASS   data      数据态标志在场；白名单网络噪声 0 条
knowledge     /knowledge      PASS   data      数据态标志在场；白名单网络噪声 0 条
plugins       /plugins        PASS   data      数据态标志在场；白名单网络噪声 0 条
memory-graph  /memory-graph   PASS   data      数据态标志在场；白名单网络噪声 0 条
合计 9 页：PASS 9 / SKIP 0 / FAIL 0
EXITCODE=0
```
样本全文 34 行（`%F4B%\fake-v2-9pass.html`）：`<h1>守岸人控制台</h1>` + 9 个 `<a href="#/…">` +
9 个各含一行 ok 文案的 `<p>` + 一句凑字数的正文。**没有 `<script>`、没有 `<style>`、没有 fetch。**
「数据态标志在场」这句话在此语境下为纯假陈述。

> 首轮样本（未含 dashboard 的 `在线`）曾得 `PASS 8 / FAIL 1`——那 1 例 FAIL 是**本席漏抄文案**，
> 不是门的功劳；补上即转绿。见 PC1 与 §4。

### E4 — 同 E2 但删掉 `#/memory-graph` 导航链接 → **SKIP 不影响退出码**

```
memory-graph  /memory-graph   SKIP   -         路由未构建（导航无该链接，二期在飞）
合计 9 页：PASS 8 / SKIP 1 / FAIL 0
EXITCODE=0
```
一条**根本没构建/没接线**的路由，代价是表格里一行 SKIP + 退出码 0。

### E5 — 真 dist 剥光全部 CSS → **门不红**

```
合计 9 页：PASS 9 / SKIP 0 / FAIL 0
EXITCODE=0
```
注入：`dist.replace(/<style[^>]*>[\s\S]*?<\/style>/gi,'')` → 977563B → 943587B，残留 `<style>` 计数 **0**。
产物层任何样式破坏（含 F4 §③ 的 P1-1 行高恒 1、以及 vis4/阶梯失守）对本门完全不可见。
原始输出：`%F4B%\E5-out.txt`。

### E6 — 真 app + 伪造 200 响应（数值不可能）→ **9/9 PASS，8 页 mode=data**

```
dashboard     /               PASS   data      数据态标志在场；白名单网络噪声 0 条
calls         /calls          PASS   data      数据态标志在场；白名单网络噪声 0 条
tokens        /tokens         PASS   data      数据态标志在场；白名单网络噪声 0 条
latency       /latency        PASS   data      数据态标志在场；白名单网络噪声 0 条
affinity      /affinity       PASS   data      数据态标志在场；白名单网络噪声 0 条
logs          /logs           PASS   graceful  优雅降级态在场（重连中）非白屏；白名单网络噪声 0 条
knowledge     /knowledge      PASS   data      数据态标志在场；白名单网络噪声 0 条
plugins       /plugins        PASS   data      数据态标志在场；白名单网络噪声 0 条
memory-graph  /memory-graph   PASS   data      数据态标志在场；白名单网络噪声 0 条
合计 9 页：PASS 9 / SKIP 0 / FAIL 0
EXITCODE=0
```
截图铁证（`%F4B%\shots-e6-fakeapi\affinity.png`，本席已逐图目验）：好感度榜渲染
`FABRICATED-USER / 000000000 · 互动 -7 次 / **-9999.0** / 档 **NOT-A-REAL-TI…** / 共 1 人`，
侧栏同时渲染 `FABRICATED-COLLECTION`。即：**越界 100 倍的好感度、负互动次数、不存在的档位名，
以「数据态」身份通过验收**。BS2 一并实证（伪造 `ok:true` 健康体 → dashboard 记 mode=data）。
构造脚本：`%F4B%\make-fetch-stub.js`（只读 `api-client.ts` L229-433 的 DTO 形状对齐字段名）。

### PC1 — 反向对照：壳文案全局消失 → **门红（exit 1）**

```
[uiacc] 应用壳未挂载（守岸人控制台 标题未见），dist 或构建损坏；截图 _app-shell-dead.png
EXITCODE=1
```
门确实能检「整个 app 没挂载」与「文案缺失」——牙只长在这一条战线上，其余全空。

---

## 4. 结论：门的真实检出能力（能检/不能检，逐条）

| # | 观测量 | 能检？ | 证据 |
|---|---|---|---|
| 1 | 应用壳是否挂载（React 崩/构建坏） | **能** | PC1 exit 1 |
| 2 | 指定文案是否出现在页面上 | **能** | E2 首轮缺 `在线` → dashboard FAIL |
| 3 | 后端是否可达、数据是否真来 | **不能** | E1：71 条网络失败，9/9 PASS，exit 0 |
| 4 | 页面是否是真 app 渲染 | **不能** | E2：34 行手写 HTML = 9/9 PASS |
| 5 | `mode` 是 data 还是 graceful | **不参与判定** | L276 记录、L303 打印、L295-304 无分支；E1 与 E2 同为 exit 0 而 mode 全异 |
| 6 | 渲染数值是否合理/在域内 | **不能** | E6：好感度 -9999.0、档 NOT-A-REAL-TIER、互动 -7 次 → mode=data PASS |
| 7 | CSS/样式层是否存活 | **不能** | E5：`<style>` 全剥 → 9/9 PASS |
| 8 | 路由是否真的存在 | **不能**（只查导航链接） | E4：无链接 → SKIP，退出码不变 |
| 9 | dist 是否为当前 src 构建 | **不能**（零比对） | E8（下） |
| 10 | 前端消费的端点与后端注册是否配平 | **不能**（零观测） | E7（§6） |

**E8 — dist 新鲜度实测（两个时点，都是「落后」）**

| 时点 | `dist/index.html` | 晚于 dist 的 `src` 文件 | 最新 src | 落后 |
|---|---|---|---|---|
| 17:38 | **977563 B @ 2026-09-19T09:36:34.875Z** | 1 / 35（`pages/memory-graph.tsx`） | 09:38:08.998Z | 94 s |
| 17:55（并发席 17:41:15Z 重建为 979729 B 之后） | 979729 B | **11 / 36** | `lib/semantics.ts` @ 09:55:43.264Z | **868 s** |
| 17:58 收尾复查 | **980836 B @ 2026-09-19T09:58:26.109Z**（并发席再次重建，本席未参与） | — | — | — |

17:55 快照的 11 个落后文件含 `src/index.css`（样式层）、`components/layout/app-shell.tsx`、
`components/semantic/semantic-state.tsx`（四态文案本体）、`locales/zh-CN/common.json`（ok 文案真相源）。
**直说：本席这次绿跑（以及任何一次绿跑）验的都是一个已经落后 14 分钟、且样式与降级文案源都已改过的产物。**
F4 §③ 当时判「dist 与 src 同步」是 16:07 快照的点状事实；此刻不同步，且没有任何门会因不同步而红。

**E7 附带结论（§6）**：前端 12 条请求路径全部有后端对位，0 缺；反向 79 条注册路由前端零消费。
门对这两个方向都是瞎的。

---

## 5. 最小补牙方案（改哪几行、判据怎么写，含代码稿）

原则：**不新增文件、不改前端、不引入服务器依赖**；四处小改全部落在
`scripts/webui_acceptance.py`，每处各自封死 §4 的一条盲区，且互相独立可分批落地。
（本席未落盘任何一处，代码稿供修复波直接取用。）

### 牙 1｜数据态必须有真实网络证据（封 §4 条 3/4/6，同时干掉 E2 与 E6）

`check_page` L252-254 现只挂 console/pageerror。加挂 response 观测，并在 L295-304 阶梯里插一条：

```python
# L252 之后（page = context.new_page() 之后）
        responses: list = []
        page.on("response", lambda r: responses.append((r.status, r.url)))
```
```python
# L295 之前插入（api_origin 由 run() 透传：args.api 去掉尾斜杠；--api 为空则取 location.origin）
        if ok_marker and api_origin:
            real_ok = [
                (s, u) for s, u in responses
                if u.startswith(api_origin) and s == 200 and "/favicon" not in u
            ]
            if not real_ok:
                # 数据态宣称必须有出网证据：E2（零请求）与 E6（fetch 被页面内垫片截获）在此双双 FAIL
                result["reason"] = (
                    f"mode=data 但窗口内零真实 200 响应（api={api_origin}，"
                    f"捕获响应 {len(responses)} 条）——夹具/降级/垫片冒充数据态"
                )
                return result
```
效果实测预期：E1 仍 PASS（graceful 不查此条，保留「不白屏」原意）；E2 FAIL（0 响应）；
E6 FAIL（0 响应）；真数据跑 PASS。

### 牙 2｜`--expect` 把 mode 升格为判定量（封 §4 条 5；一行判据）

```python
# main() L355 之前
    parser.add_argument("--expect", choices=["any", "data", "graceful"], default="any",
                        help="data=要求每页真数据态（真后端验收必带）；graceful=要求整轮为降级态验收")
# L340 print_table 改为
    return 1 if fails else 0   →   return 1 if fails else (0 if ok_all_expect else 1)
```
并在 L295-304 的 PASS 分支后追加：
```python
        if args_expect != "any" and result["mode"] != args_expect:
            result["status"] = "FAIL"
            result["reason"] = f"mode={result['mode']} 不满足 --expect {args_expect}"
```
「9/9 PASS」从此必须说明是哪一种；MOCKUI 夹具跑与真后端跑不再共享同一句绿字。

### 牙 3｜值域探针（封 §4 条 6，专治 E6 那类「结构合法、语义不可能」）

`PAGE_SPECS` 每页加一个可选 `probe`（页内求值，返回违例列表）：

```python
    {"name": "affinity", "route": "/affinity", "ok": ["好感度排行"],
     "probe": """() => {
        const bad = [];
        document.querySelectorAll('main *').forEach(n => {
          if (n.children.length) return;
          const t = n.textContent.trim();
          if (/NaN|undefined|Infinity|Invalid Date|-0\\b/.test(t)) bad.push(t);
          const num = Number(t.replace(/[,\\s]/g, ''));
          if (Number.isFinite(num) && (num < -100 || num > 100) && /好感度排行/.test(document.body.innerText))
            bad.push('affinity-out-of-range:' + t);
        });
        return bad;
     }"""},
```
```python
        # L271 之后
        if spec.get("probe") and ok_marker:
            bad = page.evaluate(spec["probe"])
            if bad:
                result["reason"] = f"值域探针违例 {len(bad)} 条：{bad[:5]}"
                return result
```
通用探针（NaN/undefined/Infinity/负计数）建议进 `run()` 对每页统一跑一遍，别只挂 affinity。

### 牙 4｜SKIP 与 dist 新鲜度进退出码（封 §4 条 8/9）

```python
# L340（print_table）：SKIP 默认为红，除非显式放行
    return 1 if (fails or (skips and not allow_skip)) else 0
```
```python
# run() L181 之后：产物落后源码即拒跑
    src_root = dist.parent.parent / "src"
    newest = max((f.stat().st_mtime for f in src_root.rglob("*") if f.is_file()), default=0)
    if newest > dist.stat().st_mtime + 2:
        raise SystemExit(f"[uiacc] dist 落后于 src（dist={dist.stat().st_mtime} newest_src={newest}，"
                         f"差 {int(newest - dist.stat().st_mtime)}s）——先 npm run build 再验收")
```
按 17:55 快照（差 868s、11 个文件）这一条今天就会红。

**优先级**：牙 1 > 牙 2 > 牙 4（新鲜度）> 牙 3。牙 1 单独落地即可让本席 E2/E6 两次欺骗同时失效。

---

## 6. 前端↔后端端点配平实测（webui 请求的每个 URL vs 控制面注册路径）

方法：`%F4B%\endpoint_pairing.py`（纯 AST 解析 `control_plane/api/*.py` 的 `APIRouter(prefix=…)`
与其函数体内 `@router.<verb>("…")`，按 `_app.py` L312-621 与 `api/v1.py` L189-191 的挂载点合成全路径；
前端侧扫 `webui/src/**/*.ts(x)` 去注释后的 `/api|/admin/api` 路径 token）。取值时刻 **17:45 快照**。
**未起任何服务器、未 import 项目代码、未跑 TestClient**（避免 lifespan 触盘建 SQLite）。

- 后端注册：**103 条声明 / 94 条去重全路径**
- 前端请求：**12 条去重路径**（全部来自 `webui/src/lib/api-client.ts`，含 L482 `logsStreamUrl`）

| 前端 URL | 后端对位 | 状态 |
|---|---|---|
| `/admin/api/v1/health` | `api/health.py:52`（prefix L50） | 对位 |
| `/admin/api/v1/status/bot` | `api/health.py:72` | 对位 |
| `/api/v1/stats/calls` | `api/webui.py`（prefix L48） | 对位 |
| `/api/v1/stats/tokens` | `api/webui.py` | 对位 |
| `/api/v1/stats/latency` | `api/webui.py` | 对位 |
| `/api/v1/affinity/board` | `api/webui.py::build_webui_stats_router` | 对位 |
| `/api/v1/logs/sources` | `api/events.py:119`（prefix L88）**或** `api/v1.py:184` 回落 | 对位（见下注） |
| `/api/v1/logs/stream` | `api/events.py:131`（prefix L88） | **对位** |
| `/api/v1/knowledge/collections` | `api/webui_ext.py:34` 族 | 对位 |
| `/api/v1/knowledge/terms` | `api/webui_ext.py:63` 族 | 对位 |
| `/api/v1/plugins` | `api/webui_ext.py:80` 族 | 对位 |
| `/api/v1/memory/graph` | `api/webui_ext.py` memory 族 | 对位 |

**[C1] 前端请求但后端未注册 = 0 条。**
**[C2] 后端注册但前端零消费 = 79 条**（94 去重中扣除 /admin 面、/healthz 与已消费的 12 条后）。
逐族实测计数（`uniq -c` 可复跑，见 `%F4B%\E-pairing.txt`）：
`llm 13 / features 10 / divination 8 / workspaces 7 / config 7 / actions 7 / metrics 6 /
traces 3 / databases 3 / logs 回落 2 / knowledge-bases 2 / 其余 singleton 11`
（singleton 含 usage·search·model-calls·memories·media·jobs·files·capabilities·protocol·openapi.json·**/ui**
——末条是 SPA 挂载点非数据端点，剔除后**真实未消费数据端点 = 78**）。
即**控制面已注册数据路由约 85%（78/92）前端零消费**——不是缺陷，但「WebUI 100% 真数据」这句话的
作用域只有 12 个端点，写文档时别按 92 讲。

**关于 `/api/v1/logs/stream`（前席已否决的旧宣称）本席独立复测：路径两侧一致，配平成立。**
`api-client.ts:482` 拼 `${getBaseUrl()}/api/v1/logs/stream`，后端 `events.py:88` prefix `/api/v1/logs`
+ `events.py:131` `@router.get("/stream")` → 完全命中。**不重复该缺陷宣称。**

**新测得的一条条件性风险（非现行缺陷，登记给修复波）**：`/api/v1/logs/stream` 只存在于
`build_event_router`，而 `_app.py:355` 的挂载整块被 `if event_service is not None:` 包住；
`v1.py:175` 的回落分支（`if event_service is None:`）只补 `/logs` 与 `/logs/sources`，**不含 `/stream`**。
即：把 `bot_control_plane_events_db` 配成空（`config.py:62` 缺省为非空路径，故当前不触发）
→ `/api/v1/logs/stream` 消失 → 日志页 SSE 404，而 E1 已证明日志页会以 `graceful` 身份 PASS。
建议：回落分支补 `/stream`（返回 503 `logs_unavailable` 也比 404 诚实），或在 §5 牙 1 里把
「logs 页 mode=graceful 且 /stream 404」记为红。

**门对 §6 的检出能力 = 0**：本表全部由本席脚本手工配平，`webui_acceptance.py` 不观测任何 URL。

---

## 7. 复跑方式（脚本路径、命令、清理方式）

全部产物在 `%F4B%` = `C:\Users\LancyCelestia\AppData\Local\Temp\f4b-scratch\`；
命令一律在仓库根 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot` 执行
（`--dist` 指 TEMP 副本，**永不指仓库 dist**）。

```bash
# 0) 备料（一次性；只读真 dist，写 TEMP）
cp webui/dist/index.html "$TEMP/f4b-scratch/dist-baseline.html"
node -e "const fs=require('fs');let d=fs.readFileSync('$TEMP/f4b-scratch/dist-baseline.html','utf8');
fs.writeFileSync('$TEMP/f4b-scratch/dist-nostyle.html', d.replace(/<style[^>]*>[\s\S]*?<\/style>/gi,''))"  # E5
node "$TEMP/f4b-scratch/make-fetch-stub.js" \
     "$TEMP/f4b-scratch/dist-baseline.html" "$TEMP/f4b-scratch/dist-fakeapi.html"                        # E6

# 1) E1 后端全灭 / E5 样式塌方 / E6 伪造数据态
PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/webui_acceptance.py \
  --dist "$TEMP/f4b-scratch/dist-baseline.html" --pages all --shot-dir "$TEMP/f4b-scratch/shots-e1"
#   换 --dist 为 dist-nostyle.html / dist-fakeapi.html 即 E5 / E6；三次都应 exit 0

# 2) E2 / E4 手写假页
… --dist "$TEMP/f4b-scratch/fake-v2-9pass.html"      # 9/9 PASS mode=data, exit 0
… --dist "$TEMP/f4b-scratch/fake-v2-8pass-1skip.html" # 8 PASS + 1 SKIP, exit 0

# 3) PC1 反向对照（应为红）
… --dist "$TEMP/f4b-scratch/fake-noshell.html" --pages all   # SystemExit, exit 1

# 4) E7 端点配平（纯 AST，零网络零 import）
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
  ../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/f4b-scratch/endpoint_pairing.py" "$(pwd -W)"

# 5) E8 新鲜度（只读 stat）
node -e "const fs=require('fs'),p=require('path');const d=fs.statSync('webui/dist/index.html');
let n=0,t=0;(()=>{for(const e of fs.readdirSync('webui/src',{withFileTypes:true}))0})();"  # 见 §4 表脚本
```

留存文件清单：`endpoint_pairing.py`、`make-fetch-stub.js`、`dist-baseline.html`、
`dist-nostyle.html`、`dist-fakeapi.html`、`fake-9pass.html`、`fake-8pass-1skip.html`、
`fake-v2-9pass.html`、`fake-v2-8pass-1skip.html`、`fake-noshell.html`、
`E1-out.txt`/`E5-out.txt`/`E6-out.txt`/`E2-E4-out.txt`/`E2v2-E4v2-out.txt`/`E-pairing.txt`、
`shots-e1/`、`shots-e5-nostyle/`、`shots-e6-fakeapi/`（含 `affinity.png` 铁证）、`shots-fake-v2-*/`。

**清理方式**：`rm -rf "$TEMP/f4b-scratch"`（整目录，仓库无对应物）。
另：PC1 那次因未显式传 `--shot-dir`，playwright 兜底截图落在脚本缺省目录
`%TEMP%\webui-acceptance\_app-shell-dead.png`（同为 TEMP，可一并清）。

**仓库留痕声明**：本席对仓库的写入 = `docs/design/unify-audit-20260919/F4b-gate-blindness-repro.md`
一份；`webui/dist/index.html`、`webui/src/**`、`scripts/**`、`tests/**` 零改动
（17:58 复查：无新增 `__pycache__`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`，
dist 字节数变化归属并发席 17:41 重建）。

---
*F4-b 席。与 F4 §④ 的关系：那条是「读码推演（自陈未实跑）」，本条是「实弹六跑 + 截图铁证」，
并新增 F4 未覆盖的三点：E2 纯伪造页可拿 mode=data 全绿、E6 越界数值以数据态通过、
E8 dist 落后 11 个 src 文件 868 秒而退出码仍为 0。*
