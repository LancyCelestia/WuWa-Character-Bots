"""今日快报数据源：只准**正规新闻机构**的 RSS（用户 2026-10-02 裁定，见名册）。

**源侧硬边界**（席 F2，2026-10-02；执法＝``tests/test_news_source_whitelist.py``）：
今日快报只准「新华社/人民日报/BBC/CNN/联合早报这一类」有采编与更正机制的新闻
机构，**不许用自媒体/论坛/聚合转载形态**。这条是产品边界而不是运维偏好 ⇒ 刻意
**不落配置键、不留开关**（能关掉的门等于没有门）：放开只能改本文件的
``NEWS_SOURCES`` 名册，且必须同批改对外宣称面（帮助册/卡面），否则宣称门红。

名册＝源的唯一真身：``_FEEDS``（抓取用）由名册里「准入 ∧ 有端点 ∧ 可达性档位
可接」的行**派生**，不另立第二份清单。可达性逐源登记在每行的 ``reachability``
与 ``probe``（实测日期＋出处）上——**未实测的候选一律不接线、不宣称**。

历史实测探针（本波**未**复跑外网，逐源复核清单见工单）：

- 2026-09-11 本机直连（旧 docstring）：IT之家 ``www.ithome.com/rss/``、少数派
  ``sspai.com/feed``、V2EX ``v2ex.com/index.xml``（Atom 1.0）、华尔街见闻
  ``dedicated.wallstreetcn.com/rss.xml``、BBC 中文
  ``feeds.bbci.co.uk/zhongwen/simp/rss.xml``（该源实际返回繁体条目）；
- 2026-09-30 席 S05（``patches/S05-NEWS-WIKI-STEAMDB.md`` §2）：新华社/人民日报
  RSS **内容冻结**（2022-12-14 / 2025-06-05）、CNN **结构性无 RSS**（502/SSL 失败）、
  联合早报 ``/rss`` 返 HTML SPA、BBC 中文直连超时且产线首连 15.5s > 6.0s 预算、
  中新社 ``chinanews.com.cn/rss/*.xml`` 当日新鲜；
- 2026-09-11 剔除：36kr ``/feed``、Solidot ``index?rss``、机器之心 ``/rss`` 实测
  返回 HTML 页面（feed 已下线），收录只会制造常态解析失败的静默噪音。

设计（与 market_data / meme_search 同一套底线）：

- 单源失败（超时/HTML 响应/XML 损坏/超限长）静默跳过，绝不上抛；
- 并发抓取类目内全部源（线程池，整类目共享 timeout_seconds 预算，
  最坏耗时 ≈ 单源超时而不是源数 × 超时）；
- 成功结果进进程内 TTL 缓存（按类目分桶，默认 10 分钟，≤64 条），
  失败不缓存，下一次调用立即重试；
- 解析同时支持 RSS 2.0 与 Atom（ElementTree ``{*}`` 通配命名空间），
  标题剥 HTML 标签 + 反转义实体 + 压空白（华尔街见闻 CDATA 标题
  实测带首尾空格）。

2026-10-08 源清单接线（用户 2026-10-08 给定的时政/综合 10 源 + AI 内容面 +
AI 厂家重点关注；本波落的就是这张清单）
---------------------------------------------------------------- --------
- **新闻不进 ANN/RAG**（用户 2026-10-08 Q-3 裁定）：快报面只做「跨源去重 +
  归类 + 当日快报卡面」。本包**不许**出现通往向量库/索引重建链的 import——
  判据形态＝AST 扫导入（锁 ``tests/test_news_source_whitelist.py`` 腿 ㉒），
  散文约定不算门；``kb_wiki`` 同步链与 23:40 那枚调度键本波一律未动。
- **可达性档位新增 ``shape_ready``（形状已备，待实跑）**：端点/取数口按公开
  口径登记进行内、本席**未复跑外网** ⇒ 不接线、不宣称。它**不在**
  ``_WIREABLE_REACH`` 里，所以「登记了」与「会去抓」在结构上就是两件事（门③）。
- **慢源纪律照抄 BBC 那枚**（``wired_degraded`` 的原文理由＝直连超时、产线首连
  15.5s > ``bot_news_timeout_seconds=6.0`` ⇒ 类目静默为空）：境外域（VOA/NHK/RT/
  半岛）与需代理的域，实跑若踩 6.0s 预算一律记 ``wired_degraded`` 并在 ``probe``
  写明「哪天、哪儿测的」，**禁记 ``wired_live``**（台账 #71 代理面：``proxy=None``
  ≠ 直连，NO_PROXY/env 在显式传 proxy 时全无效）。
- 三档推进口径（AI 厂家逐行写进 ``note`` 首词）：``档①``＝已登记官方公开
  newsroom/blog 或 RSS 候选端点，跑一条探针即可定档；``档②``＝取数口形态/页面
  口径需用户点名（本席不猜 URL、不猜主体）；``档③``＝要看就得登录态或凭据
  ⇒ 本轮一律不做，且任何凭据都不写进本文件（规则 3）。

2026-10-08 二批清单（时政法源 33 项 · 按媒体实体去重后 29 枚 · 附 B 站两枚空间号）
------------------------------------------------------------------------------
- 二批**逐枚实跑过外网**（席 W2，唯一出口＝本文件 ``_fetch_feed_text``，禁第二取数口；
  超时阈取在册缺省 ``bot_news_timeout_seconds=6.0``，见 ``config.py`` 的该字段）。逐枚
  读数（日期＋哪儿测的＋字节＋条数＋耗时）写进各行的 ``probe``。
- 🔴 **二批零接线**——原因不是「没测」，是「接线必红」：宿主件 ``tests/test_news.py``
  把 tech/finance/world 三类的抓取清单钉成逐枚相等（旧腿 ``test_fetch_category_mapping_uses_only_matching_feeds``
  当时断言 ``calls == [ITHOME_URL]``／``[WSCN_URL]``／``[BBC_URL]``，``test_fetch_unknown_category_falls_back_to_mix``
  断言 ``set(calls) == set(_WIRED_FIXTURES)``），而本册腿 ⑯（``test_leg16_...``）把
  politics/ai_vendor/ai_content 三类钉成**空集**。⇒ 七个类目里没有一个能容纳新增的
  ``wired_live``，而那两件不在本席写面。故测通的行一律记 ``pending_reverify``
  （＝**已测通、待产线出口复跑＋宿主夹具跟随**，与 ``shape_ready``「没跑过」两回事）。
  〔2026-10-08 三批状态变更：那两把钉尺已随她授权改成**派生式**（旧名已退役，新腿＝
  ``test_fetch_category_mapping_is_derived_from_roster`` 与改写的 ``..._falls_back_to_mix``），
  二批测通且无否决标记的行已进抓取清单；「零接线」自此是**历史读数**，现算值看
  ``_FEEDS`` 与替代锁腿 ㉑（派生完备）/㉒（延迟预算）/㉓（类目空态诚实登记）。
  🔴 放开账逐枚登记在 ``tests/test_news_source_whitelist.py`` 的
  ``WIRED_KEYS_BASELINE_20261008``／``W2_WIRED_BASELINE_20261008``／
  ``NEW_WAVE_WIRED_BASELINE_20261008``——多一枚（静默放开）红、少一枚（接线被吞）也红。〕
- 去重留痕：她列 **NYT／WSJ／The Times／Asahi 各两次**＝同一媒体实体，册内**各只一枚行**；
  新华社／人民日报／CNN／BBC／NHK／CCTV／半岛／RT／联合早报／路透社／美联社／法新社
  十二枚**册内本有行**⇒ 二批只补探针与类目，不另立第二真身。

2026-10-08 三批：她批准接线（三条硬约束＝延迟／呈现／禁自媒体）
--------------------------------------------------------------
- **接线的机械杠杆只有一个＝可接线索引 ``_WIREABLE_REACH``**，名册行**不改档位**。
  她的判档规则＝「只有产线出口实测才升 ``wired_live``」，而二批读数是**席位出口**（席 W2
  本机直连）⇒ 这些行照实留在 ``pending_reverify``，由本批把 ``pending_reverify``
  **纳入可接线索引**（「可接线」与「已在产线证明过」是两轴，档位不许为了接线被镀成 live）。
  ``unverified``/``shape_ready``/``frozen_stale``/``structural_absent`` 仍在索引外
  ⇒「没测过」与「测过但不可接」结构上抓不到（门③ 原样咬）。
- **第二道闸＝``wire_block``（接线否决）到本批才真的生效**：此前 ``_wired_sources()``
  只判档位、**从不读 ``wire_block``** ⇒ 二批写了「缺政策复核／缺 source_authority 登记／
  缺条序证明」的那五枚（rt/aljazeera/openai/cgtn/tass）其实一直躺在抓取列表里＝
  「写了否决却没执法」的教科书形态。现在否决非空即排除，且否决必须写明缺哪件
  （腿 ㉑ 咬留白，也咬「档位可接、无否决却不在抓取列表」＝静默失踪）。
- 产线出口复跑若踩预算／需代理 ⇒ **只改那一行的档位为 ``wired_degraded``**，抓取列表
  与类目读数不变（同 BBC中文 那枚的处置口径）。
- 🔴 **延迟天花板一字未动**：单源超时与整类目等待预算都仍＝调用方给的
  ``timeout_seconds``（生产缺省 ``bot_news_timeout_seconds=6.0``；``fetch_headlines`` 里
  只有 ``max(1.0, …)`` 的**下限**钳、没有上限钳——腿 ㉒ 逐枚核「每源拿到的超时＝调用方
  预算」，锯天花板消延迟这条路结构上走不通）。压的是**无用功**，四个手段全住
  ``fetch_headlines`` 一处，符号即读数入口：
  ① 出卡路径不再逐 ``future.result()`` join 全批，改为「预算内收已完成的那批」
  （``split_dispatch``/``dispatch_wave_width``＝等待宽度**读共享池真身**、不抄数字）；
  ② 一波装不下的源**照样派发**（不 cancel、不丢），连同预算内没跑完的那批走**补投回调**
  折回**同一代次**的缓存快照（``_on_late_result``/``_stash_or_merge``；补投比主线程写
  快照还快时先进 ``_PENDING_LATE`` 寄存，写快照时一并并进——旧写法在这种竞态下会把
  那批结果静默吞掉，2026-10-08 三批由延迟腿逮到并修）；代次不符则不塞——整批空按既有
  语义「失败不缓存、下次立即重试」，源下一轮仍被派发，不是丢投递
  （``wait_for_outstanding_fetches`` 是测试/运维的收干口，产线不调）；
  ③ 同域名**连续**取不到东西（异常或零条目）进短路账一个冷却窗，到期无条件重试、
  取到一次就清零（``_record_outcome``/``_short_circuit_split``）；绝不永久拉黑，也
  **绝不因短路把类目关空**；
  ④ 提交序按类目轮转（``_rotate_for_coverage``），波宽外的源不会永远排在补投位
  （归类维度不被静默吃掉）。
  读数尺＝``join_all_worst_case_seconds``（旧写法基线：波数 × 预算）对
  ``budget_bound_worst_case_seconds``（新写法：＝预算本身）；现算值与墙钟实测都落在
  ``tests/test_news.py`` 的延迟腿，本文件**不抄数字**（规则 10）。
- 呈现面：**本批未做**。文本按域分节、卡面按域成组出域带＝仍待改
  ``capabilities/news.py`` 与模板件（不在本席写面）；此处已落地的只有跨源同题折叠的
  **出处全列**（``fold_same_topic`` 保 ``sources`` ＋ ``_sources_suffix`` 上文本），
  由腿 ⑲/⑳ 锁着。旧版这一段写过「呈现面同批改」＝虚账，本批更正入账。
2026-10-11 出口守门接线（``SRC=`` 四值闭集 + P4 一票否决，主人裁定＝高管个人号「进正文，
但只有官方消息才进，个人互动不得进」）
------------------------------------------------------------------------------
- 判据真身＝``domains/core/search/source_authority.py`` 末段（P0–P4、闭集、门票、消毒）；
  本件只接线：抓取出口 ``_fetch_single_feed`` 在既有条目准入门之后**同一处**贴标并丢
  未核实条（``gate_news_items``），合并层 ``_fold_to_body`` 把不合格标（个人号无锚）留在
  正文之外、同题时并进既有出处并列位当佐证（不造新版面），文本行逐枚带 ``SRC=``。
- 🔴 名册数据不落 .py：个人号/职衔号行走 Runtime 侧数据面 ``data/news_account_roster.json``
  （唯一路径件重映射、gitignored），**文件缺席＝名册空＝没有任何个人号进得了正文**
  （默认关，与本件「源侧硬边界不落配置键」同口径——本波未新增任何配置键）。
- 判不出的默认方向＝不进：``NewsItem.post``（根帖/引用链/ORG 重发读数）由取数口填，
  今日 RSS 侧一律为空 ⇒ 个人号路结构上拿不到正文位，直到她开页取名册并接线。
- 门的位置只有一处：渲染侧（``capabilities/news.py``）与卡面只**读** ``item.src`` 记账，
  不再判第二遍（锁＝``tests/test_news_source_whitelist.py`` 腿 ㉜c）；出站消毒在
  ``domains/render/plain_text.py`` 的 ``redact_local_secrets`` 末腿（闭集外一律涂成
  ``SRC=UNVERIFIED``）。
"""


from __future__ import annotations

import email.utils
import html as _html
import itertools
import json
import random
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from concurrent.futures import Future, wait
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

# 审查 Q-01：user_copy 为零依赖纯常量池，sources 跨层引用不构成装配环。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core import shared_pool
from plugins.bot_unified_runtime.domains.core.search import source_authority as sa
from plugins.bot_unified_runtime.domains.core.shared_pool import get_shared_pool
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_text,
)

# 响应体上限：单源 RSS 实测最大约 260KB（华尔街见闻），1MB 已是数倍冗余，
# 只为防异常超大响应撑爆内存。
_MAX_FEED_BYTES = 1024 * 1024
# 进程内缓存上限：先清过期，再按最旧丢弃（长驻进程防无界增长）。
_CACHE_MAX_ENTRIES = 64
_CACHE_TTL_DEFAULT_SECONDS = 600.0
# mix 类目每源最多取若干条（跨类目多样性优先于单源深度）。
_MIX_PER_FEED_CAP = 4
# mix 合并后的总量上限（缓存桶存合并结果，供不同 max_items 切片）。
_MIX_MERGE_CAP = 32
# 出卡路径等待预算时的轮询片（真时间）：预算本身仍＝调用方的 timeout_seconds，
# 这片只是「别把 CPU 烧在忙等上」，不是第二把延迟尺。
_POLL_WAIT_SECONDS = 0.05
# 同域连续失败短路：连着这么多轮取不到东西（异常或零条目）就暂时不发外呼。
_FAILURE_SHORTCIRCUIT_THRESHOLD = 3
# 短路冷却窗＝一个缓存 TTL 的量级：到期无条件重试，**绝不永久拉黑**（站点抖动与
# 结构性下架在账上必须长得一样短）。类目因此变空的情形由 fetch 侧兜住。
_FAILURE_SHORTCIRCUIT_COOLDOWN_SECONDS = 600.0


@dataclass(frozen=True)
class NewsItem:
    """单条新闻标题快照。

    ``sources``＝跨源同题折叠后的**出处列表**（2026-10-08 裁定面）。约定刻意为：
    ``()`` 表示「没折叠过」（出处就是 ``source`` 那一枚），非空表示这条是
    「一条题 × N 个源」的折叠结果，``source`` 恒等于 ``sources`` 的首枚（先到的
    源占主位，链接/摘要/时间戳同样取先到的那条——判据要可确定性复跑，不许随
    线程完成顺序漂）。

    ``src``＝出口标源（``SRC=`` 四枚闭集值之一，真身在
    ``domains/core/search/source_authority.py``），**只能由出口守门 ``gate_news_items``
    写**；空串＝没经过门（渲染侧因此不打标，也永不该出现在产线条目上——抓取出口
    逐枚贴标后才进合并）。``post``＝条目的**帖形读数**（根帖/引用链/重发锚点），
    只有结构里带这些字段的取数口（个人号时间线一类）才填；不填＝P2 判不出＝
    个人号永远进不了正文（fail-closed，默认关）。
    🔴 门不许改 ``title``/``summary`` 的一个字：把个人表态改写成公司主语是本口径
    唯一红线级错误（锁＝「正文句子逐字不变」腿）。
    """

    title: str
    url: str
    source: str
    published_at: datetime | None = None
    category: str = "tech"
    summary: str = ""  # F9：RSS 描述首句（禁标题党——标题后给真实内容行）
    sources: tuple[str, ...] = ()  # 跨源去重：折叠后的出处列表（首枚＝source）
    src: str = ""  # 出口标源（SRC= 闭集值；空＝没过门）
    post: sa.PostSignals | None = None  # 帖形读数（P2/P3/P4 的输入；None＝判不出）


# F9 营销/广告条目过滤（用户实弹点名「求职」「推广」）：标题或摘要命中即弃。
_AD_TITLE_RE = re.compile(
    r"(求职|招聘|急聘|推广|赞助|广告|优惠|折扣|优惠券|薅羊毛|拼团|抽奖|送码|"
    r"众测|内测招募|招商|加盟|带货|限时购|秒杀|白嫖|福利社|好物)",
    re.IGNORECASE,
)


# ==================== 源白名单名册（用户裁定唯一落点）====================
# 档位判定的唯一真身在 ``domains/core/search/source_authority.py``（回答「哪个域名
# 更该先看」）。本名册回答**另一件事**：「哪个主体准进今日快报」——两把尺不同维，
# 但对账是机械的（门②）：名册每枚主域名要么在 source_authority 达到
# ``TIER_MAJOR_MEDIA`` 及以上，要么在本行写死 ``note`` 例外理由；判为
# ``TIER_AGGREGATOR``（自媒体/聚合转载档）者**无条件拒**，永远进不来。
NEWS_TIER_SOURCE_OF_TRUTH = "domains/core/search/source_authority.py"

# 可达性档位（逐源实测才准接线；``probe`` 字段记「哪天、哪儿测的」）。
REACH_WIRED_LIVE = "wired_live"  # 已实测可达且返回可解析条目
REACH_WIRED_DEGRADED = "wired_degraded"  # 已接线但实测踩超时预算/需代理＝常静默失败
#: 席位/他席出口实测可达、**产线出口未复核** ⇒ 2026-10-08 三批起**在可接线索引里**
#: （用户批准接线），但档位名不改：升 ``wired_live`` 只认产线出口实测（她的判档规则）。
REACH_PENDING_REVERIFY = "pending_reverify"
REACH_FROZEN_STALE = "frozen_stale"  # 端点通但内容冻结 ⇒ 接进来就是播旧闻
REACH_STRUCTURAL_ABSENT = "structural_absent"  # 结构性无 RSS 通道（诚实说拿不到）
REACH_UNVERIFIED = "unverified"  # 从未实测 ⇒ 既不接线也不宣称
#: 2026-10-08 源清单接线专用档：**形状已备、待她实跑**。端点/取数口已按公开口径
#: 登记进册（或刻意留空并注明缺哪件），但**没有任何出口跑过** ⇒ 既不接线也不
#: 宣称。与 ``pending_reverify`` 的差别＝后者**有读数**（席位出口），前者只有形状。
REACH_SHAPE_READY = "shape_ready"
#: 可接线索引（＝``_FEEDS`` 派生读的这把尺）。三档在内：两档产线/历史实测 +
#: ``pending_reverify``（席位实测、待产线复跑，2026-10-08 用户批准接线）。
#: 🔴 索引外＝「没测过」或「测了但拿不到/内容冻结」，结构上抓不到（门③ 执法）；
#: 索引内每档都必须带「哪天、哪儿测的」探针（门③＋门⑮），新造档位名一律红（门⑳）。
_WIREABLE_REACH = frozenset(
    {REACH_WIRED_LIVE, REACH_WIRED_DEGRADED, REACH_PENDING_REVERIFY}
)

#: 全部合法档位（门 ⑳ 用它拦「顺手新造一个档位名把慢源写成已接通」）。
REACHABILITY_TIERS: frozenset[str] = frozenset(
    {
        REACH_WIRED_LIVE,
        REACH_WIRED_DEGRADED,
        REACH_PENDING_REVERIFY,
        REACH_FROZEN_STALE,
        REACH_STRUCTURAL_ABSENT,
        REACH_UNVERIFIED,
        REACH_SHAPE_READY,
    }
)


@dataclass(frozen=True)
class NewsSource:
    """名册一行＝一个采编主体（不是「一个 URL」）。

    ``domains`` 首枚＝主域名（用于对 source_authority 的档位对账），其余是该主体
    自有的补充域名（如 feed 主机名与文章主机名不同域）。展示名取 ``media``
    （登记名）而**不取远端 ``<title>`` 自称**——换皮只改站点自报名就跟着改是泄露面。
    """

    key: str
    media: str
    domains: tuple[str, ...]
    admitted: bool
    endpoint: str = ""
    category: str = ""
    reachability: str = REACH_UNVERIFIED
    probe: str = ""
    #: **接线否决标记**（与「可达性档位」正的一把独立闸）：档位进了可接线索引、
    #: 但这一枚今日**还不该被真抓**——缺的那件必须由她给（政策复核／取数口口径／
    #: 新鲜度序未核）。非空即排除出 ``_FEEDS``；写明缺哪件由谁裁，空话即红。
    #: 为什么不留白或改档位：改档位＝撒谎（明明测过），改判据＝越权（她的裁定面）。
    wire_block: str = ""
    note: str = ""


#: 名册（源的唯一真身）。``_FEEDS`` 由本表派生，不手写第二份清单。
NEWS_SOURCES: tuple[NewsSource, ...] = (
    # ---------------- 准入且已接线 ----------------
    NewsSource(
        key="ithome",
        media="IT之家",
        domains=("ithome.com",),
        admitted=True,
        endpoint="https://www.ithome.com/rss/",
        category="tech",
        reachability=REACH_WIRED_LIVE,
        probe="2026-09-11 本机直连实测 200/RSS2.0（旧 docstring；2026-10-02 本席未复跑）",
        note="持牌科技新闻编辑室；source_authority 判 TIER_MAJOR_MEDIA。",
    ),
    NewsSource(
        key="wallstreetcn",
        media="华尔街见闻",
        domains=("wallstreetcn.com",),
        admitted=True,
        endpoint="https://dedicated.wallstreetcn.com/rss.xml",
        category="finance",
        reachability=REACH_WIRED_LIVE,
        probe="2026-09-11 本机直连实测 200/RSS2.0（旧 docstring；2026-10-02 本席未复跑）",
        note=(
            "例外档：source_authority 判 TIER_VERTICAL——那是**排序档**不是**自媒体判定**"
            "（该表 TIER_AGGREGATOR 才是自媒体/聚合档）。华尔街见闻是自有采编的持牌财经"
            "编辑室，本席判为正规源；若按最严口径（只准国家级通讯社与主流大报）则本行"
            "出局、finance 类目见底 ⇒ 待用户复核（工单 §5 裁定项 R-1）。"
        ),
    ),
    NewsSource(
        key="bbc",
        media="BBC中文",
        domains=("bbc.com", "bbc.co.uk", "bbci.co.uk"),
        admitted=True,
        endpoint="https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        category="world",
        reachability=REACH_WIRED_LIVE,
        probe=(
            "2026-09-11 本机直连 200；2026-09-30 席 S05 复测＝直连超时、产线 301→/zhongwen/trad "
            "首连 15.5s > bot_news_timeout_seconds=6.0；2026-10-08 席 W2 本机直连复跑两条腿＝"
            "200/RSS2.0、25212 字节、38 条、1.0s、pubDate 最新当日"
        ),
        note=(
            "主域名取文章域 bbc.com（TIER_MAJOR_MEDIA）；feed 主机 feeds.bbci.co.uk 落 "
            "bbci.co.uk，**该域未登记进 source_authority**（工单 §5 请求项 C-1）。"
            "该 feed 实测返回繁体条目，对外类目仍标「国际」。2026-10-08 二批按她给定的判档"
            "规则（条目>0 且耗时在 6.0s 阈内＝wired_live）由 degraded 升 live；🔴 S05 那枚 "
            "15.5s 是**产线出口**样本，本席席位出口复现不出它 ⇒ 产线复跑若仍踩预算，改回 "
            "wired_degraded 只动本行档位（抓取列表与类目读数都不变）。清单去重留痕：她列 "
            "「BBC News」＝本行同一媒体实体，二批不另立行。"
        ),
    ),
    # ---------------- 准入但未接线（可达性不达标或未复核）----------------
    NewsSource(
        key="chinanews",
        media="中国新闻网",
        domains=("chinanews.com.cn", "chinanews.com"),
        admitted=True,
        endpoint="https://www.chinanews.com.cn/rss/world.xml",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-09-30 席 S05 实测 200/0.1s（直连与产线均通），条目日期＝当日（唯一实测新鲜的国内权威源）；"
            "2026-10-08 席 W2 本机直连复跑三支全通＝china.xml 30 条/0.28s、world.xml 30 条/0.31s、"
            "importnews.xml 29 条/0.22s，pubDate 均当日 ⇒ S05 留的「待复核」已复核完"
        ),
        note=(
            "中国新闻社（国家级通讯社）＝TIER_MAJOR_MEDIA。类目按在册端点那一支（rss/world.xml）记 "
            "world；rss/{china,world,importnews}.xml 三支**内容各自不同**（本席 2026-10-08 逐支实测过条数与"
            "日期），要各按各类就得出第二行＝第二真身，故只留一支一行（工单 §6 待验 V-2 已清）。"
            "🔴 档位仍 pending_reverify、**接线动作被本册钉着**：腿 ③b（``test_leg3b_unverified_or_frozen_"
            "candidates_are_not_wired``）把本行档位钉成 pending_reverify 字面值，改 wired_live 当场红；"
            "同批还要跟 ``tests/test_news.py`` 的 world 类抓取清单断言。两处都不在本席写面 ⇒ 待她授权。"
            "2026-10-08 三批**已获她批准接线**：杠杆＝把 pending_reverify 纳入 ``_WIREABLE_REACH``，"
            "本行档位一字不动（升 live 仍只认产线出口实测）；腿 ③b 同批改成派生式判据＋基线，"
            "``tests/test_news.py`` 的类目抓取清单同批改派生式。三支里今日只接在册端点那一支"
            "（world.xml），china/importnews 两支不换端点（第二真身禁令）。"
        ),
    ),
    NewsSource(
        key="xinhuanet",
        media="新华社",
        domains=("xinhuanet.com", "news.cn"),
        admitted=True,
        endpoint="https://www.xinhuanet.com/politics/news_politics.xml",
        category="politics",
        reachability=REACH_FROZEN_STALE,
        probe=(
            "2026-09-30 席 S05 实测 200/text/xml 但条目冻在 2022-12-14，且无 <pubDate>（时间戳是元素外裸文本）；"
            "2026-10-08 席 W2 本机直连复跑＝200、114331 字节、299 条、0.30s，**可解析 pubDate 仍为零**"
            "⇒ 新鲜度无法判定（既不能证明新、也不能证明旧），冻结结论推翻不了"
        ),
        note=(
            "TIER_FIRST_PARTY。接进来＝把四年前的旧闻当「今日快报」播 ⇒ 必须先有新鲜度门（阈值待用户拍，S05 §9.3）。"
            "清单去重留痕：她列「新华社」＝本行同一媒体实体，二批不另立行；档位被本册腿 ③b 钉成 frozen_stale 字面值，"
            "改判需她授权（本席只补了 2026-10-08 的复跑读数）。"
        ),
    ),
    NewsSource(
        key="people",
        media="人民日报",
        domains=("people.com.cn", "peopleapp.com"),
        admitted=True,
        endpoint="http://www.people.com.cn/rss/politics.xml",
        category="politics",
        reachability=REACH_FROZEN_STALE,
        probe=(
            "2026-09-30 席 S05 实测 200/text/xml 但条目 pubDate 全为 2025-06-05；"
            "2026-10-08 席 W2 本机直连复跑＝200、188447 字节、100 条、0.22s，pubDate 最新仍是 2025-06-05"
            "⇒ 冻结复现（与 S05 同读数）"
        ),
        note=(
            "TIER_FIRST_PARTY。同新华社：新鲜度门前不接线。端点是明文 http，接线同批要评估升级 https（工单 §6 待验 V-3）。"
            "清单去重留痕：她列「人民日报」＝本行同一媒体实体；档位被本册腿 ③b 钉成 frozen_stale 字面值，改判需她授权。"
        ),
    ),
    NewsSource(
        key="cnn",
        media="CNN",
        domains=("cnn.com",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-09-30 席 S05 实测：rss.cnn.com 经代理 502、直连 SSL 失败；cnn.com/services/rss/ 无通道；"
            "2026-10-08 席 W2 复跑＝http://rss.cnn.com/rss/cnn_topstories.rss **已可解析**（200/RSS2.0/"
            "174826 字节/69 条/1.53s）但 pubDate 全落在 2023-03-19～2023-05-01；https://cnn.com/services/rss/ "
            "返 HTML 且响应体超 _MAX_FEED_BYTES(1MB) 上限"
        ),
        note=(
            "用户点名源之一（二批再点名），诚实说拿不到 ⇒ 不许用估算或转载冒充（第四部分「非上市/无源」同一口径）。"
            "🔴 今日读数其实更像 frozen_stale（通道通、内容停更）而非 structural_absent，但本册腿 ③b 把本行档位"
            "钉成 structural_absent 字面值 ⇒ 改档需她授权；两档**都不接线**，对外读数不变。"
            "去重留痕：她列「CNN」＝本行同一媒体实体。"
        ),
    ),
    NewsSource(
        key="zaobao",
        media="联合早报",
        domains=("zaobao.com", "wanbao.com"),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-09-30 席 S05 实测：/rss 返回 text/html SPA 壳（无日期串），产线 SSL UNEXPECTED_EOF；"
            "2026-10-08 席 W2 复跑＝https://www.zaobao.com/rss 与 /rss/realtime/china 均 HTTP 404"
        ),
        note=(
            "用户点名源之一（2026-10-08 清单再点名）。要接只能自建 HTML→清单解析器（成本高、且先解决 SSL 截断）⇒ 列入候选不排期。"
            "去重留痕：她列「联合早报」＝本行同一媒体实体；档位被本册腿 ③b 钉住，改判需她授权。"
        ),
    ),
    NewsSource(
        key="cctv",
        media="央视新闻",
        domains=("cctv.com",),
        admitted=True,
        category="politics",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测四形全无 feed＝news.cctv.com/rss/ 404、/rss/china.xml 404、"
            "/rss/world.xml 404、www.cctv.com/rss/ 403（本行此前从未实测，旧档位 unverified）"
        ),
        note=(
            "TIER_FIRST_PARTY。二批按她「404/HTML 而非 feed ⇒ 留 shape_ready 或降 structural_absent」的口径降为 "
            "structural_absent（＝诚实说这个出口拿不到），不猜第五形、不编 URL。要接只能走 App/开放接口面"
            "（＝档③，需凭据，本轮一律不做）。类目按主体自有面记时政。去重留痕：她列「CCTV」＝本行同一媒体实体。"
        ),
    ),
    NewsSource(
        key="thepaper",
        media="澎湃新闻",
        domains=("thepaper.cn",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_MAJOR_MEDIA。端点未实测。",
    ),
    NewsSource(
        key="caixin",
        media="财新",
        domains=("caixin.com",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_MAJOR_MEDIA。端点未实测（且有付费墙口径待裁）。",
    ),
    NewsSource(
        key="reuters",
        media="路透社",
        domains=("reuters.com",),
        admitted=True,
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测三形全无 feed＝https://www.reuters.com/rss HTTP 401、"
            "https://www.reuters.com/pfiles/rssfeed.xml HTTP 401、https://feeds.reuters.com/reuters/topNews "
            "URLError（老 feed 主机已不存在）"
        ),
        note=(
            "TIER_FIRST_PARTY（国际通讯社）。二批读数：公开 RSS 通道拿不到（401/主机消失）⇒ 端点留空、不接线、"
            "不猜第五形（不编 URL）。要去 401 得改出口 UA/凭据面＝档③，本席不动。去重留痕：她列「路透社」一枚。"
        ),
    ),
    NewsSource(
        key="apnews",
        media="美联社",
        domains=("apnews.com",),
        admitted=True,
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测四形全无 feed＝apnews.com/index.rss、/rss、/rss/topnews.xml、"
            "hub/ap-top-news 均 HTTP 403（WAF 挡本出口，非 404）"
        ),
        note=(
            "TIER_FIRST_PARTY（国际通讯社）。403 只证明**本席出口拿不到**，不证明世界上没有 feed ⇒ 若产线换出口"
            "（台账 #71 代理面）可复跑再定档，端点仍留空（不编 URL）。去重留痕：她列「美联社 AP」一枚。"
        ),
    ),
    NewsSource(
        key="afp",
        media="法新社",
        domains=("afp.com",),
        admitted=True,
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测两形 404＝https://www.afp.com/en/rss、"
            "https://www.afp.com/en/feeds/press-releases"
        ),
        note=(
            "TIER_FIRST_PARTY（国际通讯社）。二批读数：公开口径的 feed 路径拿不到 ⇒ 端点留空、不接线、不猜。"
            "去重留痕：她列「法新社 AFP」一枚。"
        ),
    ),
    # ---------------- 2026-10-08 清单接线：时政/综合补口（一律 shape_ready）----------------
    # 这四枚是清单上「册内此前没有」的源。🔴 全部**未实测**：档位 shape_ready ＝
    # 「形状已备，待她实跑」，绝不代表已接通（她台账点名的谎报形态＝「在册≠已执法」
    # 「生成了没发出」同宗）。境外域一律带 BBC 同款的慢源纪律：踩 6.0s 预算记
    # wired_degraded，禁记 wired_live。
    # 🔴 2026-10-08 二批：这四枚**已逐枚实跑**（读数逐枚写在各行 probe，含「哪天、哪儿测的」）。
    # 二批当时档位一律**不动**——不是没测，而是本册腿 ⑩（``test_leg13_new_wave_sources_are_registered_not_wired``）
    # 把首批 20 枚清单行 blanket 钉成「shape_ready 或 不准入」，升任何档位当场红那把尺；改那把尺
    # ＝改判据，不在本席写面 ⇒ 待她点名。RT/半岛 二批实测都在 6.0s 阈内，故 BBC 那枚慢源纪律
    # 今日用不上（VOA 三形无 feed、NHK 头条支停更两月＝另两回事，见各自 probe）。
    # 〔2026-10-08 三批：她点名放开后腿 ⑩ 已改成**派生式＋放开账逐枚登记**（不再是 blanket 钉档），
    # 这四枚的档位由 shape_ready 照实改为跑出来的档（有读数＝pending_reverify、通道通而内容停更＝
    # frozen_stale、这个出口没有 feed＝structural_absent）；RT/半岛今日仍不接线，缺件写在
    # ``wire_block`` 里由她裁——「档位」与「接线」是两轴。〕
    NewsSource(
        key="voanews",
        media="美国之音（VOA）",
        domains=("voanews.com", "voachinese.com"),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测三形全无 feed＝voanews.com/rss 与 voachinese.com/rss 均返 11 字节"
            "纯文本「Invalid url」（200 但不是 feed）、voachinese.com/z/2868/rss.xml HTTP 404 ⇒ 仍未取得端点"
        ),
        note=(
            "档②。清单原文＝「美国广播电台」，仓内既有叫法查无（全库 grep 无 VOA/美国之音"
            "登记行）⇒ 本席按公开口径登记为「美国之音（VOA）」，中文站在 voachinese.com。"
            "**取数口留空**：其 RSS 通道的具体形态本席无数，不猜 URL——待她给一处公开口径"
            "（列表页或 feed 地址）即可补端点转档①。境外域＋需代理面（台账 #71）⇒ 实跑踩 "
            "6.0s 预算按 BBC 同口径记 wired_degraded。"
            "2026-10-08 三批：三形读数＝两形返 11 字节「Invalid url」纯文本、一形 404 ⇒ 档位由 "
            "shape_ready 改判 structural_absent（本席出口结构性没有 feed），端点仍留空、不猜第四形。"
        ),
    ),
    NewsSource(
        key="nhk",
        media="NHK",
        domains=("www3.nhk.or.jp", "nhk.or.jp", "nhk.jp"),
        admitted=True,
        endpoint="https://www3.nhk.or.jp/rss/news/cat0.xml",
        category="world",
        reachability=REACH_FROZEN_STALE,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝www3.nhk.or.jp/rss/news/cat0.xml 200/RSS、3467 字节、7 条、0.52s，"
            "🔴 但 7 条 pubDate **全为 2026-08-08**（停更约两月）⇒ 通道通、内容冻结，接进来就是播旧闻"
        ),
        note=(
            "档①。端点＝NHK 官方 news RSS 分类表的头条支（cat0），形态凭公开口径登记、"
            "**本席未实测**：实跑若返 HTML/404 即降档②请她给页面口径。主域名取 www3.nhk.or.jp"
            "（feed 主机）；🔴 这三枚域都未登记进 source_authority ⇒ 真要接线（改档位）必须"
            "同批登记域名或在本行写死 note 例外，否则门② 咬「档位未登记」（BBC中文同形态，"
            "工单 §5 请求项 C-1）。"
            "2026-10-08 三批：读数（上面 probe）显示**通道通、内容停更两月** ⇒ 档位由 shape_ready "
            "改判 frozen_stale，与新华社/人民日报同一把尺（新鲜度门前不接线）；这一改只动档位、"
            "不动端点与类目，抓取列表与类目读数不变。"
        ),
    ),
    NewsSource(
        key="rt",
        media="RT（今日俄罗斯）",
        domains=("rt.com",),
        admitted=True,
        endpoint="https://www.rt.com/rss/",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        wire_block=(
            "两件缺：① 政策复核——「俄方官方媒体是否算有采编与更正机制的正规源」是她 2026-10-08 "
            "二批留待自己裁的问题（本席不替它镀权威）；② rt.com 未登记 source_authority ⇒ 接线"
            "同批须补登记或由她给例外理由（门②）。她裁完任一件、清空本标记即自动接线。"
        ),
        probe=(
            "2026-10-08 席 W2 本机直连实测两条腿＝www.rt.com/rss/ 200/RSS2.0、646543 字节、100 条、2.11s，"
            "pubDate 当日；复跑仍通 ⇒ 取得到 feed（646KB 已占 _MAX_FEED_BYTES 的 63%，接线前先看体积）"
        ),
        note=(
            "档①。展示名带全称刻意为之：门⑥ 的宣称面对媒体名做**子串**比对，裸「RT」两枚"
            "字母会撞进任何含 RT 的英文文案里红得没道理。端点＝其公开 RSS 主支，凭公开口径"
            "登记、本席未实测。境外域＋需代理面（台账 #71）⇒ 慢就记 wired_degraded。"
            "🔴 rt.com 未登记进 source_authority ⇒ 接线同批要补登记或在行内写例外理由；"
            "俄方官方媒体是否算「有采编与更正机制的正规源」属政策判断，本席只按清单登记，"
            "口径待她复核。"
            "2026-10-08 三批：读数已落（当日、100 条、2.11s）⇒ 档位由 shape_ready 改 "
            "pending_reverify，但**今日不接线**，缺的两件在 ``wire_block`` 里＝由她裁；"
            "真要接线时 646KB 响应体（``_MAX_FEED_BYTES`` 的 63%）还要同批看体积。"
        ),
    ),
    NewsSource(
        key="aljazeera",
        media="半岛电视台",
        domains=("aljazeera.com", "aljazeera.net"),
        admitted=True,
        endpoint="https://www.aljazeera.com/xml/rss/all.xml",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        wire_block=(
            "缺准入凭据：aljazeera.com **未登记** source_authority ⇒ 门② 令「已接线」这一态立不"
            "住（要接就得同批登记档位，那是检索侧排序面的改动，需她点名）。她登记/给例外理由后"
            "清空本标记即自动接线。"
        ),
        probe=(
            "2026-10-08 席 W2 本机直连实测两条腿＝www.aljazeera.com/xml/rss/all.xml 200/RSS2.0、17140 字节、"
            "25 条、0.45s（清空 HTTP(S)_PROXY 复跑 1.55s 仍通）、pubDate 当日 ⇒ 取得到 feed 且远在 6.0s 阈内"
        ),
        note=(
            "档①。端点＝其公开全站 RSS，凭公开口径登记、本席未实测。中文面另有"
            "aljazeera.com/chinese（同域，不另立行）。🔴 aljazeera.com 在仓内已有既有叫法"
            "可对齐：chat.py 的权威域名单里就写着 aljazeera.com（域名一致，无需改那侧）。"
            "source_authority 未登记该域 ⇒ 接线同批补登记；慢就记 wired_degraded。"
            "2026-10-08 三批：读数已落（当日、25 条、0.45s）⇒ 档位由 shape_ready 改 "
            "pending_reverify，今日**不接线**，缺的那件在 ``wire_block`` 里。"
        ),
    ),
    # ---------------- 2026-10-08 清单接线：AI 厂家重点关注（14 枚）----------------
    # 类目 ai_vendor 是**新增类目**（旧 tech 类目语义＝科技媒体头条，不与之混写）。
    # 🔴 14 枚一律未实测 ⇒ shape_ready，一行都不接线；三档推进口径写在每行 note 首词。
    NewsSource(
        key="openai",
        media="GPT（OpenAI）",
        domains=("openai.com",),
        admitted=True,
        endpoint="https://openai.com/news/rss.xml",
        category="ai_vendor",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝openai.com/news/rss.xml 200/RSS2.0、**763815 字节／1255 条**、0.63s，"
            "pubDate 最新 2026-10-07 ⇒ 取得到 feed，但这是**全站归档**型（自 2015 起累积），非当日榜"
        ),
        wire_block=(
            "缺「条序证明」：1255 条全站归档 feed，本席**没有**核过它是否最新在前 ⇒ 接进来若按"
            "``per_feed_cap`` 取前 20 条可能是把旧归档当今日快报播（与新华社/人民日报那两行同一个"
            "新鲜度门，阈值待她拍，见 S05 §9.3）。她或产线复跑确认条序后清空本标记即自动接线。"
        ),
        note=(
            "档①。openai.com 已登记 TIER_FIRST_PARTY（厂商一手发布）⇒ 接线时门② 不咬。"
            "newsroom RSS 的确切路径本席未实测，404 即降档②。展示名带括号同 RT 那条：防子串误撞。"
            "2026-10-08 三批：读数已落 ⇒ 档位由 shape_ready 改 pending_reverify（跑过就不许留"
            "「没跑过」的档），但今日**不接线**，缺件写在 ``wire_block`` 里＝档位与接线两轴。"
        ),
    ),
    NewsSource(
        key="anthropic",
        media="Claude（Anthropic）",
        domains=("anthropic.com",),
        admitted=True,
        endpoint="https://www.anthropic.com/news",
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档①（页面口径）。anthropic.com 已登记 TIER_FIRST_PARTY。登记的端点是 newsroom "
            "**列表页**而非 feed ⇒ 现管线只解 XML，探针返 HTML 时这条判「需自建 HTML→清单"
            "解析器」（联合早报同形态），不要为了接线把它写成 feed。"
        ),
    ),
    NewsSource(
        key="google_ai",
        media="Gemini（Google）",
        domains=("blog.google", "deepmind.google", "ai.google.dev"),
        admitted=True,
        endpoint="https://blog.google/rss/",
        category="ai_vendor",
        # 🔴 档位只写一次（重复关键字参数＝ SyntaxError，整包 import 崩、全树红）：
        # 二批跑出读数 ⇒ 由 shape_ready 改 pending_reverify，经她批准接线。
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝blog.google/rss/ 200/RSS2.0、29446 字节、20 条、0.67s，pubDate 当日"
            "⇒ 取得到 feed（1255 条那枚是 OpenAI 归档 feed，两回事）"
        ),
        note=(
            "档①。主域名取 blog.google（已登记 TIER_FIRST_PARTY）；Gemini 官方发布落该域的"
            "AI 栏目，feed 主机与文章域同域。RSS 路径凭公开口径登记、本席未实测。"
            "deepmind.google 同域族一并登记，避免日后接 DeepMind 博客又开一行第二真身。"
            "2026-10-08 三批：读数已落（上面那条＝席 W2 本机直连，含字节/条数/耗时）⇒ 档位由 "
            "shape_ready 改 **pending_reverify**（shape_ready 的本义是「没跑过」，跑过还留着＝档位撒谎）；"
            "同批经她批准接线 ⇒ ai_vendor 类目由此枚开第一枚实装。"
        ),
    ),
    NewsSource(
        key="meta_ai",
        media="Meta（Meta AI）",
        domains=("ai.meta.com", "meta.com"),
        admitted=True,
        endpoint="https://ai.meta.com/blog/",
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档①（页面口径）。主域名**必须取 ai.meta.com**：meta.com 在 source_authority 未"
            "登记、而 feed 主机与文章主机本就不同域（同 BBC中文那条的取域口径）。端点是 blog "
            "列表页，探针返 HTML ⇒ 判「需自建解析器」，不写 feed 冒充。"
        ),
    ),
    NewsSource(
        key="mistral",
        media="Mistral",
        domains=("mistral.ai",),
        admitted=True,
        endpoint="https://mistral.ai/news",
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note="档①（页面口径）。newsroom 列表页；mistral.ai 未登记 source_authority ⇒ 接线同批补登记（门②）。RSS 通道有无未实测。",
    ),
    NewsSource(
        key="xai",
        media="Grok（xAI）",
        domains=("x.ai",),
        admitted=True,
        endpoint="https://x.ai/news",
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档①（页面口径）。x.ai 未登记 source_authority ⇒ 接线同批补登记。🔴 该厂公告"
            "首发常在 X 平台（登录态＝档③）：本轮只登记自有站面，X 面一律不做。"
        ),
    ),
    NewsSource(
        key="qwen",
        media="Qwen（通义千问）",
        domains=("qwenlm.github.io", "qwen.ai"),
        admitted=True,
        endpoint="https://qwenlm.github.io/",
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档①（页面口径）。技术博客 qwenlm.github.io 是模型发布的一手面（GitHub Pages 站"
            "通常带 feed，路径未实测）。qwen.ai 是同主体产品域一并登记防第二行。两域都未"
            "登记 source_authority ⇒ 接线同批补登记。"
        ),
    ),
    NewsSource(
        key="deepseek",
        media="DeepSeek",
        domains=("deepseek.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。**端点留空**：其更新以 API 变更日志／X／公众号三处分散，本席无法确认哪一"
            "处算「可抓的公开取数口」⇒ 不猜 URL，请她点名页面口径（公众号面落 weixin.qq.com"
            "＝禁册域，若选它需先裁禁册，本席不擅动）。"
        ),
    ),
    NewsSource(
        key="zhipu",
        media="GLM（智谱）",
        domains=("zhipuai.cn", "bigmodel.cn"),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。端点留空：官方新闻室路径本席无数（开放平台文档站与产品站混写）。请她给"
            "一处口径。两域均未登记 source_authority ⇒ 接线同批补登记。"
        ),
    ),
    NewsSource(
        key="moonshot",
        media="Kimi（月之暗面）",
        domains=("moonshot.cn",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note="档②。端点留空：公告主阵地疑在公众号／X（前者落禁册域）⇒ 请她点名可抓的公开面。moonshot.cn 未登记 source_authority。",
    ),
    NewsSource(
        key="minimax",
        media="MiniMax",
        domains=("minimaxi.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note="档②。端点留空：官方站新闻页路径与口径未确认，不猜。minimaxi.com 未登记 source_authority。",
    ),
    NewsSource(
        key="hunyuan",
        media="腾讯混元",
        domains=("tencent.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。端点留空：混元发布多在腾讯云文档／公众号（公众号＝禁册域），公开可抓面"
            "需她点名。tencent.com 是母域、口径宽 ⇒ 若她指定的落点是 cloud.tencent.com，"
            "本行 domains 首枚由她改，本席不替她拍。"
        ),
    ),
    # ---------------- 2026-10-08 三批登记：她点名的科技主体（芯片/半导体/AI/软件/游戏）----------------
    # 口径＝**公司官方发布面**（newsroom/技术博客）＝一手来源，按她的裁定不算自媒体；
    # 高管个人社媒同属一手发布口径，但落点若在 X（登录态＝档③）／微博／公众号（＝禁册域）
    # ⇒ 今日一律不登记端点，只在 note 写明缺哪件。🔴 本批**未**跑任何外呼 ⇒ 端点留空、
    # 档位 shape_ready（＝形状已备、零读数、零接线）；amd/intel/nvidia/apple 四域的
    # 官方发布面具体路径本席不猜（不编 URL），请她给一处公开口径即可转档①。
    NewsSource(
        key="amd",
        media="AMD",
        domains=("amd.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。amd.com 已登记 TIER_FIRST_PARTY（厂商一手发布）⇒ 落端点时门② 不咬。"
            "**端点留空**：d.amd.com/newsroom 与 ddr-ram 主页两形本席无数 ⇒ 不猜 URL，"
            "她给一处公开口径即可转档①。高管个人社媒落 X＝档③，本轮不做。"
        ),
    ),
    NewsSource(
        key="intel",
        media="英特尔（Intel）",
        domains=("intel.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。intel.com 已登记 TIER_FIRST_PARTY。**端点留空**：newsroom 页与 RSS 形态"
            "本席未实测、不猜路径。"
        ),
    ),
    NewsSource(
        key="nvidia",
        media="英伟达（NVIDIA）",
        domains=("nvidia.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。nvidia.com 已登记 TIER_FIRST_PARTY。**端点留空**：官方博客 newsroom 两形态"
            "本席无数、不猜 URL。"
        ),
    ),
    NewsSource(
        key="apple",
        media="苹果（Apple）",
        domains=("apple.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。apple.com 已登记 TIER_FIRST_PARTY。**端点留空**：Newsroom 无公开 RSS 形态"
            "本席未实测 ⇒ 不猜路径；若她指定 Newsroom 列表页则同联合早报判「需自建 HTML→清单"
            "解析器」，不许把页面写成 feed。"
        ),
    ),
    NewsSource(
        key="huawei",
        media="华为",
        domains=("huawei.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。huawei.com **未登记** source_authority ⇒ 真要接线同批补登记或由她给例外"
            "理由（门②）。**端点留空**：官方新闻发布页路径本席无数、不猜 URL。"
        ),
    ),
    NewsSource(
        key="xiaomi",
        media="小米",
        domains=("xiaomi.com", "mi.com"),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。两域都未登记 source_authority ⇒ 接线同批补登记。**端点留空**：press 页与"
            "小米社区（UGC 形态，同禁册口径）不是一回事，本席不把社区当官方发布面。"
        ),
    ),
    NewsSource(
        key="smic",
        media="中芯国际",
        domains=("smics.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。smics.com 未登记 source_authority。**端点留空**：官方新闻稿页路径本席无数"
            "⇒ 不猜 URL；另按第四部分红线，非上市公司的**估值/业绩**只准官方公告口径，"
            "快报只播其官方发布的事实性新闻。"
        ),
    ),
    NewsSource(
        key="oppo",
        media="OPPO",
        domains=("oppo.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note="档②。oppo.com 未登记 source_authority。**端点留空**：官方 newsroom 形态本席无数、不猜 URL。",
    ),
    NewsSource(
        key="vivo",
        media="VIVO",
        domains=("vivo.com",),
        admitted=True,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②。vivo.com 未登记 source_authority。**端点留空**、不猜 URL；她与公开口径里"
            "的 vivo.com 与 vivo 手机域若不同请她点名主域（本席不替她换实体）。"
        ),
    ),
    # ---------------- 2026-10-08 二批清单：她的时政法源（33 项去重后**新增** 17 枚行）----------------
    # 逐枚实跑（唯一出口＝``_fetch_feed_text``，阈＝``bot_news_timeout_seconds`` 在册缺省 6.0s），
    # 读数逐枚写在各行 ``probe``（日期＋哪儿测的＋字节＋条数＋耗时）。
    # 🔴 二批**零接线**，理由见模块头注：宿主件 ``tests/test_news.py`` 钉死 tech/finance/world 的
    # 抓取清单、本册腿 ⑯ 钉死 politics/ai_vendor/ai_content 为空 ⇒ 新增一枚 wired_live 必红其一。
    # 测通的行记 ``pending_reverify``（＝已测通、待产线出口复跑＋宿主夹具跟随）；拿不到的行记
    # ``structural_absent``（＝诚实说这个出口没有 feed），试过哪几形逐枚写在 probe，不编 URL。
    # 接线前置件：主域名须在 ``domains/core/search/source_authority.py`` 达到 TIER_MAJOR_MEDIA 及
    # 以上（或恰 TIER_VERTICAL 且本行写死例外理由），否则门② 咬「档位未登记」。二批零接线用不上
    # 那一步 ⇒ 本席**没动** source_authority，需要登记哪几枚、各属哪档，逐枚写在各行 note 里。
    NewsSource(
        key="nyt",
        media="纽约时报",
        domains=("nytimes.com",),
        admitted=True,
        endpoint="https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测两条腿＝200/RSS2.0、39902 字节、18 条、1.0s（复跑 2.6s），"
            "pubDate 当日；清空 HTTP(S)_PROXY 后复跑仍通 ⇒ 本席出口**直连**可达，不是经本机 7890 代理"
        ),
        note=(
            "档①。去重留痕：她列 NYT 两次＝同一媒体实体，册内一枚。nytimes.com 已登记 TIER_MAJOR_MEDIA"
            " ⇒ 接线时门② 不咬；feed 主机 rss.nytimes.com 是该域末段，``_host_matches`` 自动命中。"
            "二批零接线理由见上方批注——测通≠可静默放开。"
            "2026-10-08 三批**已获她批准接线**：档位仍是 pending_reverify（席位出口读数，升 live 只认"
            "产线出口），接线杠杆＝``_WIREABLE_REACH`` 纳入本档；产线复跑若踩 6.0s 预算只改本行档位为 "
            "wired_degraded，抓取列表与类目读数不变。"
        ),
    ),
    NewsSource(
        key="wsj",
        media="华尔街日报",
        domains=("wsj.com", "dowjones.io"),
        admitted=True,
        endpoint="https://feeds.content.dowjones.io/public/rss/RSSWorldNews",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝200/RSS2.0、51680 字节、72 条、0.94s，pubDate 当日；"
            "另 www.wsj.com/xml/rss/3_7085.xml 已 HTTP 401 ⇒ 不取那一形"
        ),
        note=(
            "档①。去重留痕：她列 WSJ 两次＝一枚行。主域名取 wsj.com（已登记 TIER_MAJOR_MEDIA）；feed "
            "主机落在 dowjones.io（同主体自有发布域，与 BBC中文取 bbc.com 同口径）⇒ **必须**一并登记进 "
            "domains，否则运行期准入门 ``is_admissible_news_url`` 判这枚端点名册外、整源静默掉条。"
            "2026-10-08 三批接线已授权（读数＝席位出口，档位仍 pending_reverify；产线复跑踩预算只改本行为 "
            "wired_degraded）。"
        ),
    ),
    NewsSource(
        key="ft",
        media="金融时报",
        domains=("ft.com",),
        admitted=True,
        endpoint="https://www.ft.com/rss/home",
        category="finance",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝ft.com/rss/home 200/RSS2.0、7208 字节、9 条、1.58s，pubDate 当日；"
            "同主体另一形 /news-feed?format=rss 亦通（11669 字节/25 条/1.56s）"
        ),
        note=(
            "档①。两支路同一真身⇒只登记 rss/home 那一支，不另立第二行（第二真身禁令）。ft.com 已登记 "
            "TIER_MAJOR_MEDIA ⇒ 接线时门② 不咬。类目按主体面记财经（她列 FT 一次）。"
            "2026-10-08 三批接线已授权（finance 类目由本枚扩到两枚；档位仍 pending_reverify，升 live 只认产线出口）。"
        ),
    ),
    NewsSource(
        key="time",
        media="时代（TIME）",
        domains=("time.com",),
        admitted=True,
        endpoint="https://time.com/feed/",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝time.com/feed/ 200/RSS2.0、312456 字节、25 条、1.42s，pubDate 当日；"
            "镜像 feeds.feedburner.com/time/topstories 返回**同字节同条数**（312456/25 条/0.88s）⇒ 同一真身两支路"
        ),
        note=(
            "档①。展示名带括注同 RT 那条：防门⑥ 的子串比对误撞。🔴 time.com **未登记** source_authority"
            " ⇒ 真要接线（改档位）同批要登记或在本行写死例外理由，否则门② 咬「档位未登记」；本席没动那件"
            "（二批零接线用不上，且改判据不在写面）。"
            "2026-10-08 三批接线已授权 ⇒ 同批把 time.com 登记进 source_authority 的 TIER_MAJOR_MEDIA"
            "（那枚注释早已写明这是接线的唯一前置件，不登记就是红）——**登记已随本批落**"
            "（``source_authority._MAJOR_MEDIA`` 行内点名本 key）；档位仍是 pending_reverify。"
        ),
    ),
    NewsSource(
        key="newsweek",
        media="新闻周刊（Newsweek）",
        domains=("newsweek.com",),
        admitted=True,
        endpoint="https://www.newsweek.com/rss",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝200/RSS2.0、12904 字节、20 条、0.80s，pubDate 最新 2026-10-07"
            "（昨日，比 NYT/FT 那几支慢一天）；/feed 形 404 ⇒ 取 /rss 这一形"
        ),
        note=(
            "档①。🔴 newsweek.com 未登记 source_authority ⇒ 接线同批补登记（本席不擅动那件）。她列一次。"
            "2026-10-08 三批接线已授权 ⇒ 同批补登记 newsweek.com（TIER_MAJOR_MEDIA，已随本批落 "
            "``source_authority._MAJOR_MEDIA``）；档位仍 pending_reverify。"
        ),
    ),
    NewsSource(
        key="asahi",
        media="朝日新闻",
        domains=("asahi.com",),
        admitted=True,
        endpoint="https://www.asahi.com/rss/asahi/newsheadlines.rdf",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测两条腿＝200/RDF(RSS1.0)、18544 字节、40 条、0.78s 与 0.81s，"
            "pubDate 当日 ⇒ parse_feed 的 RDF 分支（``{*}item`` 后代轴）实测吃得下"
        ),
        note=(
            "档①。去重留痕：她列 Asahi 两次＝一枚行。🔴 asahi.com 未登记 source_authority ⇒ 接线同批补登记。"
            "日文标题：跨源折叠按 ``normalize_news_title`` 的 NFKC+casefold 判同题，与英文源同尺、无特例。"
            "2026-10-08 三批接线已授权 ⇒ 同批补登记 asahi.com（TIER_MAJOR_MEDIA，已随本批落 "
            "``source_authority._MAJOR_MEDIA``）；档位仍 pending_reverify。"
            "🔴 读数面：该支 feed 是**日文**标题（她点名的朝日新闻本体），卡面/文本原样透出不改写——"
            "翻译属另一件事，本席不在这条链上机翻（机翻＝把没核过的话署上她的名）。"
        ),
    ),
    NewsSource(
        key="cgtn",
        media="CGTN",
        domains=("cgtn.com",),
        admitted=True,
        endpoint="https://www.cgtn.com/subscribe/rss/section/world.xml",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        wire_block=(
            "缺准入凭据：cgtn.com 未登记 source_authority，且「同机构国际台按哪一档给」是她留待"
            "自己裁的问题（本席不替它镀权威）。登记/裁定后清空本标记即自动接线。"
        ),
        probe=(
            "2026-10-08 席 W2 本机直连实测两支＝/subscribe/rss/section/world.xml 200、175758 字节、50 条、"
            "0.36s；/section/china.xml 200、166005 字节、50 条、0.42s；pubDate 均当日"
        ),
        note=(
            "档①。两支路同一主体同一取数口形态⇒只留 world 一支一行（不另立第二真身；要 china 支即换本行端点）。"
            "🔴 cgtn.com 未登记 source_authority ⇒ 接线同批按哪一档由她裁（同机构国际台；本席不替它镀权威）。"
        ),
    ),
    NewsSource(
        key="tass",
        media="塔斯社（TASS）",
        domains=("tass.com",),
        admitted=True,
        endpoint="https://tass.com/rss/v2.xml",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        wire_block=(
            "两件缺（与 rt 同一面）：① 俄方国家通讯社的政策复核由她裁；② tass.com 未登记 "
            "source_authority。裁完清空本标记即自动接线。"
        ),
        probe=(
            "2026-10-08 席 W2 本机直连实测两条腿＝tass.com/rss/v2.xml 200/RSS2.0、49538 字节、100 条、"
            "2.52s（清空 HTTP(S)_PROXY 复跑 4.28s，仍在 6.0s 阈内），pubDate 当日"
        ),
        note=(
            "档①。俄方国家通讯社——与 rt 那行同一个政策复核面（她裁），本席只按清单登记、**不镀权威**："
            "tass.com 未登记 source_authority，真要接线按「通讯社」类给档由她点。她列一次。"
        ),
    ),
    NewsSource(
        key="ukrinform",
        media="乌克兰国家通讯社（Ukrinform）",
        domains=("ukrinform.net", "ukrinform.ua"),
        admitted=True,
        endpoint="https://www.ukrinform.net/rss/block-lastnews",
        category="world",
        reachability=REACH_PENDING_REVERIFY,
        probe=(
            "2026-10-08 席 W2 本机直连实测＝www.ukrinform.net/rss/block-lastnews 200/RSS2.0、25123 字节、"
            "30 条、1.97s，pubDate 当日"
        ),
        note=(
            "档①。主域名取英文站 ukrinform.net（feed 主机与文章域同域）；乌文版 ukrinform.ua 同族一并登记，"
            "免得日后接第二支又开一行。🔴 两域都未登记 source_authority ⇒ 接线同批补登记"
            "（三批已随本批落 ``_MAJOR_MEDIA``：登记的是主域 ukrinform.net，同族 ua 支未登记＝待她点名"
            "要抬哪一支，本席不替它镀档）。"
        ),
    ),
    NewsSource(
        key="times-uk",
        media="泰晤士报（The Times）",
        domains=("thetimes.co.uk",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测三形全无 feed＝/rss、/feed、/latest/rss 均返 1338 字节 HTML 壳"
            "（<!DOCTYPE html>，parse_feed 出 0 条），耗时 0.95–1.31s"
        ),
        note=(
            "档②。去重留痕：她列 The Times 两次＝一枚行。付费墙站点，本席出口未取得公开 feed ⇒ **端点留空、"
            "不猜路径**。主域名取伦敦 The Times（thetimes.co.uk）；若她指的其实是《泰晤士报》别家（如印度版 "
            "Times of India）请点名，本席不替她换实体。"
        ),
    ),
    NewsSource(
        key="tvb",
        media="TVB News",
        domains=("tvb.com",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测两形 404＝news.tvb.com/rss（0.47s）、news.tvb.com/list/rss（1.86s）"
        ),
        note=(
            "档②。两形拿不到 ⇒ 端点留空、不猜第三形；要接需她点名口径（页面或 App 接口）。tvb.com 未登记 "
            "source_authority。她列一次。"
        ),
    ),
    NewsSource(
        key="yonhap",
        media="韩联社（Yonhap）",
        domains=("yna.co.kr",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测五形全无 feed＝en.yna.co.kr/RSS/main.xml 404、en.yna.co.kr/rss/ 404、"
            "en.yna.co.kr/rss/topnews.xml 404、cn.yna.co.kr/rss/ 404、www.yna.co.kr/rss/ 返 81585 字节 HTML 页面"
        ),
        note=(
            "档②。www.yna.co.kr/rss/ 那枚返的是**页面不是 feed** ⇒ 按纪律降 structural_absent（HTML 而非 feed），"
            "不许把它当端点登记。yna.co.kr 未登记 source_authority。她列一次。"
        ),
    ),
    NewsSource(
        key="kcna",
        media="朝鲜中央通讯社（KCNA）",
        domains=("kcna.kp", "kcna.co.jp"),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测三形全部**连接层失败**＝kcna.kp/ 3.61s URLError、"
            "kcna.kp/rss.xml 2.48s URLError、www.kcna.co.jp/rss/ 0.80s URLError ⇒ 没拿到一个字节"
        ),
        note=(
            "档②。🔴 照她清单登记（在册＝准入判定层面），但**不替它镀权威**：不登记 source_authority、"
            "档位不可接、端点留空。「它是否算有采编与更正机制的正规源」是她的产品判断（二批她列了⇒在册），"
            "且朝方单侧口径与内容边界（台账 #36/#43 六硬线）同批复核仍待她裁。可达性＝本席出口结构性拿不到。"
        ),
    ),
    NewsSource(
        key="dpa",
        media="德新社（DPA）",
        domains=("dpa.de",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测两形 404＝www.dpa.de/rss（11.20s，🔴 已超 6.0s 阈）、"
            "www.dpa.com/en/rss（1.31s）"
        ),
        note=(
            "档②。通稿走付费 dpa-AWP，公开 feed 通道本席未取得 ⇒ 端点留空。dpa.de 未登记 source_authority。"
            "她列一次。"
        ),
    ),
    NewsSource(
        key="globaltimes",
        media="环球时报（Global Times）",
        domains=("globaltimes.cn",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测三形全无 feed＝www.globaltimes.cn/rss/china.xml 404、"
            "/rss/world.xml 404、/rss/ 403"
        ),
        note=(
            "档②。🔴 名称按《环球时报》/Global Times 登记（她原文只写「环球报」，本席按最可能实体登记）；"
            "若她指的是别家《环球报》请点名——**不编 URL、不换实体**。globaltimes.cn 在 source_authority 已"
            "登记 TIER_VERTICAL（那是**排序档**不是自媒体判定），真要接线同批须在本行写死例外理由（门② 的"
            "垂类档那条腿）。"
        ),
    ),
    NewsSource(
        key="granma",
        media="格拉玛报（Granma）",
        domains=("granma.cubadebate.cu", "cubadebate.cu"),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测三形全部连接层失败＝en.granma.cubadebate.cu/feed/ 1.67s URLError、"
            "www.granma.cubadebate.cu/feed 2.06s URLError、/rss 2.05s URLError"
        ),
        note=(
            "档②。古巴官报；本席出口连不上＝**没测到就写没测到**，端点留空、不猜路径。两域都未登记 "
            "source_authority。她列一次。"
        ),
    ),
    NewsSource(
        key="kyodo",
        media="共同社（Kyodo）",
        domains=("kyodonews.net",),
        admitted=True,
        category="world",
        reachability=REACH_STRUCTURAL_ABSENT,
        probe=(
            "2026-10-08 席 W2 本机直连实测四形 404＝www.kyodonews.net/feed（3.36s）、"
            "english.kyodonews.net/feed、english.kyodonews.net/rss/list/rss91.xml、china.kyodonews.net/feed"
        ),
        note=(
            "档②。四形拿不到 ⇒ 端点留空、不猜第五形；英文/中文支与母域同族，接线时按她点名的那一支换端点，"
            "不另立行。kyodonews.net 未登记 source_authority。她列一次。"
        ),
    ),
    # ---------------- 2026-10-08 清单点名、本波**接不进来**的行 ----------------
    # admitted=False ⇒ 不发外呼、不进抓取列表、门② 不检档位。这四枚每一枚都缺一
    # 件由她给的东西（uid／主体名／裁定），缺件就不落端点——猜 uid、猜主体名、
    # 编 URL 都在禁止面上。
    NewsSource(
        key="bili-up-juya",
        media="橘鸦",
        domains=("bilibili.com",),
        admitted=False,
        category="ai_content",
        reachability=REACH_SHAPE_READY,
        note=(
            "档①（AI 内容面・B 站 UP 主）。🔴 二批她已给定空间号＝**mid 285286947**（认人按空间号，"
            "昵称「橘鸦」只作展示：昵称可改，不许拿昵称当判据）。两重结构阻塞现状：① 2026-10-02 裁定把 "
            "bilibili.com 写进 BANNED_NEWS_HOSTS（UP 主投稿平台＝UGC），门④ 令它**不可能**标 admitted——"
            "2026-10-08 清单与 2026-10-02 裁定在此正面冲突，待她裁；本席**没有**为了让它进快报去改禁册"
            "（那是改判据，不在写面），并实测 ``is_admissible_news_url(https://space.bilibili.com/285286947)`` "
            "返回 False ⇒ 快报链结构性拒它，不是漏接。② 取数口**已有现成的、且是唯一一条**：domains/subscribe/"
            "adapters/bilibili_adapter.py 的 mid→动态腿（_FEED_SPACE_API）＋视频增量腿（_ARC_SEARCH_API），"
            "它属「订阅」不属「快报」。落点判定＝**走订阅链、快报不碰**；本席离线实测 ``resolve_target`` 对"
            "该空间号返回 target_kind＝creator、target_id＝285286947 ⇒ 结构上接得上，缺的两件是运行期的："
            "订阅对象要经命令面落 Runtime 库（本席禁写运行数据），且动态腿有牙条件是 B 站 cookie"
            "（``_fetch_creator`` 里那句 cookie 非空才走动态；无 cookie 只有视频增量）。禁在本件新建"
            "第二条 B 站通路、禁猜 uid。"
        ),
    ),
    NewsSource(
        key="bili-up-heiya",
        media="黑鸦",
        domains=("bilibili.com",),
        admitted=False,
        category="ai_content",
        reachability=REACH_SHAPE_READY,
        note=(
            "档①。同 橘鸦 那行（UGC 禁册冲突待裁，落点＝订阅链、快报不碰；禁为接线改禁册）；🔴 二批她已"
            "给定空间号＝**mid 3706929260006322**（认人按空间号，昵称「黑鸦」只作展示）。取数口复用 "
            "bilibili_adapter 的 mid→动态腿（_FEED_SPACE_API）＋视频腿（_ARC_SEARCH_API），禁第二通路；"
            "本席同样离线实测 resolve_target 对该空间号返 target_kind＝creator、target_id＝3706929260006322 "
            "⇒ 订阅链接得上，缺的两件与动态腿 cookie 条件同 橘鸦 那行，不猜 uid。"
        ),
    ),
    NewsSource(
        key="happy-series",
        media="happy 系列",
        domains=("pending-subject.invalid",),
        admitted=False,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②・**主体未点名**：清单写着「happy 系列」而本席无法确认它指哪个模型系列/"
            "哪家厂商 ⇒ 不编主体名、不编 URL。domains 填的是 RFC 2606 保留域 .invalid，"
            "结构上不可能命中任何真实站点，只作占位（行必须有 domains 才能被 news_source_for "
            "安全跳过）。她一句话点名主体后，替换该行 domains 首枚并按同规补端点。"
        ),
    ),
    NewsSource(
        key="bili-own-model",
        media="B 站自研大模型",
        domains=("pending-subject.invalid",),
        admitted=False,
        category="ai_vendor",
        reachability=REACH_SHAPE_READY,
        note=(
            "档②・**主体与发布面均未点名**：若指 bilibili 官方模型团队，其公告面在 B 站官方"
            "号（UGC 禁册域）／X（登录态＝档③），本席无法确定该按哪个口径抓 ⇒ 不猜域不猜 URL。"
            "请她点名主体（官方号 uid 或一处公开新闻页）。"
        ),
    ),
    # ---------------- 除名（2026-10-02 用户裁定：自媒体/论坛形态不准进快报）----------------
    NewsSource(
        key="v2ex",
        media="V2EX",
        domains=("v2ex.com",),
        admitted=False,
        note="论坛（用户发帖，无采编与更正机制）。2026-09-12 席 N4 接入、2026-10-02 席 F2 按用户裁定除名。",
    ),
    NewsSource(
        key="sspai",
        media="少数派",
        domains=("sspai.com",),
        admitted=False,
        note="社区投稿平台（内容主要由注册用户投）。同日同因除名；帮助册仍写着它＝宣称面违规，见门⑤ 棘轮。",
    ),
)

#: 名册外的硬禁域名（**零容忍**，不给棘轮通道）：UGC 平台形态 +
#: source_authority 的 TIER_AGGREGATOR（自媒体/聚合转载档）。
#: 判据：这三处任一命中即拒——① 不得作为名册行的 ``admitted=True`` 主域名；
#: ② 不得出现在抓取列表里；③ 条目 URL 指向这些域一律丢（运行期出站门）。
BANNED_NEWS_HOSTS: dict[str, str] = {
    "v2ex.com": "论坛 UGC（2026-10-02 除名）",
    "sspai.com": "社区投稿平台（2026-10-02 除名）",
    "zhihu.com": "问答社区 UGC",
    "weibo.com": "微博 UGC",
    "weixin.qq.com": "公众号＝自媒体主阵地",
    "douyin.com": "短视频 UGC",
    "xiaohongshu.com": "社区笔记 UGC",
    "bilibili.com": "UP 主投稿平台",
    "kurobbs.com": "游戏社区 UGC",
    "oschina.net": "开源社区投稿",
    # 与 source_authority._AGGREGATOR 同族（门④ 锁两侧不漂移）。
    "baijiahao.baidu.com": "百家号＝自媒体",
    "mbd.baidu.com": "手机百度信息流聚合",
    "360kuai.com": "快资讯聚合",
    "ixigua.com": "西瓜视频聚合",
    "toutiao.com": "今日头条聚合",
    "sohu.com": "搜狐号自媒体",
}

# ==================== 名册读口与准入判定 ====================


def _host_matches(domain: str, registered: str) -> bool:
    """整段相等或末段后缀命中（与 source_authority._matches 同语义，锁见门⑦）。

    刻意**不**复用那枚私名：跨包抓私函数＝把别席的改名权接到本件上。等价性由测试
    现算比对（含抢注探针 ``fake-ithome.com``／``evilpeople.com.cn`` 必须不命中），
    漂移当场红，所以这不是「第二把尺」而是「同一把尺的两次证明」。
    """
    return domain == registered or domain.endswith("." + registered)


def _news_domain(value: str) -> str:
    """URL/裸域名 → 可比较的裸域名（复用 source_authority 的归一，禁第二把尺）。"""
    from plugins.bot_unified_runtime.domains.core.search.source_authority import (
        normalize_domain,
    )

    return normalize_domain(value)


def news_source_for(url: str) -> NewsSource | None:
    """URL 归属到名册的哪个采编主体；不在名册（含被禁域）一律 ``None``。"""
    domain = _news_domain(url)
    if not domain:
        return None
    for source in NEWS_SOURCES:
        if any(_host_matches(domain, registered) for registered in source.domains):
            return source
    return None


def is_banned_news_url(url: str) -> bool:
    """该 URL 是否落在硬禁域名表上（UGC/自媒体聚合形态）。

    🔴 唯一例外是**逐枚点名的创作者号名册**（``NAMED_CREATOR_NEWS_EXCEPTIONS``）：
    例外按 `host/mid` 精确命中，**不按域名**——同站其他一切投稿人仍按 UGC 拒。
    """
    if named_creator_news_exception(url):
        return False
    domain = _news_domain(url)
    return bool(domain) and any(_host_matches(domain, host) for host in BANNED_NEWS_HOSTS)


#: 主人逐枚点名的创作者号豁免名册（2026-10-08 裁定：这三枚「可以作为新闻账号使用，
#: 有权威性，可以作为 ai 领域的快报」）。键＝`space.bilibili.com/<mid>` 归一形，
#: 值＝她给的理由原文。🔴 这不是"站点解禁"：`bilibili.com` 仍整档留在
#: ``BANNED_NEWS_HOSTS`` 里一字未删，第四枚 mid 想进来必须她再点名（锁在
#: ``tests/test_news_source_whitelist.py`` 的门上，注毒两发：塞第四枚必红、
#: 写成按 host 放行必红）。认人按 mid，昵称只作展示（昵称可改，不当判据）。
NAMED_CREATOR_NEWS_EXCEPTIONS: dict[str, str] = {
    "space.bilibili.com/285286947": "主人 2026-10-08 点名（橘鸦）：可作 AI 域快报源",
    "space.bilibili.com/3706929260006322": "主人 2026-10-08 点名（黑鸦）：可作 AI 域快报源",
    "space.bilibili.com/39030790": "主人 2026-10-08 点名（本轮新增；主体名她未给）：可作 AI 域快报源",
}


def named_creator_news_exception(url: str) -> str:
    """命中点名名册就返回那条例外原文，否则空串。

    归一只取「host + 首段路径」两截（`https://space.bilibili.com/285286947?x=1`
    与 `space.bilibili.com/285286947/` 必须算同一枚），刻意不做整串相等比较——
    带查询串或尾斜杠的写法漏判＝静默不豁免，那是"看着有牙其实咬空"那种洞。
    """
    return NAMED_CREATOR_NEWS_EXCEPTIONS.get(profile_slot(url), "")


def profile_slot(url: str) -> str:
    """账号槽位的唯一归一口＝``host/首段``（名册豁免与个人号名册共用这一把尺）。"""
    raw = str(url or "").strip().lower()
    if not raw:
        return ""
    path = raw.split("://", 1)[-1] if "://" in raw else raw
    segments = [seg for seg in path.replace("?", "/").replace("#", "/").split("/") if seg]
    if len(segments) < 2:
        return ""
    return f"{segments[0]}/{segments[1]}"


def is_admissible_news_url(url: str) -> bool:
    """准不准进快报：硬禁域一律拒；其余要求「名册内 ∧ admitted」。

    未登记域名同样判 False——快报是**点名要正规源**的场景，与检索侧「未登记不丢弃」
    的取向刻意相反（那侧怕误伤，这侧怕越界；差异理由写在这里，别顺手放宽）。
    🔴 唯一放行旁路是上面那份逐枚点名的创作者号名册（主人裁定，理由在册内原文）。
    """
    if named_creator_news_exception(url):
        return True
    if is_banned_news_url(url):
        return False
    source = news_source_for(url)
    return bool(source and source.admitted)


# ==================== 出口守门（``SRC=`` 四值闭集 + P4 一票否决）====================
# 主人 2026-10-11 裁定＝高管个人号「**进正文，但只有官方消息才进，个人互动不得进**」。
# 判据真身（P0–P4、闭集、门票、消毒）全部住在
# ``domains/core/search/source_authority.py``，本段**只做接线**：
# - 🔄 复用既有唯一出口：门挂在 ``_fetch_single_feed`` 里那道运行期条目闸**同一处**
#   （``is_admissible_news_url`` 之后、进合并/缓存之前），不在任何别处再判一次；
# - 🔴 名册数据不落 .py：主体白名单行、人-司绑定行是**数据**，走 Runtime 侧数据面
#   （``data/news_account_roster.json``，经唯一路径件 ``scripts.runtime_paths.runtime_path``
#   重映射、gitignored）；文件缺席＝名册空＝**没有任何个人号能进正文**＝默认关。
#   本波**没有新增任何配置键**（能关掉的门等于没有门，与快报源白名单同口径）；
# - 版面不新建：个人条降「佐证位」＝既有跨源同题折叠的 ``sources`` 出处并列，
#   装不进佐证位（无同题正文条）就只能不进。
#: 个人号/职衔号名册的数据面落点（相对数据根，缺文件＝空名册＝关）。
#: 行形状（JSON：``{"accounts": [{...}]}``）逐字段见 ``source_authority.AccountRow``；
#: 🔴 只准登记**她开页取到一手**的行，且 ``verified_badge`` 之类平台标记永不作证据。
ACCOUNT_ROSTER_DATA_PATH = "data/news_account_roster.json"

_ACCOUNT_ROSTER: tuple[str, tuple[sa.AccountRow, ...]] | None = None
_ROSTER_LOCK = threading.Lock()
#: 被丢弃（``SRC=UNVERIFIED``）的条目计数——「丢，并记入未核实清单」的最小诚实形态
#: （进程内读数，供审读标签取用；不落任何运行数据）。
_UNVERIFIED_DROPPED = 0
_DROPPED_LOCK = threading.Lock()


def account_roster_path() -> str:
    """名册数据的**落点读数**（唯一路径件解析，禁在本件自拼绝对路径）。"""
    from scripts.runtime_paths import runtime_path

    return str(runtime_path(ACCOUNT_ROSTER_DATA_PATH))


def reset_account_roster_cache() -> None:
    """清空名册读数缓存（测试隔离／她改了名册之后手动刷新；纯进程内状态）。"""
    global _ACCOUNT_ROSTER
    with _ROSTER_LOCK:
        _ACCOUNT_ROSTER = None


def _row_text(payload: dict[str, object], key: str) -> str:
    return str(payload.get(key, "") or "").strip()


def _row_int(payload: dict[str, object], key: str) -> int:
    """体量三件的取数口：非整数＝没填（0）⇒ P0 不成立，绝不当「填了个小值」放行。"""
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def account_row_from_mapping(payload: dict[str, object]) -> sa.AccountRow | None:
    """JSON 一行 → ``AccountRow``（只认形状，不认内容对错：判据在 P0/P1 里）。

    非 dict / 槽位（平台+句柄）取不到 ⇒ ``None``（这行等于没登记）。
    🔴 ``verified``/``verified_badge`` 一类平台标记**照实登记但永不参与判据**（D3）。
    """
    if not isinstance(payload, dict):
        return None
    handle = _row_text(payload, "handle")
    if not handle:
        return None
    return sa.AccountRow(
        handle=handle,
        platform=_row_text(payload, "platform"),
        kind=_row_text(payload, "kind").upper() or sa.ACCOUNT_KIND_PERSON,
        subject_full_name=_row_text(payload, "subject_full_name"),
        display_name=_row_text(payload, "display_name"),
        bio_domain=_row_text(payload, "bio_domain"),
        profile_url=_row_text(payload, "profile_url"),
        post_count=_row_int(payload, "post_count"),
        joined_year=_row_int(payload, "joined_year"),
        follower_count=_row_int(payload, "follower_count"),
        binding_company=_row_text(payload, "binding_company"),
        binding_title=_row_text(payload, "binding_title"),
        binding_valid_from=_row_text(payload, "binding_valid_from"),
        binding_valid_to=_row_text(payload, "binding_valid_to"),
        binding_source=_row_text(payload, "binding_source"),
        verified_badge=bool(payload.get("verified_badge", False)),
    )


def load_account_roster(
    path: str | Path | None = None, *, refresh: bool = False
) -> tuple[sa.AccountRow, ...]:
    """读名册（唯一读口）。**任何**失败都回空表＝所有个人号判不进正文（fail-closed）。

    缺席／空文件／非 JSON／根节点不是对象／``accounts`` 不是数组 ⇒ 一律空表，绝不当成
    「读到了但没内容」而放行，也绝不抛（快报全链「单源失败静默跳过」的语义不许被门破坏）。
    """
    global _ACCOUNT_ROSTER
    resolved = str(path) if path else account_roster_path()
    if path is None and not refresh:
        with _ROSTER_LOCK:
            if _ACCOUNT_ROSTER is not None and _ACCOUNT_ROSTER[0] == resolved:
                return _ACCOUNT_ROSTER[1]
    rows: list[sa.AccountRow] = []
    try:
        raw = Path(resolved).read_text(encoding="utf-8")
    except (OSError, ValueError):
        raw = ""
    if raw.strip():
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            entries = payload.get("accounts")
            if isinstance(entries, list):
                for entry in entries:
                    row = account_row_from_mapping(entry) if isinstance(entry, dict) else None
                    if row is not None:
                        rows.append(row)
    frozen = tuple(rows)
    if path is None:
        with _ROSTER_LOCK:
            _ACCOUNT_ROSTER = (resolved, frozen)
    return frozen


def account_row_for_slot(slot: str) -> sa.AccountRow | None:
    """按 ``platform/handle`` 槽位取行（认人不认昵称；同名不同平台不算同一枚）。"""
    wanted = str(slot or "").strip().lower()
    if not wanted:
        return None
    for row in load_account_roster():
        if row.slot == wanted:
            return row
    return None


def account_row_for_url(url: str) -> sa.AccountRow | None:
    """条目链接指向哪个在册个人号主页；不是主页形状／不在册 ⇒ ``None``。"""
    slot_from_url = profile_slot(url)
    if not slot_from_url:
        return None
    for row in load_account_roster():
        row_slot = profile_slot(row.profile_url) or row.slot
        if row_slot and slot_from_url == row_slot:
            return row
    return None


def outlet_kind_of_handle(handle: str) -> str:
    """句柄 → 号型（P2 引用目标与 P3② 重发者都问这一口；查无＝不是任何号）。"""
    row = account_row_for_slot(f"{handle.strip().lower()}") if handle else None
    if row is None:
        wanted = str(handle or "").strip().lower()
        for candidate in load_account_roster():
            if candidate.handle.strip().lower() == wanted:
                row = candidate
                break
    return row.kind if row is not None else ""


def src_label_for_item(item: NewsItem, *, now: object = None) -> str:
    """一条条目 → 一枚闭集标（🔴 全仓唯一判定口，别处不得再判一次）。

    分两路，路数按**出处形态**定，不按内容像不像公告：
    - **组织号路**：条目落在名册准入行（含「无 URL 但展示名＝名册登记名」那一形）
      ⇒ ``ORG-PRIMARY``，正文主语＝公司正式名＝名册登记名，判定复用名册门本身；
    - **个人号路**：条目带帖形读数（``item.post``），或链接指向个人主页槽位，
      或落 She 点名的创作者号豁免槽位 ⇒ 交 ``sa.judge_account_src`` 走 P0–P4；
      名册里没有这枚号 ⇒ ``UNVERIFIED``（丢）。
    """
    post = item.post
    url = item.url or ""
    row = account_row_for_url(url) if url else None
    if row is None and post is not None and post.handle:
        for candidate in load_account_roster():
            if candidate.handle.strip().lower() == post.handle.strip().lower():
                row = candidate
                break
    is_personal_outlet = (
        post is not None or row is not None or bool(named_creator_news_exception(url))
    )
    if is_personal_outlet:
        return sa.judge_account_src(
            row,
            post if post is not None else sa.PostSignals(text=item.title or ""),
            subject_admitted=is_admissible_news_url,
            outlet_kind_of_handle=outlet_kind_of_handle,
            now=now,  # type: ignore[arg-type]
        )
    source = news_source_for(url) if url else None
    if source is None:
        for wired in _wired_sources():
            if wired.media and wired.media == item.source:
                source = wired
                break
    return sa.SRC_ORG_PRIMARY if (source is not None and source.admitted) else sa.SRC_UNVERIFIED


def gate_news_items(items: Iterable[NewsItem], *, now: object = None) -> list[NewsItem]:
    """出口守门（抓取出口唯一一次贴标＋落地）：贴标 → ``UNVERIFIED`` 丢弃 → 个人条改署名。

    🔴 只动 ``src`` 与出处署名（``source``/``sources``），**不动正文句子**（``title``/
    ``summary`` 逐字不变）：把个人表态改写成公司主语是本口径唯一红线级错误。
    ``EXEC-PERSONAL`` 在这里**不删**——它还得走「同题并进佐证位」那一步
    （``_keep_body_only``）；没有同题正文条时那边才把它留在正文之外。
    """
    global _UNVERIFIED_DROPPED
    kept: list[NewsItem] = []
    dropped = 0
    for item in items:
        label = src_label_for_item(item, now=now)
        if label == sa.SRC_UNVERIFIED:
            dropped += 1
            continue
        outlet = item.source
        if label == sa.SRC_EXEC_ON_NAMEROOM:
            row = _row_for_item(item)
            if row is not None:
                outlet = sa.build_exec_signature(row)
        elif label == sa.SRC_EXEC_PERSONAL:
            # 🔴 标在门里打一次：折叠把出处并进正文条时这枚「不作口径」跟着走，
            # 佐证位因此不会长得像共同口径（到合并层才补标＝折叠过的条永远补不上）。
            outlet = f"{item.source}{_PERSONAL_CORROBORATION_SUFFIX}" if item.source else ""
        kept.append(replace(item, src=label, source=outlet, sources=()))
    if dropped:
        with _DROPPED_LOCK:
            _UNVERIFIED_DROPPED += dropped
    return kept


def _row_for_item(item: NewsItem) -> sa.AccountRow | None:
    """署名取行（与判据同一路：先看链接槽位，再看帖形句柄）。"""
    row = account_row_for_url(item.url or "")
    if row is not None:
        return row
    handle = str(getattr(item.post, "handle", "") or "")
    return account_row_for_slot(handle) if handle else None


def unverified_drop_count() -> int:
    """被丢弃的未核实条目数（审读标签读口；测试隔离用 ``reset_unverified_drop_count``）。"""
    with _DROPPED_LOCK:
        return int(_UNVERIFIED_DROPPED)


def reset_unverified_drop_count() -> None:
    with _DROPPED_LOCK:
        global _UNVERIFIED_DROPPED
        _UNVERIFIED_DROPPED = 0


def _wired_sources() -> tuple[NewsSource, ...]:
    """名册 → 真被抓取的行：**准入 ∧ 有端点 ∧ 有类目 ∧ 档位可接 ∧ 未被接线否决**。

    两道门是**正交**的（2026-10-08 二批立 ``wire_block`` 时的原话＝「改档位＝撒谎，
    改判据＝越权」）：
    - ``reachability`` 回答「测过没有、测出来什么」；
    - ``wire_block`` 回答「今日该不该真抓」（缺政策复核／缺 source_authority 登记／
      缺条序证明——缺的那件由她给，写明即红得掉、清空即自动接线）。
    🔴 索引外的档位（``unverified``/``shape_ready``/``frozen_stale``/
    ``structural_absent``）即便填了端点也不会被收录＝「未实测不得接线」 structural 保证；
    索引内的行若 ``wire_block`` 非空同样排除，且**必须**在 ``wire_block`` 里写清缺哪件
    （锁＝``tests/test_news_source_whitelist.py`` 腿 ㉑：留白即红，拦「顺手把不想要的
    源标个空否决」与「测过了却在名册里静默失踪」两种谎）。
    """
    return tuple(
        source
        for source in NEWS_SOURCES
        if source.admitted
        and source.endpoint
        and source.category
        and source.reachability in _WIREABLE_REACH
        and not source.wire_block.strip()
    )


def tier_wireable_but_blocked_sources() -> tuple[NewsSource, ...]:
    """档位可接、端点与类目齐、却因 ``wire_block`` 今日不接的行（诚实缺席的读口）。"""
    return tuple(
        source
        for source in NEWS_SOURCES
        if source.admitted
        and source.endpoint
        and source.category
        and source.reachability in _WIREABLE_REACH
        and source.wire_block.strip()
    )


# (url, 展示名, 类目)；类目取值见 CATEGORY_LABELS。**由名册派生，勿在此手写行**。
_FEEDS: tuple[tuple[str, str, str], ...] = tuple(
    (source.endpoint, source.media, source.category) for source in _wired_sources()
)


def wired_media_names() -> frozenset[str]:
    """实装（真会抓）的源登记名——对外宣称的唯一合法集合。"""
    return frozenset(source.media for source in _wired_sources())


def admitted_unwired_media_names() -> frozenset[str]:
    """名册内准入但**没接线**的媒体名：这些名字出现在任何对外宣称面即红。"""
    return frozenset(
        source.media
        for source in NEWS_SOURCES
        if source.admitted and source not in _wired_sources()
    )

# 类目 → 中文标签（对外展示与缓存分桶共用这一组键）。
# politics/ai_vendor/ai_content 三键＝2026-10-08 清单接线新增（时政 / AI 厂家 /
# AI 内容）。🔴 新增键只到「名册归类 + 缓存分桶」这一层为止：命令面的类目词解析
# 真身在 capabilities/news.py 的 ``extract_news_category``（不在本席写面），那侧
# 目前只认 财经/国际/科技 → 新类目今日只能经 mix 轮转与 ``fetch_headlines(key)``
# 程序路读到。2026-10-08 二批把这条账的**精确落点**补完（三步，缺一就点不到）：
#   ① ``domains/subscribe/capabilities/news.py::extract_news_category``——加「时政」→
#      politics（以及「AI 厂家」→ai_vendor）分支；只加这一处不够 ↓
#   ② 同件 ``_NEWS_TRIGGER_RE``——触发词表里没有「时政」任何形（含拼音/缩写），词都不
#      命中就轮不到类目解析；加词同批要过 ``tests/test_news.py`` 的触发用例；
#   ③ ``domains/chat_reply/capabilities/echo.py::_HELP_ENTRIES`` 的 快报 topic 文案 ＋
#      ``scripts/command_catalog.py --write`` 再生成 ``docs/command-catalog.md``/
#      ``COMMANDS.md``（🔴 今日非安静窗，本席**没跑**任何 --write）。
#   🔴 且「点到」≠「有内容」：类目里有没有实装源**只由名册派生现算**（腿 ㉓：读空的
#   类目必须在替代锁里逐枚写明缺哪件、由谁裁，没登记就红；登记了却读得出源＝漂移也红）。
#   2026-10-08 三批放开接线后 ai_vendor 已有实装源，politics/ai_content 仍是诚实缺席
#   （缺的那两件由她给，见 ``_FEEDS`` 派生读口与基线）。
CATEGORY_LABELS: dict[str, str] = {
    "tech": "科技",
    "finance": "财经",
    "world": "国际",
    "politics": "时政",
    "ai_vendor": "AI 厂家",
    "ai_content": "AI 内容",
    "mix": "综合",
}

#: 精确取源的类目（＝除 mix 之外的全部类目键）。**由 CATEGORY_LABELS 派生**，
#: 不写第二份清单：旧实现这里硬编码过 ("tech","finance","world")，于是新增类目
#: 会被 ``_feeds_for`` 当成「未知类目」回退成全量抓取——那等于新类目永远读不到
#: 自己的源（在册≠已执法的同宗，只是这次红在行为面）。
_EXACT_CATEGORIES: frozenset[str] = frozenset(CATEGORY_LABELS) - {"mix"}

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_degraded_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="快报暂时拉不到")

# 进程内缓存：按类目分桶，缓存最后一次成功抓取（monotonic 时间戳, 快照, 代次）。
# 代次＝这一批抓取的编号；补投/迟到件只折回**自己那一代**的快照（新一代已自己取过
# 这批源，把旧一代的迟到件混进去＝同一源在同一张卡上出现两个时刻的说法）。
_CACHE: dict[str, tuple[float, tuple[NewsItem, ...], int]] = {}
_CACHE_LOCK = threading.Lock()
#: 补投/迟到件比主线程写快照还快时的寄存位（代次 → 条目；判据见 ``_stash_or_merge``）。
_PENDING_LATE: dict[int, list[NewsItem]] = {}
#: 派发轮转位与短路账（都是进程内、自动到期的临时态，**不落任何运行数据**）。
_ROUND_OFFSETS: dict[str, int] = {}
#: 同域名 → (连续取空/异常的轮数, 恢复时刻 monotonic)。
_HOST_FAILURES: dict[str, tuple[int, float]] = {}
_STATE_LOCK = threading.Lock()
#: 已交给共享池但还没收干净的 future（补投与迟到件）；测试/运维复跑用
#: :func:`wait_for_outstanding_fetches` 收干，**禁在产线路径调用**（那等于把
#: 解耦又收回来了）。
_OUTSTANDING: set[Future] = set()
_OUTSTANDING_LOCK = threading.Lock()
_GENERATION = itertools.count(1)


def reset_news_cache() -> None:
    """清空进程内快报缓存与迟到件寄存（测试与运维手动刷新用）。"""
    with _CACHE_LOCK:
        _CACHE.clear()
        _PENDING_LATE.clear()


def reset_news_fetch_state() -> None:
    """清空轮转位与连续失败短路账（测试隔离用；短路是**临时态**不是配置）。"""
    with _STATE_LOCK:
        _ROUND_OFFSETS.clear()
        _HOST_FAILURES.clear()


def cached_snapshot(category: str) -> tuple[NewsItem, ...]:
    """类目缓存快照的只读口（补投是否真折回同一代次，由它验，禁测试直摸 ``_CACHE``）。"""
    with _CACHE_LOCK:
        bucket = _CACHE.get(category if category in CATEGORY_LABELS else "mix")
        return tuple(bucket[1]) if bucket else ()


def wait_for_outstanding_fetches(timeout_seconds: float = 15.0) -> bool:
    """把补投/迟到那批外呼收干净；返回是否全部收干（产线路径不调，测试/运维复跑调）。

    存在的理由＝**测试卫生**：出卡路径不再等第二批，若测试不等它们收干就退出，
    monkeypatch 已还原 ⇒ 后台那批会打到真网络（本仓禁联网）。
    """
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        with _OUTSTANDING_LOCK:
            pending = [future for future in _OUTSTANDING if not future.done()]
        if not pending:
            with _OUTSTANDING_LOCK:
                return not any(not future.done() for future in _OUTSTANDING)
        wait(pending, timeout=max(0.001, deadline - time.monotonic()))
        if time.monotonic() >= deadline:
            return False


def _fetch_feed_text(url: str, timeout_seconds: float) -> str:
    """单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    _, text = http_get_text(
        url,
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_FEED_BYTES,
    )
    return text


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_title(raw: str) -> str:
    """标题清洗：剥 HTML 标签、反转义实体、压空白（CDATA 常带首尾空格）。"""
    text = _HTML_TAG_RE.sub(" ", raw or "")
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_datetime(raw: str) -> datetime | None:
    """RSS pubDate（RFC 822）与 Atom updated/published（ISO 8601）都能解。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_link(node: ET.Element) -> str:
    """条目链接：Atom 取 href 属性（优先 rel=alternate），RSS 取文本。"""
    first = ""
    for link_el in node.findall("{*}link"):
        href = (link_el.get("href") or link_el.text or "").strip()
        if not href:
            continue
        if not first:
            first = href
        if (link_el.get("rel") or "alternate").strip() == "alternate":
            return href
    return first


def _entry_date(node: ET.Element) -> str:
    """条目时间：RSS pubDate / Atom published|updated / RSS1 dc:date。"""
    for tag in ("pubDate", "published", "updated", "date"):
        raw = node.findtext("{*}" + tag)
        if raw and raw.strip():
            return raw
    return ""


def _entry_summary(node: ET.Element, *, max_chars: int = 80) -> str:
    """条目摘要：RSS description / Atom summary|content 的首段纯文本。

    F9 禁标题党：标题之下必须给真实内容行。剥 HTML 标签/实体，截 80 字。
    """
    for tag in ("description", "summary", "content"):
        raw = node.findtext("{*}" + tag)
        if not raw or not raw.strip():
            continue
        text = _HTML_TAG_RE.sub(" ", raw)
        text = _html.unescape(text)
        text = _WS_RE.sub(" ", text).strip()
        # 常见 boilerplate 前缀（全图：(图)/图片来自网络 等）跳过
        if len(text) < 8:
            continue
        return text[:max_chars].rstrip() + ("…" if len(text) > max_chars else "")
    return ""


def parse_feed(text: str, *, source: str, category: str) -> list[NewsItem]:
    """解析单源 XML（RSS 2.0 / Atom / RDF 均可）；坏 XML 返回 []。

    缺标题的条目跳过，缺链接/时间的条目保留（字段尽力而为）。
    F9：营销/广告条目（求职/推广/优惠 等）直接过滤；摘要入 NewsItem。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    # {*}` 通配命名空间：RSS2 的 item 在 channel 下、RDF 的 item 在根下、
    # Atom 是 entry，全部用后代轴一网打尽。
    nodes = root.findall(".//{*}item") or root.findall(".//{*}entry")
    items: list[NewsItem] = []
    for node in nodes:
        title = _clean_title(node.findtext("{*}title") or "")
        if not title:
            continue
        summary = _entry_summary(node)
        if _AD_TITLE_RE.search(title) or _AD_TITLE_RE.search(summary):
            continue
        items.append(
            NewsItem(
                title=title,
                url=_entry_link(node),
                source=source,
                published_at=_parse_datetime(_entry_date(node)),
                category=category,
                summary=summary,
            )
        )
    return items


def _feeds_for(category: str) -> list[tuple[str, str, str]]:
    """类目 → 源列表；mix 或未知类目回退全部源。

    再过一道**名册准入门**（纵深防御）：``_FEEDS`` 本已由名册派生，但它是私名且
    可被 monkeypatch/后续改动，所以运行时不信任它的形状——名册外端点在这里就掉，
    不进线程池、不发外呼。
    """
    rows = (
        [feed for feed in _FEEDS if feed[2] == category]
        if category in _EXACT_CATEGORIES
        else list(_FEEDS)
    )
    return [feed for feed in rows if is_admissible_news_url(feed[0])]


def _fetch_single_feed(
    url: str,
    source: str,
    category: str,
    per_feed_cap: int,
    timeout_seconds: float,
) -> list[NewsItem]:
    """抓取并解析单源；任何失败静默返回 []，不给整体拖后腿。

    名册对 ≠ 条目对：RSS 里的转载链可以指向别处，所以解析后、进合并/缓存之前
    再对每条 ``item.url`` 过一次准入门（席 F2 运行期出站门），**紧接着过出口守门**
    （``gate_news_items``：贴 ``SRC=`` 标 + 丢未核实 + 个人号降佐证）。🔴 这两道门同在
    这一处、只判这一次：渲染侧与审读侧只**读** ``item.src``，不再判第二遍。
    **无 URL 的条目保留**——它的来源已是名册登记名，没有可判定的域名，宁缺不假
    （出口守门对这种条目走「展示名＝名册登记名」那一路，不因此判它未核实）。
    """
    try:
        text = _fetch_feed_text(url, timeout_seconds)
    except Exception:  # noqa: BLE001 - 单源失败静默跳过，快报绝不抛异常。
        return []
    items = parse_feed(text, source=source, category=category)
    admitted = [item for item in items if not item.url or is_admissible_news_url(item.url)]
    return gate_news_items(admitted)[:per_feed_cap]


# ==================== 跨源去重（2026-10-08 裁定：只折叠、不进向量库）====================

#: 快报同题键的命名空间。**键形只在这一处拼**（禁任何域自拼 ``f"{a}:{b}"`` 第二形，
#: 同 ``domains/core/session_keys.py:person_scope_key`` 的裁定口径）。
NEWS_DEDUPE_NAMESPACE = "news"


def normalize_news_title(raw: str) -> str:
    """标题归一（同题判据的输入）：清洗 → NFKC → casefold → 去全部空白 → 剥首尾标点。

    刻意**保留中段标点**：中段标点差异按本判据算两件事（宁可少折）。归一只做三件
    不会把两件事并成一件事的事：全角/半角与兼容字符（NFKC）、大小写（casefold）、
    空白（各家源的空格/缩进形态不一）。零依赖、纯函数、离线可测。
    """
    text = unicodedata.normalize("NFKC", _clean_title(raw)).casefold()
    chars = [char for char in text if not char.isspace()]
    while chars and unicodedata.category(chars[0])[0] in ("P", "S"):
        chars.pop(0)
    while chars and unicodedata.category(chars[-1])[0] in ("P", "S"):
        chars.pop()
    return "".join(chars)


def news_topic_key(title: str) -> str:
    """同题折叠键：``news:<归一标题段>``（🔴 **不带类目**——裁定序是「去重先于归类」）。

    🔴 **键形不自造正则、不复用别处的私名**：段过
    ``domains/emergency_info/service/dedupe.py:active_push_key_segment``——那是仓内
    「构造侧唯一洗段口」（键段禁 ``:`` 与空白、非法字符连摘要后缀一起处理，见台账
    #46 与 S184/Q-G8 两案）。中文标题不落在 ``_SEGMENT_RE`` 字符集里，该口会给出
    ``h<blake2b>`` 形态的确定性摘要段：**同输入恒同输出**（折叠可复跑）、
    **不同输入靠摘要分开**（差一个字绝不撞桶＝不过度折叠的结构保证）。
    类目不进键的理由：同一条新闻被财经源与科技源各转一次就是**一条**信息，键若带
    类目它就永远折不上，卡面会出现两行同题＝跨源去重形同虚设。
    惰性导入（跨域抓函数）与本件 ``_news_domain`` 同一口径，避免装配环。
    """
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        active_push_key_segment,
    )

    normalized = normalize_news_title(title)
    if not normalized:
        return ""
    return ":".join(
        (active_push_key_segment(NEWS_DEDUPE_NAMESPACE), active_push_key_segment(normalized))
    )


def fold_same_topic(items: Iterable[NewsItem]) -> list[NewsItem]:
    """把「同题多源」折叠成一条并保留出处列表（先到源占主位，确定性可复跑）。

    折叠条目的 ``category``/``url``/``summary``/``published_at`` 一律取**先到那条**；
    跨类目也折（同题＝同一条信息，去重先于归类）；无归一标题的条目原样保留
    （键为空＝不参与判据，绝不因为算不出键就把它当重复丢掉）。

    🔴 **幂等**（2026-10-08 二批新锁 ⑯ 咬出来的缺陷）：新键第一条落地时**沿用该条目
    自带的 ``sources``**，不重置成单源——旧写法一律写 ``(item.source,)``，于是把一批
    已经折过的条目再折一次（缓存命中后续合并、断点续发、mix 复用同一快照都会走到）
    会把「一条题 × N 个源」的出处**截成一源**＝跨源出处被静默吃掉。修后同输入恒同
    输出，且出处列表只增不减（锁＝``tests/test_news_source_whitelist.py`` 腿 ⑲/⑲b）。
    """
    folded: list[NewsItem] = []
    position_by_key: dict[str, int] = {}
    for item in items:
        topic_key = news_topic_key(item.title)
        if not topic_key:
            # 键算不出来（标题清洗后为空）＝不进判据，原样保留，绝不当重复吞掉。
            folded.append(item)
            continue
        index = position_by_key.get(topic_key)
        if index is None:
            position_by_key[topic_key] = len(folded)
            carried = tuple(item.sources) if item.sources else ((item.source,) if item.source else ())
            folded.append(replace(item, sources=carried))
            continue
        keeper = folded[index]
        outlets = list(keeper.sources or (keeper.source,))
        if item.source and item.source not in outlets:
            outlets.append(item.source)
        # 只补出处，不改主链接/主摘要/主时间：一条题在卡面上只占一格、点一次进一家。
        folded[index] = replace(keeper, sources=tuple(outlets))
    return folded


def _sources_suffix(item: NewsItem) -> str:
    """快报行的出处后缀：单源＝（源名）；多源＝（A/B/C）或（A 等 N 源）。"""
    outlets = item.sources or ((item.source,) if item.source else ())
    outlets = tuple(name for name in outlets if name)
    if not outlets:
        return ""
    if len(outlets) == 1:
        return f"（{outlets[0]}）"
    if len(outlets) <= 3:
        return f"（{'/'.join(outlets)} ·同题 {len(outlets)} 源）"
    return f"（{outlets[0]} 等 {len(outlets)} 源）"


#: 个人号降佐证位时挂在出处名尾巴上的口径标注（防「佐证」被读成「共同口径」）。
_PERSONAL_CORROBORATION_SUFFIX = "（个人号佐证·非公司口径）"


def _fold_to_body(merged: Sequence[NewsItem]) -> list[NewsItem]:
    """折叠 + 正文过滤的**唯一合成口**：合格标条目先占主位，个人条只作出处并进。

    🔴 为什么「合格条在前」：``fold_same_topic`` 的主位是**先到那条**。个人条先到、
    ORG 条后到时直接折会把整格主位交给不合格标 ⇒ 正文过滤把那格整体丢掉 =
    **在册 ORG 条被个人条挤掉**（台账 #73「在册≠已执法」的反向形态）。分区后再折保证
    同题有合格条时主位必是合格条；全员合格时（今日产线全貌）分区是恒等变换 ⇒ 逐字原序。
    """
    rows = list(merged)
    eligible = [item for item in rows if sa.body_admits_src(item.src)]
    if len(eligible) == len(rows):
        return _keep_body_only(fold_same_topic(rows))
    donors = [item for item in rows if not sa.body_admits_src(item.src)]
    return _keep_body_only(fold_same_topic(eligible + donors))


def _keep_body_only(folded: Sequence[NewsItem]) -> list[NewsItem]:
    """正文只留合格标（``ORG-PRIMARY``/``EXEC-ON-NAMEROOM``）；``EXEC-PERSONAL`` 降佐证位。

    抑制规则（名册席草案 B 最后两条）在这里兑现：同一题已经有合格条 ⇒ 个人条**不占
    条目数**，出处并进那条的 ``sources``（既有折叠能力，不造新版面）；没有同题合格条
    ⇒ 整条不进正文（现有版面没有「待确认/传闻」栏，宁可不进也不造栏目）。
    🔴 全员合格时逐字回原表 ⇒ 既有折叠锁（腿 ⑲/⑳）与卡面守恒锁零漂移；``src`` 为空的
    条目按「没过门」处理＝不进正文（fail-closed，绝不当成 ORG）。
    """
    body: list[NewsItem] = []
    donors: list[NewsItem] = []
    for item in folded:
        (body if sa.body_admits_src(item.src) else donors).append(item)
    if not donors:
        return list(folded)
    position_by_topic: dict[str, int] = {}
    for index, item in enumerate(body):
        key = news_topic_key(item.title)
        if key:
            position_by_topic.setdefault(key, index)
    for donor in donors:
        outlet = donor.source
        if not outlet:
            continue
        slot: int | None = position_by_topic.get(news_topic_key(donor.title))
        if slot is None:
            continue  # 无同题正文条 ⇒ 不进正文，也不硬塞进别的条目（不占条目数）
        keeper = body[slot]
        outlets = list(keeper.sources or (keeper.source,))
        if outlet not in outlets:
            outlets.append(outlet)
            body[slot] = replace(keeper, sources=tuple(outlets))
    return body


def _merge_dedup(lists: list[list[NewsItem]], *, interleave: bool, cap: int) -> list[NewsItem]:
    """合并 + 按 URL 去重 + **跨源同题折叠**；mix 用轮转合并保证类目多样性，其余保源序。

    2026-10-08 裁定面：同一条新闻被多家源转载时只占一格，并把出处并列保留
    （``NewsItem.sources``）。判据是**标题归一后逐字相等**，不是相似度——宁可少折
    也不把两件事并成一件（注毒腿 ⑯b 钉「差一个字不折」）。``cap`` 折的是**题**，
    折叠后条目数自然变少，这是产品要的效果不是丢数据。

    出口守门（``SRC=``）的最后一步接在这里（``_keep_body_only``）：折叠先跑，个人条
    才有机会被并到同题正文条的佐证位上；正文过滤在合并/缓存这一层 ⇒ 出卡的条目、
    进缓存的快照、补投折回的迟到件走的是同一条路，没有第二处过滤。
    """
    merged: list[NewsItem] = []
    seen_urls: set[str] = set()
    if interleave:
        pools = [list(feed_items) for feed_items in lists]
        while len(merged) < cap and any(pools):
            for pool in pools:
                if len(merged) >= cap:
                    break
                if not pool:
                    continue
                item = pool.pop(0)
                if item.url and item.url in seen_urls:
                    continue
                if item.url:
                    seen_urls.add(item.url)
                merged.append(item)
        return _fold_to_body(merged)
    for feed_items in lists:
        if len(merged) >= cap:
            break  # 与旧「到 cap 直接 return」等价：外层也不再喂第二源
        for item in feed_items:
            if item.url and item.url in seen_urls:
                continue
            if item.url:
                seen_urls.add(item.url)
            merged.append(item)
            if len(merged) >= cap:
                break
    return _fold_to_body(merged)


def _evict_cache(ttl_seconds: float) -> None:
    """缓存上限治理：先清过期，再按最旧丢弃（≤64 条）。"""
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    now = time.monotonic()
    expired = [
        key
        for key, (cached_at, _snapshot, _generation) in _CACHE.items()
        if now - cached_at > ttl_seconds
    ]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


# ==================== 延迟预算内的并发派发（2026-10-08 三批）====================
# 🔴 天花板一字未动：单源超时与出卡路径的等待预算都仍＝调用方给的 ``timeout_seconds``
# （生产缺省 ``bot_news_timeout_seconds=6.0``，真身住 ``config.py``）。压的是**无用功**
# ——「整类目逐 ``future.result()`` join」在源数 > 池宽时要等第二波，第二波不是投递、
# 是排队；改成「出卡路径只等一波，其余照旧派发、结果后台折回同代次快照」。
#: 出卡路径允许并行等待的源数＝共享池宽度。**读真身、不抄字面量**（池宽若被别的波
#: 改动，这把尺跟着走；抄一份数字＝延迟门与产线两个口径，正是台账 #68★「幽灵字段」同宗）。
def dispatch_wave_width() -> int:
    """一波并发能装几枚源（＝``shared_pool.SHARED_POOL_MAX_WORKERS``，下限 1）。"""
    return max(1, int(shared_pool.SHARED_POOL_MAX_WORKERS))


def split_dispatch(
    feeds: Sequence[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """按波宽切 **(出卡路径要等的这批, 只补投不等的这批)**。

    🔴 两批**都派发**——第二枚不是「丢掉」，是「不占出卡路径」。判据只看波宽，
    不看类目：类目再多也只等一波（这是「禁止高延迟」的结构保证，也是腿 ㉒ 的尺）。
    """
    width = dispatch_wave_width()
    rows = list(feeds)
    return rows[:width], rows[width:]


def join_all_worst_case_seconds(
    row_count: int, *, timeout_seconds: float, workers: int | None = None
) -> float:
    """**旧写法**（提交全部源后逐个 ``result()`` join）的最坏墙钟＝波数 × 单源预算。

    产线已不走这条路（``fetch_headlines`` 不再 join 第二批）。本函数只留着当
    「改前」基线尺：延迟锁用它现算旧口径，不许口头说快。
    """
    width = dispatch_wave_width() if workers is None else max(1, int(workers))
    if row_count <= 0:
        return 0.0
    waves, _ = divmod(int(row_count) - 1, width)
    return float(waves + 1) * float(timeout_seconds)


def budget_bound_worst_case_seconds(timeout_seconds: float) -> float:
    """新写法的出卡路径最坏墙钟＝**一波** × 单源预算＝调用方预算本身。"""
    return float(timeout_seconds)


def _rotate_for_coverage(
    feeds: Sequence[tuple[str, str, str]], key: str
) -> list[tuple[str, str, str]]:
    """提交序按类目轮转：一波装不下时，**这一波是谁**每轮位移，部分结果仍覆盖多域。

    不轮转的后果是结构性的：波宽 8、类目 12 枚，固定取前 8 枚 ⇒ 后 4 枚永远排在
    补投位，归类维度（哪个域上卡）被静默吃掉——台账 #73「在册≠已执法」的同一形态。
    """
    rows = list(feeds)
    if not rows:
        return rows
    width = dispatch_wave_width()
    with _STATE_LOCK:
        offset = _ROUND_OFFSETS.get(key, 0) % len(rows)
        _ROUND_OFFSETS[key] = (offset + width) % len(rows)
    return rows[offset:] + rows[:offset]


def _short_circuit_split(
    feeds: Sequence[tuple[str, str, str]], now: float
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """同域**连续**失败到阈值 ⇒ 本轮起暂时不发外呼（自动到期，绝不永久拉黑）。

    返回 (可以发的, 被短路的)。判据是「连续」：取到条目就清零，所以站点抖一次
    不会被记仇；冷却到期后无条件重试。
    """
    eligible: list[tuple[str, str, str]] = []
    deferred: list[tuple[str, str, str]] = []
    with _STATE_LOCK:
        snapshot = dict(_HOST_FAILURES)
    for row in feeds:
        host = _news_domain(row[0])
        failures, retry_at = snapshot.get(host, (0, 0.0))
        if failures >= _FAILURE_SHORTCIRCUIT_THRESHOLD and now < retry_at:
            deferred.append(row)
        else:
            eligible.append(row)
    return eligible, deferred


def _record_outcome(endpoint: str, *, ok: bool, now: float) -> None:
    """记一枚源的成败（短路账的唯一写口）。``ok``＝异常**且**零条目都算失败。"""
    host = _news_domain(endpoint)
    if not host:
        return
    with _STATE_LOCK:
        if ok:
            # 「连续」在这里兑现：取到条目就清零，站点抖一次不会被记仇。
            _HOST_FAILURES.pop(host, None)
            return
        failures, retry_at = _HOST_FAILURES.get(host, (0, 0.0))
        failures += 1
        if failures >= _FAILURE_SHORTCIRCUIT_THRESHOLD:
            retry_at = now + _FAILURE_SHORTCIRCUIT_COOLDOWN_SECONDS
        _HOST_FAILURES[host] = (failures, retry_at)


def _fetch_feed_row(
    row: tuple[str, str, str], per_feed_cap: int, timeout: float
) -> tuple[tuple[str, str, str], list[NewsItem], bool]:
    """线程池里跑的那一层：把「结果」与「这枚源到底成没成」一起带回来。

    ``_fetch_single_feed`` 本身静默吞异常返回 ``[]``，光看条目数分不清「站点挂了」
    和「今天确实没新条目」，短路账需要后者之外的信号 ⇒ 这里再包一层判定。
    """
    url, media, feed_category = row
    try:
        items = _fetch_single_feed(url, media, feed_category, per_feed_cap, timeout)
    except Exception:  # noqa: BLE001 - 单源异常绝不上抛（快报不抛是台账 #12 的语义）。
        return row, [], False
    return row, items, bool(items)


def _stash_or_merge(
    key: str, generation: int, items: Sequence[NewsItem], *, interleave: bool
) -> None:
    """把迟到/补投的条目并进**同一代次**的快照；快照还没建就先寄存（不丢投递）。

    🔴 为什么要寄存：补投/迟到件在产线里常常**比主线程写快照还快**（假源秒回、真源
    也快的时候都会踩到）。旧写法只认「缓存里已有这一代」，于是那批结果被静默吞掉
    ＝「接线了却永远读不到」，正是台账 #73「在册≠已执法」的同宗。寄存只保留到下一轮
    开跑：新一代已重新派发这些源，旧寄存届时作废（源还会被抓，不是丢投递）。
    """
    if not items:
        return
    with _CACHE_LOCK:
        bucket = _CACHE.get(key)
        if bucket is not None and bucket[2] == generation:
            merged = _merge_dedup(
                [list(bucket[1]), list(items)], interleave=interleave, cap=_MIX_MERGE_CAP
            )
            _CACHE[key] = (bucket[0], tuple(merged), generation)
            return
        _PENDING_LATE.setdefault(generation, []).extend(items)


def _outcome_or_none(future: Future) -> tuple[tuple[str, str, str], list[NewsItem], bool] | None:
    """取回 ``(行, 条目, 成不成)``；线程里炸了（含注毒样本）就给 ``None``，绝不上抛。"""
    try:
        return future.result()
    except Exception:  # noqa: BLE001 - 收不到就算这枚源没结果，快报不抛是台账 #12 的语义。
        return None


def _on_late_result(
    key: str, generation: int, interleave: bool, future: Future
) -> None:
    """补投/迟到件的收口：记账 → 折回同代次快照。跑在共享池线程里，**绝不再提交任务**
    （``shared_pool`` 禁嵌套等待）。"""
    with _OUTSTANDING_LOCK:
        _OUTSTANDING.discard(future)
    payload = _outcome_or_none(future)
    if payload is None:
        return
    row, items, ok = payload
    _record_outcome(row[0], ok=ok, now=time.monotonic())
    _stash_or_merge(key, generation, items, interleave=interleave)


def _submit(
    pool, row: tuple[str, str, str], per_feed_cap: int, timeout: float
) -> Future:
    future = pool.submit(_fetch_feed_row, row, per_feed_cap, timeout)
    with _OUTSTANDING_LOCK:
        _OUTSTANDING.add(future)
    return future


def fetch_headlines(
    category: str = "mix",
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _CACHE_TTL_DEFAULT_SECONDS,
    max_items: int = 8,
) -> list[NewsItem]:
    """按类目抓取今日头条列表；全部源失败返回 []，绝不抛异常。

    - 类目：tech / finance / world / politics / ai_vendor / ai_content / mix
      （mix 跨类目轮转各取若干，未知类目按 mix 处理）；
    - ``timeout_seconds`` **既**是单源超时**也**是出卡路径的等待预算，两个口径同值 ⇒
      天花板不在本件被调小（腿 ㉒ 锁的就是「每源拿到的超时逐枚等于调用方预算」）；
      出卡路径只等一波（``dispatch_wave_width`` 枚），其余派发后由回调折回同代次快照；
    - 成功结果按类目进进程内 TTL 缓存（默认 600s），命中直接切片返回；
      失败不缓存，下一次调用立即重试；
    - 同域连续失败短路一个冷却窗（自动到期），且绝不因短路把类目关空。
    """
    key = category if category in CATEGORY_LABELS else "mix"
    ttl = max(0.0, float(cache_seconds))
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        cached_at, cached_snapshot_items = (
            (cached[0], cached[1]) if cached is not None else (None, None)
        )
    if cached_at is not None and now - cached_at <= ttl:
        return list(cached_snapshot_items)[: max(1, int(max_items))]

    feeds = _feeds_for(key)
    if not feeds:
        return []
    per_feed_cap = _MIX_PER_FEED_CAP if key == "mix" else 20
    timeout = max(1.0, float(timeout_seconds))

    eligible, _skipped = _short_circuit_split(feeds, now)
    if not eligible:
        # 全类目都在短路冷却里 ⇒ 照旧全量试一次：短路是省无用功，不是关类目。
        eligible = list(feeds)
    rotated = _rotate_for_coverage(eligible, key)
    blocking, detached = split_dispatch(rotated)
    generation = next(_GENERATION)
    interleave = key == "mix"

    pool = get_shared_pool()
    blocking_futures = [(row, _submit(pool, row, per_feed_cap, timeout)) for row in blocking]
    detached_futures = [(row, _submit(pool, row, per_feed_cap, timeout)) for row in detached]

    # 出卡路径：在预算内收「已经完成的这批」。逐 future.result() 的旧 join 写法已退役
    # （源数 > 池宽时它必然多等一波）。
    deadline_started = time.monotonic()
    pending = [future for _row, future in blocking_futures]
    collected: dict[int, list[NewsItem]] = {}
    while pending:
        done, pending = wait(pending, timeout=_POLL_WAIT_SECONDS)
        for future in done:
            payload = _outcome_or_none(future)
            if payload is None:
                continue
            row, items, ok = payload
            collected[id(future)] = items
            _record_outcome(row[0], ok=ok, now=time.monotonic())
        if time.monotonic() - deadline_started >= timeout:
            break

    per_feed_lists: list[list[NewsItem]] = []
    for _row, future in blocking_futures:
        items = collected.get(id(future))
        if items is None:
            # 起跑没赶上预算 / 还没被取消就得收：交回调折回同代次，投递不丢。
            future.add_done_callback(
                lambda late, k=key, g=generation, il=interleave: _on_late_result(k, g, il, late)
            )
            per_feed_lists.append([])
            continue
        per_feed_lists.append(items)
    for _row, future in detached_futures:
        future.add_done_callback(
            lambda late, k=key, g=generation, il=interleave: _on_late_result(k, g, il, late)
        )

    merged = _merge_dedup(per_feed_lists, interleave=interleave, cap=_MIX_MERGE_CAP)
    with _CACHE_LOCK:
        stashed = list(_PENDING_LATE.pop(generation, []))
        final = (
            _merge_dedup([list(merged), stashed], interleave=interleave, cap=_MIX_MERGE_CAP)
            if stashed
            else merged
        )
        if final:
            _CACHE[key] = (now, tuple(final), generation)
            _evict_cache(ttl)
        # 比本轮更早的代次寄存一律作废：新一代已把这些源重新派发过（不是丢投递）。
        for stale_generation in [g for g in _PENDING_LATE if g < generation]:
            _PENDING_LATE.pop(stale_generation, None)
    return merged[: max(1, int(max_items))]


def format_news_brief(items: Sequence[NewsItem], category_label: str) -> str:
    """渲染纯文本快报：首行日期+类目，正文 ``1. 标题（来源） SRC=<闭集值>``＋摘要行。

    F9：有摘要的条目标题下缩进给真实内容行（禁标题党——用户要求把真实
    内容写在里面）；无摘要的只上标题。

    出口标源（``SRC=``）：经过出口守门的条目**每条都带一枚标**，标只由
    ``sa.src_marker`` 造（闭集外的取值它自己回落 ``UNVERIFIED``，渲染侧无从伪造一枚
    权威标）。``src`` 为空＝这条没过门（只有直接手搓条目的旧夹具这样）⇒ 不打标也
    不算放行，行形与旧版逐字相同，既有行形锁零漂移。
    """
    if not items:
        return _empty_degraded_text()
    # 本地时区日期（astimezone 使 aware，规避 DTZ005）。
    date_text = datetime.now().astimezone().strftime("%Y-%m-%d")
    lines = [f"今日快报 · {date_text} · {category_label}"]
    for index, item in enumerate(items, 1):
        marker = f" {sa.src_marker(item.src)}" if item.src else ""
        lines.append(f"{index}. {item.title}{_sources_suffix(item)}{marker}")
        if item.summary:
            lines.append(f"    {item.summary}")
    return "\n".join(lines)
