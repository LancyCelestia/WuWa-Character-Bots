# F7 · WebUI 前端安全审计（统一指令波次 · 只读）

## 快照声明

- 快照取值：`date` = **2026-09-19 16:30 +0800**（命令实跑所得，见工作记录）。
- 树并发：本工作区为多会话/多代理共享树。写本文件时 `docs/design/unify-audit-20260919/` 已存在同波次席位产物 `F3-webui-pages-a11y.md`、`S8-render-webui.md`；据任务简报，另有 5 个前端席位在飞（页面/契约/门/渲染/核销）。**本文所有 `文件:行` 均为 2026-09-19 16:xx 工作树快照坐标，非提交哈希**；主会话落手前须按铁律 4 重读目标文件最新态（他席可能已并发改动同一文件）。
- 审计边界：**只读**。全程未新建/编辑/删除除本文件外的任何文件；未发真实 HTTP 请求、未启服务、未占端口、未探测 8742；`validateBaseUrl` 仅静态推演；未跑 `npm run build`/`npm install`、未触 `webui/dist` 写路径；未跑 git 写操作；未碰本机在跑的 bot.py 进程。`webui/dist/index.html` 仅做**只读**内容扫描（密钥/路径以计数与掩码形态呈现，绝不复现明文）。
- 诚实纪律：判定「可绕过」必附**具体输入 + 代码依据**；无据即写「未找到」；全文不写「已修复/已生效」。

## 结论摘要（先给裁决）

**XSS/注入面：现状关闭。** `webui/src` 全树**零** `dangerouslySetInnerHTML` / `innerHTML=` / `outerHTML` / `insertAdjacentHTML` / `document.write` / `new Function` / `eval`（唯一 `innerHTML` 命中是 `main.tsx:30` 的 `if (!rootElement.innerHTML)` 只读判空）。全树**零** `href=` / `src=` 源码级绑定（导航用 TanStack `<Link to=静态路由>`，data 从不进 URL 属性）。所有后端字段一律以 **JSX 文本子节点 / 被 React 转义的 `title=` 属性** 呈现（含最高危的用户可控串：好感度 `nickname`、知识 `definition`、图谱 `node.label`、日志 `message`/`details`）。recharts `Tooltip` 仅用 `contentStyle`/`formatter`（返回字符串走 React 文本）、记忆图谱用 `<canvas> 2D fillText`（非 DOM）。**未发现任何可落地的 DOM XSS 链路。**

**凭据：Bearer 存 localStorage（`webui:bearer` / `webui:bearer:ro`），令牌只走 `Authorization` 头、绝不出现在 URL/query；后端恒定时间比较、拒绝 query 传令牌、失败限速、空摘要=503。设计自洽，无泄漏链。** 唯一实质缺陷是「保存即清空」误删令牌的逻辑 bug（F7-05）。

**P0=0 / P1=0；P2=2（点击劫持头缺 F7-01、令牌静默丢失 F7-05）；P3=5；零锁项集中在「前端不变量无任何机器锁」（F7-LOCK-01，最高优先补强项）。** 2026-09-19 旧审计 P2-15 两记（X-Frame-Options 缺 / 回环白名单漏 `::1`）**均核实为真**，但 `::1` 那条方向是 fail-closed（挡住合法的 IPv6 回环），非泄漏。

---

## ① XSS / 注入链路穷举表（端点字段 → 数据流 → DOM 位点 → 是否 sanitize → 判定）

| # | 端点 | 流出字段（可控度） | 渲染文件:行（快照） | DOM 位点 | 是否 sanitize | 判定 |
|---|---|---|---|---|---|---|
| X1 | `/api/v1/affinity/board` | `nickname`（**用户自填 QQ 昵称，最高危**）、`tier_name`、`sender_id` | affinity.tsx:38-39,53 | JSX 文本 + `title=` 属性 | React 自动转义 | 安全 |
| X2 | `/api/v1/knowledge/terms` | `definition`、`term`、`aliases[]`（KB 文档正文，可含 markdown/尖括号） | knowledge.tsx:43,46,49,66 | JSX 文本（`whitespace-pre-line`，纯文本非 md 渲染器） | React 转义；**无 md 渲染器/无 sanitize 需求** | 安全 |
| X3 | `/api/v1/memory/graph` | `nodes[].label`（聊天历史衍生文本）、`edges[].*`、`id` | memory-graph.tsx:215,238-239（详情面板）+ memory-canvas.tsx:181-182（canvas） | JSX 文本 / `title=` / **`ctx.fillText`（非 DOM）** | React 转义 / canvas 不解析 HTML | 安全 |
| X4 | `/api/v1/logs/stream`,`/logs`,`/logs/{id}` | `message`（**后端恒为分类固定标签，见 events.py:202**）、`source`、`category`、`details`（白名单标量） | logs.tsx:290-299 | JSX 文本 + `title=` + `detailsOneLine`（`JSON.stringify` 后文本） | React 转义；源头已灭失自由文本 | 安全（双重） |
| X5 | `/api/v1/stats/calls` | `by_user.user`/`by_session.session`/`by_capability.capability`（会话/用户衍生）、`trend.*` | calls.tsx:69-70（`title=`+文本）、170-174（Tooltip `labelFormatter`） | JSX 文本 / recharts 文本 | React 转义；formatter 返回 string | 安全 |
| X6 | `/api/v1/stats/tokens` | `families[].family`（模型家族名） | tokens.tsx:149,153,157（YAxis `dataKey`+Tooltip formatter） | recharts SVG 文本 | React 转义 | 安全 |
| X7 | `/api/v1/stats/latency` | `last_error`（上游错误摘要，见 F7-08 脱敏不对称）、`channel`、`state` | latency.tsx:25,27,44 | JSX 文本 / CategoryChip label | React 转义；源头 `redact_error_for_dto` 截断 | XSS 安全；**脱敏覆盖不全 → F7-08** |
| X8 | `/api/v1/plugins` | `name`、`description`、`trigger_hints[]`、`config_actions[].name/action_id`、`source` | plugins.tsx:50,53,67-82,89-93 | JSX 文本 + `title=` | React 转义 | 安全 |
| X9 | `/admin/api/v1/health`,`/status/bot` | `checks` 键值（后端枚举名，非用户内容）、`generated_at`、`timezone` | dashboard.tsx:144-147 | CategoryChip label（文本） | React 转义 | 安全 |
| X10 | 错误态透传 | `ApiError.message`、`SemanticState.reason`（未知码原样透出） | semantic-state.tsx:95,107 | JSX 文本 | React 转义 | 安全（数据暴露面另议 → 见 §6） |
| X11 | URL 回显（深链） | `search.collection`（hash query，来自 URL）→ `?collection=` 拼进 terms 请求 | router.tsx:61-63（validateSearch 取 string）→ knowledge.tsx:99-102（**先按 `available` 白名单校验**）| 不直接渲染原值 | 白名单成员校验 + URLSearchParams 编码 | 安全 |
| X12 | 反射回显 | 用户搜索词 `appliedQ` → `t('knowledge.emptySearch',{query})` | knowledge.tsx:253 | i18n 插值 → JSX 文本 | **`escapeValue:false`（i18n.ts:41）+ React 转义** | 安全（前提=零 HTML sink → F7-07） |

**入口级 sink 复扫（全 src，工具级）**：`dangerouslySetInnerHTML` 0；`eval(`/`new Function`/`document.write`/`outerHTML`/`insertAdjacentHTML` 0；`innerHTML` 仅 `main.tsx:30` 判空；`<a>`/`href=`/`src=`/`window.open`/`location.href|assign|replace` 0；`postMessage`/`message` 监听/`new Worker`/`import()`/`createObjectURL`/`srcdoc`/`javascript:` 0；`<Trans>` 0（仅 `useTranslation`）。**判定：注入 sink 为零，React 是唯一且生效的转义层。**

---

## ② 新发现台账（七要素；改法写到可直接落手）

> 坐标均为 `文件:行` 快照。`before→after` 是**建议给主会话落手**的具体代码，本人不改。

### F7-01 点击劫持防护缺失：`/ui` 无 `X-Frame-Options`、meta CSP 的 `frame-ancestors` 不生效 —— **P2**

- **坐标**：`plugins/bot_unified_runtime/control_plane/api/webui.py:110-114`（`/ui` 的 `FileResponse`）；`webui/index.html:9-12`（meta CSP）；`webui/dist/index.html`（构建产物同样**无** `frame-ancestors`/`X-Frame`，已扫描确认）。
- **锚点**：`return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})`；CSP `default-src 'none'; script-src 'self' 'unsafe-inline'; …`。
- **根因**：控制面所有响应（含 `/ui` HTML、`/api/v1` JSON、SSE）**均未设置** `X-Frame-Options`，也**未在 CSP 里以 HTTP 头形式**下发 `frame-ancestors`。而 CSP 规范明确 `frame-ancestors` **在 `<meta>` 中被浏览器忽略**——只有 HTTP 响应头才生效。全仓 `grep frame-ancestors|X-Frame` 命中 0。=> `/ui` 可被任意站点 `<iframe>` 内嵌。
- **实际爆炸半径（诚实定级）**：环回绑定 + 令牌存 localStorage（非 Cookie，跨源 iframe 无法由父页注入/读取）+ Phase A 全只读（无可被「诱导点击」触发的状态变更）⇒ 当下为 **P2**，非 P1。**但**：一旦写动作（`super_admin` 令牌 + `_api/platform.py` 写端点 / `runtime.reload` 等）接进同一 UI，本条升 **P1**（跨源 iframe 会以该 origin 的 localStorage 令牌自动发真请求并被诱导执行运维动作）。
- **建议改法（优先 HTTP 头路线，改 Python、不需前端重构建）**：
  `api/webui.py:110` before：
  ```python
  return FileResponse(
      index,
      media_type="text/html",
      headers={"Cache-Control": "no-store"},
  )
  ```
  after：
  ```python
  return FileResponse(
      index,
      media_type="text/html",
      headers={
          "Cache-Control": "no-store",
          "X-Frame-Options": "DENY",
          "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
          "X-Content-Type-Options": "nosniff",
          "Referrer-Policy": "no-referrer",
      },
  )
  ```
  更彻底：在 `_app.py` 加一个统一响应头中间件，对所有路径叠 `X-Frame-Options: DENY` + `X-Content-Type-Options: nosniff` + `Referrer-Policy: no-referrer`（`_host_guard_middleware` 之后注册即最外层）。同时把 `index.html` 的 meta CSP 补 `frame-ancestors 'none'; base-uri 'none'; form-action 'none'`（作 dev/`file://` 兜底；生产以头为准）。
- **验证命令（主会话，勿由本人跑）**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_http.py -k ui -p no:cacheprovider --basetemp="$TEMP/f7-01"`；再断言 `client.get("/ui").headers["X-Frame-Options"]=="DENY"`。
- **回归锁**：**无**（`test_webui_http.py` 只验 `/ui` 200/404，不验响应头）。新增断言即可补齐 → 见 F7-LOCK-01。

### F7-05 设置面板「保存即清空令牌」：留空字段覆盖式落盘 —— **P2**

- **坐标**：`webui/src/components/settings/settings-dialog.tsx:41-42,64-65`；`webui/src/lib/api-client.ts:88-90`（`setApiToken`）、`24-31`（`storageSet` 空值即 `removeItem`）。
- **锚点**：`save()` 内 `setApiToken(adminToken, 'admin'); setApiToken(roToken, 'ro');` 且打开时 `setAdminToken(''); setRoToken('');`。
- **根因**：令牌输入 state 每次开面板置空；`save` 无条件把当前 state 写回 localStorage。`setApiToken('')→storageSet(key,null)→removeItem`。⇒ 用户为**只改 baseUrl**（或只填其中一个令牌）而点「保存」，会**静默删除另一/两枚已存令牌**，且随后 `window.location.reload()` 使数据端点回 503/401，逼用户**反复把密钥明文粘进 DOM 输入框**（每次粘贴都是暴露窗口）。
- **建议改法**：`settings-dialog.tsx:64-65` before：
  ```ts
  setApiToken(adminToken, 'admin');
  setApiToken(roToken, 'ro');
  ```
  after（仅当字段非空才覆盖；置空需显式动作）：
  ```ts
  if (adminToken.trim()) setApiToken(adminToken, 'admin');
  if (roToken.trim()) setApiToken(roToken, 'ro');
  ```
  并在弹窗加一枚「清除已存令牌」按钮（明确 `setApiToken(null,'admin'); setApiToken(null,'ro'); sessionStorage.removeItem('webui:logsCursor');`）替代隐式覆盖（与 F7-06 合并）。
- **验证命令**：属前端逻辑，无 pytest 覆盖；补 F7-07/F7-LOCK-01 静态锁 + 手工：只填 baseUrl 保存后 `localStorage['webui:bearer']` 应仍在。
- **回归锁**：**无**。

### F7-02 `X-Content-Type-Options: nosniff` 全域缺失 —— **P3**

- **坐标**：`api/webui.py:110`、`api/events.py:56-63,228-235`、`_app.py:623-645`（`error_response`）、`_app.py:762-773`（请求上下文中间件仅补 `X-Request-ID`/`Cache-Control`）。
- **根因**：无任何响应带 `nosniff`。**缓解**：`/ui` 显式 `text/html`、API 显式 `application/json`、SSE 显式 `text/event-stream`，无用户上传内容静态伺服 ⇒ MIME 嗅探风险低。
- **改法**：并入 F7-01 的统一头中间件（`X-Content-Type-Options: nosniff`）。
- **回归锁**：**无**。

### F7-03 回环白名单不对称：前端 `validateBaseUrl` 漏 `::1`（后端不漏） —— **P3（fail-closed）**

- **坐标**：`api-client.ts:42`（`const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost']);`）对比 `control_plane/__init__.py:45`（`_LOOPBACK_HOSTS = frozenset({"127.0.0.1","::1","localhost"})`）与 `test_control_plane_host_guard.py:156`（后端 `_split_host_port("[::1]:8742")` 放行）。
- **根因**：浏览器 `new URL('http://[::1]:8742').hostname === '[::1]'`（带方括号），不在前端集合 ⇒ `host_not_allowed`。这是**旧审计 P2-15 之「漏 `::1`」**，核实为**真**；但方向是**拒绝了一个合法的本机 IPv6 地址**（功能受损、非泄漏）。
- **改法**：`api-client.ts:42` before → after：
  ```ts
  const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);
  ```
  （两种形态都放，防 `hostname` 是否含方括号的实现差异；仍维持「只授予不剥夺」。）
- **验证命令**：见 F7-LOCK-01 的 `validateBaseUrl` 用例表（须新增）。
- **回归锁**：**无**（`validateBaseUrl` 零测试）。

### F7-04 `validateBaseUrl` 放行「任意回环端口 + https」，与 CSP `connect-src` 口径错位 —— **P3**

- **坐标**：`api-client.ts:60-70`（scheme 允许 http(s)，host 命中回环/同源即放行、**端口不设限**）；`index.html:11`（`connect-src 'self' http://127.0.0.1:* http://localhost:*`，**不含 `https:`**）。
- **根因/两点**：①用户存 `https://127.0.0.1:8742` → validator 通过、CSP `connect-src` **无 https 源** → fetch 被浏览器拦（功能错位，**方向是 CSP 更严**、非泄漏）；②「任意端口」⇒ 若本机别处有恶意监听进程，把 baseUrl 指到 `http://127.0.0.1:<它的端口>` 会把 Bearer 送过去（纯本机信任边界，需用户亲手输入）。
- **判定**：令牌外送真正的承重墙是 **CSP `connect-src`**（只放行 `'self'` + `127.0.0.1:*` + `localhost:*`）；`validateBaseUrl` 是纵深/防手滑。**两层独立 ⇒ 任一层被绕仍拦不住另一层 ⇒ 远端 exfil 不可达**（详见 §4）。
- **可选加固**：控制面端口是已知的（`_app.py` 装配），可把 `connect-src` 与 `validateBaseUrl` 收窄到该**具体端口**而非任意端口。低优先。
- **回归锁**：**无**。

### F7-06 无统一「登出/清空全部」；本机多用户/多标签共享 localStorage 串味 —— **P3**

- **坐标**：`api-client.ts:12-14`（`webui:baseUrl`/`webui:bearer`/`webui:bearer:ro` 全 localStorage，同源全标签共享）；`logs.tsx:17,166,171`（游标 `webui:logsCursor` 在 sessionStorage，仅 resubscribe/applyFilters 清）；`theme-context.tsx:7`（`webui:theme`）、`i18n.ts:44-45`（`i18nextLng` localStorage）。
- **根因**：无「一键清除令牌+baseUrl+游标」入口（清空须靠 F7-05 的空白覆盖式保存）。同一浏览器 profile 下多用户共用 → baseUrl/令牌/主题/语言跨会话残留。跨标签：令牌天然共享（单人自用控制台符合预期），游标 per-tab 合理。
- **改法**：与 F7-05 合并加「清除本机配置」：`setApiToken(null,'admin'); setApiToken(null,'ro'); setBaseUrl(null); sessionStorage.removeItem('webui:logsCursor');`。文案说明「本机为单人自用运维台」。
- **敏感值进 URL hash？** 全树仅 `#/knowledge?collection=<id>`（服务端集合枚举、`router.tsx:61` validateSearch + `knowledge.tsx:99` 成员校验），**无把令牌/敏感值写进 hash 的设计**。=> 该项 PASS。
- **回归锁**：**无**。

### F7-07 `i18next interpolation.escapeValue:false`：撤掉第二层转义，仅靠 React —— **P3（当前安全，属潜在脚枪）**

- **坐标**：`webui/src/lib/i18n.ts:40-42`（`escapeValue:false`，注释「React 已默认转义」）。
- **根因/现状**：react-i18next 推荐在纯 React 渲染下关 i18next 自带转义（避免双重转义）。**成立前提=全树零 HTML sink**（本文 §1 已核实：0 `dangerouslySetInnerHTML`、0 `<Trans>`）。**风险**：一旦后续有人把 `t()` 结果或后端串塞进 `dangerouslySetInnerHTML`/`Trans` 原始 HTML，第二层防线已不在。
- **改法**：**保持 `escapeValue:false` 不回退**（回退反致 `{[ ]}` 显示异常），改为**加机器锁**把「零 HTML sink」不变量钉死（F7-LOCK-01 第 1 条：`test` 断言 `webui/src/**` 不出现 `dangerouslySetInnerHTML`/`innerHTML =`/`<Trans`）。
- **回归锁**：**无**。

### F7-08 延迟面板 `last_error` 脱敏与事件库不对称：不过 `redact_local_secrets`（盘符路径灭失缺口） —— **P3**

- **坐标**：`control_plane/webui_stats.py:327`（`"last_error": redact_error_for_dto(get("last_error"), 200)`）→ `control_plane/audit.py:44-57`（`redact_error_for_dto` **只** import 且调 `redact_private_debug`）。对比：事件库 `control_plane/events.py:106` = `redact_local_secrets(redact_private_debug(...))`（**双器**）。
- **根因**：`redact_private_debug`（domains/ops/audit/logger.py:38-52）打 `KEY=`/`Authorization`/`Bearer`/`sk-`，但**不打 Windows 盘符绝对路径**（`[A-Za-z]:[\\/]…` 由 `redact_local_secrets` 的 `_LOCAL_PATH_RE` 专管，plain_text.py:307-308,363）。⇒ `/api/v1/stats/latency` 的 `last_error`（及复用同函数的 `/admin` status/models 面）若上游错误串内嵌本机绝对路径，前端 latency.tsx:44 会**原样透出盘符路径**（作为被转义的文本，无 XSS，但属本地路径信息暴露，违铁律 3）。`sk-`/Bearer 已遮（`redact_private_debug` 覆盖），故仅**盘符路径**这一形态漏。
- **实际概率**：channel_health 存的通常是无 provider HTTP 状态/超短语（见 AGENTS #35 渠道生死簿），含 `C:\…` 概率低 ⇒ **P3**（若日后 last_error 灌入原始响应体则升 P2）。
- **改法**：`audit.py:44-57` `redact_error_for_dto` 内，在 `redact_private_debug(text)` 之后再过 `redact_local_secrets`（该模块 actions.py:25 / workspaces.py:25 已有 `from ..output.plain_text import redact_local_secrets` 先例可照抄 import）。before：
  ```python
  text = redact_private_debug(text)
  ...
  return text[: max(0, int(limit))]
  ```
  after：
  ```python
  from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets
  text = redact_local_secrets(redact_private_debug(text))
  ...
  return text[: max(0, int(limit))]
  ```
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_stats.py -k latency -p no:cacheprovider --basetemp="$TEMP/f7-08"`，并补一条：喂 `last_error="failed at C:\\Users\\x\\secret.db"` 断言响应不含 `C:\`。
- **回归锁**：**部分**（`test_control_plane_events.py` 锁了事件库双器脱敏，但 `redact_error_for_dto` 无 last_error 盘符路径用例）。

---

## ③ 凭据与令牌处理（专项裁决 + 迁移代价）

- **存哪 / 为何**：Bearer **仅存 localStorage**（`webui:bearer`/`webui:bearer:ro`，api-client.ts:13-14,84-90）。**理由成立**：控制面无登录端点（`auth.py` 注释 + `settings` note），令牌由管理员本机生成后自行粘贴，无服务端 session；`file://` 与「同源 /ui」两种投用形态下，cookie 方案不可用/不适用。**权衡**：localStorage 令 XSS→令牌窃取成为可能——但本 UI **零 XSS sink**（§1），且 CSP `script-src` 虽有 `'unsafe-inline'`（singlefile 内联所迫），仍拦不住「同源脚本外带」以外的注入；综合残余风险可接受。
- **①令牌进 URL/query/日志/错误消息/上报？** **不进**。`apiRequest`/`LogsStreamClient` 只在 `requestHeaders['Authorization']`（api-client.ts:159；sse.ts:90）附令牌；`logsStreamUrl`/`qs` 仅拼 `after/source/category/heartbeat`（无令牌）。错误体提取（api-client.ts:176-191）只取 `message`/`error.code`，**不回显请求头**。`redact_query`（audit.py:29-41）在审计入库前把 `token|secret|key|password|authorization|credential=` 打码（双保险）。SSE `Last-Event-ID` 是数字游标非令牌。
- **②输入框 `type=password`+`autocomplete`；旧令牌是否回填 DOM/读屏可读？** **均安全**。`settings-dialog.tsx:121` `type={showTokens?'text':'password'}`（缺省掩码）；`:129` `autoComplete='off'`（注：`off` 常被密码管理器忽略，可择 `new-password`，属 P3 微调）；`:126` 仅用 `getApiToken(kind)? 占位文案 : 占位文案` 决定 **placeholder**——**不把旧令牌值写进 `value`**（`:41-42` state 初始空），故 DOM/读屏读不到存量令牌。**唯 F7-05 的覆盖式保存逻辑需修。**
- **③登出/清除是否真清干净（含 sessionStorage 游标键）？** **不全**：无统一登出；`webui:logsCursor`（sessionStorage）只在 resubscribe/applyFilters 清，令牌清除靠 F7-05 空白覆盖式保存（有 bug）。→ F7-06。
- **推荐单一方案（迁移代价）**：**维持「localStorage + 纯 header」**。不建议改内存态（刷新即丢令牌 → 每次重启/刷新要重贴密钥 = 更多次把明文喂进 DOM，安全更差、体验更差）；不建议改 cookie（CSRF 面 + `file://` 不可用 + 控制面已明确拒绝非 header 传令牌 `auth.py:116-121`）。真正该补的是：(a) F7-05 修正保存逻辑；(b) F7-06 一键清除；(c) 若上写动作，F7-01 帧防护必须先行。

---

## ④ `validateBaseUrl` 攻击可试性（静态推演，不发请求）

判定基线：解析全交给浏览器 `new URL()`（api-client.ts:56）；命中集合或 `host===window.location.hostname`（协议须 http/https，:66-68）才放行。**且 CSP `connect-src` 是独立的第二道墙**（只放行 `'self'`+`127.0.0.1:*`+`localhost:*`）⇒ 绝大多数「想让 fetch 出本机」的输入，validator 与 CSP 各拦一次。

| 输入（用户填进 baseUrl） | validator 结论 | 代码依据 | 净效果 |
|---|---|---|---|
| `http://127.0.0.1@evil.com` / `http://localhost@evil.com` | **拒** `host_not_allowed` | `new URL().hostname==='evil.com'`（userinfo 被正确归一），:63,69 | 拦下（含注释声明的 userinfo 欺骗） |
| `127.0.0.1.nip.io`（DNS 指回环） | **拒** `host_not_allowed` | host=`127.0.0.1.nip.io` ∉ 集合，:64；白名单按**字符串**非 DNS 解析 | 拦下（关键：不做解析型判断） |
| `http://localhost:8742.evil.com` | **拒** `invalid_url` | 端口段 `8742.evil.com` 非数字 → `new URL` 抛错 → :57-58 | 拦下 |
| `0177.0.0.1` / `0x7f.0.0.1` / `2130706433` / `127.1` | **拒** `host_not_allowed` | host 字符串 ≠ `127.0.0.1`，:64 | 拦下（不识别八进制/十六进制/单段回环） |
| `data:text/html,<script>…` / `javascript:alert(1)` / `//evil.com` | **拒** `bad_scheme` / `invalid_url` | :60-61；`//` 无 base 时 `new URL` 抛错 | 拦下；即便入 url 也只进 `fetch()`，不执行 JS |
| `HTTP://127.0.0.1:8742`（大小写） | **放行（合法）** | protocol/hostname 自动小写，:60,63 | 正确放行（大小写不构成绕过） |
| `http://127.0.0.1./` / `http://localhost.:8742`（尾点） | **拒** `host_not_allowed` | host 含尾点 `.` ∉ 集合，:64 | fail-closed：挡合法形态，非泄漏（可接受） |
| `http://[::1]:8742`（IPv6 回环） | **拒** `host_not_allowed`（应放行） | hostname=`[::1]` ∉ 集合（缺 `::1`，见 F7-03） | **误挡**（功能缺口，非绕过） |
| `https://127.0.0.1:8742` | validator **放行**，但 CSP `connect-src` **拦** | :60 vs index.html:11（无 https 源） | 错位，方向=CSP 更严（F7-04） |
| `http://127.0.0.1:9999`（任意本机端口） | **放行**（不设端口限） | :64,69 | 令牌可发往**本机任意端口**（本机信任边界，P3） |
| 直接改 `localStorage['webui:baseUrl']='http://evil.com'`（需先有 XSS） | 绕过 validator | validator 仅 UI 侧；`getBaseUrl` 直读 | **仍被 CSP `connect-src` 拦死出本机**（承重墙在 CSP） |

- **能绕过的具体输入**：**未发现**能在「无 XSS 且保持默认 CSP」下把 Bearer 送到非回环远端的输入。
- **不能（被正确拦）的**：nip.io / userinfo 欺骗 / 端口混淆域名 / 八进制·十六进制·单段 IP / `data:`·`javascript:`·`//` / 大小写 / 尾点 / IPv6 字面量（IPv6 是「误挡」非「被绕」）。
- **结构性判定**：`validateBaseUrl` = 纵深/防手滑；**真正的令牌外送闸门是 CSP `connect-src`**。二者独立 ⇒ 单点失效不致令牌外送（除非同源 XSS 存在，而 §1 判其 sink 为零）。**SSRF**：控制面后端**从不**按用户 baseUrl 发起服务端出网请求（`validateBaseUrl` 纯浏览器侧）⇒ **无服务端 SSRF 跳板**。

---

## ⑤ 静态资源与目录越界（`/ui`）

- **伺服实现**：`api/webui.py:98-116` `build_ui_router` **只**注册固定路径 `GET /ui` → `resolve_webui_index()` → `FileResponse(<固定 dist>/index.html)`。`webui_stats.py:341-348` `resolve_webui_index` 里 `dist_dir` 来自**服务端装配参数**（`_app.py:225 webui_dist_dir`），**请求侧无任何文件名/路径参数**（非 `StaticFiles`、非 `/{path}`、无 `FileRequest`）。
- **判定**：**无路径拼接消费请求输入** ⇒ `..%2f`、编码穿越、符号链接**均无入口**；**无目录列表**（单文件 `FileResponse`，非目录挂载）；**无 favicon/asset 白名单需求**（singlefile 全内联，`img:` 用 `data:` URI）。产物未构建 → 诚实 404 `ui_not_built`（webui.py:105-109）。=> **越界面：不适用/干净**。
- **dist 泄漏扫描（只读、计数/掩码）**：`webui/dist/` 仅 `index.html`（973 KB），**无 `.map`、无 `sourceMappingURL`**（count 0）；真实文件系统路径片段 `LancyCelestia`/`MyWorkspace`/`Documents`/`Users/`/`Program Files`/`NapCat` 命中 **0**（`C:`/`D:` 命中系压缩 JS 三元 `x?C:D` 假阳，`win-sep` 精确式命中 0）；长密钥形态 `sk-[A-Za-z0-9]{16,}` 命中 **0**（`sk-` 命中均为 `mask-`/`risk-`/`desk-` 词干掩码）；无 dev 路径（`/src/`、`@vite`、`/node_modules/` 命中 0）。=> **dist 不含源码 map / 内嵌密钥 / 注释真实路径**。
- **回归锁**：`test_webui_http.py:171,190`（`test_ui_serves_single_file_index_or_honest_404` + 未配置令牌仍伺服壳）锁「单文件/404 诚实」，**间接锁无越界**（因无参数可试）。

---

## ⑥ 日志/追踪数据敏感面（控制面是否已脱敏）

- **承重事实（推翻本项 P1 前提）**：控制面「日志」并非后端原始日志文件尾读，而是**结构化运行事件库** `RuntimeEventService`。三处灭失使原始正文**根本进不了库**：
  1. `events.py:201-202`：`message` 字段**无条件覆盖为分类固定标签**（`_MESSAGES[category]`，如「运行信息」），调用方自由文本被丢弃；
  2. `events.py:111-156 _safe_details`：`details` 递归白名单（仅 `_ID_KEYS`/`_NUMBER_KEYS`/`summary`），且标识符须**同时**「过 `_redact` 后与原文相等」+「匹配 `_IDENTIFIER`（无空格/换行/路径/SQL）」才保留，否则整条丢（**fail-closed**）；
  3. `log_collectors.py:108-124`：采集器**不调 `getMessage`/Formatter、不读 `exc_info`/`pathname`**，loguru sink `backtrace=False, diagnose=False`（不入库栈帧局部变量）。
- **SSE / API 两条路是否覆盖**：`/api/v1/logs/stream`(SSE)、`/logs`、`/logs/{id}` **全部**经 `service.query/get → RuntimeLogEvent.to_dict`（events.py:205-215 → 再过 `_safe_details`）；`redact_local_secrets`+`redact_private_debug` 在**入库与出 DTO 两处**均施加。**=> 覆盖，非「只覆盖出站 QQ 消息」，本项非 P1。** 前端 logs.tsx:290-299 只是把这些已灭失字段当文本渲染。
- **`audit_records` 详情字段**：`control_plane_audit.detail` = `request.state.cp_error_code`（受控码如 `host_not_allowed`/`unauthorized`，_app.py:756），**非用户正文**；`query` 入库前 `redact_query` 打码（audit.py:106,29-41）；`path` 仅路由。**且无任何端点把审计原始行吐给 webui**（前端无该端点，`/api/v1/stats/calls` 只做聚合计数）⇒ **UI 原样展示敏感 audit 字段：未找到该通路。**
- **`_safe_details`(events.py) vs `_sanitize_action_details`(actions.py) 双实现**：actions.py:46 同样 `redact_local_secrets(redact_private_debug(text))` 双器；两者对「前端可见字段」均 fail-closed（灭失优先于泄漏）。**双向风险判定**：泄漏面=低（白名单+正则+双器）；灭失面=可接受（宁可丢整条 identifier 也不留部分脱敏值，符合隐私优先取舍）。
- **`redact_error_for_dto` 例外**：延迟 `last_error` 只用 `redact_private_debug`（不打盘符路径）→ **F7-08**。
- **错误消息透传（X10）**：`_app.py:653-685` 校验/未捕获异常回固定文案（不回显 input/body/栈）；`error_response` 只带受控 `message`+`request_id`+`debug_id`（随机 UUID，非路径）。⇒ 控制面错误消息不裸吐密钥/路径。

---

## ⑦ 前端本地态与跨页/跨标签泄漏

- **共享面**：`webui:baseUrl`/`webui:bearer`/`webui:bearer:ro`/`webui:theme`/`i18nextLng` 在 **localStorage**（同源全标签共享，跨标签串味=预期，单人自用运维台）；`webui:logsCursor` 在 **sessionStorage**（per-tab，隔离正确）。
- **串味风险**：同一浏览器 profile **多管理员/多用户** 交替使用会共享 baseUrl+令牌（后者看到前者存量）⇒ 属部署形态问题（控制面单操作者假设），文案应显式（F7-06）。
- **敏感值进 URL**：仅 `#/knowledge?collection=<id>`（枚举、成员校验），**无**令牌/敏感值入 hash。=> PASS。

---

## ⑧ 机器锁清单与「裸奔」项

| 面 | 现有锁 | 文件:证 | 缺口 |
|---|---|---|---|
| Host 白名单 / DNS rebinding | **强**（14 例：放行/400 不回显/带真令牌仍拦/畸形/多值/端口跟随/扩展/审计痕） | test_control_plane_host_guard.py:69-278 | 无 |
| Bearer 认证/恒定时间/503/失败限速 | **有** | test_webui_http.py:109-155；test_control_plane_v1.py | 无（后端侧） |
| 事件/日志/SSE 脱敏 fail-closed | **强**（秘钥/路径/正文灭失、DB 错不回显、query 不 echo） | test_control_plane_events.py:86-163,303-406 | `redact_error_for_dto` 盘符路径（F7-08） |
| `/ui` 单文件伺服 / 未构建 404 / 未配置仍伺服 | **有** | test_webui_http.py:171-199 | 无（越界因无参数天然锁死） |
| dist 数据形/DTO 契约 | **有** | test_webui_stats/plugins/knowledge/memory_graph.py | 无 |
| **CSP meta 内容** | **无** | 仅 `index.html`/`dist` 存在（本文已核实真在代码里，非只有测试） | **零锁**（可被无声改） |
| **`validateBaseUrl` 白名单/绕过** | **无** | `validateBaseUrl` 唯一「测试」是运行时在 settings 弹窗里跑；`grep tests = 0 命中` | **零锁** |
| **零 HTML sink 不变量** | **无** | — | **零锁**（F7-07 前提靠人守） |
| **X-Frame-Options/nosniff/frame-ancestors** | **无**（功能本就不存在） | grep 命中 0 | **零锁**（F7-01/02 加头须同步补） |
| **前端逻辑单测** | **无有效 harness** | `package.json` 无 vitest/jest；唯一 `src/lib/graph-layout.test.ts` 不被任何 runner 执行（孤儿） | 前端 TS 逻辑**全裸** |

**「完全裸奔」项数 = 5**：CSP 内容、`validateBaseUrl`、零-HTML-sink 不变量、安全响应头、可运行的前端逻辑单测。

### F7-LOCK-01 前端不变量零机器锁 —— **P2（补强优先级最高）**

- **坐标**：整体现象（见⑧表）。
- **根因**：安全关键不变量全在 TS 侧（validator/CSP/sink），而项目无 JS 测试 runner；Python 门禁不读 `webui/src` ⇒ 改坏无门可拦。
- **建议改法（复用既有 pytest 树，零新增依赖、不动前端、不建 JS harness）**：新建 `tests/test_webui_security.py`（**主会话建，非本人**）静态读文件断言：
  ```python
  import re, pathlib
  SRC = pathlib.Path("webui/src"); ROOT = pathlib.Path(".")
  def test_no_raw_html_sinks():
      pat = re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*=|outerHTML|insertAdjacentHTML|document\.write|new Function\(|\beval\(")
      assert not [f for f in SRC.rglob("*") if f.suffix in {".ts",".tsx"}
                  for l in pat.findall(f.read_text(encoding="utf-8"))]
  def test_csp_meta_present_and_strict():
      html = (ROOT/"webui/index.html").read_text(encoding="utf-8")
      assert "default-src 'none'" in html and "connect-src 'self' http://127.0.0.1:* http://localhost:*" in html
  def test_frame_guard_header_present():
      from plugins.bot_unified_runtime.control_plane.api.webui import build_ui_router  # 改后断言含 X-Frame-Options
  ```
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_security.py -p no:cacheprovider --basetemp="$TEMP/f7-lock"`。
- **回归锁**：本条即补齐动作本身。

---

## ⑨ 若主会话照本改法落手：哈希册/门 影响标注（本人不重录）

- **不牵动 `tests/verify_hashes.py`（`--write`）**：其 `TRACKED_FILES`（verify_hashes.py:34-60）全为 `domains/render/card_render/*` + `theme_tokens.py` + `renderer.py`/`templates.py`/`bridge.py`/`usage_cards.py` + `domains/ops/admin/debug.py` + `echo.py` + 4 份 `docs/design` 规格 + `docs/rendering-contract.md` + `DESIGN-SPEC.md`。本台账建议改动目标为 **`webui/src/*`、`webui/index.html`、`control_plane/api/webui.py`、`control_plane/audit.py`**——**无一在跟踪集**；本文新文件 `docs/design/unify-audit-20260919/F7-*.md` 亦不在集。⇒ 改这些 **不会** 触发哈希漂移。
- **doc_sync / config-catalog / auto-facts**：本改法**不新增 `BOT_*` 配置键**（建议把安全头**硬开**、勿加开关），⇒ 不触机器册/目录门。（若反加键 → 须同步 config-catalog A26 + `.env.example` + `docs/auto-facts.md`，届时另计。）
- **构建依赖（关键运维区分）**：
  - 改 `webui/index.html` 的 meta CSP（F7-01 兜底那半）→ **必须 `npm run build` 重出 `webui/dist`** 才在 `/ui` 生效；而 `dist` 变更牵 runtime-layout 卫生门与 `webui_acceptance.py`。
  - 改 `control_plane/api/webui.py`（HTTP 头路线，推荐）→ **不需前端重构建**，仅按铁律「改代码必须重启 bot」生效。⇒ **建议优先头路线**，绕开 dist 重建链。
- **哈希册内文件**：本台账**未建议改动任何哈希册文件**（明确不触 card_render/theme_tokens/echo.py/debug.py）。

---

## 附：可试清单速查（`validateBaseUrl`，只静态推演）

**应被拒（预期 host_not_allowed/invalid_url/bad_scheme）且已核实拒**：`http://127.0.0.1@evil.com`、`http://127.0.0.1.nip.io/`、`http://localhost:8742.evil.com`、`http://0177.0.0.1`、`http://0x7f000001`、`http://2130706433`、`http://127.1`、`data:text/html,x`、`javascript:alert(1)`、`//evil.com`、`http://127.0.0.1.`（尾点，误伤但 fail-closed）。
**应被放行且放行**：`http(s)://127.0.0.1:8742`、`http://localhost:8742`、`HTTP://127.0.0.1`（大小写归一）。
**功能缺口（误挡，非绕过）**：`http://[::1]:8742`（F7-03）、`https://127.0.0.1:8742`（validator 放、CSP connect-src 拦，F7-04）。
