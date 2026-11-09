// T1 手写层：好感度与情绪 / 记忆与知识 / 戳一戳 / 群聊与共享 / 限流与安静时段。
import type { HandwrittenEntry } from '../types.ts';

export const SOCIAL_HANDWRITTEN: Record<string, HandwrittenEntry> = {
  // ---------------------------------------------------------------- 好感度与情绪
  BOT_AFFINITY_ENABLED: {
    title: '好感度总开关',
    kind: 'switch',
    desc:
      '关闭后不再累计/读取好感度，所有档位相关行为（亲密度语气、称呼变化、亲密内容门）一起失效。' +
      '数据不会丢，重新打开即可续上。调试人格时关掉它能让输出更可预测。改完需重启。',
  },
  BOT_AFFINITY_V7_ENABLED: {
    title: '好感度 v7 算法',
    kind: 'switch',
    desc:
      '上一代好感度模型的总闸。开启→按 v7 规则计分；关闭→用更早的简单加减。' +
      '两代算法混开会让同一用户在不同路径下拿到不同分数，除迁移期外不建议同时开。改完需重启。',
  },
  BOT_AFFINITY_V8_ENABLED: {
    title: '好感度 v8 算法',
    kind: 'switch',
    desc:
      '当前主推的连续档模型（无跳变、有半衰回归）。开启→长期不互动会缓慢回落，互动越多越稳；' +
      '关闭→分数只增不减，久不联系的人也停在最高档。改完需重启。',
  },
  BOT_AFFINITY_V8_AMBIENT_HALFLIFE_DAYS: {
    title: '好感度半衰期（天）',
    kind: 'number',
    min: 1,
    max: 365,
    step: 1,
    unit: '天',
    desc:
      '多久不互动，好感度回落到一半。调大→关系很「耐久」，冷淡很久也不掉档；' +
      '调小→几天不说话就明显生分，更像真实关系但可能让人觉得翻脸快。' +
      '28 天是「一个月不聊还认得你」的折中。改完需重启。',
  },
  BOT_AFFINITY_GOODWILL_BAND_MIN: {
    title: '善意区间下限',
    kind: 'number',
    min: 0,
    max: 10,
    step: 0.1,
    desc:
      '进入「善意」语气的分数下界。调低→更早开始客气，但显得廉价；' +
      '调高→要积累很久才变温柔，早期互动会偏冷淡。必须小于上限，否则区间为空。改完需重启。',
  },
  BOT_AFFINITY_GOODWILL_BAND_MAX: {
    title: '善意区间上限',
    kind: 'number',
    min: 0,
    max: 10,
    step: 0.1,
    desc:
      '「善意」语气的分数上界，超过就进入更亲近的档。调大→善意期拖得很长，' +
      '升级变慢；调小→很快越过去，档位跳得快、缺少过渡。改完需重启。',
  },
  BOT_MOOD_ENABLED: {
    title: '心情双轴',
    kind: 'switch',
    desc:
      '开启→她的情绪会在「愉快—烦躁」与「亲近—疏离」两轴上漂移，并影响开火概率、表情档和语气；' +
      '关闭→语气恒定，行为可预测但少了活人感。改完需重启。',
  },
  BOT_BOND_ENABLED: {
    title: '羁绊系统',
    kind: 'switch',
    desc:
      '开启→记录长期共同经历（一起做过的事），并在对话里偶尔提起；' +
      '关闭→只记事实不记关系，回复里不会出现「上次我们…」这类呼应。改完需重启。',
  },

  // ---------------------------------------------------------------- 记忆与知识
  BOT_MEMORY_ENABLED: {
    title: '长期记忆总开关',
    kind: 'switch',
    desc:
      '关闭后不再写入/读取长期记忆，她会「忘了」之前聊过的事，但对话本身照常。' +
      '已有记忆不会被删，重新打开即可恢复。改完需重启。',
  },
  BOT_MEMORY_BUS_ENABLED: {
    title: '记忆总线',
    kind: 'switch',
    desc:
      '开启→各能力产出的记忆片段统一走总线归并、去重、定归属；' +
      '关闭→各能力各自写自己的，容易重复记同一件事，也容易出现「把别人的经历记成自己的」。' +
      '默认关，开启前建议先确认归属判定正常。改完需重启。',
  },
  BOT_MEMORY_MAX_ITEMS: {
    title: '记忆条数上限',
    kind: 'number',
    min: 0,
    max: 100000,
    step: 100,
    unit: '条',
    desc:
      '单个用户最多保留多少条记忆。调大→记得更久更细，但检索变慢、更容易翻出无关旧事；' +
      '调小→只留最近最重要的，久远的事会消失。改完需重启。',
  },
  BOT_MEMORY_EXTRACT_ENABLED: {
    title: '回复后自动抽取记忆',
    kind: 'switch',
    desc:
      '每轮回复后额外调一次模型，把「值得记的事」抽成结构化条目。' +
      '开启→记忆质量高、能跨会话引用；代价是每轮多一次模型调用（成本与延迟都涨）。' +
      '关闭→几乎零开销，但只能靠原文回捞。这个键可热改。',
  },
  BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS: {
    title: '记忆抽取超时（秒）',
    kind: 'number',
    min: 1,
    max: 300,
    step: 1,
    unit: '秒',
    desc:
      '单次抽取最长等多久，超时这轮就放弃（不影响正常回复）。' +
      '调大→慢模型也能抽完；调小→经常抽不到，记忆出现空洞。',
  },
  BOT_MEMORY_EXTRACT_MAX_TOKENS: {
    title: '记忆抽取输出上限（Token）',
    kind: 'number',
    min: 64,
    max: 8192,
    step: 64,
    desc:
      '抽取结果最多写多少 Token。调大→一次能抽出更多条目，但更慢更贵；' +
      '调小→只能抽一两条，信息会被截。200 足够记一件事。',
  },
  BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS: {
    title: '抽取失败冷却（秒）',
    kind: 'number',
    min: 0,
    max: 3600,
    step: 30,
    unit: '秒',
    desc:
      '抽取出错后暂停多久不再尝试，避免对坏接口死循环重试。' +
      '调大→故障期更省资源，但恢复后要等更久才继续记；调小→恢复快，但故障时会反复撞墙。',
  },
  BOT_EMBEDDING_ENABLED: {
    title: '向量嵌入',
    kind: 'switch',
    desc:
      '开启→记忆与知识按语义相似度检索，问「上次说的那个」也能找回来；' +
      '关闭→退回关键词匹配，同义改写就找不到了。改完需重启。',
  },
  BOT_EMBEDDING_MODEL: {
    title: '嵌入模型',
    kind: 'text',
    desc:
      '生成向量的模型 id。换模型→**已有向量与新向量不在同一空间，检索会整体失效**，' +
      '必须重建索引。换之前先确认重建流程。改完需重启。',
  },
  BOT_KNOWLEDGE_SERVICE_ENABLED: {
    title: '知识库服务',
    kind: 'switch',
    desc:
      '开启→加载本地知识语料并参与检索；关闭→只靠模型自身常识，设定类问题容易编。' +
      '关闭时检索相关配置全部不生效。改完需重启。',
  },
  BOT_KB_WIKI_ENABLED: {
    title: '外部百科知识库',
    kind: 'switch',
    desc:
      '开启→把抓取来的百科语料同步进独立向量库，冷门角色/设定也能查；' +
      '关闭→不占空间、同步更省事，但问到冷门条目会说不知道。改完需重启。',
  },

  // ---------------------------------------------------------------- 戳一戳
  BOT_POKE_ENABLED: {
    title: '戳一戳总开关',
    kind: 'switch',
    desc:
      '别人戳她时是否响应。关闭→完全不理，群友会觉得冷淡；' +
      '开启→按下面的概率与冷却决定回不回、怎么回。改完需重启。',
  },
  BOT_POKE_REPLY_ENABLED: {
    title: '戳后回复',
    kind: 'switch',
    desc:
      '开启→被戳后发一条消息（文字或动作）；关闭→只按回戳开关戳回去，不说话。' +
      '群聊里只回文字更安静，私聊建议开。改完需重启。',
  },
  BOT_POKE_REPLY_MODE: {
    title: '戳回方式',
    kind: 'select',
    options: [
      { value: 'text', label: '只回文字' },
      { value: 'action', label: '回戳一下' },
      { value: 'both', label: '文字 + 回戳' },
    ],
    desc:
      '决定被戳后是说话、戳回去，还是两样都做。回戳更俏皮但会触发对方客户端提示，' +
      '群里连戳容易变成互戳刷屏；只回文字最安静。改完需重启。',
  },
  BOT_POKE_PROBABILITY: {
    title: '戳一戳响应概率',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '被戳后真的响应的概率。调高（0.8+）→几乎每次都有反应，但会显得没有边界；' +
      '调低（0.1）→偶尔理一次，更像真人但可能被当成没看见。改完需重启。',
  },
  BOT_POKE_GROUP_COOLDOWN_SECONDS: {
    title: '群聊戳冷却（秒）',
    kind: 'number',
    min: 0,
    max: 86400,
    step: 10,
    unit: '秒',
    desc:
      '同一个群里两次戳响应之间的最小间隔。调大→群友连戳不会刷屏，但第二个人会觉得被无视；' +
      '调小→反应灵敏，人多时容易变成连续回复。改完需重启。',
  },
  BOT_POKE_PRIVATE_COOLDOWN_SECONDS: {
    title: '私聊戳冷却（秒）',
    kind: 'number',
    min: 0,
    max: 86400,
    step: 10,
    unit: '秒',
    desc:
      '私聊里两次戳响应之间的最小间隔。私聊通常设得比群聊短（更亲近），' +
      '但设成 0 会让人连点几次就收到一串回复。改完需重启。',
  },
  BOT_POKE_AFFINITY_ENABLED: {
    title: '戳一戳加好感',
    kind: 'switch',
    desc:
      '开启→被戳会加一点好感度；关闭→只回应不加分。' +
      '开着能让日常互动有积累感，但也可能被刷（靠下面的每日上限兜）。改完需重启。',
  },
  BOT_POKE_AFFINITY_DELTA: {
    title: '每次戳加多少好感',
    kind: 'number',
    min: 0,
    max: 5,
    step: 0.01,
    desc:
      '单次加分的幅度。调大→几次戳就明显升温，容易被当成「刷分漏洞」；' +
      '调小→几乎无感。建议保持很小（0.0x 级），让它是「点缀」而不是主要来源。改完需重启。',
  },
  BOT_POKE_AFFINITY_DAILY_MAX: {
    title: '戳好感每日上限',
    kind: 'number',
    min: 0,
    max: 100,
    step: 1,
    desc:
      '一天内戳最多能贡献多少好感。设 0＝戳不加分。' +
      '调大→愿意戳的人升级快；调小→防止靠机械戳刷分。改完需重启。',
  },
  BOT_POKE_AFTER_REPLY_ENABLED: {
    title: '回后戳',
    kind: 'switch',
    desc:
      '她说完话之后反过来戳对方一下。开启→更主动、更有存在感；' +
      '代价是每次对话都可能多一条系统提示，群里密集聊天时比较吵。改完需重启。',
  },
  BOT_POKE_AFTER_REPLY_PROBABILITY: {
    title: '回后戳概率',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.05,
    desc:
      '说完话后真的戳的概率。调高→每次回复都戳，很快会烦；' +
      '调低→偶尔来一下，反而更有惊喜感。改完需重启。',
  },

  // ---------------------------------------------------------------- 群聊与共享
  BOT_GROUP_BLACK1: {
    title: '群黑名单一（完全静默）',
    kind: 'code',
    desc:
      '名单里的群**只接收不发送**——她在那完全不出声，连 @ 都不回。' +
      '加群→彻底闭嘴（适合纯观测）；移出→恢复正常。' +
      '这是四册里最严的一册，优先级最高。JSON 数组或逗号分隔。这个键可热改。',
  },
  BOT_GROUP_BLACK2: {
    title: '群黑名单二（只回 @ 指令）',
    kind: 'code',
    desc:
      '名单里的群只在「@ 她且带指令」时才回，普通聊天一律不理。' +
      '比黑名单一宽松、比白名单二严格，适合人多但不想完全失联的群。这个键可热改。',
  },
  BOT_GROUP_WHITE1: {
    title: '群白名单一（正常 + 可主动）',
    kind: 'code',
    desc:
      '名单里的群按正常规则回复，并且**可以按主动接话开关抽签**插话。' +
      '这是最亲近的一册，加群前先确认主动接话的概率设置。这个键可热改。',
  },
  BOT_GROUP_WHITE2: {
    title: '群白名单二（只回 @ 与命令）',
    kind: 'code',
    desc:
      '名单里的群只回「@ 她」或显式命令，不做主动接话。' +
      '适合工作群、通知群这类不想被打扰又需要能问的场合。这个键可热改。',
  },
  BOT_GROUP_CHAT_AUTO_REPLY_ENABLED: {
    title: '群聊自动接话',
    kind: 'switch',
    desc:
      '没被点名的群消息是否可能被接。开启→群里更热闹，但会打断别人对话；' +
      '关闭→只回 @ 与命令，绝不插嘴。点名与命令不受此开关影响。改完需重启。',
  },
  BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY: {
    title: '自动接话概率',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.01,
    desc:
      '每条未点名消息被接的概率（确定性哈希，不是真随机，同一条消息结果稳定）。' +
      '调高→几乎每条都接，很快会被限流并惹人烦；调低→偶尔插一句，更像真人。' +
      '5% 左右是经验值。改完需重启。',
  },
  BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS: {
    title: '主动接话冷却（秒）',
    kind: 'number',
    min: 0,
    max: 3600,
    step: 10,
    unit: '秒',
    desc:
      '两次主动接话之间的最小间隔。调大→不会连续插话，但热聊时可能整段都插不上；' +
      '调小→更活跃，也更容易招人烦。改完需重启。',
  },
  BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR: {
    title: '每小时主动接话上限',
    kind: 'number',
    min: 0,
    max: 100,
    step: 1,
    desc:
      '一小时内最多主动接几次。0＝完全不主动。' +
      '调大→存在感强，但群会变成她的独角戏；调小→偶尔冒一句，更自然。改完需重启。',
  },
  BOT_GROUP_DIGEST_PUSH_ENABLED: {
    title: '群摘要定时推送',
    kind: 'switch',
    desc:
      '开启→按设定时间把群聊摘要推到指定群；关闭→只在你手动要的时候才出摘要。' +
      '推送目标由下面的名单模式决定，空名单等于不发。改完需重启。',
  },
  BOT_GROUP_DIGEST_PUSH_TIME: {
    title: '群摘要推送时刻',
    kind: 'text',
    desc:
      '每天几点推送，24 小时制 HH:MM。写错格式→该次推送直接跳过（不会报错也不会补发）。' +
      '建议避开群最安静和最多人睡的时段。改完需重启。',
  },
  BOT_GROUP_DIGEST_LIST_MODE: {
    title: '群摘要名单模式',
    kind: 'select',
    options: [
      { value: 'off', label: '关闭', desc: '不发任何群摘要' },
      { value: 'whitelist', label: '仅白名单', desc: '只发名单里的群' },
      { value: 'blacklist', label: '排除黑名单', desc: '除名单外都发' },
    ],
    desc:
      '决定摘要在哪些群生效。白名单模式最安全（不填就不发）；' +
      '黑名单模式在群多时省事，但新群会自动被纳入推送，要留意。改完需重启。',
  },
  BOT_SHARED_GROUP_CONTEXT_ENABLED: {
    title: '群共享上下文',
    kind: 'switch',
    desc:
      '开启→她在 A 群聊过的事，在 B 群也能接上（按群摘要共享）；' +
      '关闭→每个群记忆完全隔离，不会串群。隐私敏感场景建议关闭。改完需重启。',
  },
  BOT_SHARE_ENABLED: {
    title: '跨群共享总开关',
    kind: 'switch',
    desc:
      '跨群共享的上层闸，关掉后所有共享相关能力都不生效。' +
      '开启前先确认 `BOT_SHARE_GROUPS` 名单与只读设置，否则可能把私聊内容带到群里。改完需重启。',
  },

  // ---------------------------------------------------------------- 限流与安静时段
  BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE: {
    title: '群聊每分钟回复上限',
    kind: 'number',
    min: 0,
    max: 1000,
    step: 1,
    desc:
      '每个群每分钟最多回几条。0＝不限。调大→热聊时不会漏消息，但可能刷屏、也更容易撞平台风控；' +
      '调小→自动收敛，但刷屏的人会觉得被无视。这个键可热改。',
  },
  BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR: {
    title: '群聊每小时回复上限',
    kind: 'number',
    min: 0,
    max: 10000,
    step: 1,
    desc:
      '每个群每小时的回复总闸，是分钟上限之上的第二道。' +
      '调大→长时间热聊也能持续参与；调小→活跃群很快就「额度用完」，后半天不吭声。这个键可热改。',
  },
  BOT_RATE_LIMIT_EMOTION_EXEMPT: {
    title: '情绪消息免限流',
    kind: 'switch',
    desc:
      '开启→明显带情绪的消息（求助、难过、生气）不受限流限制，优先回；' +
      '关闭→一视同仁，情绪消息也可能被限流挡掉。建议开着。这个键可热改。',
  },
  BOT_QUIET_HOURS_ENABLED: {
    title: '安静时段总开关',
    kind: 'switch',
    desc:
      '开启→在设定时段内不主动说话（点名与命令仍可回，除非也把会话类型排除）；' +
      '关闭→全天候在线。这个键可热改。',
  },
  BOT_QUIET_HOURS_START: {
    title: '安静时段开始',
    kind: 'text',
    desc:
      '24 小时制 HH:MM。跨午夜（如 23:00 → 07:00）是支持的。' +
      '写错格式→该时段不生效，等于没开安静时段。这个键可热改。',
  },
  BOT_QUIET_HOURS_END: {
    title: '安静时段结束',
    kind: 'text',
    desc:
      '24 小时制 HH:MM，必须与开始时间构成有效区间。开始＝结束视为「不启用」。这个键可热改。',
  },
  BOT_QUIET_HOURS_TIMEZONE: {
    title: '安静时段时区',
    kind: 'text',
    desc:
      '安静时段按哪个时区算，**独立于** `BOT_TIMEZONE`。填错→时段整体偏移几小时，' +
      '可能出现「该安静的时候在说话」。用 IANA 名称（如 Asia/Shanghai）。这个键可热改。',
  },
  BOT_QUIET_HOURS_SESSION_TYPES: {
    title: '安静时段适用会话',
    kind: 'multiselect',
    options: [
      { value: 'group', label: '群聊' },
      { value: 'private', label: '私聊' },
    ],
    desc:
      '哪些会话类型受安静时段约束。只勾群聊→私聊随时能找她（常见）；' +
      '两个都勾→夜里彻底失联，紧急事也叫不应。这个键可热改。',
  },
  BOT_QUIET_HOURS_BYPASS_ROLES: {
    title: '安静时段豁免角色',
    kind: 'multiselect',
    options: [
      { value: 'admin', label: '管理员' },
      { value: 'super_admin', label: '超级管理员' },
    ],
    desc:
      '这些角色的消息不受安静时段限制。加角色→运维半夜也能叫醒她；' +
      '加太多→安静时段形同虚设。这个键可热改。',
  },
};
