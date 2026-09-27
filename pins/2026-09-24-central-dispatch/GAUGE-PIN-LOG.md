# 量具钉册重录日志

- 2026-09-26 08:16:08Z 重录 14 枚（与旧册不符＝s0-main-lib-api-surface.py、s0-main-lib-drift-checker.py、s0-main-lib-factory.py）｜理由：S792 盘位守卫根修落码：工厂 --out 判定改「两侧 resolve＋成员判定」并把 mkdir 移到两道守卫之后（旧码用未解析字符串前缀比，本机 temp 为 8.3 短名 ⇒ 仓内路径可绕守卫且先落空壳目录）。实测：短名仓内 out 被拒 rc=2 且仓内零目录；%TEMP% 合法 out 放行（正对照）。余 13 枚未动。
- 2026-09-26 08:16:40Z ⚠ 局部撤销上一条：只保留 s0-main-lib-factory.py 的重录（本席自落码＋双向实测）；api-surface／drift-checker 两枚**回退到旧册值**——那是他席（S785）未经我复核的改动，上一条 --repin 把它们一并洗白是本席违规（自己定的「不 repin 掩盖」），现按原判继续标不符、该格继续 NO。
- 2026-09-26 08:30:45Z 逐枚重录 1 枚（在册共 14）
  - s759-decl-sources.py：4bbf38de99b39921 → be8637db4f6badf6
｜理由：主代理自落码（S802 §六.1 补腿）：缺口尺接库轴名册腿（ReleaseLibNode.members）＋新增 SEEDED 第三态。实测：真树 gap=5 seeded=0（行为中性）；补丁态 gap=0 seeded=3（contracts 12 枚／adapter-mail 2 枚点亮，三空座单列不算达标）。板侧取保守侧＝seeded>0 仍判 NO。
- 2026-09-26 08:30:45Z 逐枚重录 1 枚（在册共 14）
  - s0-main-lib-drift-checker.py：09f4f237437b31b5 → a544fad7460d4a0e
｜理由：S785 落码但我复验通过的半边：直跑不崩（ast OK＋rc=1 STALE）且真实十库读数与 S777 基线逐值相同（SAME=439 DRIFT=26 CONCURRENT=2 MISSING=32 ONLY=5）。🔴 未验部分照实挂账：该席 15 座消盲的注毒两发（§三）从未提交、且它在 150 轮上限处阵亡，正文称在改 ONLY 归属判据——消盲这条**无证据**，由新席续做。
- 2026-09-26 08:42:37Z 逐枚重录 1 枚（在册共 14）
  - s0-main-lib-behind-commits.py：d69e58272eb82780 → 2e81d469463455c7
｜理由：落 S799 §3.1 零测自锁（S777 F5 尺侧半边、S777 #6 回归洞的追缴）：库根下扫不到 git 库即 die() FATAL rc=2，旧形态空根会 rc=0 印 UP-TO-DATE。
｜证据署名：直跑不崩：ast.parse 过，真实十库单跑 rc=1 正常出行；读数不变：BEHIND total=5 libs_stale=3 libs_measured=10、VERDICT BEHIND 与 08:01Z 板记录逐值同；另加一发 T1 空根实跑＝FATAL rc=2 点名
- 2026-09-26 08:59:43Z 逐枚重录 1 枚（在册共 18）
  - s0-main-lib-api-surface.py：d7ef7694a394ada1 → 2ad887c56b3f1cda
｜理由：S785 消盲改版、由 S810 独立复验后逐枚重录（非本席自证）：盘上 2ad887c5 与钉册旧值 d7ef7694 版在真仓真库上背靠背各跑一次 --check，22 行读数逐字节等值、两侧 rc=0；且 08:01Z 板记录（跨库 261／提供方 298／总目标边 1344／盘面 10-0-0／十库逐座行）原样命中。
｜证据署名：直跑不崩：两版均 rc=0、无 traceback；读数不变：22 行读数逐字节等值（S810 台架 5/5 CAUGHT＋本席复核其主件 §肆 命令簿），15 座新盘走全量、名册幽灵与缺目录两发注毒各 rc=2 点名
- 2026-09-26 09:08:49Z 逐枚重录 1 枚（在册共 18）
  - s759-severance.py：845373dcaf1438fd → 5a0b78d822eee830
｜理由：落 S821 #121 名册 pin 腿：实扫座数≠两轴名册座数即 FATAL rc=2 且裁决词前置禁用；今日真跑 10/15 ⇒ 断开度分母改判为不可判（旧形态会拿 10 座的 52 当全舰队的分母，S808 实证扩册会静默 52→59 非单调）
｜证据署名：直跑不崩：真库单跑 rc=2 正常出行、无 traceback；读数不变：放行路径 stdout 去掉 fp 行后与改前真尺逐字节相等（S821 台架 7 案 ALL-PASS，本席复跑同值 52/261/399/0 于宇宙齐时）
- 2026-09-26 09:08:50Z 逐枚重录 1 枚（在册共 18）
  - s759-decl-sources.py：be8637db4f6badf6 → f0bbeb9d7aa58662
｜理由：同批第二枚：decl-sources 加同名 roster_fp 输出，与 severance 构成互锁（fp 同形⇒改名册任一轴两尺同报错或同改读数，solo 静默不存在）
｜证据署名：直跑不崩：--libs 真库单跑 rc 正常、15 行逐座点名加机读行齐；读数不变：gap=5 seeded=0 与 08:2xZ 登记逐值同，仅新增 roster_fp=1cbc02d334a6 roster_n=15 两行
- 2026-09-26 09:39:48Z 逐枚重录 1 枚（在册共 19）
  - s0-main-lib-readiness.py：b31f053161e31a8f → a6f0ee797da33abb
｜理由：落 S823 就绪度补牙包：C5/C8/C9/C10 四格从无牙改成真比对，三色语义与零比对 FATAL 齐
｜证据署名：直跑：新尺在真库根 -B 跑通不崩（rc=1，VERDICT: NOT-READY（16 格））；读数：旧尺 10 红→新尺 16 红，新增 6 枚全属 C5=surface-name（S823 逐枚归因＝5 枚面表假账行＋3 枚库快照滞后），C7 十枚存量与旧尺逐枚同格、红未搬家；板侧 ready 格仍 NO，判定不因换尺翻绿
- 2026-09-26 10:27:20Z 逐枚重录 2 枚（在册共 21）
  - s0-main-lib-factory.py：e952b0914000ae0b → 5fb3fc95ec7b5885
  - s0-main-lib-version-check.py：1d7a4b6562243a6b → 9198443f311e4fbf
｜理由：落 S846 B-2/B-3 两枚版本轴根修：version-check 改取最高 semver tag（旧形 tags[0]=refname 字典序，正确 bump 反判 DIVERGE，与 readiness 互相打脸）并加 MONO 回退腿；工厂 VERSION 改保留现值不覆写（旧形每次生成写回常量 0.0.1，发过一次版就会被下一次同步静默抹回且当时两把尺都绿）
｜证据署名：直跑：version-check 在真十库跑通 rc=0 且 VERDICT 读数不变（CONSISTENT、不一致 0 处、新行 MONO regressed=0 libs=10）；两发合成树实弹＝当前 0.0.2/tags{0.0.1,0.0.2}→SAME3（旧形此处假 DIVERGE）、被抹回 0.0.1→DIVERGES＋REGRESSED＋regressed=1。工厂直跑 rc=2 停在 L2 双认领输入闸（D-5 未落，与改动前同点同读数），链级到 VERSION 分支的实跑验证等 D-5 由 S843/S851 方法补，本席如实写为不适用而非未验
- 2026-09-26 10:55:32Z 逐枚重录 3 枚（在册共 21）
  - s0-main-lib-behind-commits.py：2e81d469463455c7 → 0e1facdea9a766f2
  - s0-main-lib-readiness.py：a6f0ee797da33abb → a40d661f95d49f21
  - s0-main-lib-version-check.py：9198443f311e4fbf → 6a6a4fb856a66274
｜理由：落 S847 §5 F1/F3/F5a/F5b/F6/F7/F8 七段加 F4 死腿改形；发现谓词同族扩到版本轴与统筹尺（只修一把尺＝把尺间读数拉开）
｜证据署名：四枚直跑不崩：readiness rc=1 出十列 16 格、version rc=0 CONSISTENT、behind rc=1 BEHIND、gitinit 不在册未动写路径；真实十库读数对账＝版本轴 CONSISTENT 库 10 座不一致 0 处、统筹 total=14 libs_stale=9 两行逐字与改前等值，readiness 仅 C5 三格计数 2→4/1→3/1→2 上升（加牙后的真实增量：已 grep 主仓 plain_text.py 与 timesync/__init__.py 证实 _fn/_timesync 两侧都不存在⇒红真，非尺造）
- 2026-09-26 11:27:35Z 逐枚重录 1 枚（在册共 23）
  - s0-main-lib-readiness.py：a40d661f95d49f21 → 9d3804ef176dae2d
｜理由：落 F2 三色语义两段（STATE_NA→显式谓词 is_unverifiable＋READY 词不再被『静态验不到』支撑＋C5 拆两本账）；一段常量写法自身有 bug（OK:48·lazy=4 不以 OK· 开头），二段修
｜证据署名：直跑不崩：真十库 rc=1 正常出十列与 VERDICT 行（不是 traceback）；读数对账＝libs_measured=10 fails=16 与落码前逐字相同（格数未减），新增可判别项 na 0→10、C5 由「比过293」拆成「比过293(其中验过284·验不到9)」；台架回归 A1 由穿翻拦、A2/A3-2/A5/A6/A7/A8 仍拦、A3-1 仍按设计放行、A4 维持既知上限（盘册同改与漂移静态不可判，已改可见不升红）
- 2026-09-26 11:49:38Z 逐枚重录 1 枚（在册共 23）
  - s0-main-mandate-kinds-coverage.py：d070e516285fd9e0 → b8fe889a6f42aa18
｜理由：落 S881 背书、S864 出包的四类 locator v2：模式改编译件、按位置+basename 判，去掉吞订阅源适配器/Compat 垫片/中央治理件的裸词面枝；同时补两层域与嵌套 routes 假阴
｜证据署名：直跑不崩：尺直跑 rc=0 且 VERDICT: KINDS-GAP 在场、四类 MK 机读行齐；读数对账＝落地前后同宇宙 601 逐类 plugin 1/adapter 5/protocol 25/subfunc 59 与 S881 包 §3 预期**逐字相等**（旧四类 1/18/19/60，无主 32→29，差值逐枚有剔补理由），腿㉕ dual 全 0 未放宽、四类全零⇒FATAL rc=2 那条自锁实测未动
- 2026-09-26 12:07:00Z 逐枚重录 1 枚（在册共 23）
  - s0-main-lib-readiness.py：9d3804ef176dae2d → 1dcd1b08c8ade084
｜理由：S892 打穿 F2 二段后补三条腿：L1 wash 改吃 lazy+degenerate（star 尾注今天零腿，合成 OK:3·star/mod=1 照样 READY）；L2 蓝档判据由『OK 且含 ·』子串改整行白名单（旧写法把 C8 的 ·外锚 正常读数过采成蓝档）；L3 白名单外尾注形态 ⇒ FATAL 拒打裁决
｜证据署名：直跑不崩＝真十库直跑 rc=1 正常出十列与 VERDICT；读数对账＝libs_measured=10 fails=16 两值逐字不变，na 由**误报 10** 收正为 0（今日十库 C5 无一带 OK 尾注，旧蓝档全是 C8 的 ·外锚 被过采），C5 两本账仍 比过293(验过284·验不到9)；S892 三形复跑结论见其主件 F2-ATTACK-S892.md
- 2026-09-26 12:25:51Z 逐枚重录 1 枚（在册共 23）
  - s0-main-lib-readiness.py：1dcd1b08c8ade084 → 2d38946e7f815140
｜理由：修我自己 F2c 造的两处尺损：:501 any(bool) TypeError（S891 交卷点名）＋尾注白名单只登记一族致十库全撞 L3 永不出裁决；改两族登记（验不到／可见计数）+未知形态才拒判+wash 扩到 C8/C9/C10
｜证据署名：直跑：venv python -B probes/s0-main-lib-readiness.py（BOT_AUTOSYNC=0/PYTHONDONTWRITEBYTECODE=1/PYTHONPYCACHEPREFIX 仓外）⇒ 修复前 rc=2 TypeError 崩在 :501；修后 rc=1 读数 READY libs_measured=10 fails=16 na=2 C5=比过293(验过284·验不到9) C8=471 C9=10 C10=10 / VERDICT: NOT-READY（16 格）静态验不到合计 11 枚；现算 sha256[:16]=2d38946e7f815140
- 2026-09-26 13:08:25Z 逐枚重录 1 枚（在册共 23）
  - s759-severance.py：5a0b78d822eee830 → ce6e49d81abb281b
｜理由：S898 点名一条恒真拒判：原式 len(boards)!=len(roster_slugs) 右边恒多库轴座数、补认领宇宙也变不出第 11 座板块，且旧文案承诺「补齐后自动放行」结构上不可兑现；改判据挂到真盲区上（库轴在册成员未进任何认领根 ⇒ 逐枚点名 FATAL，播种座不算盲区），指纹行保留在拒判之前
｜证据署名：直跑：venv python -B probes/s759-severance.py ⇒ RC=2，读数 roster_fp=1cbc02d334a6 scanned=10 roster_n=15 lib_member_seats=2 lib_seed_seats=3、FATAL 点名 14 枚（adapter-mail 2＋contracts 12）；对照 s759-decl-sources 同 fp 1cbc02d334a6／ZERO-GAP 未动；现算 sha256[:16]=ce6e49d81abb281b
- 2026-09-26 13:27:42Z 逐枚重录 1 枚（在册共 23）
  - s0-main-unowned-edge-ranker.py：04101548b2078e73 → 3ce22f9e93a0176b
｜理由：#130：ranker 认领基只吃 FeatureNode.impl_paths、不读 LIBRARY_TAXONOMY ⇒ 已归主的 contracts/** 与 sender/{nonebot,onebot}.py 仍被报成无主，而它那一列表头写「建议归属」；改吃板块轴 ∪ 库轴 members（复用工厂 parse_libs，禁第二套认领），并清掉 docstring 里 1329/576/129 那组当时值＋两枚 FURB192
｜证据署名：直跑：venv python -B probes/s0-main-unowned-edge-ranker.py ⇒ 修前 RC=0 读数 无主 76／入边合计 407；修后 RC=0 读数 无主 61／入边合计 206（76-61=15 枚即被名册认领的 import 目标，407-206=201 条边≈原前十行合计 202 条，逐枚可指认）；ruff --no-cache All checks passed；现算 sha256[:16]=3ce22f9e93a0176b（旧 04101548b207 作废）
- 2026-09-26 13:52:48Z 逐枚重录 1 枚（在册共 23）
  - s759-severance.py：ce6e49d81abb281b → 442d80dcfa5748dc
｜理由：#121 正解：把库轴名册成员根并进认领宇宙（roots＋bid_slug 同批扩），覆盖面从 10 座扩到 12 座有货库座；blind_members 由 16 枚清零，断开分母随之从板块轴口径变为含库轴口径
｜证据署名：直跑：venv python -B probes/s759-severance.py ⇒ 并根前 RC=2（FATAL blind_members 16 枚）；并根后 RC=0，读数 BOARD SEV covered=12 denom=66 declared=0 half=0、VERDICT: NOT-SEVERED；中途实测崩一发 KeyError: contracts（身份表未同批扩），补 bid_slug.update 后通；现算 sha256[:16]=442d80dcfa5748dc
- 2026-09-26 15:03:29Z 逐枚重录 2 枚（在册共 23）
  - s809-buildlib-per-lib.py：39f03cc532d78f05 → ef77f369b5e90b85
  - s833-range-policy.py：2d369aa9fedc3b69 → 6010aca62cde3ea0
｜理由：#131 A 类：两把尺分母从根形第二册 NONBOARD_ROOTS 改吃声明源真身 LIBRARY_TAXONOMY（fac.parse_libs），根形册降为交叉核对、不等值即拒判；现算两册逐枚相等，属加严非放宽
｜证据署名：直跑：两把各改前改后跑一次。改后直跑读数 s833＝per=15 declared=0 missing=15 wildcard=1 VERDICT: RANGE-GAP；s809＝per=15 missing_dir=0 not_git=0 no_manifest=0 ver_bad=0 VERDICT: YES。改前旧读数（同 per=15，分母出处不同）见 SEAT-MAIN §八十五。ruff 余 1 枚 S110 属他席旧码。
- 2026-09-27（R7 迁面）：本日志随钉册三件套迁入 `pins/2026-09-24-central-dispatch/GAUGE-PIN-LOG.md`，板件 `--repin` 读点已改指此受追踪副本（逐枚重录在此续记）；`.superpowers` 原件留档不再续写。
