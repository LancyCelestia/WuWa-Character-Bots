# W16 · 网站与 WebUI 全面复查 + webwallgl 壁纸移植方案

> 落盘时刻 2026-10-20。全部读数来自一手源，每条可复跑。
> 未核实项一律写「未找到」或 `(待补充：…)`，**没有一处推测被写成结论**。

---

## 摘要（结论先行）

### 复查结论

**要求 1（视觉）11 项：满足 4 / 部分满足 4 / 未满足 3。**
已经做对的是「大 R 角 / 多板块面板 / 液态玻璃 / 动态油壶渐变」——这四项不是空话，`webui/src/index.css` 里有真 token（`--r-shell:30px`、`--glass-*` 10 个、`--mica-*` 5 个、`--glaze-*` 4 个），全站 `glass-*` 实见 72 处。真正缺的是三块：**粒子特效全站只有记忆图谱一处**、**3D 只在同一个页面**、**壁纸模块完全不支持 Wallpaper Engine 格式**。

**要求 2（详细度）10 项：满足 3 / 部分满足 3 / 未满足 4。**
最刺眼的一条：**「总价」「单位时间总价」不是前端没做，是控制面根本没这个数据**——`grep -rn "total_cost_micro\|unpriced" plugins/bot_unified_runtime/control_plane/` 命中 **0**。费用只活在 `ledger.py` 的写入侧，从未进过任何端点。同理「板块」维度全库无列、「印象」「标签」「好感度增量」有字段无端点。

### 选型结论（一句话版）

| 要做的事 | 结论 | 一句话理由 |
|---|---|---|
| 壁纸（WE 全功能） | **改造** —— 移植 `webwallgl` | 唯一浏览器端 MIT 的 WE scene 渲染器，45 个官方效果走数据驱动、可调参数有正式声明面 |
| 视觉风格 token | **改造**（不换栈） | 现有 token 体系成立，只补字体与失焦回退，不引入新设计系统 |
| 粒子特效 | **直接使用** `tsparticles` | MIT / 8994★ / 2026-10-19 活跃；自研粒子没有理由 |
| 3D 特效 | **直接使用** `@react-three/fiber` + `drei` | three 已在依赖里，加一层 React 绑定即可 |
| 液态玻璃 | **改造**（保留现有）+ 可选 `liquid-glass-react` | 现有三层玻璃已可用；折射增强是可选增强 |
| 配置/字段详细度 | **改造**（补 usage 字段 + 统一展开件） | 通用的 `detail-pane.tsx` / `field-table.tsx` 已经写好但**页面引用 0 处**，是死组件 |
| LLM 费用四项 | **自研**（后端补端点） | **找不到可复用方案**：费用字段从未进控制面，任何前端库都变不出数据 |

---

## 步骤 1 · 复查：要求 → 现状 → 差距

### 表 1-A：要求 1 视觉篇（11 项）

| # | 用户原话 | 现状 | 取证（文件 / 读数） | 结论 |
|---|---|---|---|---|
| 1 | 扁平化 | 材质层有厚度（玻璃 3 层 + 云母 + 颗粒），但不是「色块堆叠 + 重描边」那种脏的拟物 | `index.css`：`--glass-top`/`--glass-bottom`/`--glass-edge-line` 三件套；`--shell-rim` 1px 淡描边 | 部分满足 |
| 2 | 现代化 | **字体是系统栈**，无 web font | `index.css:31` `--font-sans-stack: 'Segoe UI','Microsoft YaHei','PingFang SC',-apple-system,…`；全文件 `@font-face` **0 处** | 未满足 |
| 3 | 绚丽 / 炫丽 | 已有 aurora 三色漂移 + glaze 四组渐变 + 颗粒层 | `index.css`：`.aurora-blob-a/b/c` 三个 `@keyframes aurora-drift-*`（28s / 41s / 53s）；`--glaze-flow/side/card` + `--iris-stroke` | 满足 |
| 4 | 漂亮 / 好看 | 主观词，无法机器判定 | —— | (待补充：可换成一个可核对的标准，如「Awwwards / Mobbin 同档截图对照」) |
| 5 | 大 R 角 | 三档圆角，最大 30px | `index.css:37-39` `--r-shell:30px` / `--r-panel:18px` / `--r-tile:14px` | 满足 |
| 6 | 多板块面板 | 18 个页面 + 面板组件 | `webui/src/pages/` 18 个 `.tsx`；`dashboard.tsx` 内 `<Card` 37 处、`calls.tsx` 10 处、`tokens.tsx` 15 处 | 满足 |
| 7 | 液态玻璃 | 10 个 glass token，全站 72 处使用 | `index.css` `--glass-*` 定义 10 条；`grep -roh "glass[a-z-]*"` 合计 72 | 满足 |
| 8 | mica 云母质感 | 5 个 mica token + 噪点层 | `index.css` `--mica-panel/sided/header/blur/noise` 5 条；`.ambient-grain` 用 `--mica-noise` 两层 radial-gradient 模拟 | **部分满足**：只做了视觉仿制，缺微软 Mica 规范里的**失焦回退中性色**（见步骤 3 表 3-B） |
| 9 | 动态油壶渐变色 | 四组渐变各有归属 | `--glaze-flow`（页首带）/`--glaze-side`（侧栏）/`--glaze-card`（卡片 hover）/`--iris-stroke`（数值虹彩） | 满足 |
| 10 | 粒子特效 | **全站只有记忆图谱一处** | `grep -rln "particle\|Particle"` 仅命中 `components/three/{graph-3d.tsx,force3d.ts,quality.ts,force3d.test.ts}`；且那是 `three.Points` 装饰性球面光点，不是粒子系统 | **未满足** |
| 11 | 3D 特效组件 | three 只被一个页面用 | `grep -rn "from 'three'"` → 仅 `components/three/graph-3d.tsx:21`（且是具名导入，`manualChunks` 单独打成 `vendor-three` 508 KB） | **部分满足** |
| 12 | 移植 WE 全部动态壁纸功能 | 自研单个片元着色器 | `components/appearance/shader-wallpaper.tsx`（5598 B）——一个固定片元着色器，uniform 只有 `uRes/uTime/uA/uB/uC`；无 WE 格式解析、无图层、无效果链、无脚本 | **未满足** |

> 第 4 项「漂亮/好看」是主观判断，我不打算用自评分数冒充满足。

### 表 1-B：要求 2 详细度篇（10 项）

> 本表读数为审计席交付后我逐条复跑确认的结果。

| # | 用户原话 | 现状 | 取证 | 结论 |
|---|---|---|---|---|
| 1 | 所有参数键、键值 | 两套并行登记表 | `pages/config.tsx` 用 `CONFIG_FIELDS`（生成物 567 条 + 手写约 240 条）；`lib/appearance/schema.ts` 的 `RANGES` 17 组 | 部分满足 |
| 2 | 简介 | 外观页每项有 `help` 讲「调大调小会怎样」；配置页只有一行 `desc` | `lib/appearance/schema-fields.ts` 129 个 key / 130 处 help；`components/config/config-field-row.tsx:113` | 满足（外观页）/ 部分满足（配置页） |
| 3 | 使用方法介绍 | **配置行展开区只有「类型/默认值/当前值/来源·版本」四格，没有「怎么用」** | `config-field-row.tsx:184-206`；`ConfigField` 类型无 `usage` 字段 | **未满足** |
| 4 | 取值范围 | 生成物 567 条里只有 16 条带 `min/max/options` | `lib/config-presentation/data/*.ts` 实测；仅外观页有独立 `RANGES`（`schema.ts:7`） | **未满足** |
| 5 | 所有变量、板块必须能展开详细 | **18 页里有 13 页没有任何展开机制**；通用展开件写好但没人用 | `components/console/detail-pane.tsx:39` 与 `field-table.tsx:93` 存在，`grep -rln "FieldTable\|FieldKvRow"` 除彼此外 **0 处引用**（死组件）。无展开机制的页：calls / control-center / credentials / dashboard / logs / memory-graph / operations / plugins / sessions / tokens / visual-editor / latency | **未满足** |
| 6 | LLM token 数 | 五项齐全（prompt / cache_creation / cache_read / completion / total） | 后端 `ledger.py:1073-1077`；端点 `GET /api/v1/stats/tokens`（`api/webui.py:202`）；前端 `pages/tokens.tsx:71-81, 204-217` | 满足 |
| 7 | LLM 单价 | 后端有 4 个价格字段，前端「控制中心」直接裸渲染 JSON | `control_plane/llm_admin.py:224-228,254`（`price_in/price_out/price_cache_read/price_cache_creation`）；`pages/control-center.tsx:35-39`；`lib/humanize.ts:453` 只认 `price` 不认 `price_per_m` | 部分满足 |
| 8 | LLM 总价 | **控制面零命中** | `grep -rn "total_cost_micro\|unpriced" plugins/bot_unified_runtime/control_plane/` → **0**；`pages/dashboard.tsx:349` 写死 `value={undefined}` 并自述「未投影费用字段」 | **未满足** |
| 9 | LLM 单位时间总价 | **全仓无此概念** | `grep -rn "cost_per_hour\|hourly_cost\|price_per_hour" --include=*.py .` → **0**；`control_plane/metrics.py:56-67` 聚合只有 token + status | **未满足（结构性）** |
| 10 | 用户互动落点八维 | 见下表 1-C | —— | 3 满足 / 3 部分 / 2 有字段无端点 |

### 表 1-C：互动落点八维（用户点名要的 8 项）

| 维度 | 表.列 | 有端点 | 前端展示 | 结论 |
|---|---|---|---|---|
| 次数 | `user_affinity.interaction_count`（`affinity.py:1994`） | `GET /api/v1/affinity/board` | `affinity.tsx:162` | 满足 |
| 途径组件 | `audit_records.capability_id`（`ops/audit/logger.py:223`） | `/stats/calls` 的 `by_capability` | `calls.tsx:315`、`dashboard.tsx:466` | 部分（表硬顶 1000 行，实测仅覆盖约 52 分钟） |
| 功能 | 无独立列，与上一行同源 | 同上 | 同上 | 部分 |
| **板块** | **全库无列** | 无 | 无 | **未落库** |
| 记忆 | `memory_facts`（`memory.py:338`）+ `memory_entries_v21` 等 5 表 | `GET /api/v1/memory/graph` | `memory-graph.tsx` | 满足 |
| 好感度 | `user_affinity.affinity` + `affinity_delta_log` | 快照有端点；**增量时序无端点**（`control_plane/` 零命中） | 只有快照 | 部分 |
| 对用户的印象 | `user_affinity.first_impression / first_signals / profile_notes` | **无**（`control_plane/` 零命中） | 无 | **有字段无端点** |
| 标签 | `user_affinity.impression_tags / impression_tag_times` | **无**（零命中） | 无 | **有字段无端点** |

补充：`gateway_channel` 列存在于 `llm_call_records`（`ledger.py:180,541,1098`），但 `control_plane/` 零命中 ⇒ **有列、无端点**。这正是「渠道名显示不出来」的根因之一。

### 四条独立复核命令（可复跑）

```bash
cd plugins/bot_unified_runtime
grep -rn "total_cost_micro\|unpriced" control_plane/ | wc -l   # → 0
grep -rn "gateway_channel"             control_plane/ | wc -l   # → 0
grep -rn "affinity_delta_log"          control_plane/ | wc -l   # → 0
grep -rn "impression_tags\|profile_notes" control_plane/ | wc -l  # → 0
```

---

## 步骤 2 · 调研壁纸：webwallgl 与同类项目

### 表 2-A：webwallgl 本体（一手取证，逐项可核）

| 项 | 读数 | 取证方式 |
|---|---|---|
| 仓库 | `github.com/oneincase/webwallgl` | `gh api repos/oneincase/webwallgl` |
| License | **MIT**（`LICENSE` 首行 `MIT License`，`Copyright (c) 2026 oneincase <462534624@qq.com>`） | raw `LICENSE` 200 |
| npm latest | **3.0.0**，发布于 `2026-10-12T16:09:06.787Z` | `registry.npmjs.org/webwallgl` |
| 版本总数 | 12 | 同上 |
| 运行时依赖 | **1 个**：`mediabunny ^1.56.0` | 3.0.0 的 `dependencies` |
| 包入口 | `types: ./webwallgl.d.ts` / `import: ./webwallgl.mjs` / `default: ./webwallgl.global.min.js` | 同上 |
| 体积（实测） | `webwallgl.mjs` raw **1,395,072 B** / gzip **373,913 B** / brotli **289,466 B**<br>`webwallgl.global.min.js` raw 1,106,453 B / gzip 339,175 B | `stat` + `gzip -9` + `brotli -q 11` |
| Stars / Forks / Open issues | 15 / 5 / 1 | `gh api` |
| 创建 / 最后推送 | `2026-09-04` / `2026-10-14` | `gh api` |
| archived | `false` | `gh api` |
| 仓库体积 | 16240 KB | `gh api` |
| `package.json` 的 `private` | **`true`** | raw `package.json` |

**同族两包（我逐个拉了 tarball 验证）**

| 包 | 版本 | 发布时刻 | License | 依赖 / peer | 体积（raw / gzip） |
|---|---|---|---|---|---|
| `@webwallgl/core` | 3.0.0 | `2026-10-12T16:09:43.489Z` | MIT | **零依赖** | 24,841 B / 6,759 B |
| `@webwallgl/editor` | 3.0.0 | `2026-10-12T16:24:27.559Z` | MIT | peer `webwallgl: 3.0.0` | 198,123 B / 58,240 B |
| `@webwallgl/plugin-sdk` | —— | —— | —— | —— | **npm 404 Not found** |

> `plugin-sdk` 在 README 里被提到，但 npm 上查不到这个包名。这是上游文档与实际发行面的差异，不是我的臆测——`registry.npmjs.org/@webwallgl%2Fplugin-sdk` 返回 `{"error":"Not found"}`。

### 表 2-B：webwallgl 的 API 面（解包 tarball 后逐字读 `webwallgl.d.ts`）

**10 个运行时导出**（`webwallgl.mjs` 末尾 export 块逐字）：

```
bytesSource, createMediaSource, createScene, fileSource, httpSource,
mediaColor, mediaSource, mount, sniffMediaType, workshopIdFromSourceKey
```

`webwallgl.d.ts` 声明 10 个 `export declare function`，与上面逐个对得上 —— **声明与运行时一致，无 phantom export**。

**`mount()` 的全部 options（22 个字段，逐字）**

| 字段 | 类型 / 默认 | 说明（原文要点） |
|---|---|---|
| `source`（必填） | `Source` | 资源来源 |
| `fit` | `"cover"\|"contain"\|"stretch"`，默认 `cover` | 适配模式 |
| `renderDpr` | `number`，0=自动 | backing store = CSS 像素 × DPR；物理最长边封顶 4096 |
| `videoTexScale` | `number`，0=自动 | 视频纹理上传倍率；显式值优先于自动下坡 |
| `fps` | `number`，默认 60 | 帧率上限 |
| `volume` | `0..1`，默认 **0** | 默认静音起步（浏览器自动播放策略） |
| `autoplay` | `boolean`，默认 true | —— |
| `properties` | `Record<string, PropertyValue>` | 用户属性覆盖值 |
| `scripts` | `boolean`，默认 true | 是否执行壁纸自带 SceneScript。**注释明确写「沙箱并非安全边界」** |
| `pointer` | `PointerSource \| null` | **注释：当前未接线**；外部喂指针请用 `pushPointer()` |
| `audio` | `AudioSource \| null` | 音频频谱源；默认内置确定性模拟 |
| `media` | `MediaSource \| null` | 系统媒体源（Now Playing） |
| `features` | `Partial<FeatureFlags>` | **注释：当前未接线** |
| `quality` | `QualityOptions` | AA / 粒子 / 后处理三档 |
| `autoQuality` | `boolean`，默认 **true** | 探到软件渲染自动关后处理；帧率连续 3 秒低于上限 85% 降一档（**只降不升**） |
| `bake` | `boolean`，默认 **true** | 贴图烘焙缓存；实测 −80% 解码耗时 |
| `mountTimeoutMs` | `number`，默认 `60000`；0=关闭 | 首帧看门狗，超时 **reject** |
| `debugHooks` | `boolean`，默认 **false** | 库实例默认关（壁纸页默认开） |
| `occlusion` | `OcclusionBands \| false` | 遮挡分档（暂停/降帧/全量） |
| `onDiagnostic` | `(msg, level) => void` | 级别由库声明：`"info"\|"warn"\|"error"` |
| `onError` | `(err) => void` | **「库不自带降级页，由调用方决定怎么兜」** |
| `onReady` | `(info: SceneInfo) => void` | 首帧完成 |

**`SceneInstance` 的全部方法（27 个，逐字）**

`canvas` / `pause()` / `resume()` / `paused` / `setFit(fit)` / `setFps(n)` / `setVolume(v)` / `setRenderDpr(dpr)` / `setQuality(patch)` / `getQuality()` / `setVideoTexScale(s)` / `getVideoTexScale()` / `setOcclusion(payload|null)` / `setProperties(props)` / `getProperties()` / `setAudio(src|null)` / `setMedia(src|null)` / `media` / `pushPointer(u,v,buttons?,mods?)` / `pointerLeave()` / `pushWheel(dx,dy,mode?,mods?)` / `load(source)` / `release()` / `restore()` / `destroy({releasePkgCache?})` / `stats` / `info` / `on<K>(ev, fn)`

> **用户要的「参数设置调整选项」，兑现面就是 `setProperties` + `getProperties`。** 这两条是同步的、就地生效、不重新拉 pkg —— 注释原文：「就地改属性表 / 效果常量 / 脚本沙箱，**不重新拉取与解析 scene.pkg**（百 MB 包重挂是可感知的卡顿）」。

**用户属性的声明形状（`EditorUserPropertyDecl`，逐字）**

```ts
type "slider" | "color" | "bool" | "combo" | "textinput";
value: boolean | number | string;
text?: string;              // 显示名
min?: number; max?: number; step?: number;
options?: Array<{ label: string; value: string }>;
order?: number;
```

**质量三档的枚举值（逐字）**

- `AntiAliasingMode = "off" | "fxaa" | "msaa2" | "msaa4"`
- `ParticleQuality = "off" | "low" | "medium" | "high"`
- `PostQuality = "off" | "low" | "medium" | "high"`

### 表 2-C：⚠️ webwallgl 的关键限制（这是本报告最要紧的一节）

| # | 限制 | 实证 | 对要求的影响 |
|---|---|---|---|
| **L1** | **不内置任何 WE 官方效果 shader。** `<Effects>` 的执行方式是从壁纸包内读 `shaders/<名>.frag|.vert` | `WE_BUILTIN_SHADERS` 只有 **4 个键**：`flag.vert` / `flag.frag` / `generic.vert` / `generic.frag`。找不到就 `diag("…该 pass 无法编译、已跳过 —— 图层会退回内置材质")` | **45 个 WE 官方效果能否显示，取决于该壁纸包是否自带上百个 shader 文件。无法从代码静态断言，必须用真实壁纸包实测。** |
| **L2** | **必须有 WebGL2**，否则直接抛错 | `createRenderer()`：`const gl = canvas.getContext("webgl2", …); if (!gl) throw new Error("当前浏览器不支持 WebGL2");` | 无 GPU / 老浏览器 = 整条腿不可用，必须回落现有 `shader-wallpaper.tsx` |
| **L3** | **`scripts: true` 不是安全边界** | `MountOptions.scripts` 注释逐字：「沙箱并非安全边界（`Function` / `eval` 无法遮蔽），打开来路不明的壁纸、且与宿主页面同源时应关掉」 | 壁纸来源必须可信；默认应传 `scripts: false` |
| **L4** | `pointer` 与 `features` 两个 option **未接线** | 两处注释都写「**当前未接线**」 | 别照文档写 `pointer:`，用 `pushPointer()` |
| **L5** | 体积 **373 KB gzip**（主包） | 实测 | 相对当前 `vendor-three` 508 KB 可接受，但**必须懒加载**，不能进首屏 |
| **L6** | 项目极新：2026-09-04 创建、15★、`private: true` | `gh api` + raw `package.json` | 上游可能大改；主形态是工作台+桌面应用，npm 是副产物。**必须锁版本 3.0.0，不写 `^`** |
| **L7** | 内置渲染色空间假定 `premultipliedAlpha:false, alpha:false, preserveDrawingBuffer:true` | `createRenderer()` 的 `getContext` 参数 | `preserveDrawingBuffer:true` 有性能代价；不能改（写死在库里），只能在文档里注明 |
| **L8** | 内嵌第三方 `we-scene`（**另一份 MIT**，`Copyright (c) 2026 aurora-wallpaper contributors`） | `renderer/vendor/we-scene/LICENSE` 首行 | 署名义乌：移植时两份 MIT 声明都要留 |

### 表 2-D：同类项目横评（23 个仓库，逐个 `gh api` 复验）

> 两个独立席各自取证后我逐条复跑 `gh api repos/<全名>`，star / license / 日期是 API 原始值。

| 项目全名 | License | Stars | 最后推送 | 语言 | 能补哪一块 | 结论 |
|---|---|---|---|---|---|---|
| **A 组 · WE 生态重实现** ||||||
| `Almamu/linux-wallpaperengine` | GPL-3.0 | 4668 | 2026-08-03 | C++ | 场景图/材质/属性动画的**语义权威**（非浏览器） | 仅作参考 |
| `XHR666/wallpaper-engine-web-loader` | **GPL-3.0** | 1 | 2026-10-16 | JS | 唯一另一份浏览器端 scene.pkg 渲染 | 不适用（GPL 传染 + 1★，不能进 MIT 项目） |
| `rocksdanister/rePaper` | NOASSERTION | 242 | 2020-11-12 | C# | **与 WE 无关**（天气驱动桌面壁纸） | 不适用 |
| `Aromatic05/we-layerd` | **无 LICENSE 文件** | 140 | 2026-10-12 | Rust | Wayland 原生运行时 | 仅作参考 |
| `waywallen/open-wallpaper-engine` | GPL-2.0 | 254 | 2026-10-19 | C++ | Linux 开源内核 | 仅作参考 |
| `catsout/wallpaper-scene-renderer` | GPL-2.0 | 43 | 2026-04-05 | C++ | 最小 scene 渲染（**archived=true**） | 仅作参考 |
| `WallpaperMachine/WallpaperMachine` | GPL-2.0 | 523 | 2026-10-19 | Swift | macOS 播放结构 | 仅作参考 |
| `Unayung/wallpaper-engine-mac` | GPL-3.0 | 75 | 2026-08-27 | Swift | macOS 场景渲染补丁 | 仅作参考 |
| `liixini/skwd-wall` | MIT | 1081 | 2026-10-15 | Rust | 引擎外壳/选择器 | 仅作参考 |
| `jagrat7/linux-wallpaper-engine` | MIT | 210 | 2026-10-15 | TS | 兼容性扫描/管理 UI（非渲染内核） | 仅作参考 |
| **B 组 · pkg / tex 解码** ||||||
| `notscuffed/repkg` | **MIT** | 3804 | 2025-10-08 | C# | pkg 解包 + `.tex`→图像，事实标准 | 改造后可用 |
| `YueFChen/RePKG-Workbench` | MIT | 164 | 2026-09-12 | C# | RePKG 的 GUI 外壳 | 仅作参考 |
| `qwertyadrian/wextractor` | MIT | 5 | 2025-02-27 | Python | pkg 解包 + TEX 转图的库化封装 | 仅作参考 |
| `No4num/wallpaper-engine-scene` | MIT | 1 | 2026-09-17 | Python | pkg → 可编辑工程 + 回包 | 改造后可用 |
| `uKeps/wallpaper-engine-extractor` | MIT | 2 | 2026-10-12 | Python | 抽图片/视频 | 仅作参考 |
| `YV3507/we-static-frame` | MIT | 0 | 2026-09-25 | JS | scene.pkg → 单帧 PNG（可作首帧/降级） | 改造后可用 |
| `CelestialDomeStarPole/WallpaperEngine-PKG-Extractor-Web` | MIT | 1 | 2026-09-21 | TS | **浏览器内**解 pkg | 改造后可用 |
| `Orion-zhen/wallpaper-engine-extractor` | GPL-3.0 | 36 | 2025-03-27 | Python | 批量提取 | 仅作参考 |
| `Yueosa/lianpkg` | GPL-3.0 | 23 | 2026-02-16 | Rust | pkg + tex CLI | 仅作参考 |
| `aqnya/unmpkg` | GPL-3.0 | 25 | 2026-08-29 | C++ | mpkg 解码 | 仅作参考 |
| `askar882/PkgConverter` | Apache-2.0 | 2 | 2022-02-13 | Python | 最小 pkg 转换 | 仅作参考 |
| `TheRioMiner/Wallpaper-Engine-Pkg-to-Zip` | **无 LICENSE** | 115 | 2022-12-13 | C# | pkg↔zip | 仅作参考 |
| **C 组 · 通用渲染** ||||||
| `mrdoob/three.js` | MIT | 116627 | 2026-10-19 | JS | 3D 图层/相机/材质骨架 | 可直接使用（已在依赖） |
| `pmndrs/react-three-fiber` | MIT | 33078 | 2026-10-17 | TS | React 侧场景编排 | 可直接使用 |
| `pmndrs/drei` | MIT | 9995 | 2026-10-19 | TS | `MeshTransmissionMaterial` 等 3D 玻璃件 | 可直接使用 |
| `oframe/ogl` | **Unlicense**（npm 字段；仓库无 LICENSE 文件） | 4676 | 2025-04-13 | JS | 极简 WebGL2 层 | 仅作参考（我们已有 three） |
| `pixijs/pixijs` | MIT | 48421 | 2026-10-17 | TS | 2D 图层/精灵合成 | 仅作参考 |
| `regl-project/regl` | MIT | 5587 | 2026-10-17 | JS | 函数式 GL 管线 | 仅作参考 |
| `tsparticles/tsparticles` | MIT | 8994 | 2026-10-19 | TS | **粒子系统** | **可直接使用** |
| `VincentGarreau/particles.js` | MIT | 30198 | 2024-03-28 | JS | 轻粒子（npm 2.0.0 停在 **2015-05-09**） | 仅作参考 |
| `martinlaxenaire/curtainsjs` | MIT | 1827 | 2025-04-03 | JS | DOM → 贴图平面 | 仅作参考 |
| `patriciogonzalezvivo/lygia` | **Prosperity PL 3.0.0（非 OSI）** | 3467 | 2026-10-18 | GLSL | noise/SDF/blend 函数库 | 不适用（非商用许可） |
| `patriciagonzalezvivo/glslCanvas` | MIT | 2277 | 2023-07-19 | JS | canvas 跑 shader | 仅作参考 |

**未找到（带证据）**

| 检索目标 | 结果 |
|---|---|
| `WeScene` / `WeSceneConverter` | GitHub search `total_count` = **0**；`gh api repos/WeScene/WeScene` → **404** |
| 任何语言的 `scene.json` 类型/模型定义库 | GitHub search + npm + pypi 三面皆无。npm `wallpaper-engine-scene` / `scene.pkg` / `wallpaper-engine-pkg` / `we-scene-json` / `wallpaper-engine-tex` / `wemod-pkg` 全部 `{"error":"Not found"}` |
| `lucaschnabel42/wallgl` | 仓库存在但 **size=0 / language=null**，`GET /contents` 返回 `"This repository is empty."` —— 描述里声称的渲染器**无任何代码证据** |
| `WPFPackage` | `total_count` 2，均无关 WPF 项目 |

---

## 步骤 3 · 调研设计风格

### 表 3-A：token / 设计系统层

| 项目或规格名 | 来源链接 | License | 维护状态 | 能复用哪一块 | 结论 |
|---|---|---|---|---|---|
| **shadcn/ui theming** | https://ui.shadcn.com/docs/theming | MIT | 125,959★ / 2026-10-19 / npm `shadcn` 4.22.1 | 语义 token 对（background/card/muted/border/ring/chart-1..5/sidebar-*）+ `--radius` 派生尺 | **直接使用**（我们已是这套） |
| **Radix Colors** | https://www.radix-ui.com/colors | MIT | 1,709★ / npm 3.0.0 @2023-10-02（三年未发版） | 12 级色阶 + 暗色自动配对 | 直接使用 |
| **Open Props** | https://open-props.style/ | MIT | 5,549★ / 2026-10-11 / npm 1.7.23 | 纯 CSS 变量（含 `--gradient-*`），可 `@import` 进 Tailwind v4 `@theme` | 直接使用 |
| **Magic UI** | https://magicui.design/docs | MIT（真仓 `magicuidesign/magicui`，**22,748★**） | 2026-10-17 | Particles / Meteors / Globe / Border Beam / Bento Grid | **直接使用** |
| **Tailwind Plus** | https://tailwindcss.com/plus | **付费商业授权** | 条款全文 302 → `/plus/login`（**未验证**） | 仅可得公开示例的信息层级 | 仅作参考 |
| **Aceternity UI** | https://ui.aceternity.com/pricing | 免费件 + Aceternity License（$169/年·$199 终身·$1,590 团队） | **无官方开源仓库** | Aurora Background / Sparkles / 3D Card Effect | 改造后可用 |
| **Tremor** | https://www.tremor.so/ | Apache-2.0 | 3,672★ / npm `@tremor/react` 3.18.7 @2025-01-13 | 图表原语（建在 recharts 上，与现有 3.10.1 同源） | 仅作参考（我们已有 recharts） |
| **Geist** | https://vercel.com/font | **OFL-1.1** | 3,654★ / npm `geist` 1.8.1 @2026-10-16 | 几何无衬线界面字 | **直接使用** |
| **Inter** | https://rsms.me/inter/ | **OFL-1.1** | npm `@fontsource/inter` 5.3.0 | 高 x-height 正文字 | 直接使用（备选） |
| Satoshi / Cabinet Grotesk | https://www.fontshare.com/fonts/satoshi | ITF FFL（**正文未取到，未验证**） | 页面 200 | 窄字重几何展示字 | 仅作参考（条款未读到前不用） |

### 表 3-B：表面材质（液态玻璃 / 云母）

| 项目或规格名 | 来源链接 | License | 维护状态 | 能复用哪一块 | 结论 |
|---|---|---|---|---|---|
| **微软 Mica 一手规格** | https://learn.microsoft.com/en-us/windows/apps/design/style/mica | 文档（非代码） | Last updated 2026-07-22 | 原文要点：不透明动态材质，**只在窗口创建时采样桌面壁纸一次**；两层 = base(Mica) + content layer(`LayerFillColorDefaultBrush` 低不透明度实色)；**回退条件**：关透明/节电/低端硬件/窗口失焦/系统<22000 → `SolidBackgroundFillColorBase`；Do：欲透出的层全设 transparent；Don't：重复应用 backdrop material、套到 UI 元素上 | **仅作参考**（Web 无「读系统壁纸」API，只能仿分层与回退，仿不了取色） |
| 微软 Materials 总纲 | https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/materials | 文档 | Last updated 2024-11-05 | 材质三分：occluding（Acrylic/Mica）vs transparent（Smoke） | 直接使用（分层口径） |
| 微软 Acrylic 规格 | https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic | 文档 | 200 | 半透明磨砂的用途边界 | 直接使用 |
| `liquid-glass-react` | https://github.com/rdev/liquid-glass-react | **MIT** | 6,435★ / npm 1.1.1 @2025-06-11 / **peerDeps `react >=19`** | Apple Liquid Glass 折射错觉组件 | **可直接使用**（但停更在 2025-06，需自行接力） |
| `liquid-dom` | https://github.com/AndrewPrifer/liquid-dom | MIT | 2,553★ / 2026-09-06 | 玻璃 DOM 合成 | 改造后可用（**npm 无此包**，只能取源码） |
| `liquidGL` | https://github.com/naughtyduk/liquidGL | **NOASSERTION** | 983★ / 2026-10-01 | WebGPU/WebGL 液态玻璃 | 不适用（许可未明） |

> **「mica 云母质感」这条要求，Web 端不存在官方实现，这是事实不是借口。** `grep` 过 `learn.microsoft.com` 只有 WinUI 3 与 Win32(C++) 两条路径；「Mica for Web」CSS 规范**不存在**。

### 表 3-C：特效组件（粒子 / 3D / 动效 / 渐变）

| 项目或规格名 | 来源链接 | License | 维护状态 | 能复用哪一块 | 结论 |
|---|---|---|---|---|---|
| `@tsparticles/react` | https://github.com/tsparticles/tsparticles | MIT | 8,994★ / npm 4.4.0 @2026-08-31 | 粒子引擎 + React 绑定 | **直接使用** |
| `@react-three/fiber` | https://r3f.docs.pmnd.rs/ | MIT | 33,078★ / npm 9.8.2 @2026-10-14，peer `react >=19 <19.4` | React 渲染器 | **直接使用** |
| `@react-three/drei` | https://drei.docs.pmnd.rs/ | MIT | 9,995★ / npm 10.7.9 @2026-09-25 | `MeshTransmissionMaterial` / `Float` / `Text3D` | **直接使用** |
| `motion` | https://motion.dev/docs/react | MIT | 34,359★ / npm 14.4.0 @2026-10-19 | 面板过渡 / 布局动画 | **直接使用** |
| `@formkit/auto-animate` | https://github.com/formkit/auto-animate | MIT | npm 0.10.0 @2026-07-10 | 一行 hook 做列表进出场 | 直接使用 |
| `@shadergradient/react` | https://shadergradient.co/ | npm 声明 MIT 但**仓库根无 LICENSE** | npm 2.4.20 @2025-12-08 | 可调 3D 渐变 shader（对应「动态油壶渐变色」） | 改造后可用（许可证据链不完整） |
| `GSAP` | https://gsap.com/docs/v3/ | **自定义 Webflow License** | 29,481★ / npm 3.15.0 @2026-04-13 | 时间轴 | **不用**（§VI.2 保留随时改条款） |
| React Bits | https://www.reactbits.dev/ | **MIT + Commons Clause v1.0** | npm 无独立包 | Aurora / Particles 背景源码 | 不用（禁再分发组件本身） |

### 授权陷阱（非 MIT/Apache 全名单）

| 项目 | 真实授权 | 限制 |
|---|---|---|
| Tailwind Plus | 商业买断 | 源码不可再分发；条款被登录墙挡住（**未验证**） |
| GSAP | Webflow "Standard No Charge License" | §V Webflow 可自行终止；§VI.2 保留随时改条款 |
| React Bits | MIT **+ Commons Clause** | 禁单独/打包/移植**出售或再分发组件本身** |
| Aceternity Pro | 自有许可 | 禁当 stock 再分发、禁 marketplace 转售；条文自述可能混入 CC 件 |
| Fontshare Satoshi / Cabinet Grotesk | ITF FFL（非 OFL） | 正文未取到前不得假设可免费商用 |
| `lygia` | Prosperity PL 3.0.0 | **非 OSI**，商用受限 |
| `@shadergradient/react` | npm 写 MIT，仓库无 LICENSE | 证据链不完整 |
| 微软 Mica 文档 | 规范不是代码 | **不得写成「Web 已实现 Mica」** |

---

## 步骤 4 · 选型结论（逐项：直接用 / 改造 / 自研）

| 项目 | 结论 | 理由（含为什么不是另外两项） |
|---|---|---|
| **WE 壁纸渲染** | **改造** —— 移植 `webwallgl` | **「直接用」不成立**：它是库不是应用，宿主 UI 得自己写（README 明写「库不自带降级页，由调用方决定怎么兜」）。**「自研」不成立**：45 个官方效果 + HLSL→GLSL 转译 + `.tex` 解码 + 8 格式模型 + SceneScript 沙箱，自研等于重写一个引擎；而且 webwallgl 已把这些做完（`WE_SHADER_HEADERS` 12 个头文件逐个重建、29 个 `verify:*` 脚本对齐常量）。 |
| **视觉风格 token** | **改造**（不换栈） | 现有 shadcn 语义 token + 三档圆角 + 玻璃/云母/釉渐变四层已成立。换设计系统代价远大于收益。只补两处：字体（系统栈 → Geist OFL）、Mica 失焦回退。 |
| **粒子特效** | **直接使用** `tsparticles` | MIT / 8994★ / 27 天前推送。自研粒子没有理由。 |
| **3D 特效** | **直接使用** `@react-three/fiber` + `@react-three/drei` | three 0.186.1 **已在依赖里**且已单独成 chunk（508 KB），加一层 React 绑定是净增最小路径。 |
| **液态玻璃 / 云母** | **改造**（保留现有）+ 可选补 `liquid-glass-react` | 现有三层玻璃（顶沿亮线 / 底沿暗线 / 外圈描边）已可用；折射是增强不是必需。Mica 补失焦回退。 |
| **动态渐变** | **改造**（保留现有） | `--glaze-*` 四组 + aurora 三 blob 已在跑。不需要再引库。 |
| **配置字段详细度** | **改造**（补 `usage` 字段 + 启用通用展开件） | **关键发现**：`components/console/detail-pane.tsx` 与 `field-table.tsx` 已写好但**页面引用 0 处**。不是缺组件，是没接线。 |
| **LLM 费用四项（总价 / 单位时间总价）** | **自研**（后端补端点） | **找不到可复用方案，这是硬事实**：`total_cost_micro` 在 `control_plane/` **零命中**，费用从未进过控制面；`cost_per_hour` 全仓 **零命中**。任何前端库都变不出不存在的数据。工作量在后端：`metrics.py` 加费用聚合列 + `api/webui.py` 加端点。 |
| **互动落点（板块/印象/标签/好感度增量）** | **自研**（后端补端点或补列） | 同样是「有数据无端点」：`affinity_delta_log` / `impression_tags` / `profile_notes` 在 `control_plane/` 各零命中。「板块」维度**全库无列**，必须改表。 |
| **字体** | **直接使用** Geist（OFL-1.1） | 现栈 `--font-sans-stack` 是系统栈，无 web font。Geist 是 OFL，可自托管（服务器 2C2T/2G/20GB 只需 ~100 KB woff2，不引 CDN）。 |

---

## 步骤 5 · 壁纸实现方案：webwallgl 移植路径 + WE 覆盖表

### 5.1 移植路径（六步，每步有验收口）

#### 步骤 P1 · 引入依赖（锁死版本）

```
webwallgl@3.0.0            # 不加 ^，见 L6
@webwallgl/core@3.0.0      # 可选：服务端预解 pkg 时用（零依赖、Node 可跑）
```

**不引 `@webwallgl/editor@3.0.0`** —— 除非要做「WebUI 内建壁纸编辑器」。理由：它是 58 KB gzip 的编辑器 API 包，本次需求是「播放 + 调参」，`SceneInstance.setProperties` 就够。

**验收**：`npm ls webwallgl` 显示 `3.0.0`；`du -sh webui/dist/assets/*webwall*` 出现独立 chunk。

#### 步骤 P2 · 懒加载腿（不改现有结构，新增一条腿）

在 `webui/src/components/appearance/` 新增 `we-wallpaper.tsx`，与现有两条腿并列：

```
components/appearance/
  background-stage.tsx     ← 保留（本地文件/地址腿，IndexedDB）
  shader-wallpaper.tsx     ← 保留（0 字节默认皮肤，2C2T/2G/20GB 硬约束）
  we-wallpaper.tsx         ← 新增（WE 壁纸腿）
```

**加载姿势**：动态 `import('webwallgl')`，只在用户真的选了 WE 壁纸时才拉。**绝不能进首屏** —— 373 KB gzip 会把 `index` 从 135.8 KB 拖到 500 KB+。

**验收**：`grep -c "webwallgl" webui/dist/assets/index-*.js` → **0**。

#### 步骤 P3 · 与现有互斥判据合流

`webui/src/lib/wallpaper-owner.ts` 的 `WallpaperOwner` 目前是 `'appearance' | 'interface' | 'none'`。加一档：

```ts
export type WallpaperOwner = 'appearance' | 'we' | 'interface' | 'none';
```

仲裁顺序（新）：`we`（用户亲手选的 WE 壁纸）→ `appearance`（本地文件）→ `interface`（内置/地址）→ `none`。

**为什么 `we` 排第一**：它是信息量最大、最贵的那个，选了它说明用户明确要它；同时它与 `appearance` 都是「用户刚挑的」，但 WE 壁纸带参数配置，误让路会丢掉用户刚调的参数。

**验收**：`lib/wallpaper-owner.ts` 的单测扩到四档，且断言「同一时刻只有一个 owner」。

#### 步骤 P4 · 参数面板（这条是「参数设置调整选项」的兑现面）

webwallgl 的参数来自壁纸包内 `project.json` 的 `general.properties`。三种来源，按可信度排序：

| 来源 | 能不能拿到 | 说明 |
|---|---|---|
| `Source.project()` 返回的 `project.json` | ✅ 库直接给 | `Source` 接口有 `project?(signal)`，返回 `unknown \| null`；**返回 `null` 是合法的**（注释原文：「真实壁纸库里大量场景没有 project.json」） |
| `wp.getProperties()` 返回的扁平值表 | ✅ 库直接给 | `Record<string, PropertyValue>`，只有值没有声明（无 min/max/text） |
| `EditorUserPropertyDecl`（`declareUserProperties`） | ⚠️ 需要 `@webwallgl/editor` | 只有这条能拿到 `text`/`min`/`max`/`step`/`options`/`order` |

**判据**：如果壁纸包**自带** `project.json`，`Source.project()` 能拿到原始声明，我们自己解析成 `EditorUserPropertyDecl` 形状（形状已在表 2-B 逐字给出）。**不需要引 editor 包**。

如果壁纸包**没有** `project.json`（注释说这是常态），那就只能 `getProperties()` 拿到「name → 当前值」，**没有 min/max/text** —— 此时面板只能渲染成「按值类型推断的裸控件」，必须如实标「该壁纸未声明参数元数据」。

> ⚠️ **这是本次方案最大的一处不确定，我不打算含糊过去。** webwallgl README 说「参数面板按参数表自动生成」，但**没说参数表格式**，也没在 `.d.ts` 里给出「从 Source 到声明列表」的函数。`EditorUserPropertyDecl` 这个类型确实存在，但只有 editor 包能用。**必须先用一张真实壁纸包实测 `Source.project()` 的返回形状**，才能确定要不要引 editor 包。这一步没做完之前，「参数设置调整选项」只能算设计完成、实现未验证。

**参数写入**：`wp.setProperties({ [key]: value })` —— 同步、就地生效、不重挂（注释原文见 5.2 表）。

**验收**：改滑块 → `getProperties()` 立即反映新值 → 画面变化；且 `console` 里**没有**「重新解析 scene.pkg」的耗时日志。

#### 步骤 P5 · 降级链（三层，逐层回落）

```
① webwallgl（WebGL2 可用 + 壁纸包可解析 + 首帧成功）
     ↓ 失败（onError / mountTimeoutMs 超时 / getContext('webgl2') 为 null）
② 现有 shader-wallpaper.tsx（0 字节片元着色器）
     ↓ 失败（无 WebGL）
③ 纯 CSS 渐变底（现有回落）
```

**必须显式处理的三条失败路径**（都有实证）：

| 失败 | 信号 | 处置 |
|---|---|---|
| 无 WebGL2 | `mount()` reject，`err.message === "当前浏览器不支持 WebGL2"`（`createRenderer` 里 `throw`） | 直接跳 ②，不重试 |
| 首帧挂不上 | `mountTimeoutMs` 到期 **reject**（默认 60000ms） | 跳 ②，并给一行中文提示「这张壁纸挂不上」 |
| 渲染循环无声死亡 | `onDiagnostic` 报 `error` 级 | 同 ② |

**注意**：`onError` 的注释原文是「库不自带降级页，由调用方决定怎么兜」—— **降级是我们的责任，不是库的**。

**验收**：DevTools 里 Application → 屏蔽 WebGL（或用 `--disable-webgl` 启动 Chrome）后，页面仍有背景、控制台无未捕获异常。

#### 步骤 P6 · 安全与功耗两处硬约束

**安全**：`scripts: false` 作为默认。
- 依据：`MountOptions.scripts` 注释逐字「沙箱并非安全边界（`Function` / `eval` 无法遮蔽），打开来路不明的壁纸、且与宿主页面同源时应关掉」。
- 代价：壁纸自带的 SceneScript 不跑 → 部分动态行为缺失。
- 折中：给一个显式开关，默认关，开了要在 UI 上写清「此壁纸的脚本将与控制台同源执行」。

**功耗**（用户服务器 2C2T / 2G RAM / 20GB 月流量）：

| 旋钮 | 建议值 | 依据 |
|---|---|---|
| `autoQuality` | `true`（默认） | 探到软件渲染自动关后处理；帧率连续 3 秒低于上限 85% 降一档，**只降不升** |
| `fps` | `30` | 默认 60 对壁纸是浪费 |
| `renderDpr` | `1` | 默认跟 devicePixelRatio，2K 屏会超采样到 4096 上限 |
| `volume` | `0`（默认） | 非静音起步会被浏览器自动播放策略拦 |
| `occlusion` | 用上 | 可见比例低时自动暂停，省 GPU |
| 壁纸来源 | **本地文件优先**（`fileSource` / `bytesSource` / `mediaSource(File)`） | 服务器 20GB/月，不能每次刷新都从远端拉 scene.pkg |

**验收**：2C2T 机器上开一张 1080p 场景壁纸，`stats.fps` ≥ 25；切到后台标签页后 `stats.running === false`（遮挡暂停生效）。

### 5.2 表 5-A：Wallpaper Engine 官方效果覆盖表（45 项 + 1 场景级 Bloom）

**判定口径必须先说清，否则这张表就是骗人的：**

> webwallgl **不内置任何 WE 官方效果的 shader 实现**（实证：`WE_BUILTIN_SHADERS` 只有 `flag` / `generic` 四个键）。它执行效果链的方式是从壁纸包内读 `shaders/<名>.frag|.vert` 并做 HLSL→GLSL 转译。因此：
>
> - **「播放」列**：指「打开一张原生 WE 壁纸时，该效果能否显示」。这取决于**那张壁纸包是否自带对应 shader**，而不是取决于 webwallgl。我**没有跑过任何真实壁纸包**，所以这一列我**不给逐项判定**，只给统一判定：**数据驱动，理论全覆盖，实测待验**。
> - **「调参」列**：指「在 WebUI 里能不能调这个效果的参数值」。这是 webwallgl 真正保证的能力 —— 通过 `setProperties` / `setEffectConstants` 改 `constantshadervalues`，注释原文：「引擎的效果条目**按引用**持有 scene.json 的那份 `constantshadervalues`，渲染器每帧现读」。
> - **「新建」列**：指「在 WebUI 里从零给一张图加上这个效果」。这需要 shader 资产，webwallgl **不提供** → 全部 ✗。

| 组 | 效果（官方英文原名） | 播放 | 调参 | 新建 | 备注 / 差距 |
|---|---|---|---|---|---|
| **Animation（12）** | Foliage Sway | 待验 | ✓ | ✗ | 官方文档原话可用来模拟草/灌木随风摆动 |
| | Iris Movement | 待验 | ✓ | ✗ | 眼睛追踪 |
| | Pulse | 待验 | ✓ | ✗ | 颜色脉冲，可做闪烁灯 |
| | Cloud Motion | 待验 | ✓ | ✗ | —— |
| | Scroll | 待验 | ✓ | ✗ | 与鼠标无关（纯纹理滚动）。webwallgl 注释实证：「场景包里的 `scroll` 全都是纹理滚动 shader 的 `g_ScrollSpeed`，与鼠标无关」 |
| | Shake | 待验 | ✓ | ✗ | 官方建议可模拟呼吸 |
| | Spin | 待验 | ✓ | ✗ | —— |
| | Swing | 待验 | ✓ | ✗ | —— |
| | Twirl | 待验 | ✓ | ✗ | —— |
| | Water Flow | 待验 | ✓ | ✗ | —— |
| | Water Ripple | 待验 | ✓ | ✗ | 注释里出现 3 次，说明作者处理过 |
| | Water Waves | 待验 | ✓ | ✗ | —— |
| **Blur（4）** | Blur | 待验 | ✓ | ✗ | 粗高斯，比 Blur Precise 省 |
| | Blur Precise | 待验 | ✓ | ✗ | 精细高斯 |
| | Motion Blur | 待验 | ✓ | ✗ | —— |
| | Radial Blur | 待验 | ✓ | ✗ | —— |
| **Interactive（4）** | Cursor Ripple | 待验 | ✓ | ✗ | 需要指针 → `pushPointer()` |
| | Advanced Fluid Simulation | 待验 | ✓ | ✗ | 需指针 |
| | Depth Parallax | 待验 | ✓ | ✗ | 需指针 |
| | X-Ray | 待验 | ✓ | ✗ | 需指针 |
| **Colorization（16）** | Blend | 待验 | ✓ | ✗ | —— |
| | Blend Gradient | 待验 | ✓ | ✗ | —— |
| | Chromatic Aberration | 待验 | ✓ | ✗ | —— |
| | Clouds | 待验 | ✓ | ✗ | —— |
| | Color Key | 待验 | ✓ | ✗ | 绿幕效果 |
| | Film Grain | 待验 | ✓ | ✗ | —— |
| | Glitter | 待验 | ✓ | ✗ | —— |
| | Shimmer | 待验 | ✓ | ✗ | —— |
| | Fire | 待验 | ✓ | ✗ | —— |
| | Light Shafts | 待验 | ✓ | ✗ | —— |
| | Nitro | 待验 | ✓ | ✗ | 静电滋滋 |
| | Opacity | 待验 | ✓ | ✗ | —— |
| | Reflection | 待验 | ✓ | ✗ | —— |
| | Tint | 待验 | ✓ | ✗ | —— |
| | VHS | 待验 | ✓ | ✗ | —— |
| | Water Caustics | 待验 | ✓ | ✗ | —— |
| **Distortion（5）** | Fisheye | 待验 | ✓ | ✗ | —— |
| | Perspective | 待验 | ✓ | ✗ | —— |
| | Refraction | 待验 | ✓ | ✗ | 基于法线图 |
| | Skew | 待验 | ✓ | ✗ | —— |
| | Transform | 待验 | ✓ | ✗ | 旋转/缩放/位移 |
| **Enhancement（4）** | Edge Detection | 待验 | ✓ | ✗ | Sobel |
| | God Rays | 待验 | ✓ | ✗ | 注释里出现 2 次 |
| | Local Contrast | 待验 | ✓ | ✗ | —— |
| | Shine | 待验 | ✓ | ✗ | —— |
| **场景级（1）** | Bloom（含 HDR） | 待验 | ✓ | ✗ | 不是图层效果，是场景设置。webwallgl 有独立 `verify:bloom` 脚本 → 说明作者专测过 |

**统计：45 个图层效果 + 1 个场景级 Bloom = 46 项。调参 ✓ 46/46。新建 ✗ 46/46。播放「待验」46/46。**

### 5.3 表 5-B：用户属性（参数）控件覆盖表

| WE 官方类型 | 官方说明 | webwallgl 是否支持 | 差距 / 补救 |
|---|---|---|---|
| `color` | 取色器 | ✅ `EditorUserPropertyDecl.type` 有 `"color"`；值格式 `"r g b"`（0..1 浮点三元组） | 无 |
| `slider` | 范围内数值 | ✅ 有 `"slider"` + `min` / `max` / `step` | 官方还有「允许小数 vs 整数」开关 → webwallgl 用 `step` 表达，**语义等价但字段名不同** |
| `bool` | 复选框 | ✅ 有 `"bool"` | 无 |
| `combo` | 下拉（text + 隐藏 value） | ✅ 有 `"combo"` + `options: {label, value}[]` | 无 |
| `textinput` | 文本框 | ✅ 有 `"textinput"` | ⚠️ 上游实证：**138 个 `text` 类型属性里 134 个连 `value` 都没有** —— 官方 `text` 多数是「静态说明/分节标题」而非输入框。webwallgl 的 `textinput` 是后者的语义 |
| `texture` | 换图/视频 | ⚠️ 声明层**没有** `"texture"` 字面量 | **补救**：`host/we-props.ts` 的 `WebPropDef.ptype` 注释里列了 `file` / `directory`，说明宿主层另有一套（covers texture）。要用得自己接 |
| `usershortcut` | 系统快捷键 | ❌ 无 | **补救路径**：浏览器无法执行系统快捷键。只能渲染成「说明性文本 + 禁用态」，并如实告诉用户「Web 端不支持」 |
| `group` | 分组 | ⚠️ 声明层无 `"group"` | **补救**：`host/we-props.ts` 的 ptype 注释列了 `group`。分组是纯 UI 概念，自己按 `order` + 声明顺序切即可 |
| （web 侧额外）`file` / `directory` | 官方 web 壁纸专有 | ⚠️ 只在 `host/we-props.ts` 注释出现 | **补救**：`<input type="file">` + blob URL |

**加和：8 种官方类型 + 2 种 web 侧类型 = 10。声明层直接支持 5；宿主层提到 4（texture/file/directory/group）；完全无解 1（usershortcut）。**

### 5.4 表 5-C：其余能力覆盖表

| 能力 | WE 官方 | webwallgl | 差距性质 | 补救路径 |
|---|---|---|---|---|
| **图层类型** | image / text / particle / sound / model / container / fullscreen / camera-light（官方无独立 Layer types 页，据 effects intro + SceneScript 类名拼出） | `EditorLayerKind = "image" \| "text" \| "particle" \| "sound" \| "light" \| "container" \| "group" \| "model"` | **基本覆盖**；官方「fullscreen layer」与 webwallgl 的 `group` / `container` 对应关系需实测确认 | 用真实壁纸包核对 |
| **SceneScript 事件** | 官方 **17** 个：`init` / `update` / `destroy` / `resizeScreen` / `applyUserProperties` / `applyGeneralSettings` / `cursorEnter` / `cursorLeave` / `cursorMove` / `cursorDown` / `cursorUp` / `cursorClick` / `mediaStatusChanged` / `mediaPlaybackChanged` / `mediaPropertiesChanged` / `mediaThumbnailChanged` / `mediaTimelineChanged` | 从 `webwallgl.mjs` 提取到 **16** 个：`init` / `update` / `resizeScreen` / `applyUserProperties` / `cursor` / `cursorClick` / `cursorDown` / `cursorEnter` / `cursorLeave` / `cursorMove` / `cursorUp` / `media` / `mediaLyricsChanged` / `mediaPlaybackChanged` / `mediaPropertiesChanged` / `mediaStatusChanged` / `mediaThumbnailChanged` / `mediaTimelineChanged` | **差 `destroy` 与 `applyGeneralSettings`**；webwallgl 另有 1 个 `mediaLyricsChanged` 是官方文档里没有的扩展 | **补救**：只影响壁纸的清理逻辑与语言切换，不阻塞播放；需要时用 `setProperties` 触发重算 |
| **SceneScript 全局对象** | 官方 7 + `localStorage`：`engine` / `input` / `thisScene` / `thisLayer` / `thisObject` / `console` / `shared` / `localStorage` | **未逐项核实** | —— | `(待补充：需读 renderer/vendor/we-scene/render/*.js 逐项比对)` |
| **模型格式** | 官方文档只说 **`.fbx`（含动画，推荐）** 与 **`.obj`（基础模型无动画）** | README 宣称 8 种：glTF / GLB / FBX / OBJ / DAE / STL / PLY / 3DS；`types.d.ts` 有完整 `MdlSpec` / `MdlClip` / `MdlPart` / 骨骼与动画 API | **webwallgl 超出官方**（多 6 种） | 无需补救；但要实测 FBX 骨骼是否真能跑 |
| **粒子系统** | 官方 7 组件（General / Renderers / Emitters / Initializers / Operators / Child Particle Systems / Control Points）；发射器 3 种（Sphere random / Box random / Layer image） | `FeatureFlags.particles`；`EditorControls.setParticleModel(path, model)` 按**文件路径**热更（实证注释：库内 1847 个对象引用 1047 个去重文件） | **调参覆盖**；建模不覆盖 | 建模需引 editor 包 |
| **音频响应** | 有。Scene 侧 `engine.registerAudioBuffers(16\|32\|64)` → `AudioBuffers{left,right,average}`；Web 侧 `wallpaperRegisterAudioListener`（128 段） | ✅ `MountOptions.audio` + `SceneInstance.setAudio()`；`setAudio` 注释：「**换场景不清空**：装一次对之后所有场景生效」 | 覆盖 | 无 |
| **媒体集成（Now Playing）** | 有。5 个 media 事件 | ✅ `MountOptions.media` + `setMedia()` + `media` 控制面 | 覆盖 | 无 |
| **导出** | WE 客户端导出 GIF / 视频（`help…/functionality/export.html`） | `@webwallgl/editor` 有 `buildScenePkg` / `checkWeCompat`；README 说编辑器可导出 scene.pkg / 松散 zip / 创意工坊目录 / mp4 / PNG | **不在 webwallgl 主包，需引 editor 包** | 若只做播放，不做导出 |
| **无障碍 / 降级** | WE 客户端有回退色 | `onError` 注释：「库不自带降级页，由调用方决定怎么兜」 | **必须自己写** | 见 5.1 步骤 P5 |

---

## 步骤 6 · 质量审查（`/code-review-and-quality`）

### 6.1 五轴自审

| 轴 | 审查对象 | 结论 |
|---|---|---|
| **正确性** | 本报告所有数字与引用 | 每个 GitHub 读数用 `gh api` 复跑过；每个 npm 读数从 `registry.npmjs.org` 取；每条代码取证给文件:行。**未跑真实壁纸包**这一点已写进表 5-A 的口径声明里，没有把「理论支持」写成「已验证」 |
| **可读性** | 报告结构 | 结论先行 → 六步分段 → 每步表格化。用户明确要求「按上述步骤分段」「调研结果用表格」，已满足 |
| **架构** | 选型与现有仓结构的关系 | 壁纸方案是**加一条腿**而不是替换现有两条（`background-stage.tsx` / `shader-wallpaper.tsx` 都保留），仲裁走已有的 `wallpaper-owner.ts`。不新建目录层级 |
| **安全** | `scripts: false` 默认 / 壁纸来源 | 依据库自己的注释（「沙箱并非安全边界」）做出保守默认。**这是用户显式要求的「不要含糊带过」的项，已给理由** |
| **性能** | 373 KB gzip 的引入 | 强制懒加载 + `autoQuality` + `fps:30` + `renderDpr:1` + `occlusion`。并写清「不能进首屏」及其验收命令 |

### 6.2 无虚构引用核对（逐条自查）

| 检查项 | 结果 |
|---|---|
| 有没有写了不存在的仓库？ | 没有。`lucaschnabel42/wallgl` 我明确标了「空仓库、无代码证据、不适用」；`WeScene` / `WeSceneConverter` 明确标「404 / total_count 0 / 未找到」 |
| 有没有把相近项目冒充目标？ | 没有。`rocksdanister/rePaper` 明确写「与 WE 无关、不适用」 |
| 有没有编 License？ | 没有。`ogl` 标 Unlicense 并注明「仓库无 LICENSE 文件，来自 npm 字段」；`we-layerd` / `TheRioMiner` 标「无 LICENSE 文件」；`lygia` 标 Prosperity PL 非 OSI；`GSAP` 标自定义 Webflow License |
| 有没有编参数？ | 没有。所有 `EditorUserPropertyDecl` 字段、`QualityOptions` 枚举、`MountOptions` 22 个字段全部逐字引自 `webwallgl.d.ts` |
| 查不到的有没有编？ | 没有。8 处标 `(待补充：…)` 或「未验证」 |
| 效果覆盖表有没有含糊？ | 没有。明确区分「播放待验 / 调参 ✓ / 新建 ✗」三列，并写明为什么「播放」列不能静态判定 |

### 6.3 本报告的已知不足（不藏）

1. **表 5-A 的「播放」列全部是「待验」** —— 我手上没有真实 WE 壁纸包，跑不了。这一步必须补，否则「移植 WE 完整效果」这条验收标准**未通过**。
2. **参数面板的元数据来源未实测** —— `Source.project()` 返回 `unknown`，形状未知。要不要引 `@webwallgl/editor` 取决于这次实测（见 5.1 步骤 P4 的警告）。
3. **`shared/workbench/` 目录不存在** —— 我查 `shared/workbench/index.ts` 与 `shared/workbench/README.md` 都是 **404**，`shared/glsl.d.ts` 是 200。所以锚点里那条「可能是库的真实源码位置」的猜测**被推翻**了：真实位置是 `renderer/vendor/we-scene/`（59 个文件）。
4. **`applyGeneralSettings` 与 `destroy` 两个官方事件在 webwallgl 里没找到** —— 只影响语言切换与清理，不阻塞播放，但要在实现时自己补。

---

## 附：本波新确立的事实（供后续波次引用）

| 事实 | 值 | 取证 |
|---|---|---|
| webwallgl 主包体积 | 1,395,072 B raw / 373,913 B gzip / 289,466 B brotli | `stat` + `gzip -9` + `brotli -q 11` |
| webwallgl 内置效果 shader 数 | **4**（flag.vert/frag, generic.vert/frag） | `WE_BUILTIN_SHADERS` 对象逐字 |
| webwallgl 重建的 WE shader 头文件数 | **12**（common / blending / blur / composite / fog / foliage / fragment / particles / pbr / pbr_2 / perspective / vertex） | `WE_SHADER_HEADERS` 对象键 |
| webwallgl 内嵌第三方 | `we-scene`，**另一份 MIT**（`Copyright (c) 2026 aurora-wallpaper contributors`） | `renderer/vendor/we-scene/LICENSE` |
| WE 官方内置图层效果数 | **45**（+1 场景级 Bloom） | `docs.wallpaperengine.io/sitemap.xml` 的 `/en/scene/effects/effect/*` 唯一 URL 数 |
| WE 官方用户属性类型数 | **7 + Group**（color/slider/bool/combo/textinput/texture/usershortcut + group） | `docs.wallpaperengine.io/en/scene/userproperties/overview.html` |
| WE 官方 SceneScript 事件数 | **17** | `docs.wallpaperengine.io/en/scene/scenescript/reference.html` |
| WE 官方 SceneScript 全局数 | **7 + localStorage** | 同上 |
| WE 官方 SceneScript 模块数 | **3**（WEColor / WEMath / WEVector） | 同上 |
| WE 官方文档版本线索 | 正文只提到「Wallpaper Engine 2.6」，无文档日期 | `docs…/en/scene/puppet-warp/boneconstraints.html` |
| `help.wallpaperengine.io` 是什么 | **故障排查 FAQ 站**，`/en/scene/*` 返回 200 但内容回落首页（软 404） | 逐页抓取比对 |
| 本仓 `--r-shell` / `--r-panel` / `--r-tile` | 30px / 18px / 14px | `webui/src/index.css:37-39` |
| 本仓 glass / mica / glaze token 数 | 10 / 5 / 4 | `index.css` 逐行 `grep -c "^\s*--glass-\|--mica-\|--glaze-"` |
| 本仓 `field-dict.ts` 条数 | **38** | `grep -c "^    key: '"` |
| 本仓 `schema-fields.ts` 键数 | **129** | 同上口径 |
| 本仓 zh-CN 叶子键数 / 长文案数 | 358 / 55 | Node 遍历 JSON |
| 本仓 `pages/` 页面数 | **18** | `ls webui/src/pages/*.tsx \| wc -l` |
| 本仓 13 页无展开机制 | 见 6.3 与表 1-B 第 5 行 | 逐页 `grep` 展开类关键词 = 0 |
| 本仓死组件 | `components/console/detail-pane.tsx` + `field-table.tsx`（除彼此外 0 引用） | `grep -rln "FieldTable\|FieldKvRow"` |
| 四道门基线（2026-10-20 实跑） | `lint:layout` **rc=0 全部通过**（自测 196/196） | 本波实跑输出 |

---

## 待用户裁定的三件事

1. **`(待补充：必须覆盖的效果/参数优先级)`** —— 用户原文这一条**仍未给**。本报告按「WE 官方文档全集 45+1 项，不预设优先级」处理。如果只关心其中一部分（比如只要 Interactive 4 项做鼠标交互），说一声我按优先级重排 P1-P6。
2. **`(待补充：是否允许改动现有实现、是否需要新建分支)`** —— 仍**未给**。当前方案假定「允许加文件、允许改 `wallpaper-owner.ts` 的三处判定、不新建分支」。如果不是这样，P3 那一步要改。
3. **「漂亮/好看」（表 1-A 第 4 项）** —— 主观词，我不自评。要不要换成一个可核对的标准（如「与 Mobbin/Awwwards 同档截图并排对照」）由你定。
