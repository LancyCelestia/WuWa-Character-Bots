# CAP2 实施台账 — usage 卡接入统一品牌胶囊（2026-09-20）

> 席别：CAP2 实施席（三面里主会话只裁给本席一面）。上游=CAP1-impl.md §六。
> 用户需求原话（2026-09-20，权威）：「**所有**图片都需要加上 bot头像、bot名字、
> bot英文名（可选：功能名）组起来的胶囊功能组件」。
> 本席可写面：`plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py`
> + 本台账。`mica_shell.py`/`bridge.py`/`theme_tokens.py`/`templates/*.html`/
> `tests/**` 一律只读；禁 `verify_hashes --write`、禁 `doc_sync`/`command_catalog --write`、
> 禁任何 git 写操作。

## 一、结论（三面做了几面）

| 面 | 真身路径 | 本席动作 |
|---|---|---|
| usage 卡 | `plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py` | **已接入**（本席唯一施工面） |
| debug 卡 | `plugins/bot_unified_runtime/domains/ops/admin/debug.py` | **未动**，待裁阻塞（§五.1） |
| help 卡 | `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py` | **未动**，待裁阻塞（§五.2） |

即：CAP1 §六 三面中本席落地 **1 面**，其余 2 面按主会话禁写表登记为等用户裁点，
未绕、未顺手改。

## 二、接入要点（file:line，全部在本席唯一可写文件内）

- `usage_cards.py:24-25` — 从 `mica_shell` 追加 import `BRAND_CAPSULE_CSS`（:374 缺省
  实例）与 `brand_capsule_html`（:334 生成器）；`:32` 追加 `BRAND_THEME`（中文名单一源）。
- `usage_cards.py:86` — 形参缺省 `bot_name: str = "守岸人"` → `bot_name: str = ""`
  （字面量废除，回落品牌名在 :226）。
- `usage_cards.py:210-229` — 自写页脚 DOM（旧 `avatar_html` + `bot_footer_html`
  两支 f-string，含 `.bf-avatar`/`.bf-dot`/`.bf-name` 与 `"守"`/`"守岸人"` 字面量）
  **整体删除**，改为：
  - `:220` 函数内局部 import `bot_avatar_uri`（与 `bridge.py:1986` mermaid 同一手法，
    不新建第二份头像路径逻辑）；
  - `:222` `avatar_url = (bot_avatar_url or "").strip() or str(bot_avatar_uri(config) or "")`
    —— 入参优先（payload 契约零变），空则走既有头像口径；
  - `:223-229` `bot_footer_html = '<footer class="bot-foot">' + brand_capsule_html(...)
    + '</footer>'`，`bot_name=(bot_name or BRAND_THEME.display_name)`、
    `feature_label` 沿用既有入参（缺省「模型用量」）、英文名**不传**（组件内部读
    `theme_tokens.BRAND_NAME_EN`，本模块零英文字面量）。
- `usage_cards.py:296-300` — `<style>` 内旧 `.bot-foot`（玻璃底 + 两枚 linear-gradient
  rgba 字面量 + padding/border-radius/box-shadow）与 `.bot-foot .bf-dot/.bf-avatar/.bf-name`
  四段手抄 CSS **全部删除**，只留 `.bot-foot {{ margin:0 14px 14px; }}` 一行摆位，
  随后拼入 `{BRAND_CAPSULE_CSS}`（单一来源）。
- `usage_cards.py:99-102` — 函数 docstring 补 CAP2 口径（三枚输入来源）。
- diffstat：`33 insertions / 26 deletions`，文件 362→369 行。

**零破坏面**：`render_usage_card_png`（`:332` 出图失败返回空串→纯文本兜底）零接触；
payload 三键（`bot_name`/`bot_avatar_url`/`feature_label`）语义与优先级不变；
生产调用方 `domains/ops/monitor/usage_monitor.py:673` 不传这三键，走缺省链，
**接入后自动获得英文名与本地头像**（该文件本席未动）。

## 三、与 CAP1 §六 方案的差异（两处，均为事实修正）

1. **§六 说「页脚（或头部替代位）插 `brand_capsule_html(...)`」——本席多保留一层
   `<footer class="bot-foot">` 宿主**。原因：`tests/test_mica_builders_contract.py:362-363`
   以字面量 `class="bot-foot"` 为取材锚点（`assert 'class="bot-foot"' in html_text`
   与 `html_text.split('class="bot-foot"', 1)[1]`），而 `tests/**` 是本席禁写面。
   这与 CAP1 自己在 universal 卡的处理同法（§5.1「保留 `footer-bot-pill` wrapper 类名、
   内容换成胶囊，锁不红」）。宿主类内**不含任何署名 DOM/文案**，只有一行 margin。
   若主会话愿意改 `tests/`，可去掉宿主、把摆位并进组件的 `extra_class`
   （`mica_shell.py:351` 已为此留参），届时 :362-363 两行需同步。
2. **§六 说「改后 `test_mica_builders_contract.py:357-364` 需同步」——本席实测无需同步**
   （三条断言在保留宿主后全部原样通过）。差异源于 §六 假定页脚被整体替换。

其余与 §六 一致：三枚输入零 token 桥接（本卡 `render_root_tokens` 公共段已含
`--r-pill/--mica-glass-*/--glow-accent/--text-*`），未新增 config 键，未新增 CSS 字面量。

## 四、样张（用户裁定素材，全部在 %TEMP%，源码树零产物）

根目录：`C:\Users\LancyCelestia\AppData\Local\Temp\cap2-shot\`
生成方式：`scripts/render_card_samples.py` 既有 `render_baseline`（同一后端、同一
WAAPI 钉帧、同 payload 双渲比字节），经 `%TEMP%\cap2-shot\cap2_samples.py` 驱动
（脚本只落 TEMP，不入树）；「改动前」集由 `git show HEAD:...usage_cards.py` 落到
`%TEMP%\cap2-shot\usage_cards_before.py` 后动态装载产出，payload 与改后完全同值。
四集 `deterministic=True`（PNG 字节等值），尺寸/字节/html_sha 见 `manifest.json`。

| 绝对路径 | 在验什么 |
|---|---|
| `...\cap2-shot\before\01_usage_report.png` | **改动前**基线：通宽页脚条、守点+守岸人+「· 模型用量」，**无英文名**、非统一组件 |
| `...\cap2-shot\after_noavatar\01_usage_report.png` | **改动后·无头像降级**：「守」字圆点 + 守岸人 + Shorekeeper + · 模型用量（透明底原图） |
| `...\cap2-shot\after_avatar\01_usage_report.png` | **改动后·有头像**：圆形头像 + 守岸人 + Shorekeeper + · 模型用量（头像以 data URI 注入） |
| `...\cap2-shot\after_avatar_fileuri\01_usage_report.png` | 取证集（非三态之一）：头像按生产 `bot_avatar_uri` 的 **file URI** 注入时的真实出图形态（见 §六 缺陷） |
| `...\cap2-shot\composited\before_light\01_usage_report.png` / `before_dark\...` | 改动前压浅底(#eef1f5)/深底(#171a21) 聊天背景 |
| `...\cap2-shot\composited\after_noavatar_light\...` / `after_noavatar_dark\...` | 改动后无头像态明暗可读性（圆点字与英文名次级灰在两种底上） |
| `...\cap2-shot\composited\after_avatar_light\...` / `after_avatar_dark\...` | 改动后有头像态明暗可读性 |
| `...\cap2-shot\composited\*_crop.png`（6 份） | 各态页脚带裁切（150px 高），逐张细看用 |
| `...\cap2-shot\composited\_contact_sheet.png` | **一张看全**：六条页脚带纵向堆叠 + 左侧标签（推荐主会话直接给用户看这张） |
| `...\cap2-shot\bot_avatar_sample.png` | 示意头像（96×96 淡蓝→深蓝渐变+白描边圆） |

三态 × 亮暗 = 6 张复合图（`composited\{before,after_noavatar,after_avatar}_{light,dark}\`），
另附 3 张透明原图 + 1 张 file URI 取证图 + 6 张裁切 + 1 张联系表。

## 五、禁写两面的待裁阻塞（按事实记录，本席未动）

### 5.1 `plugins/bot_unified_runtime/domains/ops/admin/debug.py`
- 实况（本席 02:39 取证）：`git status` = **M（工作树脏）**，mtime **2026-09-20 01:59:46**，
  文件内 `brand_capsule|mica-capsule` 命中 **0**。
- 为什么不能现在动：主会话按热写状态裁为禁碰——他席此刻正在这份文件上施工
  （工作树未合流），本席写入必与在飞改动撞车（同文件并发编辑竞态，本项目
  0913 批次已两次实锤）。它同时也在 `verify_hashes.py` 哈希册 19 件内（:54 登记）。
- 接入方案（CAP1 §六 原文照录，两行）：import `brand_capsule_html/BRAND_CAPSULE_CSS`；
  CSS 拼入 `<style>`；`feature_label="接入检查"`，注意该卡 `.setup-shell` 尾插。

### 5.2 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py`
- 实况（本席 02:39 取证）：`git status` = **干净（不在 M 清单）**，mtime
  **2026-09-19 20:01:58**，文件内 `brand_capsule|mica-capsule` 命中 **0**。
- 为什么不能现在动：**不是**因为工作树脏，而是①主会话裁为禁碰（今晨被其它波次
  连续提交，属热面）；②它在哈希册 19 件内（:56 登记）且**当前记录值与文件一致**
  （§七 实测），本席一改就立刻把常驻哈希门 `--check` 从 1 项漂移推到 2 项，
  而重录授权归「看图后主会话统一执行」，本席禁 `--write`。
- 接入方案（CAP1 §六 原文照录）：import 组件；CSS 拼入 `<style>`；页脚（或头部
  替代位）插 `brand_capsule_html(bot_name=bot_name, avatar_url=bot_avatar_url,
  feature_label="帮助手册" if ... else "")`——该卡头部现有「头像+bot_name+角色 chip」
  与胶囊语义重叠，**摆位需用户看图后裁**（本席倾向：头部保留、页脚加胶囊，
  与其余 10 面同构；但这是设计裁决不是本席权限）。

## 六、本席发现但**未动**的跨面存量缺陷（上报，不修）

**卡片里的 `file://` 头像在渲染后端下取不到图**——`file URI` 注入的头像集
（`after_avatar_fileuri`）页脚**没有头像也没有圆点**（`<img>` 在场但尺寸塌陷）。
取证脚本 `%TEMP%\cap2-shot\probe_file_uri.py`（同一 playwright/chromium 默认参数
+ 同一 `set_content` 路径）实跑输出：

```
img#f: bounding_box={'x':0,'y':0,'width':60,'height':60} naturalWidth=0 onerror='1'
img#d: bounding_box={'x':70,'y':0,'width':60,'height':60} naturalWidth=1 onerror=''
[error] Not allowed to load local resource: file:///C:/Users/.../bot_avatar_sample.png
[requestfailed] file:///C:/Users/.../bot_avatar_samp
```

- 根因链：`domains/render/render_backends.py:658` 用 `page.set_content(html)`（文档源
  = about:blank），`:496` `chromium.launch()` 未带 `--allow-file-access-from-files`；
  Chromium 禁止非 file 文档加载 `file://` 子资源。`_orb_route`（`:617-633`）只在
  HTML 含 http(s)  orb-prone 图时注册，且 `_HTML_URL_RE`（:56）只匹配 `https?://`，
  救不了 `file://`。
- 影响面：**全仓所有走 `bot_avatar_uri()` 的卡面**（台账 #29「11 处卡片头像来源统一
  bot_avatar_uri」），非 CAP2 引入、非胶囊独有；`onerror="this.style.display='none'"`
  使头像位静默塌陷而非回落圆点。
- 本席为何不修：`render_backends.py` 与 `mica_shell.py` 均在禁写清单，且修法
  （launch 加参数 / 路由拦截 file 子资源 / 头像转 data URI）是跨面视觉与性能决策。
- 建议主会话裁：①最小修=`render_backends` 注册 file 子资源路由 fulfill 本地字节
  （复用既有 `_fetch_image_bytes`），或 ②`bot_avatar_uri` 出口即转 data URI
  （96px 头像约 1.5KB，卡片 HTML 体积可接受）。**在此之前，用户看到的卡片
  头像位是空的**——这一点必须与「有头像」样张一并说明，故本席把 data URI 集
  与 file URI 集并列交付。

## 七、`verify_hashes.py --check`（只跑不改）自证

```
$ PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 \
    ../ChatBot_Runtime/venv/Scripts/python.exe tests/verify_hashes.py --check
DRIFT    DESIGN-SPEC.md（字节变更未记录——确认后 --write）
verify_hashes: 1 项漂移；确认属预期改动后执行 python tests/verify_hashes.py --write 重录。
EXIT=1
```

- 唯一漂移项 = `DESIGN-SPEC.md`（工作树 M，mtime **02:34:32**，DOC1/他席地盘，
  非本席），**CAP2 零贡献**。
- **对简报前提的一处事实订正**：简报称 usage_cards.py「不在哈希册 19 件内」——
  实为**在册**（`tests/verify_hashes.py:57` 登记，入册史见 commit `c9dc1d2`
  「哈希清单补 6 个 builder 源文件(K-06)…usage_cards 入 TRACKED_FILES」）。
- 那为何本席改动没被记成 DRIFT？取证：`tests/render_hashes.json` mtime
  **02:24:23**（本席 02:22:40 落笔之后），其记录值与本席改后文件哈希**逐位相同**
  （`5778827e…404d`）→ 说明**另有会话在 02:24:23 跑过一次 `--write`**
  （最可能是 `dev.ps1 -Task test` 的 `BOT_AUTOSYNC=1` 常驻钩子，
  `tests/conftest.py:46-50` 三步之一）把本席改动**吸收成了新基线**。
  本席自身全程 `BOT_AUTOSYNC=0`（钩子按 `is_autosync_enabled` 判定直接跳过），
  未执行过任何 `--write`。
- 治理含义（交主会话）：CAP1 §七.3 的裁定是「看图后由主会话统一重录」，
  但 usage 卡这一件已在用户看图**之前**被自动重录。若要求「用户裁图前基线不动」，
  需要把 usage_cards 一项回退到 HEAD 记录值（本席无权重录，仅如实报告）。
- 顺带：`tests/test_verify_hashes_coverage.py::test_builder_drift_gate_red_then_green`
  在全面跑测时**红**，根因即上述 DESIGN-SPEC.md 既存漂移导致演练收尾的
  「还原后应绿」断言失败（断言输出点名 `DRIFT DESIGN-SPEC.md`），**与本席改动无关**；
  演练自身「改红→还原」两段均正常。

## 八、完工判据实跑（本席全部动作的复跑证据）

```
$ ... python.exe -m pytest tests/test_mica_builders_contract.py tests/test_rendering_contract.py \
    -p no:cacheprovider --basetemp=../ChatBot_Runtime/cache/pytest_cap2/basetemp -q
190 passed in 3.40s                      # 与主会话基线 190 一致（改前改后各跑一次，均 190）

$ ... python.exe -m ruff check --cache-dir ../ChatBot_Runtime/cache/ruff_cap2 \
    plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py
All checks passed!                        RUFF_EXIT=0

$ ... python.exe -m mypy --cache-dir ../ChatBot_Runtime/cache/mypy_cap2 \
    --explicit-package-bases --ignore-missing-imports \
    plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py
Success: no issues found in 1 source file
  # 注：裸跑 `python -m mypy <file>`（不带 --explicit-package-bases）会因
  # domains/assistant/daily/store/ 缺 __init__.py 报「Source file found twice」，
  # 属项目 mypy 口径（dev.ps1:362-369 同两枚参数），非本席改动引入。

# 单源自证（脚本 %TEMP%\cap2-shot\cap2_selfcheck.py，RESULT: ALL PASS / EXIT=0）
PASS  usage 卡产物含恰好一处 class="mica-capsule"
PASS  胶囊 DOM 与 mica_shell.brand_capsule_html 逐字节等价（零手写）
PASS  降级形态=守字圆点 mc-dot（非整段消失）
PASS  英文名常驻且取自 BRAND_NAME_EN（本模块零英文字面量）=Shorekeeper
PASS  功能名沿用「模型用量」
PASS  CSS 单份且与 mica_shell.BRAND_CAPSULE_CSS 逐字节相同
PASS  有头像态=mc-avatar + src 直进（无第二份 img 手写）
PASS  显式 bot_name 优先（品牌名仅缺省回落）
PASS  产物不再含手抄残留 class="bf-avatar" / "bf-dot" / "bf-name" / 旧 rgba 渐变
PASS  源码（注释外）不再含字面量 class="bf- / bf-name { / "守岸人" / "Shorekeeper" / class="mc-
PASS  全仓 mica-capsule 生产语句仅 mica_shell.py 一处
      producers=['plugins\bot_unified_runtime\domains\render\card_render\mica_shell.py']
PASS  宿主 .bot-foot 仅摆位声明 'margin:0 14px 14px;'
```

扩面（usage 全族 + 交叉/确定性/样张/哈希覆盖门，共 12 个测试文件）：
`475 passed / 1 failed`，唯一失败=§七 末所述 `test_verify_hashes_coverage` 既存漂移项，
非本席。usage 六族单独跑：`203 passed`。

树卫生：`data/` 不存在、无 `__pycache__`/`.pytest_cache`；本席两次裸跑 ruff/mypy
曾在既存 gitignored `.ruff_cache/0.16.4/`、`.mypy_cache/3.12/` 落下 3 条目，
已删除本席所造 2 个 ruff 条目（余 3 个属他席早于本席），此后统一带
`--cache-dir` 出树。工作树本席仅 `usage_cards.py`（M）+ 本台账（新建）。

## 九、未做事项与原因

1. `debug.py` / `echo.py` 两面无接入（§五，禁写面 + 哈希册授权）。
2. `tests/test_mica_builders_contract.py:362-363` 的 `bot-foot` 锚点未改（禁写面），
   以「保留摆位宿主」绕开而非改锁——**没有放水，也没有动锁**。
3. `file://` 头像塌陷缺陷未修（§六，禁写面 + 跨面决策），只交付取证。
4. 哈希册重录/回退未做（§七，禁 `--write`；且吸收本席改动的重录非本席所为）。
5. `docs/rendering-contract.md`/`DESIGN-SPEC.md` 契约条文（DOC1 席地盘）。
6. 真机验收：本席纯离线；生产生效仍需提权重启 bot（台账 #10/#31 旧例）。
