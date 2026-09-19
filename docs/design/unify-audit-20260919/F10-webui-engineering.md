# F10 · 前端工程底座审计（webui 构建配置/环境变量/代理/依赖/产物/可重现性）

> **快照声明**：本审计为**只读**快照，拍摄于 `2026-09-19 16:30–16:38 +08:00`（`date` 实跑输出 Sat Sep 19 16:30:00 2026 / 16:38:38）。
> 快照期间**并行席位仍在改 webui 源码**（`webui/src/pages/dashboard.tsx` 等 mtime=16:33/16:34，见 §三实证），行号与 mtime 证据以本时刻为准；所有「命令实跑」输出原样记录，未跑的一律写「未执行」。
> 本席未修改任何文件、未 build、未 install、未起服务、未 commit；唯一写入=本文件。

---

## 〇、结论速览（八问八答）

| 问题 | 结论 |
|---|---|
| dist 是否入库（假绿路径成立否） | **dist 不在 git**（`git ls-files webui/dist`=0），但发现更狠的假绿：**pre_restart_check 第 8 项与 webui_acceptance 都只验 dist「存在/体积/无外链」，不验新鲜度**——现网 dist(03:55) 落后 src(16:34) 约 12.7 小时仍全绿。判 P1。另一层：**整个 `webui/` 从未进过 git**（`git log --all -- webui/` 空），是单机唯一副本，判 P0 |
| `.tmp-test` 与 ignore 现状 | `.tmp-test/`=8100 文件（含 **275 个 .py**），既不在 `.gitignore`（`git check-ignore` 无输出）也不在 ruff exclude（`pyproject.toml:82` 仅 `_crawlwiki_patch2`）；`ruff check .` 根跑 **44/80 错误来自 .tmp-test**（23 文件）→ lint 门被 scratch 目录压红。原判 P2-16 升级为 P1 |
| 代理前缀缺口 | **1 条**：vite proxy 表只有 `/api/v1`，缺 `/admin/api/v1`；而 api-client 实调两前缀（health/status/bot 走 `/admin/api/v1`）→ P2-9 **属实未修**（`vite.config.ts:18-23`） |
| 前端/后端两套配置账 | 前端唯一 `VITE_API_BASE_URL` 在 `webui/.env.example`（**不存在**）、根 `.env.example`、`docs/config-catalog-full.md`、tests/scripts **全部零登记**（grep 零命中）；端口 8742 后端权威=config.py `bot_control_plane_port` 缺省，前端在 ≥5 处硬编码兜底/提示，无同步机制 |
| 依赖面 | 14 个运行时依赖**全部在用**（逐个 grep import ≥1）；无重复功能库；devDeps 无混入运行时；lock=v3、`npm ls --depth=0` 零 missing/extraneous；lifecycle 脚本仅 esbuild/fsevents 两条常规二进制安装；**`npm audit` 在 npmmirror 镜像上 404 不可用（实跑取证）**，本机无法出漏洞表 |
| 双生效面提示机制 | **无任何机制**。后端铁律「改代码重启才生效」由 pre_restart_check 把守；前端「dist 重建才生效」既不在重启预检、不在 dev.ps1 任何任务、也不在哈希册（verify_hashes 19 项无 webui）→ 「我以为改了」三不管 |
| test/check 聚合入口（P3-21） | **仍未补**：package.json scripts 无 `test`/`check`；`node --test` 单测与 `tsc -b` 只能手敲；dev.ps1 不跑任何前端门 |
| eslint/prettier（P3-20） | 全树无 eslint/prettier/biome 配置文件与依赖；`logs.tsx:121,144` 两处 `eslint-disable-next-line react-hooks/exhaustive-deps` **死注释仍在**（指向不存在的 linter） |

---

## 一、配置项清单与不一致点表

### 1.1 `webui/vite.config.ts`（29 行全文核）

| 项 | 现值 | 口径问题 |
|---|---|---|
| plugins | react + tailwindcss + **viteSingleFile** | 与「单文件壳挂 /ui」设计一致（plus） |
| base | 未设（缺省 `/`） | hash 路由（router.tsx:1 `createHashHistory`）+全内联产物 → 挂 `/ui` 无碍（plus，无需改） |
| alias | `@ → ./src` | 与 tsconfig.app/node 两处 paths **三份重复登记**（vite.config.ts:13 / tsconfig.json:7 / tsconfig.app.json:21），改一处忘两处风险；其中根 tsconfig.json 那份是**死配置**（见 1.2） |
| server.port | 5174 | 未进任何文档/env（与 mock server 注释 `1272 行` 一致） |
| server.proxy | 仅 `/api/v1 → process.env.VITE_API_BASE_URL ∥ 'http://127.0.0.1:8742'` | ①缺 `/admin/api/v1`（P2-9 属实）；②**`process.env` 读不到 `.env` 文件**——Vite 不向 vite.config 的 process.env 注入 VITE_*（须 `loadEnv`），即 proxy target 只认 shell 变量，与客户端 `import.meta.env` 是**两个通道**（P2 新发现）；③`changeOrigin` 拼写正确（http-proxy 选项本名如此，非笔误） |
| build.outDir/emptyOutDir | dist/true | OK |
| build.target/sourcemap/define | 均未设 | vite 7 缺省（target 'modules' 等价 ES2020+/无 sourcemap/无 define）——与 tsconfig `target: ES2023` 不齐平（构建面由 vite esbuild 缺省兜住，信息级）；**dist 不含 sourcemap=无泄密面**（plus） |

### 1.2 `tsconfig*.json`

| 文件 | 关键点 | 不一致/缺口 |
|---|---|---|
| `tsconfig.json` | `files: []` + references(app/node)；**却带 baseUrl/paths** | solution 式配置的 compilerOptions 对引用工程**不生效** → 这份 paths 是死配置（P3） |
| `tsconfig.app.json` | target ES2023 / strict / noUnusedLocals+Parameters / noFallthrough / noUncheckedSideEffectImports / isolatedModules / noEmit / `types:["vite/client","node"]`；include=["src"]（覆盖 `graph-layout.test.ts`，typecheck 顺锁测试文件——plus） | ①**未开 `noUncheckedIndexedAccess`**——前端空值安全影响最大的一条（数组下标/Record 取值一律非空断言）；②未开 `verbatimModuleSyntax`（type-only import 纪律靠人肉）；③未开 `erasableSyntaxOnly`——**本仓库唯一原生 runner（node --test 类型剥离）恰要求可擦除语法**，不开=未来 enum/参数属性会静默炸掉测试门（与 F10-④ 关联，建议开）；④浏览器代码挂 `"node"` types 扩大误用 Node API 面（P3） |
| `tsconfig.node.json` | target ES2022 / include 仅 vite.config.ts | 与 app 的 ES2023 不齐平（本机 Node 26 无实害，登记即可）；**不含 `scripts/*.mjs`**（纯 JS 无类型，layout 门自跑正常，plus） |

composite 问题：references 无 `"composite": true`，但 `webui/node_modules/.tmp/tsconfig.{app,node}.tsbuildinfo` **两枚实存** → `tsc -b` 在本机 TS 5.8.3 实际可跑通（不凭记忆判炸，实据为准）。

### 1.3 `webui/package.json` scripts

| script | 现值 | 判定 |
|---|---|---|
| dev | `vite` | OK |
| build | `node scripts/layout-constitution.mjs && vite build` | 宪法门=**build 前置**，可被「不 build 直接拿旧 dist」绕过（§四 F10-02） |
| typecheck | `tsc -b` | OK（证据见 1.2） |
| lint:layout | `node scripts/layout-constitution.mjs` | OK |
| preview | `vite preview` | OK |
| **test / check** | **不存在** | **P3-21 属实未修**；`node --test src/lib/graph-layout.test.ts` 只活在测试文件第 6 行注释里 |

无 eslint/prettier/format 脚本、无对应依赖与配置——「lint」一词在本前端=自研宪法扫描一员。

### 1.4 与项目其它部分的口径差

| 口径 | 后端/根 | 前端 webui | 差 |
|---|---|---|---|
| 运行时版本声明 | `pyproject.toml requires-python >=3.10,<4.0` | 无 `engines`、无 `.nvmrc`（root+webui 均 ls 无）。本机实跑 node **v26.7.0**/npm 11.19.0；但 `node --test *.ts` 需 **≥22.18/23.6**（原生类型剥离）→ 换机 Node 18/20 即门炸 | **P2 缺口** |
| 配置键登记 | config.py 529 字段 + catalog + auto-facts 三件套，机器门常驻 | VITE_API_BASE_URL 四处零登记（§二.2） | **P2 缺口** |
| 门禁聚合 | dev.ps1 test/lint/typecheck/runtime-layout 四门 | dev.ps1 grep `webui\|npm\|tsc` 零命中——**前端三门（typecheck/宪法/node --test）无一接入** | **P1/P2（F10-08）** |
| 哈希册 | tests/verify_hashes.py 19 项（渲染域交付物） | webui 源码与 dist **均不在册** | 缺口（§五） |
| CI/hook | 无 .github；git hooks 实存 2 枚（post-commit/post-checkout）但=Qoder AI 用量遥测，非质量门 | 同左 | 「四门禁」全靠人自觉（§四 F10-09） |
| 行尾 | .gitattributes：py/md/json/txt/yml 钉 LF、ps1 钉 CRLF、`* text=auto`；`core.autocrlf=true` | `.ts/.tsx/.mjs/.html/.css` 未显式列→检出 CRLF（auto 通道） | 信息级：`* text=auto` 已兜底，入库后如需字节钉帧再补属性行 |

### 1.5 代理与 baseUrl 决定链（三层优先级 + 一暗通道）

```
运行时(浏览器)：localStorage['webui:baseUrl']  >  构建期 baked import.meta.env.VITE_API_BASE_URL  >  ''(同源)
     [api-client.ts:35 实码；设置面板 settings-dialog.tsx:56-68 录入，validateBaseUrl 白名单锁同源/127.0.0.1/localhost]
开发代理(Node)：shell env VITE_API_BASE_URL  >  'http://127.0.0.1:8742'   [vite.config.ts:20，.env 文件无效——暗通道]
```

- 「改一处忘三处」实证面：控制面端口若从 8742 改动，需人肉同步 ≥5 处——config.py:58（后端真值）、vite.config.ts:20（代理兜底）、locales/{zh-CN,en}/common.json:29（面板提示文案）、api-client.ts:33 与 vite-env.d.ts:4（注释）——无任何机器门互锁。
- SSE：`/api/v1/logs/stream` 在现有 proxy 前缀覆盖内（fetch 流式非 WebSocket，`ws:true` 不需要；vite 缺省 http-proxy 不缓冲心跳帧）——**dev 流式无缺口**；唯 `/admin` 缺口使 dev 下 dashboard 健康位与 status/bot 两处坏。
- 静态资产：单文件产物 `data:,` favicon + 全内联，无其它前缀要走代理——proxy 表应含且仅含 2 前缀，现缺 1。

---

## 二、环境变量账（VITE_ 全树核）

- `import.meta.env.*` 全树使用点=**1 处**：`api-client.ts:35` 的 `VITE_API_BASE_URL`；类型面 `vite-env.d.ts:5` 声明同键。`define: {}` 未设——**产物内可编入的构建期常量仅此一键，无 token/host 密钥泄入产物面（结论含证据：使用点唯一且语义为回环 URL，非机密）**。
- 该键登记现状：`webui/.env.example` **文件不存在**；根 `.env.example`、`docs/config-catalog-full.md`、`scripts/`、`tests/` grep `VITE_` 全零命中；唯一文档踪迹=`docs/design/webui-axonhub-adoption.md:26,93` 两处描述性提及。→「前端配置键与后端配置键两套账」的形态是：**前端账本压根没建页**（不矛盾、纯失踪）。
- 与后端键的关系：后端 `BOT_CONTROL_PLANE_PORT=8742`/`HOST=127.0.0.1` 在 .env.example:23-24 + config.py:57-58 有账；前端对位值全靠硬编码兜底——两套账无交叉锁（pre_restart_check 第 9 项只查后端三键是否配置，不查前端兜底常量是否仍等于后端真值）。
- 生产 `webui_dist_dir`：`create_control_plane_app(webui_dist_dir=None)` 无调用方传参（全树 grep 零命中）→ 走 `webui_stats.py:341-348` 缺省 **`Path(__file__).parents[3]/webui/dist`**，锚定文件位置而非 cwd——换工作目录起进程不坏（plus）；产物缺失 404 `ui_not_built` 诚实体（api/webui.py:103-110，plus）。

---

## 三、产物入库与忽略策略（判词 + 现场证据）

```
$ git ls-files webui/            → 0 行（COUNT=0）
$ git ls-files webui/dist        → 0 行
$ git log --all --oneline -- webui/  → 空
$ git status --porcelain webui/  → ?? webui/            ← 整个前端=未跟踪，史上零提交
$ git check-ignore -v .tmp-test webui/dist webui/node_modules ...
  .gitignore:86:webui/dist/	webui/dist
  .gitignore:85:webui/node_modules/	webui/node_modules     ← .tmp-test / %TEMP% / .tmp-cp-* / 根 *.png 均无输出=未忽略
$ find webui/src webui/index.html webui/vite.config.ts -newer webui/dist/index.html
  webui/src/components/patterns/patterns.tsx  webui/src/components/ui/card.tsx
  webui/src/pages/dashboard.tsx  webui/vite.config.ts          ← src 五件套比 dist 新
$ ls -la: dist/index.html=Sep 19 03:55（973,154 B）；上述 src=Sep 19 16:33/16:34
```

**判词**：
1. 「dist 入库→不改源码也能过门」**狭义不成立**（dist 被 ignore 且零跟踪；`.gitignore:86` 系未提交工作区改动，`git diff` 实证）。
2. **广义假绿路径真实成立且已兑现**：`pre_restart_check.py check_webui`（432 行起）只做存在/0<size<10MB/无外链三查、**缺失=SKIP 不算红**；`webui_acceptance.py --dist` 直接伺服 dist 现物；两门都**不比对 src mtime**→当前树「src 比 dist 新 12.7h、预检照样绿、验收拿旧壳」是活案例。收口级，**判 P1**。
3. `.tmp-test/`（并行席位 scratch，8100 文件含 275 py，正在被他人使用——本席未动）：不在 .gitignore、不在 ruff exclude，**根跑 lint 44 错/23 文件全出自它**（`ruff check .tmp-test --no-cache` 实跑 "Found 44 errors"）→ lint 四门之一不可能绿。判 **P1**。
4. 顺带登记（同族卫生，非 webui 本体）：根目录实存 `%TEMP%`（字面量目录名，重定向事故化石）、`.tmp-cp-82ed…/`、验收截图 `logs-page.png/tokens-page.png/affinity-page.png/calls-page.png`——全部未忽略未跟踪，`git status` 噪音源。

---

## 四、新发现台账（七要素）

**F10-01｜P0｜整个 `webui/` 从未纳入版本控制**
- 坐标：仓库根（`git ls-files webui/`=0；`git log --all -- webui/` 空，实跑见 §三）
- 锚点：`?? webui/`（git status）
- 根因：前端波次全部产物（源码 34 文件+THIRD_PARTY 许可证 2 份+lock+config）停在未跟踪态；历批「未 commit 裁决权在用户」惯例外溢，但其它批有已入库前史、本树是**从零单机唯一副本**——磁盘事故=前端整体归零，且 archive 覆盖情况未查证（禁读 Archive）
- 建议改法：主会话按 git 纪律逐文件显式 `git add webui/`（node_modules/dist 已被 ignore 兜住，`.gitignore:85-86` 两行须先随本次提交落库）→ 提交后 `git show --stat HEAD` 核对；提交前顺手 `git ls-files webui | wc -l` 预期 ≈40
- 验证命令：`git ls-files webui/ | wc -l`（>0）；`git check-ignore -v webui/dist/index.html`
- 回归锁：无需新增（跟踪态本身即事实）；**授权面提醒：本席未做任何 git 写**

**F10-02｜P1｜dist-vs-src 无新鲜度断言——「双生效面」前端半侧裸奔（含现网实证）**
- 坐标：`scripts/pre_restart_check.py:432-470`（check_webui）；测试面 `tests/test_pre_restart_check.py:325`
- 锚点：`WEBUI_INDEX_REL = "webui/dist/index.html"`（pre_restart_check.py:63）与 `check_webui` 中仅 `is_file/stat().st_size/_external_asset_refs` 三查
- 根因：后端有重启门、前端「重建才生效」无任何门/提示；AGENTS.md 铁律只覆盖 py 侧；现网 dist(03:55) 落后 src(16:34) 即活案例
- 建议改法（可直接落手）：check_webui 外链判定之后追加第四查——
  ```python
  newest_src = max(
      (p.stat().st_mtime for p in [
          *project_root.joinpath("webui", "src").rglob("*"),
          project_root / "webui" / "index.html",
          project_root / "webui" / "vite.config.ts",
          project_root / "webui" / "package.json",
          project_root / "webui" / "package-lock.json",
          project_root / "webui" / "scripts" / "layout-constitution.mjs",
      ] if p.is_file()),
      default=0.0,
  )
  if newest_src > index_path.stat().st_mtime + 2.0:
      return CheckResult(cid, name, FAIL,
          f"dist 早于源码（index.html mtime {datetime.fromtimestamp(index_path.stat().st_mtime):%F %T} < 最新 src {datetime.fromtimestamp(newest_src):%F %T}）",
          "改了 webui/src 未重建：cd webui && npm run build。")
  ```
  （`datetime` 需入 imports；`+2.0` 容文件系统粒度。若嫌硬可先 WARN 一代再升 FAIL。）同时把该检查并入 tests/test_pre_restart_check.py 的 make_project 夹具：写一个 src mtime>dist 的负样本，断言 FAIL 文案含「未重建」
- 验证命令：venv python scripts/pre_restart_check.py --json（当前树应出红；带 --project-root tmp 正负样本）
- 回归锁：**建议改后新增**（现状无）

**F10-03｜P1｜`.tmp-test/` 污染 lint 门（P2-16 升级：从「不卫生」到「门必红」）**
- 坐标：`.gitignore`（缺行）＋ `pyproject.toml:82` `extend-exclude = ["_crawlwiki_patch2"]`（缺项）
- 锚点：`ruff check .tmp-test --no-cache` 实跑 → `Found 44 errors.`；`ruff check . --no-cache --statistics` 实跑 → 全树 `Found 80 errors`，其中 concise 输出 grep `tmp-test` 前缀=44（23 文件）
- 根因：各席把 scratch 落 `.tmp-test/`，双 ignore 体系（git/ruff）都没跟上；ruff 显式路径可扫入、根跑经 `--no-cache` 复验亦计入
- 建议改法：`.gitignore` 追加 `.tmp-test/`（顺带 `%TEMP%/`、`.tmp-cp-*/`）；`pyproject.toml` 改 `extend-exclude = ["_crawlwiki_patch2", ".tmp-test"]`；目录本体**不动**（可能正被占用）
- 验证命令：`git check-ignore -v .tmp-test`（出命中行）；`ruff check . --no-cache --statistics | grep -c tmp-test`（=0）
- 回归锁：无（可并入既有 doc_sync 类门，非必须）

**F10-04｜P2｜vite proxy 缺 `/admin/api/v1`（P2-9 属实未修）**
- 坐标：`webui/vite.config.ts:18-23`（proxy 表）；消费方 `webui/src/lib/api-client.ts:450,452`
- 锚点：`'/api/v1': {`（表内唯一键）
- 根因：端点分双前缀（health/status 在 /admin/api/v1，统计在 /api/v1），proxy 表按单前缀写就；dev 模式总览页健康位/状态位打不通（同源 5174 下 404）
- 建议改法：见 F10-05 的 loadEnv 版整体替换——`proxy: { '/api/v1': { target, changeOrigin: true }, '/admin/api/v1': { target, changeOrigin: true } }`
- 验证命令：dev 起后 `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:5174/admin/api/v1/health`（控制面在线时应为 401/200 而非 404）——**本席未起服务，属后人验收项**
- 回归锁：无（前端配置文件在 pytest 盲区；可并入 F10-07 的 dev.ps1 门+一条断言 vite.config 文本含两前缀的极简静态锁）

**F10-05｜P2｜proxy target 读 `process.env`，`.env` 文件通道不通（双通道暗坑）**
- 坐标：`webui/vite.config.ts:20`
- 锚点：`process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8742'`
- 根因：Vite 只把 `.env` 的 VITE_* 注入 `import.meta.env`，**不注入 vite.config 的 process.env**（需 loadEnv）；而客户端用的恰是 import.meta.env（api-client.ts:35）→ 同名键两通道语义分裂：写进 webui/.env 只影响构建产物，不影响 dev 代理，「改了没效果」型
- 建议改法：`import { defineConfig, loadEnv } from 'vite';` 改函数式 config：
  ```ts
  export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    const target = env.VITE_API_BASE_URL || 'http://127.0.0.1:8742';
    return { /* plugins/resolve 原样; */ server: { port: 5174, proxy: {
      '/api/v1': { target, changeOrigin: true },
      '/admin/api/v1': { target, changeOrigin: true },
    } } , build: { outDir: 'dist', emptyOutDir: true } };
  });
  ```
  并新建 `webui/.env.example`：`# 控制面基址（dev proxy 与构建期 baked 双通道同读此键；生产同源留空）` + `VITE_API_BASE_URL=`
- 验证命令：webui/ 下 `npm run typecheck`；`node --experimental-strip-types` 不需要——proxy 行为验收同 F10-04
- 回归锁：无；**.env.example 新文件须在 `webui/.gitignore` 之外正常入库（本席未建，改法供主会话）**

**F10-06｜P2｜`test`/`check` 聚合入口缺失（P3-21 属实未修）+ 宪法门「常驻」口径与机制漂移**
- 坐标：`webui/package.json:6-12`；对照 `docs/HANDBOOK.md:2257`（「常驻门：…WebUI 版式宪法扫描门…」）与 `webui/scripts/layout-constitution.mjs`
- 锚点：scripts 块无 `"test"`；`grep -in "webui|npm|tsc|layout" scripts/dev.ps1` 仅命中 runtime-layout 字样（实跑）
- 根因：宪法门仅挂 `npm run build` 前置——不 build 即可绕过；HANDBOOK 称其常驻，实际 pytest/dev.ps1 双不接；node --test 门仅活在注释（graph-layout.test.ts:6）
- 建议改法：package.json scripts 增两行：
  ```json
  "test": "node --test src/lib/graph-layout.test.ts",
  "check": "npm run typecheck && npm run lint:layout && npm run test"
  ```
  dev.ps1 增 `-Task frontcheck`：`Invoke-External npm.cmd @("run","check","--prefix","webui")`（Windows 下 npm 须 `.cmd` 直调的坑一并规避）；AGENTS.md 第五部分验证命令表补一行；或退一步——把 HANDBOOK「常驻」措辞降为「build 前置」，二选一改，别两头都假
- 验证命令：`cd webui && npm run check`（预期 7 测试 pass + 两门绿；本席未跑，npm run 会触发 tsc 写 tsbuildinfo，属 node_modules 变更禁区）
- 回归锁：无；tests/test_pre_restart_check.py:325 仅锁「缺失=SKIP 文案」，与 freshness 无关

**F10-07｜P2｜前端无 Node 版本锚（engines/.nvmrc 双缺），node --test 门在旧 Node 必炸**
- 坐标：`webui/package.json`（无 engines 字段，全文核）；`ls webui/.nvmrc .nvmrc` → 皆 No such file（实跑）
- 锚点：`graph-layout.test.ts:2-6`（`import { test } from 'node:test'` + 注释「Node ≥23 原生 TS 类型剥离」）
- 根因：测试门依赖非显式运行时前提；本机 v26.7.0 过，换机 v20 即 `ERR_UNKNOWN_BUILTIN_MODULE`/SyntaxError——「本地能跑别人跑不通」模板
- 建议改法：package.json 顶层加 `"engines": { "node": ">=22.18" }`（下限按类型剥离转稳定通道日期的保守线，与注释 ≥23 一致亦可）；`webui/.nvmrc` 落一行 `26`；dev.ps1 frontcheck 里先 `node --version` 断言
- 验证命令：`node -p "process.version"`；`npm run check` 于目标 Node 复跑
- 回归锁：无

**F10-08｜P2｜前端唯一 env 键零登记 + 端口 8742 多点散布无互锁（「统一变量」正面缺口）**
- 坐标：`webui/vite.config.ts:20`、`webui/src/lib/api-client.ts:33`、`webui/src/vite-env.d.ts:4`、`webui/src/locales/{zh-CN,en}/common.json:29`；登记面 `webui/.env.example`（不存在）、根 `.env.example`、`docs/config-catalog-full.md`（grep VITE_ 零命中，实跑）
- 锚点：`BOT_CONTROL_PLANE_PORT=8742`（.env.example:24）无前端对位锁
- 根因：前端没有配置账本页，值靠抄；后端改端口→前端 5 处静默过期（validateBaseUrl 只校回环不校端口）
- 建议改法：①F10-05 的 `webui/.env.example` 落地；②pre_restart_check 第 9 项加一条对表：读 `.env` 的 BOT_CONTROL_PLANE_PORT（已有读取通道），若 ≠ vite.config.ts 内兜底常量则 FAIL「前端兜底端口与 .env 漂移」；③config-catalog-full 增「前端键」附表（VITE_API_BASE_URL + localStorage 三键 `webui:baseUrl/webui:bearer/webui:bearer:ro` 的语义登记——后三者非 env 但同属「前端配置账」，文档登记即可）
- 验证命令：venv python scripts/pre_restart_check.py --json 后 grep webui/control_plane 行
- 回归锁：无；pre_restart_check 第 9 项已有雏形可扩展

**F10-09｜P2→裁定制｜静态门「无 CI 常驻」的最小方案（现状=谁都能跳过）**
- 坐标：仓库级——`.github` 不存在（实跑 ls）；`../ChatBot_Runtime/git/hooks/` 实存 post-commit/post-checkout 两枚=**Qoder AI 用量遥测**（全文已读，非质量门）；dev.ps1 四门纯手动
- 锚点：hooks 内 `# BEGIN Qoder AI tracker`
- 根因：无 CI、无 pre-commit；多代理+多人环境下「跑没跑门」不可证；哈希册/文档同步门已把「忘同步」变红，但**门本身不跑就是没有**
- 建议改法（最小可行）：新增 `post-restart` 之外的一枚 **pre-commit hook**（本项目 gitdir 在 Runtime，钩子路径 `ChatBot_Runtime/git/hooks/pre-commit`——属工作区外文件，**须用户单独授权**）只挂快速子集：`ruff check`（秒级）+ `verify_hashes --check` + 若 staged 含 webui/** 则跑 `npm.cmd run check --prefix webui`；重量级（全量 pytest）不挂，留 dev.ps1 -Task test。若无 CI 授权，退阶方案=把「本波四门+前端三门」的**实跑输出归档进 .superpowers 席位台账**作人肉证据链（现行惯例即此，如实定性）
- 验证命令：`git config core.hooksPath`；`ls ../ChatBot_Runtime/git/hooks`
- 回归锁：N/A（改法本身即建锁）

**F10-10｜P3｜死 eslint-disable 注释 ×2（P3-20 属实仍在）**
- 坐标：`webui/src/pages/logs.tsx:121,144`
- 锚点：`// eslint-disable-next-line react-hooks/exhaustive-deps`
- 根因：全树无 eslint（package.json 无依赖、无配置文件、无 .eslintrc*/eslint.config.*——ls+grep 实跑零命中），注释是骨架移植（axonhub 上游有 eslint）残留物；它**掩盖了一个真问题**：两处 useEffect 依赖数组确实不全（`[]` 依赖 startStream、`[paused]` 依赖 appendRows），一旦未来接上 eslint 当场两红
- 建议改法（二选一，用户裁定）：A=删两行注释+各写一行「依赖有意收窄：<原因>」纯文本注释；B=正式引入 eslint react-hooks 并修依赖。最小取 A
- 验证命令：`grep -rn "eslint-disable" webui/src`（=0 或成对出现配置）
- 回归锁：无

**F10-11｜P3｜tsconfig 三处 alias 重复 + 根 tsconfig 死配置；空值安全双开关未开**
- 坐标：`webui/tsconfig.json:5-8`（死 paths）、`tsconfig.app.json:20-22`、`vite.config.ts:12-14`；`noUncheckedIndexedAccess`/`erasableSyntaxOnly`/`verbatimModuleSyntax` 全文无
- 锚点：`"files": [],`（根 tsconfig 第一行即证 compilerOptions 无消费方）
- 根因：脚手架惯性；`erasableSyntaxOnly` 不开=未来 enum/参数属性可静默废掉 node --test 门（与 F10-06/07 联动）；`noUncheckedIndexedAccess` 不开=前端空值安全靠自觉（recharts/stats 数组下标面大）
- 建议改法：①删根 tsconfig 的 compilerOptions 死块（留 files+references）；②app 开 `"erasableSyntaxOnly": true`（TS 5.8.3 支持，先开锁 runner 兼容）；③`noUncheckedIndexedAccess` 单开一票整改 PR（存量 will-red，**不可顺手开**），登记为裁定点
- 验证命令：`npm run typecheck`
- 回归锁：tsc 本身即锁

**F10-12｜P3｜`npm audit` 本机不可用（镜像端点未实现）——供应链门在 registry 层缺位**
- 坐标：用户级 `~/.npmrc`（registry=https://registry.npmmirror.com，`npm config get registry` 实跑）
- 锚点：`npm warn audit 404 ... /-/npm/v1/security/* not implemented yet`（本席实跑 npm audit --omit=dev 输出）
- 根因：国内镜像未代理官方审计端点；非项目缺陷，但「有没有洞」在本机不可证
- 建议改法：文档记一行替代路径：需审计时临时 `npm audit --omit=dev --registry=https://registry.npmjs.org`（纯网络查询不改树）；本次取证中该镜像拉包=既有事实，lock 内仅 esbuild/fsevents 带 install script（`grep '"hasInstallScript"'` 命中 2，均为官方二进制通道常规项）
- 验证命令：上句加 `--registry` 复跑
- 回归锁：无此门类

---

## 五、牵动标注（哈希册 / dist 重录 / 在飞冲突）

- **`tests/verify_hashes.py` 哈希册**：19 项全为渲染域交付物（7 Jinja+theme_tokens+rendering-contract+DESIGN-SPEC+3 规格+6 builder），**零 webui 条目**（grep webui 零命中，实跑）→ F10 全部改法**不牵动哈希册、无需 --write 重录**。
- **dist 重录**：F10-02 只改 pre_restart_check（py 侧）——**不触发 build**；F10-04/05 改 vite.config 仅影响 dev proxy 与 loadEnv 通道，**理论上不改产物字节**（singlefile 输出仍由 src 决定），但改完若任何人为跑 `npm run build`，当前本已 stale 的 dist 会**顺带变新鲜**（dist 不在哈希册、不在 git，无「重录义务」）。**本席零 build 零写**。
- **`.gitignore`/`pyproject.toml` 改动（F10-03）**会牵动既有门：dev.ps1 runtime-layout（scripts/runtime_layout_smoke.py grep webui/dist 零命中，不受影响）；doc_sync/config 系门不读 .gitignore——无连锁。
- **在飞冲突警示（重要）**：快照期间 `webui/src/pages/dashboard.tsx、components/patterns/patterns.tsx、ui/card.tsx、vite.config.ts` mtime=16:33/16:34，**并行席位此刻正在动 webui**（疑似 TTS/前端续批）。主会话落手 F10-04/05/06/10/11 前须重读目标文件最新态（AGENTS 规则 4），行号可能漂移；锚点字符串已给足重定位能力。
- 根目录散落的 `logs-page.png` 等 5 张验收截图与 `%TEMP%` 字面量目录：建议随 F10-03 一并入 ignore/归档纪律，不在本席改法强制项。

---

## 附：依赖审计明细（§任务 4 全项）

| 包 | 版本范围 | import 计数(webui/src) | 判定 |
|---|---|---|---|
| react / react-dom | ^19.2.0 / 19.3.0 实装 | 全树/1 | 必需 |
| @tanstack/react-router | ^1.121.34 | 4 | 手写 createRoute（无 codegen 步骤，plus）|
| @tanstack/react-query | ^5.81.2 | 2 | 数据面 |
| recharts | ^3.10.1 | 2 | 图表唯一 |
| d3-force | ^3.0.0 | 2 | 记忆图谱布局专用（与 recharts 不重叠；确定性测试锁其包装层 graph-layout）|
| lucide-react | ^0.523.0 | 10 | 图标唯一 |
| i18next + react-i18next + browser-languagedetector | 一家三件套 | 2/14/1 | 全在用 |
| clsx + tailwind-merge + class-variance-authority | cn 三件套 | 1/1/2 | shadcn 标准形态，非重复 |
| @radix-ui/react-slot | ^1.2.3 | 2 | Button asChild |
| （devDeps）tailwindcss + @tailwindcss/vite / vite / plugin-react / vite-plugin-singlefile / typescript ~5.8.3 / @types×4 | — | — | 无混入运行时；无 unused（@types/d3-force 对位 d3-force）|

- lock=lockfileVersion 3；`npm ls --depth=0` 实跑 24 顶层全配平、零 invalid；「请求库」=原生 fetch 单一（无 axios 双轨）；「日期库」=无（format.ts 手写，单轨）。
- package.json lifecycle：无 pre/post 钩子；仅 scripts 五条（见 1.3）。
