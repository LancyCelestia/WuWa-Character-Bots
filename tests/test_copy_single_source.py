"""文案单一真身常驻门（SEAT-S-COPY，2026-09-22）。

用户原令「统一文本/模板/内容/口径」的执行门：**同一句人话被抄成第二份**这件事，
在本仓必须是一份**带理由的登记**，而不是一句"知道了下次注意"。

与本仓另一条文门 `tests/test_user_copy_unification_gate.py` 的分工（互不替代）：
- 那件是**模式门**：钉死「旧句式（晚点再试试？/只有管理员才能…）不得在池外回潮」，
  带文件级白名单。
- 本件是**份数门**：钉死「同一句文案现在有几份、该留哪一份、为什么暂时容得下副本」，
  **无文件级豁免**——豁免只能是逐簇登记，且登记本身会过期。

判据（扫描真身 = `scripts/copy_duplication_census.py`，本门按路径加载，逻辑只有一份）：
AST 取用户可见字符串单元（docstring / 日志调用 / 正则 pattern / URL 不算，口径同
`tests/test_copy_redline_gate.py`）→ 归一化（NFKC 收全半角、占位符 `{var}` 折成 `{}`、
去标点空白、小写）→ 同一归一化形态出现在 >=2 个文件 = 一簇。门槛：归一化 >=12 字，
或带句末标点且 >=6 字（短标签的重复是词汇复用，不是文案同构）。

四条不变量（红在哪条必须点名）：
- `NEW_CLUSTER`            出现了未登记的近重复簇（新增副本 ⇒ 红）
- `STALE_REGISTRATION`     登记的簇已经不在树里（已被收编或话已改写 ⇒ 登记必须删，红）
- `REGISTRY_INTEGRITY`     登记项自身不合格（缺 home / 缺 reason / home 路径不存在 / key 重复）
- `SCAN_SCOPE_SANITY`      扫描面塌陷（文件数或簇数异常缩水，防空转）

改登记面的规矩：收编掉一处副本 ⇒ 同批改登记；确需新增副本 ⇒ 登记 home + reason，
reason 要写「为什么暂时允许」而不是「允许」。
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CENSUS_PATH = REPO_ROOT / "scripts" / "copy_duplication_census.py"
RUNTIME_PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"

_CENSUS_MODULE = "copy_duplication_census"


def _load_census():
    spec = importlib.util.spec_from_file_location(_CENSUS_MODULE, CENSUS_PATH)
    assert spec is not None and spec.loader is not None, f"普查器加载失败：{CENSUS_PATH}"
    module = importlib.util.module_from_spec(spec)
    # dataclass 解析需要模块在 sys.modules 里（PEP 562 之外的老坑）。
    sys.modules[_CENSUS_MODULE] = module
    spec.loader.exec_module(module)
    return module


census = _load_census()


# ---------------------------------------------------------------------------
# 登记面（逐簇：key=归一化文案 sha256[:12]，home=唯一该留的地方，reason=为什么暂时容得下）
# 由 scripts/copy_duplication_census.py 实跑派生，勿手改 key。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cluster:
    key: str
    sample: str
    home: str = ""
    note: str = ""


@dataclass(frozen=True)
class ClusterFamily:
    name: str
    home: str
    reason: str
    members: tuple[Cluster, ...]


REGISTRY: tuple[ClusterFamily, ...] = (
    ClusterFamily(
        name="interface-double",
        home="plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
        reason="两份清单同描述双写（base_router.InterfaceEntry ↔ capability_registry.InterfaceDecl）。⚠ 2026-09-22 更正：本族 42 簇**并非全出自接口清单**——成员里混着路由 reason 与内部 note（如\"提醒（12点提醒我…）\"\"预留：游戏直播事件接入\"\"内部：桥接层\"），故只收 InterfaceEntry 一侧清不掉整族；逐条组成与分批见 decisions/INTERFACE-DECL-DEDUP-PLAN-20260922.md。好消息：两侧**没有分叉**，test_capability_registry 已逐字段双向锁等值⇒收编属观察输出零变更。收编方向=单一声明源由调度层投影，属 WP8 Wave 1-4 挂账，本门只钉住不再加第三份",
        members=(
            Cluster("6e191d3a45ff", "北向资金（北向资金/沪股通/深股通成交总额，触发词见 domains/finance/c"),
            Cluster("1218d3bdb801", "SnowLuma / OneBot V11 传输"),
            Cluster("1dd9646999f6", "OneBot V11 群 API（get_group_info/成员列表/公告/精华）："),
            Cluster("273eeb1b38e2", "提醒（12点提醒我写作业/提醒列表/取消提醒）"),
            Cluster("2ddb3c4b2976", "汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页"),
            Cluster("36df61b70cb9", "商品行情（黄金/金价/白银/原油/铜价/大宗商品）"),
            Cluster("3d4cc01cd1b2", "预留：游戏直播事件接入，尚未实现"),
            Cluster("43bee50bdcdc", "内部：桥接层，接收游戏侧消息，无用户命令"),
            Cluster("4883a60c79d0", "个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stock"),
            Cluster("51716dc52c2b", "汇率（美元兑人民币/汇率面板）"),
            Cluster("56915a2fd585", "今日快报（快报/科技新闻/财经快报/国际新闻）"),
            Cluster("603d6eb8abb2", "B站/小红书/抖音/油管/推特/Lofter/Pixiv/allcpp/米画师/小黑盒/"),
            Cluster("6673e1ac2f80", "百度百科公开接口 + 每日推送"),
            Cluster("6c38df19f9fa", "群信息（群信息/群主是谁/群人数/群公告/群精华/本群多大了）"),
            Cluster("7215e73b159e", "预留：GsCore 侧指令统一进入基层路由"),
            Cluster("757aae02733a", "紧急信息（外部预警与政务应急聚合：紧急信息｜紧急信息 待审）"),
            Cluster("7700041f9485", "UP主/番剧/小红书博主等新内容与开播推送"),
            Cluster("7a444acef52f", "入站 QQ 消息与出站发送统一走 OneBot V11（SnowLuma），由发送队列收"),
            Cluster("7bd04d92d5d6", "预留：GsCore 侧指令统一进入基层路由，尚未实现"),
            Cluster("8308fdf09241", "萌百 MediaWiki 公开 API：显式指令 + 二次元问句自动查询（未命中降级人格"),
            Cluster("87e4aff64e1f", "人格档案 + 向量知识库 + 世界观注入的大模型回复"),
            Cluster("89c81bd9ca25", "调用本地 meme-generator-rs HTTP API 生成表情包"),
            Cluster("fe0cac5ddf2d", "商品行情（黄金/白银/原油/铜现货与 30 日走势，触发词见 domains/finan"),
            Cluster("995c938b5ad7", "媒体归档（收藏/归档/存图+媒体；存聊天记录）"),
            Cluster("9c4a97e72b45", "作为上下文能力注入，不单独占用文本路由"),
            Cluster("9ed6e9952242", "监听群图片异步下载、MD5 去重、权重筛选、VLM 打标与 NSFW 过滤"),
            Cluster("9f6011019330", "国债收益率（国债/期限利差/收益率曲线）"),
            Cluster("a19cf9c4da5e", "个股行情（英伟达/AMD/英特尔股价）"),
            Cluster("a3a9329bc2a0", "内部：心情引擎，经上下文注入，不占文本路由"),
            Cluster("b02591f62032", "自然语言对话（人格+世界观+价值观+方法论）"),
            Cluster("c1e95f032b2e", "链接解析（视频/图片/社交媒体/商品等）"),
            Cluster("c6137f4c5cc9", "中国气象局 NMC 免 key 查询"),
            Cluster("ca638def3f39", "北向资金（北向资金/沪股通/深股通）"),
            Cluster("ca7e1ebf64b2", "二次元问句（萌娘百科自动查询，未命中降级聊天）"),
            Cluster("e0ae4287371a", "收件箱（收件箱 买牛奶/收件箱）"),
            Cluster("e505ca102c14", "全球股指行情（行情/美股行情/大盘）"),
            Cluster("e935cc238df6", "预留：游戏内直播/活动事件接入"),
            Cluster("e9eeae0737ed", "收件箱随手记 + 定时吃什么推荐与早晚简报（BOT_DAILY_ASSIST_*，纯文本"),
            Cluster("ef2d2b3a1556", "网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 搜索"),
            Cluster("f127c2a333fd", "本机 GPT-SoVITS v2ProPlus HTTP API（api_v2.py 的"),
            Cluster("fd36ee743a21", "国债收益率（国债/期限利差/收益率曲线，触发词见 domains/finance/cap"),
            Cluster("f900aae234b9", "MediaWiki 公开 API"),
            # S-BASE 基线席 2026-09-29 逐簇补账：批⑪／同意门／需求 5 三波把 InterfaceEntry ↔
            # InterfaceDecl 双写形照旧复制了四枚说明句（同族判据：两侧无分叉、双向锁等值、
            # 收编=调度层投影挂 WP8 账），本门只钉住不再加第三份。
            # S-BASE 续账（同批现算换键）：财经域分家把三枚说明句里的触发词路径由
            # ``capabilities/market.py`` 改写为 ``domains/finance/capabilities/market.py``，
            # base_router 与 capability_registry 两侧**同批同形**改写（判据不变：两侧零分叉）
            # ⇒ 旧 key 005d53d28e15 / 8a22c3551f85 / f6c37a70f8b4 按本门规矩作废（STALE 即删），
            # 三枚新 key 由 census 现算照抄，族、home、reason 一字未动。
            Cluster("2e3fccff9b1c", "宿主机状态（机器状态/机器配置/宿主状态；超管视图卡片）"),
            Cluster("3415ed002b8e", "书面同意（同意卡 待批/看/批/驳；危险参数改动的批准入口，仅管理员）"),
            Cluster("42a17383b6c5", "危险参数改动（R1/R2）签出的同意卡在这里批/驳/看：判定唯一住 safety_exe"),
            Cluster("e882f39e8078", "本机运行时事实（版本族/硬件/占用率）经 host_metrics 单一取数口现读，Mica 卡片出图；仅超管视图，读数"),
        ),
    ),
    ClusterFamily(
        name="help-double",
        home="plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
        reason="echo._HELP_ENTRIES 的接口说明与 capability_registry 声明同句双写；「一处变更处处跟随」未通，收编方向=帮助条目由声明源投影",
        members=(
            Cluster("2332cf866444", ".env（持久化开关，改后重启生效，无运行时命令）"),
            Cluster("2d65c20ec0d9", "meme_absorb（群图自动收库，无命令）"),
            Cluster("2eacd3f85b43", "/bot runtime set（配置型模块，无独立命令）"),
            Cluster("33d0c562e455", ".env（Telegram 适配器配置）"),
            Cluster("3f6a444edb3e", "matcher:admin_file_export（文件导出）"),
            Cluster("437ff9e07b09", ".env（模型注册表；/bot model 亦可视图）"),
            Cluster("590ebb163d3b", "matcher:IGNORE（空消息静默；未知命令形态回引导）"),
            Cluster("e59f05a2dd37", "bot.moegirl（二次元问句路由同归此能力）"),
            # S-BASE 基线席 2026-09-29 补账：亲密档（台账 #36 R 系列）帮助条目与声明面同句双写，
            # 同族判据（echo._HELP_ENTRIES ↔ capability_registry 声明），收编方向不变。
            Cluster("c555ddcb459f", "bot.chat（整句「亲密模式 开/深开/关」；关系档子命令见 /bot identity）"),
        ),
    ),
    # 2026-09-22 SEAT-S-AFFCOPY：affinity-tier-attitude 族 6 簇已收编（展示表与
    # relationship.familiar 改为由 character/affinity.py 的 _ATTITUDE_TIERS 投影），
    # 副本消失 ⇒ 按本门规矩同批删登记（留着就是假账）。锁：tests/test_affinity_tier_single_source.py
    ClusterFamily(
        name="contracts-schema",
        home="plugins/bot_unified_runtime/domains/core/contracts/request.py",
        reason="契约件字段说明与校验短语在 creation / billing_entities / event_store 重复；属开发者可见 schema 文案而非聊天话术，暂留原地但不许再加份（home=契约文案的目标单一出处）",
        members=(
            Cluster("152fc5646434", "出站必须已过 Review"),
            Cluster("1de0992afd05", "metric= 的单位必须是 ，收到"),
            Cluster("2b0133fa2993", "status= 时 value 必须为 null（未知/不适用不得携带数量）"),
            Cluster("58e354fc81f2", "token_status=measured 必须 provider 真报（token_p"),
            Cluster("aea729da2057", "必须带时区（UTC ISO8601）"),
            Cluster("bc98abc1a593", "expires_at 必须晚于 issued_at"),
            Cluster("fadfeb72a123", "status= 必须携带 value（未知不是 0）"),
        ),
    ),
    # 2026-09-22 统一波：ops-diag 族 3 簇已收编——诊断话术单一出处落在
    # plugins/bot_unified_runtime/domains/ops/smoke/diagnostics.py
    # （LLM_DIAGNOSTIC_* 三枚常量 + llm_diagnostic_messages()），
    # admin/debug 与 smoke 两处改为引用；簇随之消失，故整族摘牌（不是放宽判据）。
    ClusterFamily(
        name="one-off",
        home="",  # 本族逐条自带 home
        reason="单点跨文件同句：逐条登记 home=唯一该留的地方、note=为什么暂时允许副本存在"
        "（2026-09-22 SEAT-S-AFFCOPY 删 6c876cd3d292：友善档态度句的 relationship.py 副本改为投影，簇随之消失）",
        members=(
            Cluster("387057d25bf3", "必须提供非负整数 expected_version。", home="plugins/bot_unified_runtime/control_plane/config_store.py", note="CAS 版本校验话术三件同句；收编方向=错误目录枚举"),
            Cluster("48f6599d5ef9", "未配置任何凭据引用，无需检查。", home="plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py", note="凭据检查空态句两件同句；收编方向=凭据状态话术单一出处"),
            Cluster("54cda064ae32", "（ 次调用未计价：价格未配置，未计入账单）", home="plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py", note="未计价脚注在监控与卡片两处同句（账单口径）；收编方向=账单话术入 user_copy 池"),
            Cluster("582b56a43771", "配置控制服务尚未装配。", home="plugins/bot_unified_runtime/control_plane/api/v1.py", note="「服务尚未装配」三处同句；收编方向=错误目录枚举"),
            Cluster("589905369095", "BOT_TRANSPORT_TIMEOUT_SECONDS 必须是数字（秒）", home="plugins/bot_unified_runtime/config.py", note="装载期与 settings 热改面各写一条同型报错；收编方向=配置报错单一出处"),
            Cluster("97b15bcd48ac", "（板块页为前端渲染列表，机器人拿不到帖子列表；想看哪篇帖子，请把帖子链接发我）", home="plugins/bot_unified_runtime/domains/link_parse/parsers/types.py", note="米游社/森兰同句板块页降级提示；收编方向=parsers 共用常量件"),
            Cluster("9c0c8e25605a", "此操作需要 super_admin 权限。", home="plugins/bot_unified_runtime/control_plane/services.py", note="控制面四件各硬编码同一句 super_admin 拒绝；收编方向=control_plane 统一错误目录"),
            Cluster("a527c0a7e510", "没有权限操作该订阅。", home="plugins/bot_unified_runtime/domains/subscribe/capabilities/subscribe_v2.py", note="订阅两代能力件同句；该语义已在 user_copy.py 头 Q 组豁免登记（资源属主校验非管理员门禁），本门只钉份数"),
            Cluster("a9156348ece4", "要找的模型不存在。", home="plugins/bot_unified_runtime/domains/core/contracts/errors.py", note="「模型不存在」在控制面两件各写一份；收编方向=错误目录枚举"),
            Cluster("a91c81d1f1fb", "这件事超出了你现在的权限，先到这里为止了。", home="plugins/bot_unified_runtime/domains/core/contracts/errors.py", note="控制面复制了错误目录里的越权回执，两处措辞全等；收编方向=control_plane 改引 errors 真身"),
            Cluster("b34892eecd03", "对话历史未记录：输入含提示注入风险。", home="plugins/bot_unified_runtime/__init__.py", note="反注入回执句被 smoke 侧复制；__init__.py 属禁碰面，故登记而不要求改根文件"),
            Cluster("d31be0c054f4", "该配置尚无安全热更新路径，请修改 .env 并重启。", home="plugins/bot_unified_runtime/control_plane/config_store.py", note="热改拒绝话术两件同句（其中一件少句号＝标点已飘）；收编方向=错误目录枚举"),
            Cluster("da3cab50c19e", "LLM就绪：，ready_for_real_llm=", home="plugins/bot_unified_runtime/domains/ops/smoke/diagnostics.py", note="/bot status 与诊断件拼同一状态行前缀；收编方向=状态行单一构造口"),
            Cluster("e8a4dba1f095", "（该页面无法直接提取内容，点开链接查看）", home="plugins/bot_unified_runtime/domains/link_parse/parsers/types.py", note="三件解析器同句「无法直接提取内容」兜底；收编方向=parsers 共用常量件"),
            # ---- S-BASE 基线席 2026-09-29 逐簇补账（现算 sha256[:12] 由 census 输出照抄，勿手改 key）。
            # 归因：以下 15 簇全部为 ed802d3/近期提交之后的波次新增副本；多为在飞件，登记 note 逐枚
            # 写明「为什么暂时容得下」与收编方向；在飞件文案被改写时本登记即 STALE 转红，由页主跟办。
            Cluster("01b6c150e9d1", "job 形请求未过契约自验：", home="plugins/bot_unified_runtime/domains/creation/tts/engine_provider.py", note="image/tts 两枚引擎 provider 同句拒绝（契约自验失败）；两件同波新建、措辞零分叉，收编方向=creation 契约自验话术共用常量件"),
            Cluster("4bd85cb95be3", "非成功终态但未给出原因（不应发生：诚实说明缺失）", home="plugins/bot_unified_runtime/domains/creation/tts/engine_provider.py", note="同上一对 provider 的第二枚同句（诚实缺因兜底）；与上枚分开点名，防「一条糊两枚」，收编方向同上"),
            Cluster("16312d3d1b77", "邮件没有「群」这种对象：群名、群号、公告、精华、群主、成员名单这些格子在这里是空的——S", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="会话画像波（在飞件 conversation_profile.py，未跟踪）复制 group_info 邮件空态说明；⚠ 在飞件文案一改本条即虚设转红，页主按本门规矩重登记；收编方向=邮件空态共用常量件"),
            Cluster("27e6500e5971", "公告：接口这会儿没回应，拿不到（可能需要我有管理员身份）。", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="画像格复制群信息「接口没回应」诚实失败句（公告枚）；逐枚点名，收编方向=群信息失败话术单一出处"),
            Cluster("9b36a0fb7fc4", "精华：接口这会儿没回应，拿不到（可能需要我有管理员身份）。", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="同一话术族的精华枚（与公告枚同形不同字段），按「一条至多消费一簇」逐枚点名"),
            Cluster("7de8f7d0e9d9", "发件人昵称（From 显示名）：", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="画像侧沿用群信息邮件昵称字段标签措辞；字段标签同句属两读同一事实，收编方向=邮件字段标签共用常量"),
            Cluster("7ff6e0d73e0a", "我这儿还没有人说过话的记录——这不等于这屋里没人说过话，只是我这边没记下。", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="参与者读空诚实句被画像侧照抄（台账 #51「没检索禁写它没有」同源话术）；收编方向=缺席话术单一出处"),
            Cluster("95e441a6be45", "（这条记录的昵称与账号都没回）", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="同话术族的记录级兜底短括号句；逐枚点名，收编方向同上"),
            Cluster("2b6df43c6b22", "（用户发送了图片/表情包/视频，未附文字。）", home="plugins/bot_unified_runtime/__init__.py", note="合并波（在飞件 message_merge.py）复制摄取层空段占位句；__init__.py 属禁碰面，登记而不要求改根文件（b34892eecd03 同型判例）；⚠ 在飞件文案一改即转红，页主跟办"),
            Cluster("4ba06a0e2a41", "（用户发送了语音消息，未附文字。）", home="plugins/bot_unified_runtime/__init__.py", note="同上一对占位句的语音枚（摄取真身 vs 合并副本），按逐枚点名分列两条，不许一条糊两枚"),
            Cluster("7b3d4ce531a8", "占卜服务尚未装配（未配置持久化路径），先不假装能抽牌。", home="plugins/bot_unified_runtime/domains/divination/routes.py", note="控制面 api/divination.py 端点复制聊天侧真身的未装配拒绝句（台账 #47 真身合并波的残余）；收编方向=占卜未装配话术单一出处"),
            Cluster("db89b54acddd", "（娱乐参考口径见牌面本地解读；本端点当前固定返回 503。）", home="plugins/bot_unified_runtime/domains/divination/routes.py", note="同一对文件的第二枚同句（503 尾注），逐枚点名；收编方向同上"),
            Cluster("908c790cd78c", "宿主机卡未出图（渲染后端不可用），以上读数即全部结果。", home="plugins/bot_unified_runtime/domains/ops/capabilities/host_state.py", note="echo 命令面兜底支复制 host_state 真身渲染失败句（需求 5 波残余；台账 #55「失败→纯文本兜底」同源）；收编方向=卡片渲染失败话术单一出处"),
            Cluster("9458e559b539", "注意：写进去再读回来是 ，与批的 不一致（转换器改了形），已如实记账，不谎称一致。", home="plugins/bot_unified_runtime/domains/core/safety_exec/consent.py", note="settings_gate 复制 consent 的 roundtrip 不一致诚实记账句（同意门换代波，台账 #63）；收编方向=safety_exec 共用 roundtrip 警告"),
            Cluster("f9459fbd684c", "我自查的大概原因（推测）与建议", home="plugins/bot_unified_runtime/domains/ops/monitor/error_report.py", note="统一错误报告卡真身与 card_render/bridge 文本兜底同标签（台账 #62 卡面波，error_report 正被页主改写）；⚠ 在飞件文案一改即转红，页主跟办；收编方向=告警段落标签单一出处"),
            # 会话画像波（在飞件 conversation_profile.py）第三枚同句补账，同 16312d3d1b77/
            # 7ff6e0d73e0a 判例：真身住 group_info 的个性签名空态话术，画像侧照抄。
            Cluster("c7b8052ac91c", "接口回了空——多半是没设置，也可能没回，不替你断言。", home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py", note="画像格复制群信息「个性签名空态」诚实句（会话画像波残余，与同文件 27e6500e5971/9b36a0fb7fc4 同话术族）；收编方向=群信息失败与空态话术单一出处"),
        ),
    ),
)

# 簇数下限：低于此即认定扫描面塌陷（现值 81 只作下限，不作快照断言）。
_MIN_CLUSTER_FLOOR = 60


# ---------------------------------------------------------------------------
# 不变量求值（纯函数：注毒自证点名红在哪条，靠的就是这里）
# ---------------------------------------------------------------------------

NEW_CLUSTER = "NEW_CLUSTER"
STALE_REGISTRATION = "STALE_REGISTRATION"
REGISTRY_INTEGRITY = "REGISTRY_INTEGRITY"
SCAN_SCOPE_SANITY = "SCAN_SCOPE_SANITY"


def registered_clusters(registry: tuple[ClusterFamily, ...] = REGISTRY) -> dict[str, Cluster]:
    flat: dict[str, Cluster] = {}
    for family in registry:
        for member in family.members:
            flat[f"{member.key}|{family.name}"] = member
    return flat


def resolve_home(family: ClusterFamily, member: Cluster) -> str:
    return member.home or family.home


def integrity_problems(registry: tuple[ClusterFamily, ...] = REGISTRY) -> list[str]:
    """登记项自检：key 不重复、home 有落点且真实存在、reason/note 非空、sample 非空。"""
    problems: list[str] = []
    seen: set[str] = set()
    for family in registry:
        if not str(family.reason).strip():
            problems.append(f"族 {family.name} 缺 reason")
        for member in family.members:
            token = f"{family.name}/{member.key}"
            if len(member.key) != 12 or any(ch not in "0123456789abcdef" for ch in member.key):
                problems.append(f"{token} 的 key 形态非法（应为归一化文案 sha256[:12]）")
            if member.key in seen:
                problems.append(f"{token} key 重复登记")
            seen.add(member.key)
            if not str(member.sample).strip():
                problems.append(f"{token} 缺 sample（文案前缀）")
            home = resolve_home(family, member)
            if not str(home).strip():
                problems.append(f"{token} 缺 home：唯一该留的地方必须写出来")
            elif not (REPO_ROOT / home).exists():
                problems.append(f"{token} 的 home 指向不存在的文件：{home}")
            if not str(member.note or family.reason).strip():
                problems.append(f"{token} 缺 reason/note：副本必须写清为什么暂时容得下")
    return problems


def diff_clusters(
    detected_keys: set[str],
    registered_keys: set[str],
    cluster_floor: int = _MIN_CLUSTER_FLOOR,
) -> dict[str, list[str]]:
    """三条对账不变量 → 命中项列表（按不变量名分组，红在哪条一目了然）。"""
    result: dict[str, list[str]] = {NEW_CLUSTER: [], STALE_REGISTRATION: [], SCAN_SCOPE_SANITY: []}
    if len(detected_keys) < cluster_floor:
        result[SCAN_SCOPE_SANITY].append(
            f"检出簇数 {len(detected_keys)} < 下限 {cluster_floor}：扫描面或判据被削弱"
        )
    result[NEW_CLUSTER] = sorted(detected_keys - registered_keys)
    result[STALE_REGISTRATION] = sorted(registered_keys - detected_keys)
    return result


def detected_cluster_keys() -> dict[str, str]:
    """现树检出的簇：key → 文案前缀（供报错时点名）。"""
    return {cluster.key: cluster.render_sample(44) for cluster in census.cluster_units(census.scan_tree())}


# ---------------------------------------------------------------------------
# 门测试：现网必须全绿
# ---------------------------------------------------------------------------


def test_scan_scope_sanity() -> None:
    """扫描面自证：普查器在位、面没塌、判据没被偷偷放宽。"""
    assert CENSUS_PATH.exists()
    py_files = list(RUNTIME_PKG.rglob("*.py"))
    assert len(py_files) >= 400, f"扫描面异常收缩：{len(py_files)} 个 .py"
    assert census.CLUSTER_MIN_NORM_LEN >= 12, "入簇门槛不得低于登记时的 12 字（放宽=掏空本门）"
    assert census.SENTENCE_MIN_NORM_LEN >= 6
    assert (RUNTIME_PKG / "domains/chat_reply/capabilities/user_copy.py").exists(), (
        "文案池真身移位：登记面的 home 锚点须随迁，否则本门在扫一堆垫片"
    )


def test_registry_integrity() -> None:
    problems = integrity_problems()
    assert not problems, "登记面不合格（home/reason/key/sample）：\n" + "\n".join(problems)


def test_near_duplicate_clusters_are_exactly_registered() -> None:
    """主门：检出簇集合 == 登记簇集合（多一只红、少一只也红）。"""
    detected = detected_cluster_keys()
    registered = {member.key for member in registered_clusters().values()}
    verdict = diff_clusters(set(detected), registered)
    unregistered = verdict[NEW_CLUSTER]
    stale = verdict[STALE_REGISTRATION]
    assert not unregistered, (
        f"{NEW_CLUSTER}：出现未登记的文案近重复簇 {len(unregistered)} 个"
        "（要么收编成一份，要么逐簇登记 home+reason）：\n"
        + "\n".join(f"  {key} | {detected[key]}" for key in unregistered)
    )
    assert not stale, (
        f"{STALE_REGISTRATION}：登记面有 {len(stale)} 条已失效"
        "（簇已被收编或文案已改写，登记必须同步删除，否则本门是给未来留的假账）：\n"
        + "\n".join(f"  {key}" for key in stale)
    )


# ---------------------------------------------------------------------------
# 注毒自证：红必须落在指定的那条不变量上
# ---------------------------------------------------------------------------


def test_poison_new_cluster_reds_on_new_cluster_invariant() -> None:
    """合成两模块各放同一条文案 ⇒ 被抓，且红名指向 NEW_CLUSTER。"""
    text = "这条文案是本门自己注毒的样本，只活在测试里。"
    norm = census.normalize(text)
    units = [
        census.Unit("plugins/bot_unified_runtime/domains/ops/poison_a.py", 10, text, norm),
        census.Unit("plugins/bot_unified_runtime/domains/ops/poison_b.py", 20, text, norm),
    ]
    clusters = census.cluster_units(units)
    assert len(clusters) == 1, "两文件同句未成簇：判据已失效"
    poison_key = clusters[0].key
    detected = set(detected_cluster_keys()) | {poison_key}
    registered = {member.key for member in registered_clusters().values()}
    verdict = diff_clusters(detected, registered)
    assert verdict[NEW_CLUSTER] == [poison_key], (
        f"注毒未被 {NEW_CLUSTER} 抓到（实际：{verdict[NEW_CLUSTER]}）"
    )
    assert not verdict[STALE_REGISTRATION], "注毒不该动到已登记面"


def test_poison_registration_outlives_cluster_reds_on_stale_invariant() -> None:
    """登记的簇已被收编掉（树里不再检出）⇒ 红名指向 STALE_REGISTRATION 并点名该 key。"""
    detected = set(detected_cluster_keys())
    registered = {member.key for member in registered_clusters().values()}
    assert registered <= detected, "主门已红（登记 ⊄ 检出），本自证的前提不成立"
    victim = min(registered)
    verdict = diff_clusters(detected - {victim}, registered)
    assert verdict[STALE_REGISTRATION] == [victim], (
        f"簇被收编、登记未删，未被 {STALE_REGISTRATION} 抓到（实际：{verdict[STALE_REGISTRATION]}）"
    )
    assert not verdict[NEW_CLUSTER]


def test_poison_deleting_registration_reds_on_new_cluster_invariant() -> None:
    """反向对称：树里副本还在就把登记删了 ⇒ 红在 NEW_CLUSTER（登记不能靠删除来消化副本）。"""
    detected = set(detected_cluster_keys())
    registered = {member.key for member in registered_clusters().values()}
    victim = max(registered)
    shrunk = tuple(
        ClusterFamily(
            name=f.name,
            home=f.home,
            reason=f.reason,
            members=tuple(m for m in f.members if m.key != victim),
        )
        for f in REGISTRY
    )
    survivors = {member.key for member in registered_clusters(shrunk).values()}
    verdict = diff_clusters(detected, survivors)
    assert verdict[NEW_CLUSTER] == [victim], (
        f"删登记未被抓（实际：{verdict[NEW_CLUSTER]}）——登记面可以用删除来掏空，本门即假"
    )
    assert not verdict[STALE_REGISTRATION]


def test_poison_home_rot_reds_on_integrity_invariant() -> None:
    """home 指向不存在的文件 ⇒ 红名指向 REGISTRY_INTEGRITY。"""
    family = REGISTRY[-1]
    rotten = tuple(
        ClusterFamily(
            name=f.name,
            home=f.home,
            reason=f.reason,
            members=tuple(
                Cluster(m.key, m.sample, "plugins/bot_unified_runtime/no_such_home.py", m.note)
                if f.name == family.name
                else m
                for m in f.members
            ),
        )
        for f in REGISTRY
    )
    problems = integrity_problems(rotten)
    assert problems, "home 腐化未被 REGISTRY_INTEGRITY 抓到"
    assert any("no_such_home.py" in problem for problem in problems)


def test_poison_shrunken_scan_reds_on_scope_invariant() -> None:
    """扫描面塌陷（簇数骤降）⇒ 红名指向 SCAN_SCOPE_SANITY。"""
    verdict = diff_clusters({"0123456789ab"}, set(), cluster_floor=_MIN_CLUSTER_FLOOR)
    assert verdict[SCAN_SCOPE_SANITY], "扫描面塌陷未被点名"


@pytest.mark.parametrize(
    ("raw_a", "raw_b", "same"),
    [
        ("行情暂时拉不到，稍后再试。", "行情暂时拉不到，稍后再试。", True),
        # 全半角 + 标点差异 ⇒ 仍算同一条。
        ("提醒列表（第1页）", "提醒列表(第1页)。", True),
        # 变量名差异（占位符归一）⇒ 仍算同一条。
        ("要{action}，找管理员来操作。", "要{thing}，找管理员来操作。", True),
        # 语义不同 ⇒ 不许算同一条。
        ("要{action}，找管理员来操作。", "要{action}，找超管来操作。", False),
    ],
)
def test_normalization_equivalence_table(raw_a: str, raw_b: str, same: bool) -> None:
    """归一化判据的防假阳性/防假阴性对照表（改判据必须先看这张表）。"""
    equal = census.normalize(raw_a) == census.normalize(raw_b)
    assert equal is same, f"{raw_a!r} vs {raw_b!r}：归一化等值判定应为 {same}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
