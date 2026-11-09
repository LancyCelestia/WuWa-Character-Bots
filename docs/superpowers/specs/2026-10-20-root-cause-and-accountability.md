# 根因与问责报告（W18 阶段 0）

> 产出时间：2026-10-20
> 取证工具（本波新建，均可复跑）：`webui/scripts/diagnose.mjs`、`request-audit.mjs`、`perf-audit.mjs`、`idle-cost.mjs`、`byte-audit.mjs`
> 所有数字都来自实跑输出，没有一条是推断。复跑命令附在每节末尾。

---

## 一、先纠正一个前提：「网站打不开」不成立

按你的描述我先假设了白屏/崩溃，实测**不成立**。必须先把这条说清楚，否则后面所有修复都会打在错的地方。

**实测：17 条路由全部正常渲染，零未捕获异常、零 console.error。**

```
/console/              总览           body=64     exc=0  console=0  net=0
/console/calls         调用统计        body=247    exc=0  console=0  net=0
/console/tokens        Token 面板     body=97     exc=0  console=0  net=0
/console/latency       延迟           body=570    exc=0  console=0  net=0
/console/affinity      好感度榜        body=119    exc=0  console=0  net=0
/console/sessions      会话身份        body=107    exc=0  console=0  net=0
/console/logs          日志尾流        body=320    exc=0  console=0  net=0   ← 唯一一条 401
/console/knowledge     知识库          body=111    exc=0  console=0  net=0
/console/plugins       插件           body=119    exc=0  console=0  net=0
/console/memory-graph  记忆图谱        body=159    exc=0  console=0  net=0
/console/config        参数设置        body=468    exc=0  console=0  net=0
/console/resources     实时资源        body=140    exc=0  console=0  net=0
/console/models        模型与渠道       body=437    exc=0  console=0  net=0
/console/visual-editor 可视卡片编辑器    body=127    exc=0  console=0  net=0
/console/appearance    外观           body=2108   exc=0  console=0  net=0
/console/credentials   加密凭据        body=170    exc=0  console=0  net=0
/console/operations    受控操作与回执    body=330    exc=0  console=0  net=0
```

移动端 390×844 也验了：无横向溢出（`scrollWidth 390 = innerWidth 390`），侧栏与横栏正确隐藏，抽屉可用。

复跑：`cd webui && node scripts/diagnose.mjs tmp/w18-routes.json`

**所以「无法正常使用」不是渲染失败，是下面七条里的 R1 + R2。**

---

## 二、故障复现（可操作，按顺序做就能撞上）

| # | 复现步骤 | 你看到的 | 严重度 |
|---|---|---|---|
| R1 | 打开 `/console/`，没保存过令牌 | 六张卡全显示「控制面未配置访问令牌 / 请粘贴管理员提供的令牌」——而**你手上没有这串明文**（见第三节 R1） | 🔴 阻断 |
| R1′ | 去 `.env` 找 token | 只有 `BOT_CONTROL_PLANE_TOKEN_SHA256=4aa5a1…`（64 位摘要），**没有明文** | 🔴 阻断 |
| R1″ | 去仓库找生成/找回脚本 | `grep -rn token_urlsafe scripts/` 零命中（只有 actions/credential/workspaces 三处**业务**令牌） | 🔴 阻断 |
| R2 | 随手粘一个错令牌 | 5 发 401 + 5 发 429，主面锁 60 秒；此时**粘对令牌也还是 429** | 🔴 阻断 |
| R3 | 开 DevTools → Network，看任一 js/css | `content-length` 等于原始大小、**无 `content-encoding`** ⇒ 服务端零压缩 | 🟠 带宽 |
| R4 | 外观页关掉「动效」 | 页面上仍有 7 个动画在跑（见第四节 R4 名单） | 🟠 诚实性 |
| R5 | 移动端 DevTools 数 `<a>` | 54 个（18 项 × 侧栏/横栏/抽屉三份） | 🟡 结构 |
| R6 | 启用本地视频壁纸 | 一次拉满 4.9 MB（`bg-1080p.mp4` = 4,919,455 B） | 🟠 带宽 |
| R7 | `npm run typecheck` | 9 errors（存量，不阻塞 build） | 🟡 欠账 |

---

## 三、根因（每条给文件:行）

### R1 · 你根本拿不到令牌 —— 这是「进不去」的唯一真因

**证据链：**

1. `plugins/bot_unified_runtime/control_plane/auth.py:1-10` 模块 docstring 原文：
   > 管理员只配置 token 的 SHA-256（`BOT_CONTROL_PLANE_TOKEN_SHA256`），**明文只在生成时展示一次**
2. `docs/design/control-plane-api.md:127` 原文：
   > 管理员生成 32 字节随机 token（`secrets.token_urlsafe(32)`），配置中只存 SHA-256；**明文只在生成时展示一次**。
3. 仓库里**没有任何**面向运维的令牌生成 CLI：
   ```
   $ grep -rn "token_urlsafe" --include=*.py .
   control_plane/actions.py:200                ← 业务：受控动作确认令牌
   control_plane/credential_service.py:43      ← 业务：凭据预览令牌
   control_plane/workspaces.py:306             ← 业务：工作区预览令牌
   ```
   三条全是业务令牌，**没有一条是控制面登录令牌的生成器**。
4. `.env:31,33` 只有两枚摘要（`4aa5a1…` / `b5f010…`），`SHA-256` 不可逆。

**根因定性：设计上「明文只展示一次」，实现上「展示那一次没有任何落点」。**
配置摘要的人（上一轮的我）把明文丢进了聊天记录，而你不可能去翻几十万 token 的聊天记录找一个 43 字符的串。这不是你操作失误，是交付缺陷。

**问责：**

| 项 | 内容 |
|---|---|
| 引入时间 | 控制面 Phase 1 落地时（`docs/design/control-plane-api.md` 写下「只展示一次」的那一波） |
| 引入者 | 主控（我）。当时只写了规格，没写「怎么给用户」 |
| 为何测试没拦 | 全部测试都从**已知明文**出发（`hash_token(tok)` 然后拿 `tok` 去请求），没有一条测「运维如何获得 `tok`」 |
| 缺失的验收项 | 首次部署必须有一条可复跑的「生成令牌 → 输出明文 → 写摘要」路径 |

---

### R2 · 错一次令牌，锁 60 秒，而且锁着的时候对的也进不去

**实测（`scripts/request-audit.mjs`，注入错令牌，干净 profile）：**

```
route=/console/  total=10  statuses={"401":5,"429":5}
  +  224ms  401  /admin/api/v1/health
  +  232ms  401  /admin/api/v1/status/bot
  +  234ms  401  /api/v1/stats/calls?window=24h&…
  +  236ms  401  /api/v1/stats/calls?window=7d&…
  +  241ms  401  /api/v1/stats/tokens?window=24h&limit=5
  +  242ms  429  /api/v1/stats/latency          ← 第 6 发起被锁
  +  251ms  429  /api/v1/affinity/board?…
  +  260ms  429  /api/v1/metrics/overview
  +  263ms  429  /api/v1/knowledge/collections
  +  265ms  429  /admin/api/v1/health
BODY: 令牌无效或无权限 —— 请核对令牌是否正确、是否仍在有效期，然后到设置中更新。
```

**根因链（三处都对，合起来就错）：**

1. `control_plane/_app.py:172-183`：**先查冷却 → 再认证 → 失败登记**。顺序本身是对的（令牌错时它是唯一止损点）。
2. `control_plane/auth.py:33`：`FAILURE_MAX_COUNT = 5` + `FAILURE_WINDOW_SECONDS = 60`。第 5 次失败当天起 60 秒内该来源全 429。
3. WebUI 首屏**并发**打 7 个查询（总览页 7 个 `useSemanticQuery`），加上 `AppShell` 的健康灯 1 个 ⇒ 一次加载就把 5 发配额打光。

**关键的坏后果**：429 是**按来源**（本机 /32）判的，不区分令牌对错。所以「粘错的 → 改成对的 → 重试」这条路在 60 秒内**必然失败**，用户会以为对的令牌也是错的。

**问责：**

| 项 | 内容 |
|---|---|
| 引入时间 | 首屏改成并发查询那一波（总览页 7 卡同时拉） |
| 引入者 | 主控（我） |
| 为何测试没拦 | 前端测试全是 mock fetcher，后端测试全是单发请求；**没有人测过「一次页面加载 = 几发请求」** |
| 缺失的验收项 | 「无令牌时请求数必须为 0」「错令牌时请求数必须 ≤ 1」两条机器断言 |

**已做的一半修复（本轮已落，有测试）：**
`webui/src/lib/api-client.ts:298-307` 已有守卫——一个令牌都没有时直接抛 503，**不发请求**。实测确认有效：

```
无令牌 + 干净 profile → total=0  statuses={}
BODY: 控制面未配置访问令牌 —— 服务端要求 Bearer 令牌（防裸奔保护）。请在设置中粘贴管理员提供的令牌后重试。
```

`webui/src/lib/auth-budget.ts` + `.test.ts`（6 test 全绿）把「无令牌不发 / 错一次即停 / 30s 自愈」写成纯函数，**但还没接进 `use-semantic-query`**（见第五节待办）。

---

### R3 · 静态资产零压缩（731.9 KiB/次，本可 250 KiB）

**实测（`scripts/byte-audit.mjs`，禁缓存，1440×900）：**

```
total=731.9 KiB  requests=12
byType={"Document":"3.3KiB","Stylesheet":"95.4KiB","Script":"632.6KiB","Media":"0.6KiB"}
     327.1 KiB  Script     vendor-react-CPa0NETY.js
     149.9 KiB  Script     index-rGRkqRtr.js
      95.4 KiB  Stylesheet index-CCs3eBuI.css
      93.7 KiB  Script     vendor-ui-VKyTiqAr.js
      37.4 KiB  Script     dashboard-D7PIwVav.js
      13.2 KiB  Script     field-dict-ClqitiEp.js
```

**服务端响应头（带 `Accept-Encoding: gzip, br` 请求）：**

```
content-type: text/javascript; charset=utf-8
content-length: 334304          ← 与原始文件字节数完全相等
etag: "074ad5137d591be620d26a1fafb9ae2a"
cache-control: public, max-age=31536000, immutable
```

**没有 `content-encoding`。** `grep -rn "GZipMiddleware\|add_middleware" control_plane/_app.py` → 零命中。

**代价（你的硬约束 20GB/月）：**

| 口径 | 单次冷加载 | 20GiB 盈亏平衡 |
|---|---|---|
| 现状（不压缩） | 0.715 MiB | **28,655 次/月** |
| gzip 后（按 build 报告实测值累加 ≈ 250 KiB） | ≈0.244 MiB | ≈83,900 次/月 |

> ⚠️ 上一版我在脚本里把 MiB 标成了 GB，算出「14294 GB/月」这种不可能的数是错的。已修：脚本现在同时给 GiB 与十进制 GB，并标出 20GiB 平衡点。

**问责：**

| 项 | 内容 |
|---|---|
| 引入时间 | `mount_webui_assets` 落地时（只挂了 `StaticFiles`，没挂压缩中间件） |
| 为何测试没拦 | 全部前端测试跑在 vite dev（自带压缩），生产入口只有「200 且 MIME 正确」这一条断言，**没断言 `content-encoding`** |

---

### R4 · 动效总开关是半真的：关掉后仍有 7 个动画在跑

**实测（`document.getAnimations()`，1440×900）：**

| 状态 | total | running | 名单 |
|---|---|---|---|
| 默认 | 12 | 11 | aurora-drift-a/b/c ×3、glaze-breathe ×3、mark-breathe ×1、brand-ring-spin ×1、iris-shift ×3、panel-in ×1 |
| `data-motion='off'` | 7 | **7** | **glaze-breathe ×3、mark-breathe ×1、iris-shift ×3** |

**根因**：存在**两份**停动画名单，一份全、一份漏。

- ✅ `index.css:1158-1174` 的 `@media (prefers-reduced-motion: reduce)` 名单是**全的**，含 `.mark-breathe` / `.glaze-band` / `.iridescent-ring` / `.aurora-blob`。
- ❌ `index.css:1392-1396` 的 `:root[data-motion='off']` 名单只列了 `.aurora-blob` / `.ambient-grain` / `.irid-layer` / `.aurora-sidebar-glow` / `.irid-edge-ring`，**漏了 glaze-breathe 的宿主、mark-breathe 的宿主、iris-shift 的宿主**。

**用户感知**：外观页把「动效」关到底，侧栏釉瑚还在缓慢喘、品牌标还在呼吸、虹彩还在流转 ⇒「这个开关是假的」。

**问责：** 名单双写没有单一事实源。`prefers-reduced-motion` 那份由设计席写，`data-motion` 那份由 Q3 背景席写，两边不同步，也没有机器门比对两份名单。

---

### R5 · 54 个导航 `<a>` 常驻 DOM

侧栏 18 项 + 顶置横栏 18 项 + 移动抽屉 18 项 = 54，三份都常驻（靠 `display:none` 或 `md:flex` 切换）。桌面实测 `stripItems: 18`，移动实测 `navCount: 54`。

不算 bug（隐藏的那些不可达焦），但每一份都带 `activeProps` / `MutationObserver` 监听成本，且三份 `NavIndicator` 各自观察。**这是 W17 我自己引入的**（你说「垂直侧栏 + 顶置横向栏都要」，我就各渲染了一份）。

---

### R6 · 视频壁纸 4.9 MB，一播就拉满

```
webui/dist/assets/bg-1080p.mp4   4,919,455 B
webui/dist/assets/bg-720p.mp4    1,802,980 B
```

当前未触发（实测 Media 仅 0.6 KiB——`preload` 策略没让它真下载），但一旦播放就是整份：**20GiB 只够播 4,300 次**。这是全站单文件最大的带宽黑洞。

---

### R7 · 9 个 tsc errors（存量，不阻塞 build）

```
2  src/pages/visual-editor.tsx    TS2322  string | number 赋给 string
2  src/pages/knowledge.tsx        TS2339  rate_limited 分支没有 .data
1  src/pages/knowledge.tsx        TS7006  item 隐式 any
1  src/pages/appearance.tsx       TS6133  DEFAULT_OPEN_LIMIT 未使用
1  src/lib/dropdown.ts            TS6133  state 未使用
2  src/lib/*.test.ts              TS6133  未使用符号
```

vite build 不做类型检查，所以 `npm run build` 是绿的（实测 `rc=0`，5.52s）。但 `npm run typecheck` 红 —— 这条红灯会掩盖未来真正的新错。

---

## 四、其余实测基线（不是故障，是「改之前长这样」的尺）

| 指标 | 实测值 | 采集脚本 |
|---|---|---|
| 总览页 FCP / LCP | 204ms / 224ms | `perf-audit.mjs` |
| 总览页 CLS | 0.0098 | 同上 |
| 长任务（>50ms） | 1 个（88ms） | 同上 |
| 总览页 DOM 节点 | 519 | 同上 |
| 外观页 DOM 节点 | 2180（**4 倍**，最长的一页） | 同上 |
| 总览页 JS 堆 | 5.59 MB | 同上 |
| 静置 4s 脚本耗时（动效开） | 309ms | `idle-cost.mjs` |
| 静置 4s 脚本耗时（动效关） | **40ms** | 同上 |
| 静置 4s 样式重算 | 1256 / 1282（**两档分不开**，因为 R4 那 7 个还在跑） | 同上 |
| 布局门 196/196 | 全绿 | `npm run lint:layout` |
| 全量测试 | 517 pass / 0 fail | `npm test` |
| 构建 | 12.8s → 5.5s，rc=0 | `npm run build` |

**静置脚本耗时 309ms → 40ms 是 R4 的直接代价**：那 270ms/4s ≈ 单核 6.8% 的持续占用，来自气泡场 rAF + 光标 rAF，而且「动效关」并没有把它们真正停掉。

---

## 五、修复方案（每项给「怎么证明修好了」）

| # | 最小修复路径 | 回归验证（可复跑） | 触碰面 |
|---|---|---|---|
| R1 | 新增 `scripts/control_plane_token.py`：生成 `secrets.token_urlsafe(32)` → 打印明文 → 打印 `sha256` → 提示粘贴到 `.env` 哪一行。**不改后端任何逻辑**。设置面板补一句「令牌从哪来」 | 脚本跑一次，用输出明文 `curl -H "Authorization: Bearer <tok>" /admin/api/v1/health` 得 200 | 新增 1 个脚本 + 1 处 i18n 文案 |
| R2 | 把已写好的 `auth-budget.ts` 接进 `use-semantic-query`：请求前 `spendAuthBudget`，401/429/503 后 `classifyAuthFailure === 'halt'` 则全局停发并显示「等 N 秒」倒计时 | 新断言：错令牌时 `total ≤ 1`；无令牌时 `total === 0`（后者已实测为 0，前者现在是 10） | `use-semantic-query.ts` + `api-client.ts` |
| R3 | `_app.py` 加 `GZipMiddleware(minimum_size=1024)`（Starlette 自带，零新依赖） | `curl -D - -H 'Accept-Encoding: gzip' …/vendor-react-*.js` 必须出现 `content-encoding: gzip` 且 `content-length ≈ 110k` | `_app.py` 一行 import + 一行 add_middleware |
| R4 | 把两份名单合并成一份（`data-motion='off'` 段补 `.glaze-band::before` / `.mark-breathe` / `.iridescent-line` / `.iridescent-ring`），并加机器门断言「两份名单的集合相等」 | `document.getAnimations().filter(a=>a.playState==='running').length === 0`（现在是 7） | `index.css` 一个段落 + 1 个新测试 |
| R5 | 横栏在 `<md` 时不渲染（`hidden` 已有，改成条件渲染）；抽屉在 `!navOpen` 时不渲染 | 移动端 `document.querySelectorAll('nav a').length` 从 54 降到 18 | `app-shell.tsx` |
| R6 | 视频壁纸改 `preload='none'` + 首帧后 `play()`；或提供 720p/1080p 让浏览器按 `matchMedia` 选；或干脆默认关 | 播放前 Network 只有 1 个 Range 请求；未点击播放时 0 字节 | `background-stage.tsx` |
| R7 | 逐条修 9 个 tsc error（都是小改：加 optional chain、删未用符号） | `npx tsc -b` 输出 `error TS` 计数 = 0 | 6 个文件 |

**修复顺序建议（依赖关系）：** R1 → R2 → R3 → R4 → R5/R6/R7。
理由：R1 不解，你进不去，后面所有视觉验收都无法进行；R2 不解，验 R1 时手一抖就锁 60 秒；R3/R4 是纯收益且低风险。

---

## 六、禁止触碰清单（修复期间）

| 禁改项 | 理由 | 依据 |
|---|---|---|
| `webui/scripts/layout-constitution.mjs` | 门禁本体。改它 = 自己给自己发合格证 | AGENTS.md 长期约束 |
| `control_plane/auth.py` 的 `FAILURE_MAX_COUNT` / `FAILURE_WINDOW_SECONDS` | 防暴力枚举的安全参数，前端问题不许后端放宽 | 安全边界 |
| `_app.py` 里 `mount_webui_assets` 与 `include_router(build_ui_router)` 的**顺序** | 反了会让 `/console/assets/*` 被 SPA 回壳吞成 `text/html` ⇒ 严格 MIME 校验拒载 ⇒ 白屏 | `_app.py:672-680` 注释已写明 |
| `plugins/bot_unified_runtime/config.py` | 与机器册双向漂移 | AGENTS.md 规则 10 |
| `webui/src/components/ui/*` 的 `/ui/` import 路径 | 27 处不变量 | 仓内约定 |

---

## 七、需要你裁的三件事

1. **R1 的令牌**：我打算写生成脚本，但**明文会出现在这个会话里**。你是否接受？如果不接受，我改成「只写脚本，你自己跑，输出不进聊天」。
2. **R6 的视频**：4.9 MB 的 1080p 默认关掉、还是保留但改按屏宽选档（手机拿 720p 仍 1.8 MB）、还是压到 1 MB 以内重编码？三个选项对「壁纸效果」的观感损失依次递减、带宽依次递增。
3. **R3 的压缩**：`GZipMiddleware` 会让 2C2T 的 CPU 在每次冷加载时多做一次压缩（334 KB → 110 KB 大约 3–8ms/文件，12 个文件 ≈ 50ms CPU）。**缓存命中时不压缩**（Starlette 的 GZip 只看 `minimum_size` 不看缓存头，需确认是否重复压）。是否接受这点 CPU 换 3 倍带宽？

---

## 附：复跑清单

```bash
cd webui
node scripts/diagnose.mjs tmp/w18-routes.json      # 17 路由异常巡检
node scripts/request-audit.mjs tmp/w18-req-noauth.json   # 无令牌请求数（应 0）
node scripts/request-audit.mjs tmp/w18-req-wrong.json    # 错令牌请求数（现 10）
node scripts/byte-audit.mjs tmp/w18-bytes.json     # 传输字节 + 月流量推算
node scripts/perf-audit.mjs tmp/w18-perf.json      # FCP/LCP/CLS/长任务/DOM
node scripts/idle-cost.mjs tmp/w18-idle.json       # 动效开关的真实代价
npm test            # 517 pass
npm run lint:layout # 196/196
npx tsc -b          # 9 errors（存量）
npm run build       # rc=0
```
