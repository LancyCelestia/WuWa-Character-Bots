# COOKIE-KEYMAP · 平台凭据四处缺口（🔴 2026-10-06 用户批准全修，已实施并加锁＝见 §7）

落笔＝2026-10-06（主代理本窗；起因＝凭据合并波取证，见 `角色文档/_平台凭据导入与缺口说明.md` §六/§七）。
§1-§6 是**取证与方案原文**（一字未改，含 §3 里我后来推翻的一条自述，改正在 §7.3）；实施结果、四把锁与读数在 §7。

**授权面与禁面（先读这两句）**：本件只**列**缺口与一行改法，未改任何 `.py`、未动 `.env`、未建 cookies 文件以外的任何东西。
🔴 改代码必须重启 bot 才生效（AGENTS 铁律 #10；生产进程以管理员权限常驻，杀它需提权）——**重启、`git add`、commit、push 一律归用户或需用户明示**。
本件按用户裁定 B 落在此处待审；未经批准不得当"已修"记账（AGENTS 规则 5）。

---

## §0 取证底（全部本窗实跑，非转抄）

| 读数 | 值 | 出处 |
|---|---|---|
| 凭据件真身 | `ChatBot_Runtime/data/platform_cookies.txt`（本波前 890 行／98,691 B／sha `228b98761b7fc5cb`→现 921 行／103,631 B／sha `06189fbaf8720055`） | `角色文档/_规划/尺存/_主代理/cookie_before_after_20261006T110125Z.jsonl` |
| 注册表 | 20 平台；每项＝`(域集, 必需键名集)` 二元组 | `domains/link_parse/parsers/cookies.py:41` |
| 读侧解析＝写侧路径 | True | `cookie_provider_verify_20261006T110002Z.jsonl` |
| 门 | `test_cookie_file_loader_end_to_end.py` 19 passed；`test_cookie_import_hot_reload.py`+`test_platform_credentials.py` 7 passed | venv python 3.12.10，带 `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider --basetemp=<仓库外>` |

---

## §1 缺口① `zhihu` 有注册位、有解析器形参、**无绑定**＝导了也不生效（功能面）

- 现象：`PLATFORM_COOKIE_DOMAINS` 在册（`cookies.py:62`，键集 `d_c0/_zap/__snaker__id`）；`parse_zhihu` 也收 `cookie_header` 形参（`platforms_zhihu.py:149`，经 `:31 _headers()` 真放进 `headers["cookie"]`）；解析器名册也有 `zhihu`（`parsers/__init__.py:246`）。
- 根因：绑定表 `_PARSER_COOKIE_PLATFORM`（`parsers/__init__.py:671-690`）**没有 `"zhihu"` 这一项**，于是取头处拿到空串即原样返回函数——
  `parsers/__init__.py:780` `cookie_platform = _PARSER_COOKIE_PLATFORM.get(parser_id, "")` → `if cookie_platform:` 不进。
- 一行改法：在该表内补 `"zhihu": "zhihu",`（表内现有 18 项，全部是 `parser_id → 平台键` 的同名或改名映射）。
- 影响面：知乎问题/专栏解析（`zhihu.com/question/<id>/answer/<id>`、`zhuanlan.zhihu.com/p/<id>`）从不带登录态。补后＝现役件里那 4 个键第一次真被送出。
- 配锁：见 §5 锁 L1（覆盖差集为空）。

## §2 缺口② 网易云**下载腿**传错实参＝恒空串（功能面）

- 现象：`domains/music/capabilities/music.py:448`
  `cookie_header = build_cookie_provider(config).cookie_header("netease_music")`
- 根因：`cookie_header()` 的入参是**平台键**（`cookies.py:166` `return self.headers.get(platform, "")`），而 `netease_music` 是 **parser_id**；平台键叫 `netease`（`cookies.py:48`）。`"netease_music"` 永远不在 `headers` 里 ⇒ 恒 `""`，且被外层 `except Exception` 包着，静默。
- 一行改法：把实参换成 `"netease"`（`parsers/__init__.py:819` 那一处用的就是对的映射，可对照）。
- 影响面：网易云试听直链下载不带登录票（解析腿经 `_PARSER_COOKIE_PLATFORM` 是正常的，所以症状只在下载失败/清晰度降级上）。
- 配锁：§5 锁 L2（AST 扫全仓 `cookie_header("<字面量>")`，断言每个字面量 ∈ 注册表平台键）。

## §3 缺口③④ 注册表第二元素**无任何消费者**＝"必需键齐不齐"是纸面判据（文档面，非功能）

- 实尺：全仓 8 处用到 `PLATFORM_COOKIE_DOMAINS` 的地方，第二元素一律被丢弃——
  `cookies.py:76 / :98 / :458` 写作 `_key_names`，`http_util.py:66`、`tests/test_credential_domain_binding.py:147` 写作 `_keys`，
  `platform_credentials.py:144-148` 只取 `platform_entry[0]`。**没有任何一处按必需键名筛过 cookie、也没有任何一处因缺键拒绝发头**。
  ⇒ 结论：发不发 cookie 只由"域在册＋未过期＋名非空"决定；键名集纯注释。
- 于是这三处名漂移**不会**咬功能，但会**骗读代码的人**（本窗我自己就被骗过一次，把它当白名单用）：
  - `kugou`（`cookies.py:50`）要 `userid/token/dfid`，浏览器实存 `kg_h_uid`/`kg_dfid`/`kg_mid`；
  - `epic`（`:68`）要 `EPIC_SESSID`，实存是 `EPIC_SESSION_AP`/`EPIC_LOGIN_ID`/`EPIC_SSO_RM`；
  - `steam`（`:64-67`）必需名里写着 `'steam Machineid'`——**中间一个空格**，任何真实 cookie 名都不含空格，此判据恒不成立。
- 两个走法（**要用户裁定，本件不代裁**）：
  - 甲＝**给它接上消费者**：`/bot cookie status`（`platform_credentials.py:111`）按平台报"缺哪个登录主键"，让注释变成能力（缺键面今天只能靠人读源码）；同时订正上面三名。
  - 乙＝**删掉死半元**：注册表收成 `平台→域集`，把"主键清单"移进注释或文档。少一份没人执行的判据。
  - 推荐＝甲。理由：登录态失效目前完全静默（`expired_dropped` 只进日志、`has_cookie` 不区分缺键），而 `docs/acceptance-manual.md:174` 已经写明"失效用 `/bot cookie import` 重灌"——接上消费者才谈得上"知道该重灌"。

## §4 附带第五处（卫生面，非本补丁必要项）

现役件 921 行里**同键 `(HttpOnly, domain, path, name)` 重复 526 行**（一个键最多 90 行同键不同值）。
成因＝两条写入口都只 append：`/bot cookie import` 同名不覆盖（`platform_credentials.py:166-171`），
`/bot cookie login`/`check` 一律 append（`:423-424`、`:539-540`），读侧靠"同名取更长 path、再取更晚到期"（`cookies.py:469-473`）挑一条。
⇒ 危险不在体积而在**旧值可能凭更晚到期压掉新值**（重登后旧票还没到期时，bot 会继续带旧票）。本窗合并已把重复行的值对齐（`cookie_merge3_readout_20261006T105830Z.jsonl`），但**写入口本身没有修**。
可选补丁＝写前按平台折叠同键行（一处改法：在 append 前先删除同键旧行），配锁＝`apply(apply(x))` 留痕幂等。是否做，等用户裁。

## §5 改动面与回归门（批准后才动）

| 缺口 | 文件 | 锁 |
|---|---|---|
| ① | `plugins/bot_unified_runtime/domains/link_parse/parsers/__init__.py`（`_PARSER_COOKIE_PLATFORM` 加 1 行） | **L1** 覆盖锁：`set(解析器名册里带 cookie_header 形参的 parser_id) − set(_PARSER_COOKIE_PLATFORM) ⊆ {steam, epic}`（这两家自读兜底，`platforms_steam.py:75-104`/`platforms_epic.py:64-90`，白名单要写死并注明理由） |
| ② | `plugins/bot_unified_runtime/domains/music/capabilities/music.py:448` | **L2** AST 锁：全仓 `cookie_header("字面量")` 的字面量必须 ∈ `PLATFORM_COOKIE_DOMAINS`；本窗先跑一次应**只有 music.py:448 一处红**（RED），换实参后转绿 |
| ③④ | `.../parsers/cookies.py:41-69`（＋`platform_credentials.py:111` 若走甲案） | **L3** 名集对齐锁：每平台必需名须"在该平台域下至少出现过一次"（拿现役件当样本），否则红——防 `'steam Machineid'` 这类不可能判据再生 |
| ⑤（若做） | `platform_credentials.py` 两条写入口 | **L4** 幂等锁：同一 Cookie 头连灌两次 ⇒ 文件行数不增 |
| 文档 | `docs/acceptance-manual.md:174`（"已灌 18 平台"→ 以 `cookie_status`/机器册为准，AGENTS 规则 10）、`_平台凭据导入与缺口说明.md` §二 表标"当时值" | — |

跑门（一律带规则 6 卫生前缀，或走 `scripts/dev.ps1 -Task test`）：
`tests/test_cookie_file_loader_end_to_end.py`、`tests/test_cookie_import_hot_reload.py`、`tests/test_platform_credentials.py`、`tests/test_credential_domain_binding.py` ＋ 新建的 L1–L4。

## §6 本窗已确认为"不是缺口"的两条（免得再审一遍）

- `steam`/`epic` 不在绑定表＝**有意**，它们自读同一文件；`http_util.py:66` 用注册表域集做附凭证前的归属判定，二者互补。
- `skland`/`miyoushe` 必需键集为空＝**有意**（只认域不挑键），现役件在发的键数＝`miyoushe` 12、`skland` 1（`cookie_provider_verify_20261006T110002Z.jsonl`）。

---

## §7 实施记录（2026-10-06 用户批准「四个完整全部去修复」后落地）

### 7.1 改了哪四处（🔴 真身代码已动，共 4 文件 +35/−4 行；提交与重启仍归用户）

| 缺口 | 文件 | 改动 |
|---|---|---|
| ① 绑定漏 | `domains/link_parse/parsers/__init__.py`（`_PARSER_COOKIE_PLATFORM`） | 补 3 条：`zhihu→zhihu`、`bilibili_show→bilibili`、`kugou_mixsong→kugou`；表头注释写死两族豁免与理由 |
| ② 实参错 | `domains/music/capabilities/music.py:448` | `cookie_header("netease_music")` → `cookie_header("netease")` |
| ③ 死数据 | `domains/link_parse/parsers/cookies.py` | `PlatformCookieProvider` 新增 `missing_required`；构建腿把 `_key_names` 改成 `required` 并真按它算缺哪些主证键 |
| ③ 消费者 | `domains/core/credentials/platform_credentials.py`（`cookie_status_text`） | 有凭据但缺主证 → 状态页追加 `；缺主证键 X、Y（可能未登录）` |
| ④ 不可寻址名 | `cookies.py:64-67`（steam 必需键） | 删 `'steam Machineid'`（真实 cookie 名不含空格，判据永不成立；机器票名形如 `steamMachineAuth<steamid>` 带号、静态名单表达不了，留着＝永久误报） |

### 7.2 四把锁＝`tests/test_cookie_key_contract_locks.py`（173 行，9 例）

**先看它红**（改动前实跑）：`9 failed`，红因逐条＝`Extra items in the left set: 'bilibili_show' 'zhihu' 'kugou_mixsong'`／`Left contains one more item: "music.py:448 'netease_music'"`／`assert ["steam: 'steam Machineid'"] == []`／`AttributeError: 'PlatformCookieProvider' object has no attribute 'missing_required'`／状态页断言里那行文本压根没有 `缺主证键`。中途还修过一次**测试自己的错**（`Path / "…%s.py" % name` 缺括号＝TypeError，不是有效红）。

**再看它绿**：`9 passed`。族测（凡引用 cookie 的 20 本）＝`462 passed, 2 skipped`；`ruff check .`＝`All checks passed!`（我这文件初版吃了 8 条 UP031/RUF019，已改 f-string/`.get`）；`dev.ps1 -Task typecheck`＝`Success: no issues found in 606 source files`。

**绿了还要验尺不是空的**（区分度）：① 探测器仍见 6 个未绑定且域已注册的 parser_id（全落在豁免表内）＝覆盖腿有牙；② AST 面现扫到 2 个字面量调用点（`netease`/`twitter`）＝有判据可判，但🔴 只拦**写死字面量**的调用点，变量传入的走①那条腿管；③ 注册表必需键共 57 个＝③④两腿有实际对象。

### 7.3 🔴 推翻我 §3 里的一条自述（kugou 不是"名漂移"）

§3 说 kugou 注册表要的 `userid/token/dfid` 与盘上 `kg_h_uid/kg_dfid` "名不符"。查了自家解析器才看清：`platforms_music.py:640-704` 的酷狗腿走 `hash=` 的 `getSongInfo`，**匿名也能出链**、根本不按 cookie 名筛；而浏览器里那三枚 `kg_*` 是**设备/匿名**票，`userid/token/dfid` 才是登录票。⇒ 实情＝**这台浏览器没登酷狗**，不是名单写错。照 §3 去"订正名"会把判据改成"永远齐"，反而废掉这条报告。
同理 `epic` 的 `EPIC_SESSID` 从未在任何盘上件里出现过（实存 `EPIC_SESSION_AP/EPIC_LOGIN_ID/EPIC_SSO_RM`）＝待核，**没把握就不改名**：新增的消费者会如实报"缺 EPIC_SESSID"，比静默强，也逼着下一次核。

### 7.4 修的时候挖到的更大一面（只报不擅动）

`_PLATFORM_RULES` 52 条里**32 条**解析器签名收 `cookie_header`，绑定表原本只有 18 条。其中宿主域已在注册表的＝9 条：已绑 3（真同站）＋自读豁免 2（steam/epic）＋🔴 **故意不绑 4**＝`ds163`/`buff`/`huajia`（域借在 `.163.com`＝网易云音乐键下）、`qsmusic`（借 `.douyin.com`）。把这四家绑进别家的票＝将网易云/B站/抖音的登录态发给游戏与饰品站，属新增外泄面，不是修复；要真用得先给它们注册自己的平台键（另案）。其余 23 家（pixiv/lofter/spotify/facebook/douban…）连注册域都没有＝仍是"无代码"族，见 `角色文档/_平台凭据导入与缺口说明.md` §四。

### 7.5 生效、回滚、未做

- 生效＝**重启 bot**（绑定表与 provider 字段都是进程内代码；铁律 #10，重启归你）。重启后 `/bot cookie status` 会开始报「缺主证键」，`知乎/会员购/酷狗 mixsong` 才真带票。
- 回滚＝撤销上表 4 个文件的改动（＋删 `tests/test_cookie_key_contract_locks.py`）；凭据件本身**没再动过**，`platform_cookies.txt` 仍是本窗合并后的 `921 行／sha 06189fbaf8720055`，回滚点 `.bak-20261006T105639Z` 未变。
- 未做＝`.env` 没动；git 只有新增两个未跟踪件（本件＋锁），🔴 未 `add`、未 commit、未 push。
