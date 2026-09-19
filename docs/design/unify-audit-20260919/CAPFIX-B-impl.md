# CAPFIX-B — 品牌胶囊四条单一来源缺陷修复席（实现）

- 日期：2026-09-21
- 被修对象：`0765292`（品牌胶囊）之上的评审 `.superpowers/sdd/FRONTEND-AUDIT/review-CAP1-report.md` I-1 / I-3 / I-4 / I-7；I-2 只登记不施工
- Status: STARTED

## 任务拆解
1. I-1 media 卡双重转义（templates.py × mica_shell.brand_capsule_html）— 复核转义层数后修
2. I-3 中文名第二处源（models.py:150 bot_name 默认值）— 收敛到 BRAND_THEME.display_name
3. I-4 功能名 6 处硬编码 + 「诊断」新增卡面文案 — 改调用方传入、缺省省略
4. I-7 mermaid 卡裸调 bot_avatar_uri() 不传 config — 传 config 跟齐
5. I-2 echo/debug 两面 — 只登记坐标与三步接入方案

## 进度台账（每条完成即 append）

### I-1 media 卡双重转义 — **成立，已修**（2026-09-21）
- **评审说的对不对**：对。本席实跑复核（`/tmp/capfixb/probe_i1.py`，同输入喂两路）：
  改前 `media(f-string) double-amp count: 3`、
  `src="https://cdn.example.com/a.png?t=1&amp;amp;v=2"`；
  market（bridge 路）count 0、`&amp;` 一层——与报告 I-1 逐字一致。
- **两条路各自转义层数（取证）**：
  - bridge/Jinja 路：能力层 payload **原值** → `bridge._capsule_context` 原值 →
    `mica_shell.brand_capsule_html` 内 `_html.escape` **一次** → 模板
    `{{ capsule_html | safe }}` 直插不重转义 ⇒ 共 1 层。正确。
  - f-string 直拼路（`domains/render/templates.py::render_media_card_html`）：
    旧代码 `bot_name/bot_avatar/feature_label` 先 `_esc`（第 1 层，f-string 卡
    对其它字段这是**必需**层，因无 autoescape）→ 再喂组件又 escape（第 2 层）
    ⇒ 胶囊三输入共 2 层。其余字段（title/cover/badge 等）仍 1 层、不受影响。
- **修法（落在同一层）**：组件内那一层是唯一转义层——media 卡胶囊三输入改传
  原值（`str(payload.get(...) or "")`，去掉 `_esc` 预转义与多余的
  `or BRAND_THEME.display_name` 兜底，中文名回落由组件内部单点完成）；
  `badge_text` 走手写 HTML，改为**用处**转义 `_esc(feature_label) if
  feature_label else platform`（platform 仍沿用原一处 `_esc`，层数不变）。
  文件：`plugins/bot_unified_runtime/domains/render/templates.py`
  （三输入 :129-137、badge :163-167；BRAND_THEME 导入随兜底 removal 摘除）。
- **怎么证明改对了**：探针复跑 media count 0，胶囊逐字节：
  `src="...?t=1&amp;v=2"`、`<span class="mc-name">O&#x27;Neil &amp; Co</span>`、
  `<span class="mc-feature">· 天气&amp;预警</span>`；并新增回归锁 2 条
  （`tests/test_mica_builders_contract.py` §11）：
  `test_media_capsule_escapes_exactly_once` +
  `test_capsule_dom_identical_across_two_render_routes`（同输入下直拼卡与
  bridge 卡胶囊 DOM 逐字节相等）。契约面实跑 **199 passed**（基线 197+2）。
- **反向**：任何人把 `_esc`/`html.escape` 重新预转义喂进胶囊 →
  `test_media_capsule_escapes_exactly_once` 红（`&amp;amp;` 检出）；
  两路层数再分叉 → `test_capsule_dom_identical_across_two_render_routes` 红。

### I-3 中文名第二处源（models.py:150）— **成立，已修**（2026-09-21）
- **评审说的对不对**：对。本席同法复跑（进程内 `object.__setattr__` 把
  `bridge.BRAND_THEME.display_name` 改 `ZZTEST`，渲染三面对照 `mc-name`）：
  改前 `render_universal_card_html -> 守岸人`（不跟随）、
  market/error `-> ZZTEST`（跟随）——与报告 I-3 实证逐字一致。
  根因坐实：`models.py:150 bot_name: str = "守岸人"` →
  `bridge.py:125 _DEFAULT_CONTEXT = RenderPayload().to_dict()` →
  universal 路径 `bridge.py:1440 _as_str(context.get("bot_name"))` 恒非空 →
  `_capsule_context` 的 `bot_name or BRAND_THEME.display_name` 回落分支恒不生效。
- **改在哪**：`card_render/models.py:150` 默认值 `"守岸人"` → `""`（评审两案
  取「置空让回落链生效」——`BRAND_THEME.display_name` 直填默认值会在 import
  期固化，monkeypatch/运行期改值 universal 仍不跟随，达不到「单一来源」的
  动态语义）。回落发生在渲染期 `bridge._capsule_context`（bridge.py:214）与
  组件内（mica_shell.py:365），全卡同一点。仅改 `bot_name` 一行+注记，
  该文件别的字段零触碰。
- **影响面复核**：`universal_card.html` 模板本体不引用 `{{ bot_name }}`
  （`git grep bot_name templates/` 仅 affinity_card.html 两处 `dlabel`，且
  bridge 传值恒非空、`| default('守岸人')` 为死分支——该模板字面量本席不动，
  登记见「残余」）；生产 universal 路径由 content_parser 显式传
  payload["bot_name"]（实例名或能力侧回落），本改动只影响「调用方没传」的
  缺省形态，值仍=「守岸人」逐字节不变（探针 `restored -> 守岸人`）。
- **怎么证明改对了**：复跑同一探针 → universal/market/error 三面全出
  `ZZTEST`；恢复后出「守岸人」；`RenderPayload().bot_name == ''`。
  新增回归锁 `tests/test_rendering_contract.py` §10a
  `test_brand_display_name_single_source_across_faces`（四面含 mermaid，双断言
  + finally 还原）。契约面实跑 **200 passed**（199+1）。
- **反向**：把字面量写回 `models.py` 默认值 → 锁内
  `RenderPayload().bot_name == ""` 断言红；任何一面新增第二处硬编码缺省 →
  该面 `mc-name` 不跟随 ZZTEST，断言红。

### I-4 功能名 6 处硬编码 +「诊断」无出处 — **成立，已修**（2026-09-21）
- **评审说的对不对**：对。改前探针（空 payload 逐面抓 `mc-feature`）实锤六处
  桥内回落全部上卡面：market `· 全球股指`、finance `· 金融`、song `· 点歌`、
  affinity `· 好感度`、error `· 诊断`、mermaid `· 流程图`（universal=OMITTED
  合规，证明「调用方传入、缺省省略」通道本来就是承诺形态）。
- **调用方真相复核（决定能不能删回落）**：生产调用方**全部已显式传**——
  market.py:738「全球股指」+ `_card_common_payload` 三面「商品行情/国债收益率/
  北向资金」；stocks.py:406/616「个股行情/股价」；fx.py:132「汇率」；
  music.py:645「点歌」；affinity.py:176/221「好感度」；error_report.py 载荷
  **无 feature_label 键**（:714 只有 card_title「运行异常」）⇒「诊断」确为
  CAP1 新增无出处卡面文案，删除回落后错误卡功能名段整体省略（既有 card_title
  承载语义，信息零丢失）。mermaid 无 payload 通道 ⇒ 改参数化。
- **改在哪**：`bridge.py` 六处——market :1540/finance :1623/song :1683/
  affinity :1779 `_as_str(data.get("feature_label")) or "…"` → 去回落；
  error :1861 `or "诊断"` → 去回落（注释同步改口）；mermaid 旧
  `feature_label = "流程图"` 硬编码 → 改**关键字参数**
  `render_mermaid_html(code, *, config=None, feature_label="")`，缺省省略、
  调用方可传（`render_mermaid_png` 同签名透传）。桥内不再存功能名字面量。
- **怎么证明改对了**：改后探针=六面+mermaid 全 OMITTED；
  `render_market_card_html({"feature_label":"测试功能"})` 与
  `render_mermaid_html(code, feature_label="流程图")` 正常显 `· 值`（通道
  未死）。回归锁两条入 `tests/test_rendering_contract.py` §10c
  （`test_feature_label_omitted_without_caller_source` 七面断言无
  `mc-feature` + 传入即显）。契约面 **200 passed** 不变（无既有断言依赖
  这六枚回落——`git grep '全球股指\|"金融"\|点歌\|好感度\|诊断\|流程图' tests/` 于
  三份授权测试文件零命中，复核过）。
- **反向**：任何人恢复 `or "全球股指"` 等任一回落或给错误卡加回「诊断」→
  空 payload 面冒出 `mc-feature`，§10c 红。

### I-7 mermaid 裸调 `bot_avatar_uri()` 丢显式配置级 — **成立，已修（桥内侧）**（2026-09-21）
- **评审说的对不对**：对。`bot_avatar.py:176-183` 优先级=显式配置>进程内>
  磁盘发现；裸调 `bot_avatar_uri()` → `getattr(None,...)=""` 跳过第一级，
  且 `_discover_local_uri(None)` 因 `bot_runtime_data_dir=""` 立即回空
  （:143-145）丢第三级——CAP1 注释只辩解了磁盘级，未覆盖显式配置级。
- **改在哪**：`render_mermaid_html(code, *, config=None, …)` →
  `bot_avatar_uri(config)`（与同模块 usage_cards.py:222 及能力侧五处
  `bot_avatar_uri(config)` 同口径，优先级逻辑零复制）；`render_mermaid_png`
  加同名参数原样透传。缺省 `config=None` 行为与改前逐字节一致（既有调用方
  renderer.py/样张脚本零改动零漂移）。
- **残余（如实登记）**：生产唯一调用方 `renderer.py::_render_mermaid_png`
  （`future.submit(render_mermaid_png, code)`）**拿不到 config**——renderer
  全文件无 config 引用，且不在本席可写面 ⇒ 桥面已把通道打开，**接线待合流
  波**（步骤见 §待接入登记 ②）。评审 I-7「破坏它需要什么」的实弹形态
  （BOT_PERSONA_AVATAR_URL 配置后 mermaid 不跟随）在接线前仍成立，本席只
  闭环桥侧，不越权改 renderer.py。
- **怎么证明改对了**：探针 stub config（`bot_persona_avatar_url=
  "https://explicit.invalid/av.png"`）→ `render_mermaid_html(code,
  config=Cfg())` 产物含 `src="https://explicit.invalid/av.png"`（改前该形态
  必须裸调不可能达成）；回归锁两条入 `tests/test_rendering_contract.py`
  §10d（html 级+png 透传级，后者 monkeypatch `_get_mermaid_backend` 捕获
  payload）。
- **反向**：把参数改回裸调/丢掉透传 → 显式级断言红（`src=` 匹配不到）。

### I-2 help/debug 两面零胶囊 — **成立，本席不施工，登记待接入**（按简报纪律）
- **复核**：对。`git grep -c 'mica-capsule|brand_capsule|capsule'` →
  echo.py=0、debug.py=0（工作树 exit=1 零命中），与评审实测一致；usage 面已由
  `6551c93` 接入（三面中只剩这两面）。两文件均为他席在飞脏文件（echo.py 正
  在 COPY-V2/在飞；debug.py verify_hashes 显示其工作树内容与他波改动相关），
  本席禁写，只交坐标+方案。
- **echo 面施工坐标**（`domains/chat_reply/capabilities/echo.py`，行号以合流时
  最新态复核为准——该文件脏）：`_help_mica_html` 定义 :3086；旧署名 DOM=
  页脚 `<div class="help-bot-pill">{avatar}<span>{_esc(bot_name)} · 命令手册
  </span></div>`（:3250 一行内）；CSS 段 `.help-bot-pill` 于 :3242。
  **三步接入**：① `from ...card_render.mica_shell import BRAND_CAPSULE_CSS,
  brand_capsule_html`；② `BRAND_CAPSULE_CSS` 拼进卡 `<style>`（若迁
  `render_shell` 装配则走 `capsule_html=` 自动附带）；③ 页脚 DOM 换
  `brand_capsule_html(bot_name=bot_name, avatar_url=bot_avatar_uri(config),
  feature_label="命令手册")`——「命令手册」出处=同卡既有可见串（header_title
  :3135 / 旧 pill :3250），不新增文案；`.help-bot-pill` 的 CSS 与 DOM 同批
  退役。接入后该卡自动落进 `test_mica_builders_contract.py` 既有统一门。
- **debug 面施工坐标**（`domains/ops/admin/debug.py`，脏文件行号合流复核）：
  `_llm_setup_mica_html` :717；外壳 `<section class="setup-shell">` 尾插点
  :813。三步同构（import/CSS 入 style/尾插胶囊）。feature_label：本席未读通
  该在飞脏文件，若「接入检查」在其既有标题串中有出处则传入，**无出处则留空
  =整段省略**（I-4 纪律：没有来源的串不上卡面）。
- 两面接入完成后，用户裁定「所有 html 模板都要有胶囊」方成立；提交信息/台账
  的「全站接入」口径届时才名副其实（评审 I-2 建议动作同步闭环）。

## 契约文档随实相更新（逐条）
- `DESIGN-SPEC.md` §8 胶囊页脚，**改一句**：旧「页脚第二槽位口径=功能名优先
  （feature_label），无功能名回英文品牌词 Shorekeeper（universal/旧媒体卡既有
  行为）」→ 新「功能名只认调用方传入、缺省整段省略（六枚桥内回落字面量退役）
  + 三输入传原值/转义层收敛组件内一处 + 中文名缺省回落 BRAND_THEME.display_name
  + 头像 bot_avatar_uri(config)」。理由：该句被 CAP1 作废后又经本席 I-1/I-3/
  I-4/I-7 四修，旧文已成**失实**承诺；四句新文各对应一条已入库行为与回归锁。
- `docs/rendering-contract.md`：**零改动**（grep 复核其中无胶囊文案/转义层
  口径条款，仅玻璃档表提「页脚胶囊」为 GLASS_FOOT 消费位——语义未变）。

## 门禁与卫生自证（本席离场核对）
- 授权契约面终态：**204 passed**（基线 197+新增锁 7：I-1×2/I-3×1/I-4×2/
  I-7×2），每改一条即跑一次，命令逐次实跑（`BOT_AUTOSYNC=0` 全程）。
- 定向邻面回归：render 族 9+9 文件（universal/phase/mermaid/icon/mica_shell/
  market/fx/feature_cards/error_async 等）实跑 **181 passed+1 skipped+…见下
  两条例外**；首轮批量 4 collection errors 复跑全绿=瞬态（本机内存压力先例，
  非代码）。
- **存量红一枚（非本席造成，本席不可写该文件）**：
  `tests/test_mermaid_reply_render.py::test_render_mermaid_html_mica_and_escapes`
  `assert count("box-shadow") == 2` 于 **HEAD 即红**——CAP1 给 mermaid 模板换
  胶囊 CSS 后实测恒 3（对照实验：feature_label/config 各 DOM 变体下 count 不
  变，CSS 源文件 mica_shell.py+templates/ 对本席 git status 全干净），且 CAP1
  未同步该测试（其 200-passed 三件套不含此文件，即评审 C-1「零契约覆盖」的
  又一实锤侧面）。该文件工作树为他席 import 修复在飞脏 → **待合流波按现势
  口径修正**（合理改法：`== 3` 或改锚 `--mica-shadow-panel` 在壳层的断言族，
  归属合流席裁）。
- 静态门：ruff 改动 5 文件 All checks passed；mypy（dev.ps1 同旗标、cache 置
  TEMP 外）改动 3 源文件 Success。
- 哈希册（只读 `--check`）：4 项 DRIFT=本席三件（`bridge.py`/
  `domains/render/templates.py`/`DESIGN-SPEC.md`，预期内）+`echo.py` 一件
  （他席在飞）。本席禁 `--write`，交合流波统一重录；19 张 PNG 样张同理未动
  （全站像素自 CAP1 起已变，属既登记 M-6 债）。
- 源码树卫生：无 `__pycache__`/`*.pyc`/`.pytest_cache`/`data/`/样张新增；
  本席新增文件仅本日志；qx.json 完好（未触碰）。
- git：**零写操作**（全程 status/diff/show/grep/rev-parse 只读）。

## 待裁/待接清单（移交）
1. **renderer.py mermaid config 接线**（I-7 桥侧已闭环，生产级差最后一公里）：
   `apply_mermaid_blocks/_render_mermaid_png` 全链无 config 引用 → 需装配层把
   config 递到 `render_mermaid_png(code, config=cfg)`；届时
   `BOT_PERSONA_AVATAR_URL` 显式级与磁盘发现级对 mermaid 生效。
   renderer.py 非本席可写面。
2. `affinity_card.html:264/271` `{{ bot_name | default('守岸人') }}`：死分支
   （bridge 传值恒非空）+第二处字面量，建议合流波删 `| default(...)`（行为
   零变化）——超本席 I-3 单行授权，未动。
3. `models.py:152` `feature_label` 行注释「空回退通用文案」与 I-4 实况矛盾
   （本席被令只许动 bot_name 一行），合流随手改。
4. `DESIGN-SPEC.md` §8 「Bot 头像白边 2px」vs 胶囊 mc-avatar 现势
   `border:1px solid #fff`（CAP1 落地值，数值面归 VIS 席）→ 登记待裁。
5. echo/debug 两面胶囊接入（§I-2 三步方案）——待两面在飞席收口后派工。

## Status: DONE（I-1/I-3/I-4/I-7 成立并修毕+锁，I-2 登记毕；四修全为离线证据，
重启后才生效；未 commit——共享工作树，提交裁决权在用户）




