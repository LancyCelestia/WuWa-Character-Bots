# AVT1 — bot 身份可参数化（bot_avatar.py 多 bot 自动取）实现文档

Status: DONE

> 席位：AVT1-c（续跑阵亡者半成品）。范围严格限定 `domains/render/bot_avatar.py` + `tests/test_bot_avatar.py` + 本文档。
> 禁碰面：card_render/**（VIS1-b 独占）、personas/**、config.py（本波纪律：零新增 config 键）。

## 一、现状（AVT1-c 接手时点，全部实跑核实）

**阵亡席留下的"半成品"实况，比简报更糟一档：只有承诺、没有实现。**

1. `git diff -- plugins/.../domains/render/bot_avatar.py` = **仅 docstring 重写 + 三行新 import**
   （`Callable` / `dataclass` / `Any`）。docstring 承诺的
   `bot_identity(bot_id, config)` / `register_identity` / `set_identity_resolver`
   **函数体全树不存在**——全树 grep `bot_identity|register_identity|set_identity_resolver|BotIdentity`
   仅命中该 docstring 自身两行。即：不是"死代码"，是"零代码"。
2. 直接后果：`ruff check` 该文件 **3 个 F401**（三个 import 全部未使用，
   `[*] 3 fixable`）——工作树此刻是静态门红档，本席顺手收口（属唯一可写面）。
3. 测试侧 diff 仅一行：import 路径 `output.bot_avatar` → `domains.render.bot_avatar`
   （v21r2 域重组正当工作；`output/bot_avatar.py` 是 `import *` 垫片仍存活，
   两条路径同物）。存量 10 例锁的是三个进程级全局
   （`_LOCAL_AVATAR_URI` / 远端 URL 缓存 / `_DISCOVER_MISS_TS` 负结果 TTL）
   与 `_resolve_bot_avatar_url` 远端链语义，无一触新面。
4. docstring 两处失实/失配：① 承诺的实现文档不存在（本件即补）；
   ② 文内引用「待裁点见 §五」与本文档节号不符（§五=接入计划、§七=待裁），
   本席实现波内改正（该文件=本席可写面）。
5. 消费面（只读勘察）：`bot_avatar_uri()` 真实消费点 =
   根 `__init__.py:2187/2208-2210`（`_refresh_local_bot_avatar` +
   `_resolve_bot_avatar_url`）、能力侧经 output 垫片六处
   （affinity.py:29,339,391 / stocks.py:51,446,488 / market.py:33,226,736 /
   fx.py:32,157 / music.py:33,643 / content_parser.py:47,412）、
   `card_render/bridge.py:1986-1989`（mermaid 卡，够不到 config）、
   `card_render/usage_cards.py:220-222`。全部为单实例口径。
6. "写死"真身定位：`mica_shell.brand_capsule_html()` **本身已参数化**
   （`bot_name`/`bot_name_en`/`avatar_url` 皆入参，空值才回落
   `BRAND_THEME.display_name`/`BRAND_NAME_EN`）；写死发生在**调用侧**——
   bridge 各 render 函数 `bot_name = _as_str(data.get("bot_name")) or
   BRAND_THEME.display_name`（:1536/:1617/:1677/:1771）与 mermaid 直调
   `bot_avatar_uri()`（:1989，连 config 都不传）。名字/头像随发送方变化的
   缺口在"值从哪来"，不在胶囊组件。
7. 既有 config 字段可承载面（零新键纪律下）：`bot_persona_display_name`
   （config.py:150，缺省 `"报存"`；theme_tokens.py:37-38 注释明言其语义=
   "实例可配的面貌字段（中文名）"——名字第三级取它，口径同源）、
   `bot_persona_avatar_url`、`bot_runtime_data_dir`。第二/三实例的名字与
   头像**没有任何既有键可承载**（`bot_campus_self_ids`/`bot_campus_push_bot_id`
   是路由/白名单语义，挪用=语义污染，本席不动），故名字面只开
   登记入口 + 装配层钩子，配置化进 §七 待裁。
8. 运行头像目录实况（只读 `ls ../ChatBot_Runtime/data/avatar/`）：仅一枚
   `bot_8887340775.png`（971 B，主号 2026-09-19 23:38 落盘）。校园号
   2300230562 / 推送号 3958874605 **无头像文件**——接入后它们暂走全局回落链
   （=今天所有卡的观感，零退化），主号逐实例直命中。`refresh_from_qq`
   落盘命名 `bot_<qq>.png` 天然逐实例隔离，这是"头像自动取"无需新机制的
   事实基础。

## 二、改了什么（全部在本席可写三件内）

### 2.1 `plugins/bot_unified_runtime/domains/render/bot_avatar.py`

把阵亡席 docstring 的承诺**兑现成实现**（文件内坐标为终态行号）：

| 构件 | 坐标 | 内容 |
|---|---|---|
| `BotIdentity` | :56-66 | `@dataclass(frozen=True)`，字段仅 `name` / `avatar_uri`（空串=本级不表态、交给回落）|
| 新槽位 | :68-69 | `_IDENTITY_REGISTRY: dict[str, BotIdentity]` + `_IDENTITY_RESOLVER: Callable[[str, object], str \| None] \| None`，均挂既有 `_LOCK` 下存取 |
| `_data_root(config)` | :115-128 | 自 `_discover_local_uri` **原样提级**的目录解析（绝对直用/相对挂 `parents[4]`/缺字段=None），发现逻辑与逐实例查盘共用一把口径 |
| `register_identity` | :189-203 | 空白 bot_id 拒绝入库；**整条替换**语义（再登记未带字段=清旧值，不隐式继承）|
| `set_identity_resolver` | :206-217 | 单槽装配钩子，传 None 摘除 |
| `_persona_display_name` | :220-222 | 名字第三级：`getattr(config, "bot_persona_display_name")`（config.py:150 既有字段，theme_tokens:37-38 注释背书其"实例面貌中文名"语义）|
| `_per_instance_avatar_uri` | :225-245 | 头像第二级：`avatar/bot_<qq>.png` 纯数字号+存在+非空才 file URI；非数字形态跳过 |
| `bot_identity` | :248-287 | 统一入口。空/纯空白 bot_id：头像**字面上调用** `bot_avatar_uri(config)`（同函数、零新路径），名字=人格配置名，注册表/解析器/逐实例磁盘**一律不经过**；非空：名字「登记→解析器→人格名→空」四级、头像「登记→逐实例盘→旧全局链」三级；解析器**不持锁调用**、异常 catch 后顺延（fail-safe）；本函数任何输入不抛 |

顺手收口（同文件内）：
- 未使用的 `from typing import Any` 删除（阵亡席 import 三件套中 `Callable`/`dataclass` 现已被真用，ruff F401 3→0）；
- docstring 引用「待裁点见 §五」改为「§七」（与本文档节号对齐）。

**逐字节不动面**：`refresh_from_qq` / `set_local_path` / `bot_avatar_uri` 函数体一字未改；
`_discover_local_uri` 仅目录解析三行提级为 `_data_root` 调用，TTL 键、探测序、副作用
（正结果登记内存+清负缓存）逐行等价——旧 10 例锁原样全绿背书。
零新增 config 键（只 getattr 既有三字段）。`output/bot_avatar.py` 垫片为
`import *` 且无 `__all__`，新 API 自动从旧路径可达，垫片零改动。

### 2.2 `tests/test_bot_avatar.py`

- 旧 10 例（含三个进程级全局锁、L-14 TTL 三例、`_resolve_bot_avatar_url` 远端链两例）
  **一行未改**；新增面不触碰旧语义，故无需动旧锁的说明=「没有需要动的东西」。
- 新增 19 例（AVT1 节，`_avt1` 夹具=在 `_isolated` 三全局之外再隔离两新槽位；
  刻意**不**把新全局塞进 `_isolated`——旧用例不消费新槽位，塞入会让 RED 阶段
  无差别炸旧锁、污染"是否削弱旧语义"的判读）。
- 顶部 `import dataclasses`（frozen 值对象锁用）。

### 2.3 本文档

新建并逐节落盘（本文即交付物之一；阵亡席缺的就是这份）。

## 三、为什么这样落点

1. **空 bot_id=旧版**不靠"测出来像"，靠"代码上就是同一条路"：空键分支直接
   `return BotIdentity(name=_persona_display_name(config), avatar_uri=bot_avatar_uri(config))`，
   新槽位物理不经过，回归锁因此是构造级成立、测试只是钉住它。
2. **头像末级回落旧全局链**（登记→逐实例盘→`bot_avatar_uri`）＝「不比今天差」原则：
   接入前所有卡本就共用同一枚全局头像；逐实例信息缺失（如校园号还没连过、
   盘上没文件）时维持该观感，绝不因接入把卡面打空。代价（次级实例可能短暂
   显主号脸）与今天完全同形，登记为 §六-① 而非本席私改。
3. **解析器不持锁调用**：`threading.Lock` 非重入，装配层解析器反读
   `bot_avatar_uri`（要拿同一把锁）是合理用法，持锁回调=自杀式死锁；
   快照式取用（锁内读引用、锁外执行）。死锁用例用 daemon 线程+5s join
   超时判定，挂死也不会拖垮套件。
4. **整条替换而非字段合并**：登记面状态单调用可推，避免"第二次登记忘了头像
   字段却隐式继承旧头像"的远距离耦合；测试 ⑤ 族已锁。
5. **逐实例盘命中不加负 TTL**：单次 `is_file+stat` 与 L-14 要治的
   "整目录 glob+stat"差一个量级，TTL 缓存是净增复杂度，不做。
6. **不做 `name_en`**：`BRAND_NAME_EN`（theme_tokens:42）是品牌固定身份 token，
   注释明言不进 config；逐实例英文名的需求未经用户裁定，先开槽=过度设计。
   进 §七-③。
7. **名字第三级用人格配置名而非品牌名**：品牌回落住在胶囊侧
   （mica_shell:365-366）已是单一来源事实；本模块若再兜一层品牌名，就是把
   card_render 的语义抄进值提供层。返回空串让胶囊按既有优先级走。
8. **修 `refresh_from_qq` 全局槽位不属本席**：那是三个旧锁之一（last-connect-
   wins 是现行锁定语义），动它=动旧锁语义，违反任务约束；已按"登记不修"处理
   （§六-①），并给出接入面的缓解事实（逐实例盘优先）。

## 四、测试与实跑输出（全离线，零缓存三件套 + BOT_AUTOSYNC=0）

统一命令（basetemp 落仓库外）：

```bash
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_bot_avatar.py \
  -p no:cacheprovider --basetemp="$TEMP/avt1c" -q
```

| 阶段 | 实跑输出 | 判读 |
|---|---|---|
| RED（实现前，只追加测试） | `10 passed, 19 errors`，报错=`AttributeError: module ... has no attribute '_IDENTITY_REGISTRY'`（夹具）/ 缺 `bot_identity` 等 | 旧 10 锁原样绿=未削弱；新 19 例精确钉住"API 零存在"这一现状事实 |
| GREEN（实现后） | `29 passed in 2.38s` | ①-⑤ 全覆盖 + 死锁/极端入参附加锁 |
| 变异抽检 M1（删掉逐实例盘一级） | `-k "per_instance or registry_and_single"` → `1 failed`（`test_per_instance_avatar_isolated_by_filename` :319）| ②的命名隔离锁有牙齿（"最新 mtime 全局口径"顶不掉逐实例命中）|
| 变异抽检 M2（持锁回调解析器） | `-k "deadlock or empty_bot_id"` → `1 failed`（`test_resolver_may_read_module_state_without_deadlock` :473，join 超时判定）| 锁纪律锁有牙齿；两处变异当即回滚，回滚后全量复跑 `29 passed in 2.60s`（最终态三度复跑 `29 passed in 3.14s`）|
| 邻面消费方 | `tests/test_error_card_contract.py` → `7 passed`（bot_avatar 全树唯一另一测试消费点）| `_data_root` 提级零破坏 |
| 静态门 | `ruff check --no-cache` 两文件 `All checks passed!`；`mypy --cache-dir ../ChatBot_Runtime/cache/mypy --explicit-package-bases --ignore-missing-imports`（dev.ps1 同旗标）`Success: no issues found in 1 source file` | 阵亡席留下的 F401×3 一并清零 |
| 树卫生 | `find plugins tests` 无 `__pycache__`/`*.pyc`；`git status` 足迹=可写三件 | 见 §六-⑤（树根缓存两度起落，如实登记）|

覆盖清单对照任务要求：①回归锁 2 例（含"新槽位零经过"反证）②逐实例隔离 2 例+0 字节/回落/非数字 3 例 ③四级链 5 例（登记>解析器>人格>空+摘除解析器）④异常 fail-safe 2 例（含"登记名不被解析器失败遮蔽"）⑤互不污染 3 例（含空白键 no-op、整条替换）附加：死锁 1 例、None-config 1 例、frozen 1 例。

## 五、接入计划（三步；本席零执行——bridge.py/mica_shell.py 归 VIS1-b 独占）

> ⚠️ 施工窗口：以下 `card_render/**` 行号为 2026-09-20 只读勘察值，VIS1-b 在飞编辑中，
> **动工当日必须以当时文本重锚**（按函数名/语句文本检索，勿按行号盲改）。

### 步骤一：能力侧 payload 构造点换身份源（config 与 bot_id 都够得着的地方）

现状 7 处写死单实例口径 `bot_avatar_url=bot_avatar_uri(config)`：

- `domains/chat_reply/capabilities/affinity.py:339,391`
- `domains/finance/capabilities/stocks.py:446,488`
- `domains/finance/capabilities/market.py:226,736`
- `domains/finance/capabilities/fx.py:157`
- `domains/music/capabilities/music.py:643`
- `domains/link_parse/capabilities/content_parser.py:412`

每处形如替换：

```python
from plugins.bot_unified_runtime.output.bot_avatar import bot_identity  # 垫片自动再导出

identity = bot_identity(message.bot_id, config)   # IncomingMessage.bot_id 已存在：
                                                 # domains/core/contracts/runtime.py:125，零契约改动
payload["bot_avatar_url"] = identity.avatar_uri
if identity.name:
    payload["bot_name"] = identity.name  # 不传=桥侧照旧回落品牌名，逐能力可分批上车
```

`bot_name`/`bot_avatar_url` 均是 payload 既有键（各 `render_*_card_html` docstring 字段表
已列，如 bridge.py:1494-1497），**无需动模板**。若某 handler 作用域够不到 message，
把 `bot_id` 作显式形参上溯到调用点传，禁止在能力侧从 config 猜收信账号。

### 步骤二：card_render 面（VIS1-b 让位后执行）

a) `bridge.py:195-220 _capsule_context(bot_name: str, bot_avatar_url: str,
feature_label: str) -> dict[str, str]`：**签名不动**（身份已在能力侧解析完，
桥保持纯展示面）；四处 `bot_name = _as_str(data.get("bot_name")) or
BRAND_THEME.display_name`（:1536/:1617/:1677/:1771）回落原样保留——接入后触发
条件从"恒触发"收窄为"能力侧未传名才触发"，零 DOM 改动。
b) `bridge.py:1975 def render_mermaid_html(code: str) -> str` →
`def render_mermaid_html(code: str, *, bot_id: str = "", config: object | None = None) -> str`；
体内 :1986-1989 改：

```python
identity = bot_identity(bot_id, config)
bot_name = identity.name or BRAND_THEME.display_name
bot_avatar_url = identity.avatar_uri
```

调用点 :2031 `render_mermaid_html(code)` 补传 `bot_id=`（config 够不到可不传：
注册表名/内存槽位照常工作，磁盘级恒空与今日注释同形）。此路是 §六-② 缺陷面，
接入时一并消化。
c) `mica_shell.py:345 brand_capsule_html(*, bot_name, bot_name_en, avatar_url,
feature_label, extra_class)` 及回落 :365-366、圆点 :373 `name[:1] or name_en[:1]`：
在建议裁定（§七-②：圆点=实例名首字、无名回落品牌「守」）下**零改动**——接入后
校园卡自然显「校」字点。仅当用户裁"固定守字/逐实例专字"才动 :373 加
`dot_char: str = ""` 形参（mica_shell+bridge 各一行透传）。
d) 步骤二落账后必跑：`tests/test_rendering_contract.py`、
`test_mica_builders_contract.py`、样张基线、`verify_hashes` 手动 `--write`
重录（BOT_AUTOSYNC=0，禁自动重录）。

### 步骤三：装配层名字供给（根 `__init__.py` 装配面）

- **形态 B（推荐）**：插件装配期挂解析器（装饰器区 `:4019 @driver.on_bot_connect`
  之前的装配函数内）：

```python
from .domains.render.bot_avatar import set_identity_resolver
set_identity_resolver(_resolve_bot_display_name)  # (bot_id, config)->str：查平台登记/
                                                  # 档案表，不识别的 id 返回 ""放行
```

  id→名字的**数据源**当前无既有 config 键可承载（`bot_campus_self_ids`
  config.py:472 / `bot_campus_push_bot_id` :475 只有号没有名）——配置化进
  §七-① 待裁，裁定前解析器可先返回 ""（=行为与今天一致，接入不死等）。
- **形态 A（即时轻方案）**：对确定实例直接 `register_identity("2300230562",
  name="<裁定名>")`；A/B 可并存（登记>解析器天然有序）。
- **头像侧零工作**：`_refresh_local_bot_avatar`（`__init__.py:2185-2193`）本就随
  每实例连接按 `bot_<qq>.png` 落盘，逐实例命中天然成立（目录实况只读核验：
  主号 `bot_8887340775.png` 已在，校园/推送号待其 WS 实际接入——§七-⑤）。

**回滚面**：三步各自独立可回退；步骤一每能力一行替换、git diff 即清单；
未接入前 `bot_identity` 全树零消费，对生产零影响（本席终态即此）。

## 六、存量缺陷登记（台账外发现，只登记不修）

| # | 缺陷 | 位置 | 定性与处置 |
|---|---|---|---|
| ① | **全局头像槽位 last-connect-wins**：`_LOCAL_AVATAR_URI` 是进程级单槽，任何实例 `refresh_from_qq` 成功即覆写；多实例并存时后连接者（校园/推送号）会顶掉主号脸——所有仍走旧口径的卡受影响 | `bot_avatar.py:76-103`（`refresh_from_qq` :98-101 写槽）＋根 `__init__.py:2185-2193` 每实例连接都调它 | 属三个旧锁之一锁定的**现行语义**，本席不动；接入后逐实例盘优先天然缓解大半（主号卡不再经全局槽取图）；彻底修法=连接钩子按 self_id 写登记表头像，归接入席/裁定后施工 |
| ② | mermaid 路径 `bot_avatar_uri()` **裸调用不传 config**（磁盘兜底级恒空，只吃显式配置+内存槽）| `card_render/bridge.py:1989`（注释 :1986-1988 自知"够不到 config"）| 多实例下该面是 ① 的最直接暴露点（内存槽=最后连接号）；接入计划步骤二 b 一并消化 |
| ③ | `bot_persona_display_name` 缺省值 **"报存"** 与品牌"守岸人"不一致；若 `.env` 未显式设 `BOT_PERSONA_DISPLAY_NAME`，接入方按"identity.name 直填 bot_name"写会把卡面中文名从品牌名改成"报存" | `config.py:150` | 生产 .env 实况禁读本席不可证；接入步骤一按"`if identity.name` 才覆盖"渐进式写法规避断链风险，但**名字口径本身**进 §七-① 一并裁 |
| ④ | `_discover_local_uri`"取最新 mtime"多实例语义=**最近连接号的头像冒充全局** | `bot_avatar.py:131-173` | 旧语义旧锁（`test_discover_picks_newest_avatar_file` 钉死），本席保留；逐实例路径不依赖它，仅回落级兜底时与 ① 同根 |
| ⑤ | **树根缓存反复再现，多席并行下不可根除**：本席前两轮裸跑 ruff/mypy 在树根生成 `.ruff_cache/`/`.mypy_cache/`，发现即删并改 `--no-cache`/外置 `--cache-dir` 复跑取证；终扫时两目录**再度出现且 mtime 落在本席末轮命令（仅含 ruff --no-cache/外置缓存 mypy/pytest 三件套）执行窗内**——无法归因本席，判定为并行席位裸跑产物 | 树根 | 本席足迹部分已清；树根缓存属可再生目录（非运行数据，不涉 %TEMP% 备份规程）。卫生提醒后续席位与收尾波：ruff 一律 `--no-cache`、mypy 一律 `--cache-dir` 指 Runtime；收尾合流时按 git check-ignore 复核再清一波 |
| ⑥ | 工作树海量在飞（`M output/bot_avatar.py`、`D sources/data/qx.json`、树根 `logs-page-live.png` 等 373 条 untracked）| 全树 | **均非本席足迹**（本席 `git status` 足迹=可写三件，已定向 grep 核对），只如实记录 |

## 七、待用户裁定点

1. **实例名字的数据源要不要配置化**（新增映射键如 `BOT_BOT_NAMES={"2300230562": "…",
   "3958874605": "…"} dict[str,str]）？本席守"零新键"纪律，只开了
   `register_identity`/`set_identity_resolver` 两入口；裁定前卡面名字走
   "登记→人格名→品牌"回落链，次级实例显示人格名是可接受的中间态还是
   必须逐实例专名，请裁。③的"报存"口径问题一并裁。
2. **降级圆点首字取谁**（无头像时 `mc-dot` 里的字）：本席建议=**实例名首字、
   名字也缺时回落品牌「守」**——这是 `mica_shell:373` 现成语义，接入零改动，
   校园卡自动显「校」点；备选=全局钉死「守」/逐实例专设 dot 字（要加参数）。请裁。
3. **逐实例英文名**：`BRAND_NAME_EN="Shorekeeper"` 是品牌固定 token
   （theme_tokens:42，注释明言不进 config）；接入后非主号卡英文名仍=品牌英文名。
   是否需要逐实例英文名（如校园号 "CampusKeeper"），请裁；现 API 无此字段，裁"要"
   再扩，不预防性加宽。
4. **系统视角面**（`/bot help`、错误卡、`usage_cards` 等无具体收信消息的卡）：
   身份跟主号走还是保持品牌通用（不传 bot_id 走空路径）？接入计划步骤一批量替换
   时把选择权留在 payload 构造点，请裁。
5. **次级实例头像自动取的前提**：校园号/推送号需其 WS 实际接入触发
   `on_bot_connect→refresh_from_qq` 才有 `bot_<qq>.png`（现目录实况：仅主号一枚）。
   启用与否属 campus 波既有开关链（`.env.prod` 3002 解注释等），本席不催、只登记
   依赖关系。

---

### 交接账（铁律 5 口径）

- 状态：**DONE**。可写三件全部交付：实现（`bot_avatar.py` 新 API 全部兑现 docstring
  承诺）、测试（`tests/test_bot_avatar.py` 10→29 例，RED→GREEN→变异抽检→回滚复跑）、
  本文档（逐节落盘）。
- 证据：§四 表格全部为实跑输出（可复跑命令在 §四 首段）；未 commit（共享
  工作树，提交裁决权在用户；本席禁 git 写）。
- 本席之后：`bot_identity` 具备生产可用条件，但**全树仍零消费**（按任务要求只出
  接入计划）；下一步=§五 步骤一（可分批）→步骤二（等 VIS1-b）→步骤三（等 §七-① 裁定）。
