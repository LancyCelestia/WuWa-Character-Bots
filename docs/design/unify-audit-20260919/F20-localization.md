# F20 · 前端本地化与格式化层审计（统一消息/架构/函数/变量/参数·前端切片）

> 快照声明：本文件于 `date` = **2026-09-19 16:54 +0800**（工作机时区 Asia/Shanghai）生成，锚定当时 `webui/src` 树态。审计期间**零修改工作树**（主会话与他席在飞），证据命令均可复跑。只读扫描 + `webui/node_modules` 内的 `i18next` 真身探测，未跑 `npm build/install`、未起服务、未占端口、未碰任何在跑进程。

## 0. 范围与前置结论（诚实边界）

- **本项目「用户面默认中文」是有意设计**，不是缺陷：`webui/src/lib/i18n.ts:2` 明写「语种收敛为 zh-CN 优先（本项目用户面为中文）」。因此「切英文界面后日期/数字仍中文」这个用户命题，落到实盘只有一条**真实可达路径**：**用户使用英文系浏览器首访**（无手动开关，见 §2）。本报告全部「错在哪」都锚定在「en 浏览器会话」这一真实场景，不虚构「用户点了切换」——因为**没有这个按钮**。
- 双字典 `zh-CN/common.json` 与 `en/common.json` **实盘完全对称 238/238 叶子键**，由本代理程序化解析得出（非抄文档），见 §3。
- 关键反差：**字典是全的，但格式化层把 locale 写死**——en 浏览器会看到「英文文案 + 中文语序日期 + 中文单位时长 + `<html lang="zh-CN">`」四不像。

## 1. locale 硬编码穷举清单（before → after）

### 1.1 单一事实源建议（消除六处重复字面量 = 统一函数/统一参数）

`webui/src/lib/format.ts` 顶部新增一个中心解析器，所有 formatter 调它，**call site 零改动**（保持「统一函数」签名）：

```ts
// format.ts 顶部
import i18n from '@/lib/i18n';

/** Intl 可懂的 BCP-47，随当前 UI 语言。唯一 locale 事实源。 */
export function uiLocale(): string {
  const lng = i18n.resolvedLanguage || i18n.language || 'zh-CN';
  return lng && lng.startsWith('en') ? 'en' : 'zh-CN';
}
```

### 1.2 逐条清单

| # | 坐标 | 锚点字符串 | 当前行为（zh-CN 字面量） | en 浏览器下错在哪 | 正确改法 before→after | 实跑证据 | 可见性 |
|---|---|---|---|---|---|---|---|
| L1 | format.ts:20 | `` `${days}天${hours}小时` `` | 恒输出「3天5小时」 | **英文界面里出现「天/小时」中文单位** | 走 i18n 键（见 §1.3）| 静态（单位是字面量，必出中文）| **可见·高** |
| L2 | format.ts:21 | `` `${hours}小时${minutes}分` `` | 「5小时3分」 | 同上 | 走 i18n 键 | 静态 | **可见·高** |
| L3 | format.ts:22 | `` `${minutes}分${total%60}秒` `` | 「3分12秒」 | 同上 | 走 i18n 键 | 静态 | **可见·高** |
| L4 | format.ts:30 | `date.toLocaleString('zh-CN',{hour12:false})` | `2026/9/20 00:54:27`（Y/M/D 斜杠） | 英文界面里日期是**中文语序 Y/M/D**，英文习惯应 M/D/Y | `date.toLocaleString(uiLocale(),{hour12:false})` → en 得 `9/20/2026, 00:54:27` | **实跑**：zh-CN=`2026/9/20 00:54:27` vs en=`9/20/2026, 00:54:27` | **可见·中** |
| L5 | format.ts:37 | `date.toLocaleTimeString('zh-CN',{hour12:false})` | `00:54:27` | **en/zh 输出相同**（hour12:false 钉 24 时制，冒号分隔一致）| 改 `uiLocale()` 属正确性/一致性，非视觉修复 | 实跑：zh-CN==en==`00:54:27` | 不可见·低 |
| L6 | format.ts:45 | `toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'})` | `09/20` | en/zh 相同 | `uiLocale()` 一致性 | 实跑：zh-CN==en==`09/20` | 不可见·低 |
| L7 | format.ts:47 | `toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})` | `00:54` | en/zh 相同 | `uiLocale()` 一致性 | 实跑：zh-CN==en==`00:54` | 不可见·低 |
| L8 | format.ts:5 | `value.toLocaleString('zh-CN')` | `1,234,567` | **en/zh 分组符同为逗号，输出相同**；仅若日后加 comma-decimal 语种（de/fr）才塌 | `value.toLocaleString(uiLocale())` | 实跑：zh-CN==en==default==`1,234,567` | 不可见·低（潜在） |
| L9 | format.ts:53 | `value.toLocaleString('zh-CN')`（compactNumber 内） | 同 L8 | 同 L8 | 见 §1.4（整函数拟删） | 同 L8 | 不可见·低 |
| L10 | format.ts:51,52 | `` `${…}M` `` / `` `${…}k` `` | 恒英文缩写 k/M | 中文界面里 k/M 应为 千/万/百万；反向不是问题 | `Intl.NumberFormat(uiLocale(),{notation:'compact'})` | 实跑：`compactNumber` **src 内零引用**（`grep -rn compactNumber src/` 仅命中定义行）| 死代码 |
| L11 | format.ts:10 | `${(value/1000).toFixed(...)}s` | `1.5s`/`500ms` | `.` 小数点恒用，en/zh 皆可；`s/ms` 为通用符号 | 可留；若统一小数分隔走 `Intl.NumberFormat(uiLocale(),{maximumFractionDigits:1}).format(...)`+'s' | 静态 | 不可见·低 |
| L12 | affinity.tsx:49 | `item.score.toFixed(1)` | `87.0` | 小数点恒 `.`，en/zh 一致；仅绕开了统一数字层 | 建议 `new Intl.NumberFormat(uiLocale(),{minimumFractionDigits:1,maximumFractionDigits:1}).format(item.score)` 并入 format 层 | 静态 | 不可见·低 |

小结：**可见型硬编码 bug 集中在 L1–L4**（时长中文单位 + 日期中文语序）。L5–L9、L11、L12 对 en/zh 语种对**当前输出相同**——诚实降级为「正确性/一致性隐患 + 违反统一函数原则」，不夸大为「英文界面立刻错乱」。L10 `compactNumber` 是**孤儿函数**（他席 F8「recharts 用 compactNumber」的口径**已过时**：tokens.tsx:145 tickFormatter 实为 `formatInt`）。

### 1.3 时长单位改法（L1–L3，双字典需加键，走 §3 奇偶门）

```ts
// format.ts
import i18n from '@/lib/i18n';
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const total = Math.floor(seconds);
  const d = Math.floor(total / 86400), h = Math.floor((total % 86400) / 3600),
        m = Math.floor((total % 3600) / 60), s = total % 60;
  if (d > 0) return i18n.t('format.uptime.dh', { d, h });
  if (h > 0) return i18n.t('format.uptime.hm', { h, m });
  return i18n.t('format.uptime.ms', { m, s });
}
```
新增键（两份字典都要加，维持 238→241）：
```jsonc
// zh-CN/common.json
"format": { "uptime": { "dh": "{{d}}天{{h}}小时", "hm": "{{h}}小时{{m}}分", "ms": "{{m}}分{{s}}秒" } }
// en/common.json
"format": { "uptime": { "dh": "{{d}}d {{h}}h", "hm": "{{h}}h {{m}}m", "ms": "{{m}}m {{s}}s" } }
```

## 2. 主题切换的语言面（穷尽实装）

| 维度 | 实装真相 | 证据 |
|---|---|---|
| **有无独立语言开关** | **无**。全树无 `changeLanguage` 调用（`grep -rn changeLanguage src/` → 零命中），无任何语言下拉/按钮。 | 见命令 |
| **与明暗主题是否同一入口** | **否，且语言根本无入口**。`theme-switch.tsx` 只切 light/dark（`setTheme`），不碰语言。二者完全分离。 | theme-switch.tsx:17 |
| **语言从哪来** | 仅首访**浏览器自动探测**：`i18n.ts:44` order `['localStorage','navigator','htmlTag']`，`fallbackLng:'zh-CN'`。 | i18n.ts:37,44 |
| **localStorage 键名是否统一命名空间** | **不一致**：主题/令牌/URL 用 `webui:theme`（theme-context.tsx:7）、`webui:baseUrl`+token（api-client.ts），但语言探测缓存走 i18next 浏览器探测插件**默认键 `i18nextLng`**（i18n.ts 未显式设 `lookupLocalStorage`，`caches:['localStorage']`）。命名空间游离于 `webui:` 之外。 | i18n.ts:45 |
| **首访默认语言判定（实测非推断）** | 用 `webui/node_modules/i18next` 真身探得：`en`/`en-US` → **English**；`zh-TW` → `zh`→中文；`ja`/`fr` → 回落 `zh-CN` 中文。即「英文系浏览器得英文，其余一律中文」。`convertDetectedLanguage`（i18n.ts:46-50）虽只归一 zh 未归一 en-US，但 i18next 内核自行按主语言子标签解析到 `en`，故 en-US 能点亮英文。 | 探测输出：`{"lng":"en-US","resolved":"en","title":"ShoreKeeper Console"}` / `{"lng":"ja","resolved":"zh-CN","title":"守岸人控制台"}` |
| **切换后是否只有部分文案变** | **会**（若有开关）：字典内文案变英文，但 §1 的时长/日期 formatter、§4 的绕字典串（`sse.ts`、`baseUrlErrorText`）、§3 的 `：`/`、` 全角标点、后端直出的 `state.reason/message`（semantic-state.tsx:95,107）**都不变**。 | — |
| **语言切换是否重渲染** | **集成无误**：用 `initReactI18next`（i18n.ts:34），`useTranslation` 会订阅 `languageChanged`，一旦有人调 `changeLanguage` 即自动重渲染。**当前无重渲染 bug，只因压根没开关**。将来加开关走 `i18n.changeLanguage` 即可，无需额外 wiring。 | i18n.ts:33-34 |

## 3. 双语言完整性实测（程序化解析，非抄文档）

复跑命令（只读，解析两份 JSON → 展开叶子键）：
```bash
cd webui/src/locales && node --input-type=module -e '<内联 flatten+diff 脚本>'
# 展开嵌套为叶子键，比对 key 集合、空值、{{插值参数}} 集合
```
实跑输出（本代理亲测）：
```json
{ "zhLeaves": 238, "enLeaves": 238, "onlyZh": [], "onlyEn": [], "empty": [], "interp": [] }
```

| 指标 | 结果 | 说明 |
|---|---|---|
| zh-CN 叶子键数 | **238** | 解析所得 |
| en 叶子键数 | **238** | 解析所得 |
| 仅在 zh-CN（onlyZh） | **0** | 差集空 |
| 仅在 en（onlyEn） | **0** | 差集空 |
| 空值/缺值 | **0** | 无 `null`/空串 |
| 插值参数集合不一致 | **0** | 同键两侧 `{{...}}` 完全一致（含 `{{count}}`/`{{unknown}}`/`{{timezone}}`/`{{list}}`/`{{attempt}}`/`{{seconds}}`/`{{shown}}`/`{{dropped}}`/`{{cursor}}`/`{{query}}`/`{{start}}`/`{{end}}`/`{{total}}`/`{{window}}`/`{{name}}`/`{{state}}`/`{{reason}}`/`{{limit}}`/`{{unattributed}}`/`{{code}}`/`{{message}}` 等） |

**「只在一种语言出现的硬编码回退文案」= 0**（键层面）；但**代码层**存在仅在中文里出现的硬编码回退（`sse.ts:126,159` 与全角标点），属 §4 范畴，不在字典差集里，故键奇偶门**抓不到它们**。结论：**字典侧健康度满分，但无机器锁维持**（见 §7），一旦他席改字典漏一侧即悄然漂移。

## 4. 绕过字典的用户可见文案 + 统一路径裁决

| # | 坐标 | 内容 | 类型 | 内联双语 vs 新键 谁划算 | 裁决 |
|---|---|---|---|---|---|
| B1 | settings-dialog.tsx:51 | `'URL 无法解析，请检查格式 · Could not parse URL'` | 内联双语（中·英），带披露注释「locales 不在本改动域」 | 该文件注释自称**规避字典**；三串各含中英 | **统一走字典**（见裁决） |
| B2 | settings-dialog.tsx:52 | `'仅支持 http(s):// 地址 · http(s) URLs only'` | 同上 | — | 走字典 |
| B3 | settings-dialog.tsx:53 | `'仅允许本机地址：同源 / 127.0.0.1 / localhost（任意端口）· Loopback addresses only'` | 同上 | — | 走字典 |
| B4 | sse.ts:126 | `onStatus('auth_error',{ message:'响应无正文流' })` | **纯中文硬编码**，经 `logs.streamError` 的 `{{message}}` 直出到界面 | 无英文对 | **走字典**（`logs.noBodyStream`），英文界面现出中文 |
| B5 | sse.ts:159 | `?? '保留窗口已推进，当前订阅存在缺口。'` | **纯中文硬编码回退**，经 `logs.gapBanner` 的 `{{message}}` 直出 | 无英文对 | **走字典**（`logs.gapDefault`） |
| B6 | dashboard.tsx:38,40,42 | `` `${t('state.noData')}：${…}` `` | **全角冒号 `：` 写死在 TSX** | 英文界面得 `No data yet：xxx` | 冒号并入模板或用半角，**走字典分隔**（如新增 `state.noDataWithReason` "{{label}}: {{reason}}"） |
| B7 | plugins.tsx:28 | `` `：${reason}` `` / `` `：${translated}` `` | 同全角冒号 | 同 B6 | 同 B6 |
| B8 | knowledge.tsx:46 | `item.aliases.join('、')` | **顿号 `、` 写死** | 英文界面别名用 `、` 分隔不合习惯 | 传 `uiLocale()` 或按语言选 `,`/`、` |
| B9 | semantic-state.tsx:95 | `{key ? t(key) : state.reason}` | 未知 reason **直出后端原码** | 后端 reason 可能中文 | 保持「绝不编语义」，但属诚实未译，登记 |
| B10 | semantic-state.tsx:107 / error-boundary.tsx:24 / dashboard.tsx:42 | `{state.message}` / `error.message` | 后端/JS 异常消息直出 | 同上 | 保持直出（技术串），登记为设计取舍 |

**统一路径裁决（不两头下注）**：
> **一律走字典**。理由：①字典 238/238 已满配健康，新增 3–5 个键边际成本极低，且 §3 实测无任何一侧缺键的既成事实，不存在「内联双语更省事」的前提；②`baseUrlErrorText` 的「locales 不在本改动域」是**上批次的改动域借口，不是架构裁定**——本席裁定：本地化文案的唯一真相源就是 `locales/*.json`，内联双语属越权旁路；③一旦确立「§7 键奇偶门」，新键有机器锁保中英同步，内联双语反而**绕过锁**。故 B1–B8 全部迁入字典并删内联串（B6/B7 建议做成带 `{{reason}}` 的完整句键，避免把标点逻辑留在 TSX）。B9/B10 维持直出（后端真相源、禁编语义），不强行塞字典。

## 5. 数字 / 时间语义正确性

**5.1 时区**：后端 `last_message_at`/`started_at`/`created_at` 为 **UTC ISO**，`api-client.ts:249` 注明。前端 `formatDateTime/formatTime` = `new Date(iso).toLocaleString(local)` → **渲染的是浏览器本地时区**。而带时区标注的两处（`calls.tsx:152` `trendDesc` 的 `{{timezone}}`、`dashboard.tsx:159` `startedAt · {{timezone}}`）标的是**后端 `timezone` 字段=服务器时区**——**标签时区 ≠ 数字实际时区**，跨时区机器上二者背离。affinity.tsx:56、logs.tsx:302、dashboard 的 `rowLastMessage`（:74）渲染本地时间却**无时区标注**。
> 统一方案（格式化层落地）：`formatDateTime(iso, timeZone?)` 增可选参，缺省时 `uiLocale()` + 固定 `timeZone` 策略三选一，全站一处定策：①`Intl.DateTimeFormat(uiLocale(),{timeZone:'<server tz>',...})` 并在**每个绝对时间旁统一挂同一 tz 标签**；②或显式按浏览器本地并显示 `resolvedOptions().timeZone` 名。禁止「A 页服务器 tz、B 页浏览器 tz、C 页无标」三态并存。此项呼应 F12 点名，但根因在 formatter 无 tz 参。

**5.2 相对时间**：**未实现共享 helper**。全树仅 `logs.heartbeatAlive`「心跳 {{seconds}}s 前」一处近似相对语义（且拼在字典值里）。`无 Intl.RelativeTimeFormat`、无 `formatRelative()`。绝对/相对取舍：最后消息、启动时间、好感更新时间全用绝对，无「5 分钟前」体验。属功能缺口非缺陷，登记。

**5.3 大数字**：`formatInt`（千分位）与 `compactNumber`（k/M）**两套并存**，但 `compactNumber` 零引用（死代码）。recharts 轴刻度（tokens.tsx:145/153）用 `formatInt` 全量分组，非缩写——**F8「recharts 用 compactNumber」口径过时**。裁决：删 `compactNumber` 或改 `Intl.NumberFormat(uiLocale(),{notation:'compact'})` 后再接轴；不要留孤儿函数（违「统一函数」）。

**5.4 百分比/比率**：无 `formatPercent`/比率 helper；`affinity.tsx:49 score.toFixed(1)` 是分值非百分比。无 `0.85 vs 85%` 混用证据（后端已给口径）。登记为「暂无比率场景」。

**5.5 时长三套口径对照**（互斥性检查）：

| 函数 | 输入 | 输出 | 单位语言 | 场景 | 与其余互斥? |
|---|---|---|---|---|---|
| `formatMs` (format.ts:8) | 毫秒 | `1.5s`/`500ms` | 拉丁 s/ms | 延迟 latency.tsx:30,33 | 独立（ms→可读），与 uptime 不重叠 |
| `formatUptime` (:14) | 秒 | `3天5小时`/`5小时3分`/`3分12秒` | **中文单位** | 进程运行时长 dashboard:156 | 与 formatMs 语义不重叠，但**单位语言不一致**（一拉丁一中文） |
| `formatDateTime`/`formatTime`/`formatBucket` | ISO 时刻 | 时刻串 | — | 时间戳/坐标轴 | 是「时刻」非「时长」，与上两者正交 |

> 结论：时长类**两套**（formatMs + formatUptime），时刻类**三套**（DateTime/Time/Bucket）。无重复计算，但**跨套单位语言不统一**（s/ms 拉丁 vs 天/时/分/秒 中文）。统一：全部单位后缀走 i18n 键或 `Intl.NumberFormat(locale,{style:'unit'})`，一处定义。

## 6. 可访问的语言标记

| 项 | 现状 | 后果 | 改法 |
|---|---|---|---|
| `index.html` `<html lang>` | **静态 `lang="zh-CN"`**（index.html:2）| — | — |
| 语言切换是否更新 `<html lang>` | **从不更新**：`grep documentElement.lang / setAttribute('lang')` 全树零命中；theme-context 只 `classList.toggle('dark')`+`style.colorScheme`（:39-40,49-50），不碰 lang | **en 浏览器拿到英文正文，但 `<html lang>` 仍 zh-CN → 读屏按中文音库念英文，发音错乱** | 在 i18n `languageChanged`（或首启后）同步：`document.documentElement.lang = i18n.language`（建议 `en`/`zh-CN` 二值映射）|
| `<title>` | **静态中文 `守岸人控制台`**（index.html:12）| 英文界面浏览器标签/读屏仍中文 | 监听语言变化写 `document.title = t('app.title')` |

**核心 a11y bug**：英文会话里 `lang` 与实际语言恒不匹配，且**没有任何代码路径去改它**——因没有语言开关触发。

## 7. 锁（机器门现状 + 最小锁草案）

**7.1 现状**
| 问题 | 有锁吗 | 证据 |
|---|---|---|
| 两侧键集合/插值奇偶 | **无**。没有任何测试/脚本解析 `locales/*.json` 做 parity。`test_copy_redline_gate.py` 是**后端文案红线门**（扫 Python 危险内容），与 webui 字典无关。`webui/src` 唯一测试 `graph-layout.test.ts` 只测图布局，不测 locale | `grep -rln i18n/locale` 命中集里无 parity 断言 |
| 格式化层禁 locale 字面量 | **无**。`layout-constitution.mjs` 只扫 hex/字号/间距/调色板（:51-56），不扫 `toLocaleString('zh-CN')`/`天/小时` | layout-constitution.mjs 全文 |
| `webui_acceptance.py` 断中还是断英 | **断中文**且**强制 `locale="zh-CN"`**：`SHELL_MARKER='守岸人控制台'`（:92）、每页 ok 标记为中文串（`窗口内调用`/`别名：`/`热更新即可`/`关联图谱`/`图例`/`渠道（`/`好感度排行`/`心跳`…）、`COMMON_GRACEFUL` 全中文（:91）、`new_context(locale="zh-CN")`（:195）| webui_acceptance.py:53,91-92,195 |

**7.2 「切语言会不会红门」判定**：当前 acceptance **永远只验中文**（locale 钉死 zh-CN），故：①英文面任何回归**门完全看不见**（零英文覆盖）；②但若某修复把 shell 标题改为随 i18n（英文默认）或动了被当标记的中文字面量（尤其 `别名：` 含全角冒号、`渠道（` 含全角括号），**门会因找不到中文串而红**。即门与中文硬字面量**强耦合**——这正是为什么 §4 的 `：`/`（` 标点不该乱改（改了破门），也说明门本身需要语言参数化。

**7.3 最小锁草案（三条，②③可并入 F4/F19 门禁）**

**锁①—键奇偶 + 插值奇偶常驻断言**（纯读、无依赖，pytest 或 node 皆可；建议 pytest 进离线树）：
```python
# tests/test_webui_locale_parity.py  （草案，勿由本席落盘——主会话/收尾统一落）
import json, re, pathlib
BASE = pathlib.Path(__file__).parent.parent / "webui/src/locales"
def leaves(o, p=""):
    d = {}
    for k, v in o.items():
        kk = f"{p}.{k}" if p else k
        d.update(leaves(v, kk)) if isinstance(v, dict) else d.__setitem__(kk, v)
    return d
def vars_(s): return sorted(set(re.findall(r"\{\{\s*([^},]+)", s)))
zh = leaves(json.loads((BASE/"zh-CN/common.json").read_text("utf-8")))
en = leaves(json.loads((BASE/"en/common.json").read_text("utf-8")))
def test_same_keys(): assert set(zh) == set(en), (set(zh)^set(en))
def test_no_empty(): assert all(str(v).strip() for v in {**zh,**en}.values())
def test_same_interpolation():
    for k in zh & en: assert vars_(zh[k]) == vars_(en[k]), (k, vars_(zh[k]), vars_(en[k]))
```
（本席已用等价内联 node 实跑：238/238、onlyZh=[]、onlyEn=[]、interp=[]——断言草案当前即绿。）

**锁②—格式化层禁 locale 字面量静态断言**（并入现有 `webui/scripts/layout-constitution.mjs`，零新基建，`npm run build`/`lint:layout` 已跑它）：
```js
// layout-constitution.mjs check() 内追加
scan(/\.toLocale(?:String|DateString|TimeString|Number)\(\s*['"]/, '写死 locale：改 uiLocale()');
scan(/\bhour12\b/, 'hour12 字面量：随 uiLocale 派生 hourCycle');
scan(/['"]zh-CN['"]/, 'zh-CN 字面量：走 uiLocale()/i18n');
scan(/[天时分秒]/.test ? /(?<!\/\/.*)(天|小时(?!unknown)|(?<!\d)分(?!钟))/ : /(?!)/, '中文时长单位写死：走 i18n 键');
```
（首三条精确；第四条防中文单位正则较糙，建议对 `format.ts` 定向断言 `!(text.match(/[天]/)&&!/t\(/.test(text))` 之类，避免误伤注释。）

**锁③—验收脚本语言参数化**（消 §7.2 耦合 + 补英文覆盖）：`webui_acceptance.py` 增 `--locale {zh-CN,en}`，`new_context(locale=args.locale)`，并把 ok 标记源从**硬编码中文串**改为**按 locale 从 `locales/<lng>/common.json` 读同名键值**。这样中文/英文各跑一轮，英文回归第一次变得可被门看见；且不再因中文标点微调误红。

## 8. 新发现台账（七要素）

严重度基于「en 浏览器这一唯一可达路径下的真实影响」+「是否破统一原则」诚实定级。

| 严重度 | 坐标 文件:行 | 锚点字符串 | 根因 | 建议改法 | 验证命令 | 有无回归锁 |
|---|---|---|---|---|---|---|
| P1 | webui/src/lib/format.ts:20-22 | `` `${days}天${hours}小时` `` | 时长中文单位写死在纯函数，locale 无关化缺失 | 迁 `format.uptime.*` i18n 键（§1.3）| 键奇偶 + §7.2 英文 acceptance | 无锁→补锁②③ |
| P1 | webui/src/lib/i18n.ts:33-52 | `order: ['localStorage','navigator','htmlTag']` | 无 `changeLanguage` 入口，en 面只能靠浏览器探测、用户不可控；键名 `i18nextLng` 游离 `webui:` 命名空间 | 若产品要可切换：加语言开关（i18next 集成已就绪，调 `changeLanguage` 即自动重渲染）；探测缓存键显式 `lookupLocalStorage:'webui:lng'` | 手测 + grep changeLanguage | 无锁 |
| P1 | webui/index.html:2 + 全树 | `<html lang="zh-CN">`（静态）| 无任何代码在语言变化后写 `documentElement.lang`（`grep setAttribute('lang')`=0）| `i18n.on('languageChanged',()=>document.documentElement.lang=i18n.language)`，初值同步；`<title>` 同办 | 起 en 会话查 DOM lang（需实测，现静态推断）| 无锁 |
| P2 | webui/src/lib/format.ts:30 | `toLocaleString('zh-CN',{hour12:false})` | 日期语序钉 zh-CN，en 浏览器出 Y/M/D | `uiLocale()`（§1.2 L4，实跑证语序差异）| 锁② | 无锁→补锁② |
| P2 | webui/src/lib/sse.ts:126,159 | `'响应无正文流'` / `'保留窗口已推进，当前订阅存在缺口。'` | 绕字典纯中文硬编码，经 logs `{{message}}` 直出，en 界面现中文 | 迁 `logs.noBodyStream`/`logs.gapDefault` | 锁①只护键、护不到绕字典串→需 §7.2 acceptance 英文面 | 无锁 |
| P2 | webui/src/components/settings/settings-dialog.tsx:51-53 | `'…格式 · Could not parse URL'` | 内联双语旁路字典，披露注释自认「locales 不在改动域」| 迁 3 键、删内联（§4 裁决=走字典）| 键奇偶 + 组件文案断 | 无锁 |
| P2 | webui/src/pages/calls.tsx:152 / dashboard.tsx:159 vs affinity.tsx:56 / logs.tsx:302 | `trendDesc … {{timezone}}` vs 无标注 | 标签用后端服务器 tz、数字用浏览器本地 tz，二者背离且部分页无 tz 标注 | `formatDateTime` 增 `timeZone` 参统一策、绝对时间旁一致挂 tz（§5.1）| 需真机跨时区实测（现静态推断）| 无锁 |
| P3 | webui/src/pages/dashboard.tsx:38,40,42 + plugins.tsx:28 | `` `：${…}` `` | 全角冒号写死 TSX，en 界面 `No data yet：…`；且该标点被 acceptance 中文标记间接依赖 | 冒号并入完整句键，勿在 TSX 拼（§4 B6/B7）| 改前须同步锁③否则误红 | 无锁（改反会破现有门）|
| P3 | webui/src/pages/knowledge.tsx:46 | `.join('、')` | 顿号写死，英文别名分隔不合习惯 | 按 `uiLocale()` 选分隔符 | 组件测 | 无锁 |
| P3 | webui/src/lib/format.ts:50-54 | `compactNumber` / `${…}k` | **孤儿函数**（src 零引用），英文缩写 k/M 中文不适；F8「recharts 用它」口径过时（实为 formatInt）| 删除，或改 `Intl.NumberFormat(uiLocale(),{notation:'compact'})` 后再接轴 | `grep -rn compactNumber src/`（已跑=仅定义行）| 无锁 |
| P3 | webui/src/components/semantic/semantic-state.tsx:95,107 | `{state.reason}`/`{state.message}` 直出 | 后端原码/异常消息不译（设计：绝不编语义）| 维持直出，登记为「诚实未译」，en 面后端中文串仍中文 | — | 设计取舍，不加锁 |
| P2 | scripts/webui_acceptance.py:195,92,53 | `new_context(locale="zh-CN")` / `SHELL_MARKER="守岸人控制台"` / ok=`"窗口内调用"` | 门只验中文、零英文覆盖、且与中文字面量强耦合 | 锁③参数化 `--locale` 双语各跑 | 复跑 acceptance | 本身即门，但覆盖不对称 |
| P1 | （门缺失）webui/src/locales 无任何测试引用 | — | **键奇偶/插值/禁 locale 字面量三条全无机器锁**，238/238 纯人工维护，他席改字典漏一侧无门可挡 | 补锁①②（§7.3）| 本席内联 node 已证当前绿 | 无锁 |

## 9. 摘要回执（交回主会话）

见文末「返回摘要」。核心一句话：**字典侧健康（238/238 实测对称、零差集、零插值漂移），但格式化层与 a11y 层把中文写死且无任何机器锁**——en 浏览器会话下必现「英文文案 + 中文时长单位(天/时/分/秒) + 中文语序日期 + `<html lang=zh-CN>`」；且**根本没有语言切换按钮**（en 只能靠浏览器探测），验收门 `webui_acceptance.py` 钉死 `locale=zh-CN` 只验中文、与中文字面量强耦合，英文面回归零覆盖。修复面集中在 `format.ts`（uiLocale 单点 + 时长迁键）、`sse.ts`/`settings-dialog.tsx`（绕字典串迁键）、`documentElement.lang` 同步、以及三条锁（键奇偶 + locale 字面量禁 + 验收语言参数化）。
