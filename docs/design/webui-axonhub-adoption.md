# WebUI AxonHub 采纳规格（路线 B：抽设计系统 + 定向移植）

> 状态：v1（2026-09-19，WEBUI 采纳席落盘）。上游快照：`looplj/axonhub` unstable 分支 commit
> `19a3c27d8b947ea794cc3b956ca4c8f86aea1842`（2026-09-17）。上游授权裁定：路线 B（用户已批准）。
> 修订联动：`webui-dashboard-spec.md` §三 Phase A「零构建」条款已改为「构建产物单文件化
> （vite-plugin-singlefile）」。

## 一、来源与许可（合规面）

- 上游前端源码在仓库 `frontend/`；本机 `C:\Software\AxonHub` 只是运行时部署、无源码，与本采纳无关。
- **LICENSE 实读结论**：仓库根 `LICENSE` = Apache License 2.0，适用「除 `llm/` 外全部」；`llm/`
  目录为 LGPL-3.0（Go 后端），本项目**未采用、不涉及**；`llm/bedrock/` 另有 anthropic-sdk-go
  NOTICE，同样不涉及。与批准口径一致。
- **NOTICE 实读结论**：`frontend/NOTICE` 声明上游前端包含 **shadcn-admin（MIT，Copyright (c)
  2024 Sat Naing）** 代码——故义务件是「LICENSE + frontend/NOTICE」两份。
- **义务落点**：两份副本已存 `webui/THIRD_PARTY/axonhub-LICENSE` 与
  `webui/THIRD_PARTY/axonhub-frontend-NOTICE`；`docs/THIRD_PARTY_NOTICES.md` §4 已登记
  （注明修改、不以 AxonHub 名义宣传）。

## 二、路线 B 范围（保留 / 丢弃）

| 上游资产 | 处置 | 说明 |
|---|---|---|
| `src/index.css` token 组织（shadcn 语义变量 + `.dark` + `@theme inline`） | **保留骨架、重彩取值** | 变量名面兼容 shadcn 生态；数值全部换为守岸人卡片值册（§三） |
| `components/ui/` 子集（button/card/badge/skeleton） | **定向移植** | 仅取布局壳与仪表盘所需；Radix 依赖只留 react-slot |
| `webui/src/lib/utils.ts`（cn）、`webui/src/lib/api-client.ts`（fetch 封装 + ApiError） | **移植并改造** | api-client 改造：baseURL 可配（env `VITE_API_BASE_URL`，缺省同源/8742）、Bearer 双 token、`/api/v1` envelope 宽容解包 |
| TanStack Router + Query 骨架 | **保留** | 路由改 **hash history**（单文件 file:// 可开、静态挂载免 SPA fallback）；Query 供 wave-2 真接口 |
| appearance/暗色切换（theme-context 模式） | **保留模式、精简实现** | light/dark/system + localStorage，`documentElement.classList` 切 `.dark` |
| i18next 基建（glob 合并 locales、语言探测、zh-CN） | **保留** | 仅保留 `locales/zh-CN/` 与 `en/` 子集，键为本项目自建 |
| GraphQL/gql 目录、features/*（channels/usageLogs/playground 等）、playwright、ai-sdk、@lobehub、dnd、数据表全家桶 | **丢弃** | 与只读仪表盘无关；需要时按页面逐个再移植 |

## 三、token 映射表（卡片值册 → 前端 oklch）

换算方法：sRGB → 线性化 → Ottosson OKLab 矩阵 → OKLCH，**精确换算非近似**（实跑脚本，值
保留 3/4/1 位精度）。wash 洗色 token 直接取 `domains/render/card_render/theme_tokens.py`
`derive_wash_tokens("#318ce7")` 的产出 hex 再换算，保证与卡片渲染**同源**。

### 3.1 品牌与洗色（卡片值册 → 语义变量）

| 卡片值册 | hex | oklch | webui 落点 |
|---|---|---|---|
| `BRAND_ACCENT` 品牌淡蓝（hsl 210,65%,55%） | `#318ce7` | `oklch(0.632 0.1608 252)` | `--primary`（浅）；`--ring` |
| BRAND darken(×0.8，值册 `_darken_hex`) | `#2770b8` | `oklch(0.537 0.1334 251.6)` | `--primary` hover 基准 / 图表强调 |
| BRAND lighten(+12%，值册 `_lighten_hex`) | `#4999e9` | `oklch(0.669 0.1427 250.8)` | `--primary`（暗色模式） |
| `wash_1` 洗淡蓝（hue210, L0.88, S0.231） | `#d9e0e7` | `oklch(0.903 0.0122 248)` | `--secondary` |
| `wash_2` 洗星空紫（hue265, L0.88, S0.22） | `#dfdae7` | `oklch(0.896 0.0183 303.4)` | `--accent`；`--sk-wash-2`（阴影染色） |
| `wash_3` 洗深蓝（hue228, L0.89, S0.2475） | `#dcdfea` | `oklch(0.905 0.0153 273.8)` | `--muted` |
| `wash_mist` 雾底（hue214, L0.96, S0.11） | `#f4f5f6` | `oklch(0.970 0.0017 247.8)` | `--background`（浅） |
| 亮卡面（hue214, L0.985, S0.30） | `#fafbfc` | `oklch(0.988 0.0017 247.8)` | `--card` / `--popover` 基准 |
| 主文（hue228, L0.20, S0.30） | `#242a42` | `oklch(0.291 0.0448 272.6)` | `--foreground` |
| 次文（hue228, L0.42, S0.16） | `#5a617c` | `oklch(0.497 0.0441 273.4)` | `--muted-foreground` |
| 亮边（hue214, L0.86, S0.16） | `#d6dbe1` | `oklch(0.889 0.0099 252.8)` | `--border` / `--input` |

### 3.2 星空紫 / 深蓝「可用级」（非 pastel，供交互与图表）

| 名称 | 生成式 | hex | oklch | 落点 |
|---|---|---|---|---|
| 星空紫可用级 | hsl(265,55%,55%) | `#824dcb` | `oklch(0.544 0.1875 299.5)` | `--sk-purple`；chart-2 |
| 星空紫 darken | ×0.8 | `#683da2` | `oklch(0.464 0.1571 299.9)` | chart 深紫档 |
| 深蓝可用级 | hsl(228,50%,45%) | `#3950ac` | `oklch(0.466 0.1494 269.3)` | `--sk-deep`；chart-3 |
| 淡蓝中段 | hsl(210,55%,62%) | `#699ed3` | `oklch(0.683 0.0969 249.4)` | chart-4 |
| 紫中段 | hsl(265,45%,68%) | `#a789d2` | `oklch(0.685 0.1095 302.5)` | chart-5；暗色 chart-2 |
| 深蓝中段 | hsl(228,45%,60%) | `#6b7dc7` | `oklch(0.608 0.1145 272.2)` | chart-6；暗色 chart-3 |

### 3.3 图表 `--chart-1..6`（浅 / 暗）

| 变量 | 浅色 | 暗色 |
|---|---|---|
| `--chart-1` | 品牌 `oklch(0.632 0.1608 252)` | 亮品牌 `oklch(0.715 0.1229 250.2)`（`#64a8ed`） |
| `--chart-2` | 星空紫 `oklch(0.544 0.1875 299.5)` | 紫中段亮 `oklch(0.731 0.0922 303.4)`（`#b49ad8`） |
| `--chart-3` | 深蓝 `oklch(0.466 0.1494 269.3)` | 深蓝中段亮 `oklch(0.678 0.0921 273.1)`（`#8594d1`） |
| `--chart-4` | 淡蓝中段 `oklch(0.683 0.0969 249.4)` | 淡蓝中段亮 `oklch(0.729 0.0817 249)`（`#7facd9`） |
| `--chart-5` | 紫中段 `oklch(0.685 0.1095 302.5)` | 星空紫 `oklch(0.544 0.1875 299.5)` |
| `--chart-6` | 深蓝中段 `oklch(0.608 0.1145 272.2)` | 深蓝 `oklch(0.466 0.1494 269.3)` |

暗色面板面：`--background` `oklch(0.248 0.0329 273.6)`（`#1c2031`）、`--card`
`oklch(0.286 0.0375 273)`、`--foreground` `oklch(0.946 0.0017 247.8)`、`--border`
`oklch(0.4 0.0258 273.4)`、`--muted-foreground` `oklch(0.778 0.0084 253.9)`。

### 3.4 圆角 / 阴影 / 字重

- **圆角三档直传**：`--r-shell:30px`（卡壳）→ Tailwind `rounded-xl`；`--r-panel:18px`（面板）→
  `rounded-lg`；`--r-tile:14px`（瓦片）→ `rounded-md`；`--radius` 基准 =14px，`--radius-sm`=8px。
  （覆盖上游 `--radius:0.75rem` 及其 ×1.5/×2 派生式，改为显式钉值——保证与卡片值册 30/18/14 逐值一致。）
- **阴影**：映射值册两级（`SHADOW_PRIMARY`/`SHADOW_SECONDARY`）为 `--shadow`/`--shadow-sm`
  两枚 + wash-2 染色，族外不设第三形态（与卡片「两枚阴影 token」纪律同构；webui 面板非渲染
  契约管辖，但保持同构降低心智）。
- 字重 ≤700、间距克制等 UI 铁律精神照搬；卡片渲染契约（`META_VIEWPORT_POLICY` 等）只管
  QQ 卡片，不约束 webui 页面（webui 是浏览器页，viewport meta 必须有）。

## 四、控制面对接面（wave-2 接线口径）

- **基址**：`http://127.0.0.1:8742`；生产挂 control_plane 静态目录时**同源**（`VITE_API_BASE_URL`
  留空走相对路径），开发走 vite proxy `/api/v1` → 8742。
- **鉴权**：Bearer 双 token（管理 token / 只读 token）。客户端 `localStorage` 键
  `webui:bearer`（管理）与 `webui:bearer:ro`（只读）；`webui/src/lib/api-client.ts` 提供
  `setApiToken()/setReadonlyToken()`，请求头统一 `Authorization: Bearer <token>`。
- **envelope**：`/api/v1` 返回 JSON 信封（code/message/data 形态，以控制面 registry 实现为
  准）；api-client 做宽容解包——对象含 `data` 字段即解包返回 `data`，否则原样透传，避免与
  后端形态漂移耦合。
- **端点**（四端点由并行席在建，wave-2 对齐字段后接真）：
  `GET /api/v1/stats/calls`、`GET /api/v1/stats/tokens`、`GET /api/v1/stats/latency`、
  `GET /api/v1/affinity/board`；日志尾流 `SSE GET /api/v1/logs/stream`（EventSource，
  Bearer 走 query/fetch-stream 以控制面实现为准）。
- 已有可复用端点：`/health`、`/status`（总览页用，spec §三 Phase A 第 1 块）。

## 五、Phase A 页面清单（webui/ 骨架已留位）

1. **总览** `/`：bot 在线/版本/运行时长/发送队列深度/告警数（+一块 mock 统计卡演示）。
2. **调用统计** `/calls`：时间窗（24h/7d/30d）× 会话/用户/能力维度 + 趋势折线（recharts，wave-2 装）。
3. **Token 面板** `/tokens`：输入/缓存创建/缓存命中/输出四项堆叠 × 时间窗 × 模型族。
4. **延迟** `/latency`：渠道 EWMA 当前值 + 历史曲线。
5. **好感度榜** `/affinity`：昵称+数值+档位色阶（WebUI 显数值=2026-09-15 用户裁定；聊天面定性口径不变）。
6. **日志尾流** `/logs`：SSE 追加流。

## 六、工程决策与风险

- **单文件化**：`vite-plugin-singlefile` 全内联 JS/CSS；路由用 hash history 兼容 `file://` 离线
  直开与静态挂载；构建产物仅 `webui/dist/index.html`（node_modules/dist 已入 .gitignore）。
- **不引上游 router-plugin（文件式路由）**：改手写 code-based routeTree，砍掉构建期代码生成
  与 autoCodeSplitting（单文件场景无意义），降低单文件构建的 chunk 边界风险。
- **风险**：① React 19 + TanStack Router 版本漂移（锁 ^1.121 与上游同版）；② Tailwind v4
  CSS-first 需 Vite 插件在场（已用 @tailwindcss/vite）；③ color-mix() 需现代浏览器
  （控制面本机使用，可接受）；④ envelope 形态以并行席后端实作为准，wave-2 对表时若解包
  规则不符只动 `webui/src/lib/api-client.ts` 一处；⑤ 上游后续演进不同步（快照制，升级=重跑抽取）。
- **工程量**：骨架（本轮已落）≈ 半席；wave-2 六页真数据 + recharts + SSE ≈ 1-1.5 席；
  Phase B 配置表单另计。

## 七、本轮已验证

- `npm install` + `npm run build` 实跑通过，产物 `webui/dist/index.html` 单文件，无外部 CDN
  引用（实跑输出见交付报告与 progress-WEBUI.md）。

## 八、版式宪法（2026-09-18 增补，WEBUI-SPEC2 席落盘）

> 适用范围：`webui/src` 全部页面与组件。生效方式：本节落盘后新写页面即时生效；既有六页随
> wave-2 真数据接线一并整改。机器门脚本由 WEBUI-FE 席统一交付（脚本名以其 progress 为准）。

### 8.1 五条铁律

1. **字号五档**（下表即全集，其余字号档与任意值 `text-[…]` 一律禁用）：

| 档 | Tailwind 类 | px / rem | 用途 |
|---|---|---|---|
| 最小 | `text-xs` | 12 / 0.75rem | meta 行、来源路径等宽字、时间戳 |
| 次小 | `text-sm` | 14 / 0.875rem | 次要正文、chip、徽章、副题 |
| 基准 | `text-base` | 16 / 1rem | 正文、卡内主文 |
| 强调 | `text-lg` | 18 / 1.125rem | 组头、卡片标题 |
| 最大 | `text-xl` | 20 / 1.25rem | 页头标题（PageHeader） |

2. **间距 4px 栅格刻度 {4,8,12,16,24}px**：margin/padding/gap 只允许 Tailwind `{1,2,3,4,6}`
   档（=4/8/12/16/24px）；`p-5`/`p-8`/`gap-8` 等刻度外类与任意值间距一律禁用；更大留白用刻度
   值组合实现。
3. **圆角三档 30/18/14**：`rounded-xl`=`--r-shell`(30) 卡壳、`rounded-lg`=`--r-panel`(18)
   面板、`rounded-md`=`--r-tile`(14) 瓦片（index.css 已显式钉值）；`rounded-full` 仅限
   chip/徽章/头像胶囊；其余圆角档禁用。
4. **零硬编码色值/字号**：颜色只经语义 token（§三变量面：--primary/--muted/--border/
   --chart-1..6 等）与 Tailwind 语义类引用；`*.tsx`/`*.ts` 内禁止 `#hex`、`rgb()/rgba()`、
   `oklch()` 字面量；canvas/SVG 绘制取色用 `getComputedStyle` 读 token，不造新色。
5. **组件拼装**：页面一律由清单内组件拼装——`components/ui/`（button/card/badge/skeleton）、
   可复用组件 **StatCard / PageHeader / SectionCard / DataGrid / CategoryChip / Pager**
   （WEBUI-FE 席交付，签名以其 progress 落盘为准）、`app-shell` NavItem。验收口径：
   **新写 CSS 类=0、新增 `.css` 文件=0**（三页工单详见 `webui-pages2-spec.md` §5）。

### 8.2 机器门与违规处置

- 门规则（扫描 `webui/src` 的 `*.tsx`）：①色值字面量 `#[0-9a-fA-F]{6}|rgba?\(|oklch\(`；
  ②任意值字号/间距 `text-\[|\[\d+px\]`；③间距类尾数字不在 {1,2,3,4,6}；④圆角类不在
  {md,lg,xl,full}。命中>0 即红 = 构建验收不通过。
- 快查命令（脚本落地前等价用，webui/ 目录下）：
  `rg -n "#[0-9a-fA-F]{6}|rgba?\(|oklch\(|text-\[|\[\d+px\]" src`
- 违规处置：门红不许交付；确需例外（如 canvas 容器尺寸内联）必须在工单/progress 登记白名单
  条目（文件+行号+理由），禁止行内 suppress 注释绕过；例外条目随下次整改复查。

> 三页施工工单（知识库 / 插件 / 记忆图谱）见 `docs/design/webui-pages2-spec.md`。
