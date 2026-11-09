// T1 手写层：联网检索 / 多模态与媒体 / 表情与贴纸 / 内容解析。
import type { HandwrittenEntry } from '../types.ts';

export const CONTENT_HANDWRITTEN: Record<string, HandwrittenEntry> = {
  // ---------------------------------------------------------------- 联网检索
  BOT_WEB_SEARCH_ENABLED: {
    title: '联网检索总开关',
    kind: 'switch',
    desc:
      '开启→遇到时效性问题（新闻、价格、汇率、赛事）会去搜；世界观与人格问题永远只走本地知识。' +
      '关闭→完全不联网，速度快、零外部依赖，但问「今天…」类问题只能说不知道。这个键可热改。',
  },
  BOT_WEB_SEARCH_PROVIDER: {
    title: '检索供应商',
    kind: 'select',
    options: [
      { value: 'tavily', label: 'Tavily' },
      { value: 'exa', label: 'Exa' },
      { value: 'bing', label: 'Bing' },
      { value: 'duckduckgo', label: 'DuckDuckGo' },
    ],
    desc:
      '主检索源。换源→结果风格与覆盖差异很大（有的偏英文、有的中文好）。' +
      '这个键在装配期读取，改完必须重启；运行中热改不生效。',
  },
  BOT_WEB_SEARCH_FALLBACK_PROVIDERS: {
    title: '检索兜底链',
    kind: 'code',
    desc:
      '主源失败时按顺序尝试的备用源。加源→不容易全挂，但失败时会多等几跳；' +
      '留空→主源挂了这轮就不搜了（通常会诚实说没查到）。改完需重启。',
  },
  BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD: {
    title: '本地知识够用阈值',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '本地知识相关度高于它就不搜。调高（0.8）→很爱联网，信息新但慢且贵；' +
      '调低（0.3）→几乎不搜，容易拿旧知识答新问题。' +
      '注意它只决定「要不要补搜」，总闸仍是联网检索开关。这个键可热改。',
  },
  BOT_WEB_SEARCH_CONFIDENCE_FLOOR: {
    title: '强制补搜底线',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '安全阀：本地知识近乎空白时无条件补搜一次，不受上面阈值影响。' +
      '调高→空白时更容易补搜，防止把「不知道」当成「不用搜」；' +
      '调低→省调用，但冷门问题会硬答。这个键可热改。',
  },
  BOT_WEB_SEARCH_MAX_RESULTS: {
    title: '单次检索结果条数',
    kind: 'number',
    min: 1,
    max: 50,
    step: 1,
    desc:
      '一次搜索取几条结果。调大→信息更全，但塞进上下文后成本上升、噪声也变多；' +
      '调小→快而精，但容易漏掉关键那条。改完需重启。',
  },
  BOT_WEB_SEARCH_TIMEOUT_SECONDS: {
    title: '检索超时（秒）',
    kind: 'number',
    min: 1,
    max: 120,
    step: 1,
    unit: '秒',
    desc:
      '单次检索最长等多久，超时按「没查到」处理。调大→慢源也能出结果，但用户等待变长；' +
      '调小→响应快，但经常在快回来时被掐断。改完需重启。',
  },
  BOT_WEB_SEARCH_ADMIN_NOTICE: {
    title: '管理员可见检索提示',
    kind: 'switch',
    desc:
      '开启→有真实结果链接时，在管理员私聊里附一句「这次联网了」和来源；' +
      '普通用户看不到。排查「她到底有没有联网」时很有用。这个键可热改。',
  },
  BOT_SEARCH_ACG_ENABLED: {
    title: 'ACG 竖源检索',
    kind: 'switch',
    desc:
      '命中二次元意图（番剧、漫画、B 站梗、二次元游戏）时，额外并发查几个垂直站。' +
      '开启→这类问题答得准很多；关闭→走通用搜索，经常搜不到条目页。这个键可热改。',
  },
  BOT_SEARCH_ACG_BANGUMI_ENABLED: {
    title: 'Bangumi 竖源',
    kind: 'switch',
    desc:
      '查番剧条目元数据与放送日期。开启→「这部番什么时候播」能答准；' +
      '关闭→少一路请求。无 key，但有限流。这个键可热改。',
  },
  BOT_SEARCH_ACG_MOEGIRL_ENABLED: {
    title: '萌娘百科竖源',
    kind: 'switch',
    desc:
      '查角色/梗的百科条目。开启→梗与角色背景准确；' +
      '主站有 WAF，被拦时会诚实降级为空（不会编）。这个键可热改。',
  },
  BOT_SEARCH_ACG_BILIBILI_ENABLED: {
    title: 'B 站竖源',
    kind: 'switch',
    desc:
      '查 B 站公开视频，带发布时间作为时效信号。开启→能答「最近 B 站上…」；' +
      '无 cookie 时常见 412 风控，会降级为空。这个键可热改。',
  },
  BOT_SEARCH_ACG_TIMEOUT_SECONDS: {
    title: '竖源单路超时（秒）',
    kind: 'number',
    min: 1,
    max: 30,
    step: 0.5,
    unit: '秒',
    desc:
      '每个竖源最长等多久。多路是并发的，所以整体耗时约等于最慢那一路。' +
      '调大→慢站也能等到；调小→总有一路被掐，结果变少。这个键可热改。',
  },
  BOT_SEARCH_ACG_MAX_PER_SOURCE: {
    title: '单竖源结果条数',
    kind: 'number',
    min: 1,
    max: 20,
    step: 1,
    desc:
      '每个竖源取几条。调大→候选更全，但上下文里同质内容变多；' +
      '调小→只留最相关的。这个键可热改。',
  },

  // ---------------------------------------------------------------- 多模态与媒体
  BOT_VISION_ENABLED: {
    title: '图片识别',
    kind: 'switch',
    desc:
      '开启→聊天里发的图/表情会被识别成文字描述；关闭→只当「一张图」处理。' +
      '开启后每条带图消息都多一次模型调用（成本与延迟都涨）。这个键可热改。',
  },
  BOT_VISION_MODE: {
    title: '识别模式',
    kind: 'select',
    options: [
      { value: 'direct', label: '直连主模型', desc: '主模型本身支持读图，省一层调用' },
      { value: 'proxy', label: '转专用视觉模型', desc: '先描述再交给主模型' },
    ],
    desc:
      '直连最快最省，但要求主模型本身是多模态；主模型不支持时用直连会直接失败。' +
      '转专用模型兼容性好，但多一跳、慢一点。这个键可热改。',
  },
  BOT_VISION_MODEL_REGISTRY: {
    title: '视觉模型注册表',
    kind: 'code',
    desc:
      '视觉模型 id → 渠道配置的对照表，JSON 对象。漏配→识别直接降级为「看不到图」；' +
      '配错地址→每次带图消息都超时。改完需重启。',
  },
  BOT_ASR_ENABLED: {
    title: '语音转写',
    kind: 'switch',
    desc:
      '开启→语音消息先转成文字再理解；关闭→语音当「一条语音」处理，内容全丢。' +
      '开启后每条语音多一次转写调用。这个键可热改。',
  },
  BOT_VIDEO_UNDERSTANDING_ENABLED: {
    title: '视频理解',
    kind: 'switch',
    desc:
      '开启→视频抽帧+音轨+字幕，做结构化理解；关闭→走旧的抽帧摘要，开销小但粗。' +
      '开启后长视频的等待时间与成本都会明显上升。这个键可热改。',
  },
  BOT_VIDEO_MAX_FRAMES: {
    title: '视频抽帧上限',
    kind: 'number',
    min: 1,
    max: 64,
    step: 1,
    unit: '帧',
    desc:
      '一个视频最多抽几帧送给模型。调大→动作/画面变化捕捉更全，但成本和延迟线性上涨；' +
      '调小→只看到几个瞬间，容易答错情节。改完需重启。',
  },
  BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE: {
    title: '有字幕就跳过转写',
    kind: 'switch',
    desc:
      '开启→视频自带字幕时直接用字幕，不再跑语音识别（省一次调用）；' +
      '关闭→两者都做，信息更全但更慢。字幕质量差时关掉更准。改完需重启。',
  },
  BOT_VIDEO_DEEP_ENABLED: {
    title: '视频深度分析',
    kind: 'switch',
    desc:
      '开启→对视频做更细的分段理解（多轮问答式）；关闭→只出一段摘要。' +
      '深度分析很贵很慢，适合用户明确要求「讲讲这个视频」时。改完需重启。',
  },
  BOT_VIDEO_DEEP_COOLDOWN_SECONDS: {
    title: '深度分析冷却（秒）',
    kind: 'number',
    min: 0,
    max: 86400,
    step: 60,
    unit: '秒',
    desc:
      '同一个会话两次深度分析之间的最小间隔。调大→防止有人连发视频把额度烧光；' +
      '调小→响应更快，但成本不可控。改完需重启。',
  },
  BOT_CONTENT_VIDEO_AUTO_SEND: {
    title: '视频自动下载发送',
    kind: 'switch',
    desc:
      '解析器给出视频直链时自动下载并随卡片发出。开启→体验完整；' +
      '关闭→只给下载提示。注意这会让单条消息的流量与磁盘占用明显上升。改完需重启。',
  },
  BOT_MEDIA_ARCHIVE_ENABLED: {
    title: '媒体归档',
    kind: 'switch',
    desc:
      '开启→收到的图片/视频/文件按规则存进归档目录，可回溯；' +
      '关闭→不落盘，省空间也不留痕。开启前先确认磁盘余量。改完需重启。',
  },
  BOT_MEDIA_ARCHIVE_DIR: {
    title: '归档目录',
    kind: 'text',
    desc:
      '媒体文件落到哪个目录。相对路径按运行数据根解析。' +
      '指到不存在的盘或只读目录→每条归档都失败（日志会报错，消息本身照常）。改完需重启。',
  },
  BOT_MEDIA_ARCHIVE_MAX_FILE_MB: {
    title: '单文件归档上限（MB）',
    kind: 'number',
    min: 1,
    max: 4096,
    step: 1,
    unit: 'MB',
    desc:
      '超过这个大小的文件不归档。调大→能存大视频，但磁盘消耗快；' +
      '调小→大文件被跳过，回看时会缺。改完需重启。',
  },
  BOT_MEDIA_ARCHIVE_DAILY_LIMIT: {
    title: '归档每日条数上限',
    kind: 'number',
    min: 0,
    max: 100000,
    step: 10,
    desc:
      '一天最多归档多少条，防止被刷爆磁盘。0＝不限（不建议）。' +
      '调小→活跃群很快触顶，后面全丢。改完需重启。',
  },
  BOT_MEDIA_ARCHIVE_MIN_ROLE: {
    title: '谁能触发归档',
    kind: 'select',
    options: [
      { value: 'user', label: '所有人' },
      { value: 'admin', label: '管理员及以上' },
      { value: 'super_admin', label: '仅超级管理员' },
    ],
    desc:
      '最低角色门槛。设成所有人→群里任何图都会被存（注意隐私）；' +
      '设成仅超管→最保守，但普通用户发的素材就不入库了。改完需重启。',
  },

  // ---------------------------------------------------------------- 表情与贴纸
  BOT_MEME_SEARCH_ENABLED: {
    title: '表情搜索',
    kind: 'switch',
    desc:
      '开启→回复时可以去表情库找一张贴切的表情发出来；关闭→纯文字。' +
      '这个键可热改，是贴表情相关能力的总闸之一。',
  },
  BOT_MEME_LIBRARY_ENABLED: {
    title: '表情库收库',
    kind: 'switch',
    desc:
      '开启→监听群里的图，异步下载、去重后入库，之后可以随机发；' +
      '关闭→不发也不收。开启前务必看下面几个收库守卫，否则会把一堆无关图存进来。改完需重启。',
  },
  BOT_MEME_LIBRARY_DIR: {
    title: '表情库目录',
    kind: 'text',
    desc:
      '图片库落盘位置。与「贴纸目录」是两片不同的目录，混用会导致入库永远走逃逸分支。' +
      '换目录→旧图不会自动搬，等于从零开始。改完需重启。',
  },
  BOT_MEME_LIBRARY_MIN_FILE_KB: {
    title: '收库字节下限（KB）',
    kind: 'number',
    min: 0,
    max: 10240,
    step: 10,
    unit: 'KB',
    desc:
      '小于这个大小的图不收。调大→只留真贴纸，图标/缩略图被挡；' +
      '调小→连小图标都进库，之后随机发出来会显得莫名其妙。改完需重启。',
  },
  BOT_MEME_LIBRARY_MIN_SIDE: {
    title: '收库短边下限（像素）',
    kind: 'number',
    min: 0,
    max: 4096,
    step: 50,
    unit: 'px',
    desc:
      '短边小于这个像素的图不收。调大→只留清晰大图，但很多真表情会被挡；' +
      '调小→低清图也进库，发出来糊。改完需重启。',
  },
  BOT_MEME_LIBRARY_MAX_FILES: {
    title: '表情库容量上限',
    kind: 'number',
    min: 0,
    max: 1000000,
    step: 100,
    unit: '张',
    desc:
      '库内最多存多少张。超了会按策略裁剪。调大→素材更丰富，但检索变慢、占盘；' +
      '调小→很快开始淘汰旧图，本命贴纸受单独保护。改完需重启。',
  },
  BOT_MEME_LIBRARY_VLM_ENABLED: {
    title: 'VLM 打标',
    kind: 'switch',
    desc:
      '开启→入库时让视觉模型给每张图打标签并评 NSFW 分，之后能按语义选图；' +
      '关闭→只按文件名/哈希索引，选图基本靠运气。开启后收库变慢且花钱。改完需重启。',
  },
  BOT_MEME_RELEVANCE_MIN: {
    title: '选图相关性地板',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '合格分低于它就宁可不发。调高→只发很贴切的表情，经常「找不到合适的」；' +
      '调低→几乎总能发一张，但容易图文不符。0.35 是「宁可少发也别乱发」的位置。改完需重启。',
  },
  BOT_MEME_STICKER_SCOPE_MODE: {
    title: '贴纸去重作用域',
    kind: 'select',
    options: [
      { value: 'global', label: '全局', desc: '本机发过就不再发' },
      { value: 'session', label: '按会话', desc: '每个群/私聊各记一本账' },
    ],
    desc:
      '全局→同一张绝不发第二次，长期会「无图可用」；' +
      '按会话→不同群可以重复，新鲜感更久但同一群里仍不重复。改完需重启。',
  },
  BOT_RANDPIC_ENABLED: {
    title: '随机图',
    kind: 'switch',
    desc:
      '开启→命中触发词时从本地目录随机发一张图；关闭→不响应。' +
      '只读配置里的目录清单，不会自己找图。改完需重启。',
  },
  BOT_RANDPIC_DIRS: {
    title: '随机图目录',
    kind: 'code',
    desc:
      '图片所在的目录清单（JSON 数组）。加目录→素材变多；' +
      '目录写错或为空→功能静默不可用（不会报错，只是永远没图）。改完需重启。',
  },
  BOT_RANDPIC_TRIGGER_WORDS: {
    title: '随机图触发词',
    kind: 'code',
    desc:
      '命中这些词就发图。加词→更容易触发，但太通用的词会在正常对话里频繁插图；' +
      '删词→更难触发。逗号分隔。改完需重启。',
  },
  BOT_RANDPIC_MIN_SIDE: {
    title: '随机图短边下限（像素）',
    kind: 'number',
    min: 0,
    max: 4096,
    step: 50,
    unit: 'px',
    desc:
      '太小的图不参与随机。调大→只发清晰图；调小→可能发出糊图或缩略图。改完需重启。',
  },
  BOT_REACTIONS_ENABLED: {
    title: '主动贴表情',
    kind: 'switch',
    desc:
      '开启→她会在合适时机给消息贴一个表情回应（不占文字消息）；关闭→完全不贴。' +
      '注意私聊没有贴表情通道，这条只在群里生效。改完需重启。',
  },
  BOT_REACTIONS_PROBABILITY: {
    title: '贴表情概率',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '每条消息被贴表情的概率。调高→满屏表情，很快就腻；' +
      '调低→偶尔来一下，更像真人。改完需重启。',
  },
  BOT_REACTIONS_COOLDOWN_SECONDS: {
    title: '贴表情冷却（秒）',
    kind: 'number',
    min: 0,
    max: 86400,
    step: 10,
    unit: '秒',
    desc:
      '同一个会话两次贴表情的最小间隔。调大→不会连续贴，但热聊时贴不上；' +
      '调小→反应及时，也更容易刷。改完需重启。',
  },
  BOT_REACTIONS_MAX_PER_HOUR: {
    title: '每小时贴表情上限',
    kind: 'number',
    min: 0,
    max: 1000,
    step: 1,
    desc:
      '一小时内最多贴几次。0＝不贴。调大→存在感强；调小→克制。改完需重启。',
  },
  BOT_REACTIONS_MEME_ENABLED: {
    title: '表情贴纸联动',
    kind: 'switch',
    desc:
      '开启→贴表情时会从表情库里挑一张更贴切的大图（贴纸回应）；关闭→只贴系统小表情。' +
      '联动更生动，但也更显眼、更容易被当成刷屏。改完需重启。',
  },
  BOT_REACTIONS_MEME_PROBABILITY: {
    title: '贴纸联动概率',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '贴表情时改用大贴纸的比例。调高→几乎每次都发图，群里很吵；调低→偶尔一张，惊喜感更强。改完需重启。',
  },

  // ---------------------------------------------------------------- 内容解析
  BOT_CONTENT_PARSE_ENABLED: {
    title: '链接解析',
    kind: 'switch',
    desc:
      '开启→消息里的链接会被抓取并总结成一段话；关闭→原样留着链接。' +
      '开启后每条带链接消息都会触发一次抓取（慢且可能被目标站拦）。改完需重启。',
  },
  BOT_CONTENT_PARSE_PLATFORMS: {
    title: '解析平台白名单',
    kind: 'code',
    desc:
      '只解析这些平台的链接（逗号分隔，全小写）。加平台→覆盖更广；' +
      '留空→不解析任何平台（等于关掉链接解析）。改完需重启。',
  },
  BOT_CONTENT_ROUTE_ENABLED: {
    title: '内容路由',
    kind: 'switch',
    desc:
      '开启→按消息内容判定走普通档还是亲密档，并可能切到专用模型；' +
      '关闭→全部走默认模型与默认语气。改完需重启。',
  },
  BOT_CONTENT_ROUTE_MODEL: {
    title: '内容路由专用模型',
    kind: 'text',
    desc:
      '命中亲密档时改用哪个模型。换强模型→描写更细，成本更高；' +
      '留空→不切模型，只改语气。改完需重启。',
  },
  BOT_CONTENT_ROUTE_NORMAL_THRESHOLD: {
    title: '普通档判定阈值',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '内容信号超过它才进普通档路由。调高→更难触发，路由基本不生效；' +
      '调低→几乎每条都触发，可能把日常对话也判成需要特殊处理。改完需重启。',
  },
  BOT_CONTENT_ROUTE_INTIMATE_THRESHOLD: {
    title: '亲密档判定阈值',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '超过它才进亲密档（还会叠加上好感度门与授予面）。' +
      '调高→几乎进不去；调低→容易误判，日常对话被当成亲密语境，观感很怪。改完需重启。',
  },
  BOT_COOKIE_EXPIRY_REMINDER_ENABLED: {
    title: 'Cookie 到期提醒',
    kind: 'switch',
    desc:
      '开启→解析用的 Cookie 快过期时提前通知管理员，避免某平台突然解析不了；' +
      '关闭→到期后表现为「该平台链接解析失败」，得自己发现。改完需重启。',
  },
};
