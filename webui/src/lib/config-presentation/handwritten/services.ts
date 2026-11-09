// T1 手写层：语音合成 / 点歌 / 天气 / 金融行情 / 订阅与快报 / 日程与笔记 / 校园 / 紧急信息 / 卡片渲染。
import type { HandwrittenEntry } from '../types.ts';

export const SERVICES_HANDWRITTEN: Record<string, HandwrittenEntry> = {
  // ---------------------------------------------------------------- 语音合成
  BOT_TTS_ENABLED: {
    title: '语音合成总开关',
    kind: 'switch',
    desc:
      '开启→可以把文字念成语音发出来；关闭→所有语音相关功能静默。' +
      '合成要跑本地 GPT-SoVITS 服务，机器负载不低，低配机建议按需开。改完需重启。',
  },
  BOT_TTS_API_URL: {
    title: '合成服务地址',
    kind: 'text',
    desc:
      '本地合成服务的接口地址（通常指向本机的 GPT-SoVITS）。' +
      '服务没起或地址写错→每次合成超时，表现为「语音功能没反应」。改完需重启。',
  },
  BOT_TTS_PRESET: {
    title: '音色预设',
    kind: 'select',
    options: [
      { value: 'default', label: '默认音色' },
      { value: 'shorekeeper', label: '守岸人' },
    ],
    desc:
      '用哪套参考音色。换预设→整体声音变了，语速与情绪基线也跟着变。' +
      '预设名不存在时会退回第一组可用配置（并留一条告警）。改完需重启。',
  },
  BOT_TTS_REF_AUDIOS: {
    title: '参考音频清单',
    kind: 'code',
    desc:
      '音色克隆用的参考音频文件列表。加音频→可选音色变多；' +
      '文件缺失或格式不对→合成直接失败（这条链对输入很敏感）。改完需重启。',
  },
  BOT_TTS_MAX_CHARS: {
    title: '单次合成字数上限',
    kind: 'number',
    min: 0,
    max: 10000,
    step: 10,
    desc:
      '超过就不合成（或截断后合成，取决于下游）。调大→长句也能念，但合成时间明显变长；' +
      '调小→长回复直接放弃语音。改完需重启。',
  },
  BOT_TTS_TIMEOUT_SECONDS: {
    title: '合成超时（秒）',
    kind: 'number',
    min: 1,
    max: 600,
    step: 1,
    unit: '秒',
    desc:
      '单次合成最长等多久。调大→长文本有机会念完，但用户等很久；' +
      '调小→长句频繁超时，表现为「有时有语音有时没有」。改完需重启。',
  },
  BOT_TTS_SPEED_FACTOR: {
    title: '语速倍率',
    kind: 'number',
    min: 0.6,
    max: 1.65,
    step: 0.05,
    desc:
      '0.6 很慢很柔，1.0 正常，1.65 明显偏快。调慢→更有情绪但听着拖；' +
      '调快→利落但容易显得急躁。0.85 是「温柔但不拖」的位置。改完需重启。',
  },
  BOT_TTS_TEMPERATURE: {
    title: '合成温度',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '合成时的随机性。调低→音色稳定但平；调高→有起伏，也更容易出现怪音、破音。' +
      '0.9 已经偏高，再往上不稳。改完需重启。',
  },
  BOT_TTS_TOP_K: {
    title: '合成 Top-K',
    kind: 'number',
    min: 1,
    max: 100,
    step: 1,
    desc:
      '每步只在概率最高的 K 个候选里采样。调小→更稳更单调；调大→更多变，也更容易跑音。改完需重启。',
  },
  BOT_TTS_TOP_P: {
    title: '合成 Top-P',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '核采样阈值，与 Top-K 一起控制多样性。调低→保守稳定；调高→自由但可能失真。改完需重启。',
  },
  BOT_TTS_TEXT_LANG: {
    title: '合成文本语言',
    kind: 'select',
    options: [
      { value: 'zh', label: '中文' },
      { value: 'ja', label: '日文' },
      { value: 'en', label: '英文' },
      { value: 'auto', label: '自动判断' },
    ],
    desc:
      '告诉合成器按哪种语言念。选错→多音字读错、日文假名念成中文。' +
      '自动判断省事但偶尔判错，固定语言最稳。改完需重启。',
  },
  BOT_TTS_TEXT_SPLIT_METHOD: {
    title: '文本切分方式',
    kind: 'select',
    options: [
      { value: 'cut0', label: '不切' },
      { value: 'cut1', label: '四句一切' },
      { value: 'cut2', label: '两句一切' },
      { value: 'cut3', label: '一句一切' },
      { value: 'cut4', label: '按标点' },
      { value: 'cut5', label: '按标点与换行' },
    ],
    desc:
      '长文本怎么切段再合成。切得细→语气更自然、停顿更好，但合成次数多、更慢；' +
      '不切→一次念完，长句容易断气或糊在一起。改完需重启。',
  },
  BOT_TTS_CACHE_ENABLED: {
    title: '合成结果缓存',
    kind: 'switch',
    desc:
      '开启→相同文本直接复用上次音频，重复句子几乎零成本；' +
      '关闭→每次都重算，慢且吃 CPU。注意改音色参数后旧缓存不会自动失效。改完需重启。',
  },
  BOT_TTS_AUTO_REPLY_ENABLED: {
    title: '自动语音回复',
    kind: 'switch',
    desc:
      '开启→部分回复会自动配一条语音；关闭→只在被明确要求时才合成。' +
      '开启后每条命中消息都多一次合成，负载明显上升。改完需重启。',
  },
  BOT_TTS_AUTO_REPLY_PROBABILITY: {
    title: '自动语音概率',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '命中时真的转语音的比例。调高→大部分回复都带语音，很快会腻且吃 CPU；' +
      '调低→偶尔来一条，更像惊喜。改完需重启。',
  },
  BOT_TTS_AUTO_REPLY_MAX_CHARS: {
    title: '自动语音字数上限',
    kind: 'number',
    min: 0,
    max: 2000,
    step: 10,
    desc:
      '超过这个长度的回复不转语音（只发文字）。调大→长回复也念，等待变长；' +
      '调小→只有短句有语音。改完需重启。',
  },
  BOT_TTS_AUTO_REPLY_SCOPE: {
    title: '自动语音作用域',
    kind: 'select',
    options: [
      { value: 'group', label: '仅群聊' },
      { value: 'private', label: '仅私聊' },
      { value: 'both', label: '群聊与私聊' },
    ],
    desc:
      '哪些会话会自动出语音。群里语音很显眼、容易吵；私聊更合适。' +
      '两个都开→负载最高。改完需重启。',
  },

  // ---------------------------------------------------------------- 点歌
  BOT_MUSIC_ENABLED: {
    title: '点歌总开关',
    kind: 'switch',
    desc:
      '关闭后点歌指令不再响应，已下载的缓存与曲库保持不动，重新打开即可续用。' +
      '开启时仍受平台白名单与曲库目录约束：任一路径不可用就只会走另一路。改完需重启。',
  },
  BOT_MUSIC_MODE: {
    title: '点歌返回形态（运行时覆盖）',
    kind: 'text',
    desc:
      '纯运行时覆盖键：决定点歌返回「音频文件」还是「卡片 + 链接」等形态。' +
      '留空→回退 `BOT_MUSIC_DEFAULT_MODE`。这个键可热改，改完下一条点歌就按新形态出。',
  },
  BOT_MUSIC_DEFAULT_MODE: {
    title: '点歌默认形态',
    kind: 'text',
    desc:
      '没有运行时覆盖时用哪种返回形态。改这里影响所有会话；' +
      '写不认识的值→回落到代码内缺省。改完需重启。',
  },
  BOT_MUSIC_PLATFORMS: {
    title: '点歌平台白名单',
    kind: 'code',
    desc:
      '允许从哪些平台取歌（逗号分隔，全小写）。加平台→命中率上升；' +
      '留空→点歌整体不可用。平台越多，搜索越慢。改完需重启。',
  },
  BOT_MUSIC_DIR: {
    title: '曲库目录',
    kind: 'text',
    desc:
      '本地音频文件所在目录。指错→本地命中永远为空，只能走在线源（更慢且可能失败）。改完需重启。',
  },

  // ---------------------------------------------------------------- 天气
  BOT_WEATHER_ENABLED: {
    title: '天气总开关',
    kind: 'switch',
    desc:
      '关闭→天气与预警相关指令全部不响应。开启时走 NMC 主源、Open-Meteo 兜底，' +
      '地名必须能在码表里匹配到，否则会要求你说得更具体。改完需重启。',
  },
  BOT_WEATHER_TIMEOUT_SECONDS: {
    title: '天气请求超时（秒）',
    kind: 'number',
    min: 1,
    max: 60,
    step: 1,
    unit: '秒',
    desc:
      '单次请求最长等多久。调大→慢的时候还能出结果；调小→更容易触发兜底源切换，' +
      '表现为数据来源忽变。改完需重启。',
  },

  // ---------------------------------------------------------------- 金融行情
  BOT_MARKET_ENABLED: {
    title: '行情总开关',
    kind: 'switch',
    desc:
      '关闭→股指、大宗、债券、北向等卡片全部不出。开启时按多源交叉验证，' +
      '凑不满三个官方源的数据会显式标注缺口而不是硬出数。改完需重启。',
  },
  BOT_MARKET_CACHE_SECONDS: {
    title: '行情缓存（秒）',
    kind: 'number',
    min: 0,
    max: 3600,
    step: 5,
    unit: '秒',
    desc:
      '同一标的多久内复用上次结果。调大→快且省请求，但盘中数据会滞后；' +
      '调小→更实时，但容易被上游限流。改完需重启。',
  },
  BOT_MARKET_TIMEOUT_SECONDS: {
    title: '行情请求超时（秒）',
    kind: 'number',
    min: 1,
    max: 120,
    step: 1,
    unit: '秒',
    desc:
      '单个数据源最长等多久。调大→慢源也能回来，但整卡等待变长；' +
      '调小→更容易只凑到一两源，触发「数据不足」标注。改完需重启。',
  },
  BOT_STOCKS_ENABLED: {
    title: '个股行情',
    kind: 'switch',
    desc:
      '关闭→个股查询不出。开启后非上市公司**结构性没有价格字段**，' +
      '只会给公告口径的说明，不会编一个数字。改完需重启。',
  },
  BOT_FX_ENABLED: {
    title: '汇率',
    kind: 'switch',
    desc:
      '关闭→汇率查询不出。开启后无源币种会诚实标注「暂无数据」，' +
      '不会拿相近币种顶替。改完需重启。',
  },
  BOT_COMMODITIES_ENABLED: {
    title: '大宗商品与债券',
    kind: 'switch',
    desc: '关闭→这两类卡片不出。开启时按三源核对，超容差会标注分歧。改完需重启。',
  },
  BOT_NORTHBOUND_ENABLED: {
    title: '北向资金',
    kind: 'switch',
    desc:
      '开启→出北向成交额/笔数卡片。注意净买入已停止披露，' +
      '这里**只报成交额与笔数口径**，绝不会编一个净流入数字。改完需重启。',
  },

  // ---------------------------------------------------------------- 订阅与快报
  BOT_SUBSCRIBE_ENABLED: {
    title: '订阅总开关',
    kind: 'switch',
    desc:
      '关闭→所有 RSS/事件订阅停止拉取与推送。已订阅列表保留。' +
      '开启后按各自的周期轮询，源多时会有持续的网络与解析开销。改完需重启。',
  },
  BOT_SUBSCRIPTION_SEEN_RETENTION_DAYS: {
    title: '已读记录保留（天）',
    kind: 'number',
    min: 1,
    max: 3650,
    step: 1,
    unit: '天',
    desc:
      '记住「这条推过了」多久。调大→不会重复推送老条目，但库变大；' +
      '调小→超过保留期的老文章可能被当成新内容再推一次。改完需重启。',
  },
  BOT_SUBSCRIPTION_OUTBOX_MAX_ATTEMPTS: {
    title: '推送最大尝试次数',
    kind: 'number',
    min: 1,
    max: 20,
    step: 1,
    desc:
      '一条推送失败后最多重试几次。调大→网络抖动时更容易送达，但坏地址会占用很久；' +
      '调小→失败得快，可能漏推。改完需重启。',
  },
  BOT_SUBSCRIPTION_OUTBOX_SENT_RETENTION_DAYS: {
    title: '已发送记录保留（天）',
    kind: 'number',
    min: 1,
    max: 3650,
    step: 1,
    unit: '天',
    desc:
      '发件箱里成功记录的保留时长，只影响审计与去重，不影响推送本身。' +
      '调大→可回溯更久；调小→省空间但查不到久远的推送记录。改完需重启。',
  },

  // ---------------------------------------------------------------- 日程与笔记
  BOT_SCHEDULE_ENABLED: {
    title: '日程总开关',
    kind: 'switch',
    desc:
      '关闭→提醒、日程、课表相关指令不响应，已排的提醒也不会触发。' +
      '数据保留在库里。改完需重启。',
  },
  BOT_SCHEDULE_DB_PATH: {
    title: '日程数据库路径',
    kind: 'text',
    desc:
      '日程与提醒的落库位置。改路径→旧数据不会自动搬，等于从空库开始。' +
      '指到不可写目录→所有创建操作失败。改完需重启。',
  },
  BOT_SCHEDULE_LLM_DRAFT_ENABLED: {
    title: '日程草稿自动解析',
    kind: 'switch',
    desc:
      '开启→「明天下午三点提醒我…」这类自然语言由模型解析成结构化日程；' +
      '关闭→只认固定格式。开启后每次创建多一次模型调用。改完需重启。',
  },
  BOT_REMINDER_LLM_EXTRACT_ENABLED: {
    title: '提醒自动抽取',
    kind: 'switch',
    desc:
      '开启→聊天里随口提到的时间点会被抽成提醒候选（通常还要你确认）；' +
      '关闭→只在你明确要求时才建提醒。开启后每轮多一次抽取调用。改完需重启。',
  },
  BOT_NOTES_ENABLED: {
    title: '笔记与备忘录',
    kind: 'switch',
    desc:
      '关闭→笔记与备忘录相关指令不响应，已有笔记原样保留在库里，重新打开即可读回。' +
      '关闭期间不写入也不淘汰，所以不会因为停用而丢内容。改完需重启。',
  },
  BOT_NOTES_DB_PATH: {
    title: '笔记数据库路径',
    kind: 'text',
    desc:
      '笔记落库位置。改路径→旧笔记不会自动搬。指到不可写目录→创建全部失败。改完需重启。',
  },
  BOT_NOTES_MAX_PER_CHAT: {
    title: '单会话笔记条数上限',
    kind: 'number',
    min: 0,
    max: 100000,
    step: 10,
    desc:
      '每个会话最多存多少条。超了会拒绝新建（或按策略淘汰最旧）。' +
      '调大→能记很多；调小→很快满，开始拒绝。改完需重启。',
  },
  BOT_TIME_SYNC_ENABLED: {
    title: '联网授时',
    kind: 'switch',
    desc:
      '开启→定时校准系统时间，避免提醒时间整体漂移；关闭→用系统钟，' +
      '系统时间不准时所有定时都会偏。改完需重启。',
  },
  BOT_TIME_SYNC_HTTP_URL: {
    title: '授时 HTTP 源',
    kind: 'text',
    desc:
      'NTP 被网络拦截时的 HTTPS 兜底源。地址失效→这一路静默失败，' +
      '仍会尝试多源互证再回落系统钟。改完需重启。',
  },
  BOT_TIME_SYNC_MAX_DRIFT_MS: {
    title: '允许的最大漂移（毫秒）',
    kind: 'number',
    min: 1,
    max: 600000,
    step: 50,
    unit: 'ms',
    desc:
      '多源校时的簇直径超过它就不采信，直接回退系统钟。' +
      '调大→更容易采信（但可能采到错的时间）；调小→经常不采信，授时形同虚设。改完需重启。',
  },

  // ---------------------------------------------------------------- 校园
  BOT_CAMPUS_ENABLED: {
    title: '校园通知监听',
    kind: 'switch',
    desc:
      '开启→监听校园来源的新通知并转发到指定对象。' +
      '这是**纯监听**：绝不会向学校群发任何消息。三重来源门任一为空则整链关闭。改完需重启。',
  },
  BOT_CAMPUS_GROUP_WHITELIST: {
    title: '校园监听群白名单',
    kind: 'code',
    desc:
      '从哪些群抓校园通知。加群→来源变多；留空→整条链关闭（不会猜群）。' +
      '注意这里只决定「听哪里」，不决定「发哪里」。改完需重启。',
  },
  BOT_CAMPUS_SELF_IDS: {
    title: '校园来源自身账号',
    kind: 'code',
    desc:
      '把哪些账号视为校园通知的发布者。名单不准→要么漏掉通知，要么把闲聊当通知转发。改完需重启。',
  },

  // ---------------------------------------------------------------- 紧急信息
  BOT_EMERGENCY_INFO_ENABLED: {
    title: '紧急信息订阅',
    kind: 'switch',
    desc:
      '开启→订阅紧急事件并按级别推送（P0 最高）。只认事件自带的群号/本人号，' +
      '不会推测收件人。关闭→整条链静默。改完需重启。',
  },

  // ---------------------------------------------------------------- 卡片渲染
  BOT_RENDER_MAX_CONCURRENCY: {
    title: '渲染并发上限',
    kind: 'number',
    min: 1,
    max: 32,
    step: 1,
    desc:
      '同时最多渲染几张卡片。调大→高峰不排队，但内存与 CPU 飙升（2C2G 机器很容易被拖死）；' +
      '调小→排队，用户等待变长。2C2G 建议 2–3。改完需重启。',
  },
  BOT_RENDER_WAIT_BUDGET_MS: {
    title: '渲染等待预算（毫秒）',
    kind: 'number',
    min: 100,
    max: 60000,
    step: 100,
    unit: 'ms',
    desc:
      '为出图最多等多久，超时就直接发纯文本兜底（不会没反应）。' +
      '调大→更可能出图，但慢的时候用户干等；调小→经常降级成文字，稳定但不够好看。改完需重启。',
  },
};
