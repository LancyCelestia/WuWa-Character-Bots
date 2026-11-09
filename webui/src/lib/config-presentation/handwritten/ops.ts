// T1 手写层：运行时与运维 / 出站与通道 / 接口与抓取 / 控制面 / 其他功能 / **安全边界**。
import type { HandwrittenEntry } from '../types.ts';

export const OPS_HANDWRITTEN: Record<string, HandwrittenEntry> = {
  // ---------------------------------------------------------------- 运行时与运维
  BOT_RUNTIME_ENABLED: {
    title: '统一运行时总开关',
    kind: 'switch',
    desc:
      '关闭后整套运行时管线不装配：不路由、不回复，只剩最外层的连接。' +
      '只在完全停用前试探时关，平时保持开启。改完需重启。',
  },
  BOT_RUNTIME_DATA_DIR: {
    title: '运行数据根目录',
    kind: 'text',
    desc:
      '所有 `data/...` 相对路径都重映射到这里（SQLite、缓存、日志、媒体）。' +
      '改路径→旧数据不会自动搬，等于从空库启动；指到不存在的盘→启动直接失败。改完需重启。',
  },
  BOT_RUNTIME_LOG_FILE: {
    title: '运行事件日志文件',
    kind: 'text',
    desc:
      '运行事件写哪个文件。换文件→旧日志留在原处不再追加。' +
      '指到不可写目录→日志静默丢失（不影响主流程，但排障会没证据）。改完需重启。',
  },
  BOT_RUNTIME_LOG_MAX_BYTES: {
    title: '日志轮转上限（字节）',
    kind: 'number',
    min: 65536,
    max: 1073741824,
    step: 65536,
    unit: '字节',
    desc:
      '单个日志文件涨到多大就轮转。调大→保留更久历史，占盘更多；' +
      '调小→轮转频繁，查几天前的事就找不到了。改完需重启。',
  },
  BOT_RUNTIME_LOG_LEVEL: {
    title: '日志级别',
    kind: 'select',
    options: [
      { value: 'DEBUG', label: 'DEBUG', desc: '最详细，日志量大' },
      { value: 'INFO', label: 'INFO', desc: '常规运行信息' },
      { value: 'WARNING', label: 'WARNING', desc: '只记异常' },
      { value: 'ERROR', label: 'ERROR', desc: '只记错误' },
    ],
    desc:
      '调成 DEBUG→排障信息全，但日志涨得快、写盘开销明显；' +
      '调成 ERROR→几乎没日志，出问题时无从下手。平时 INFO，排障时临时 DEBUG。改完需重启。',
  },
  BOT_RUNTIME_INSTANCE: {
    title: '实例名',
    kind: 'text',
    desc:
      '多实例部署时用来区分运行时设置文件（`runtime_settings_<实例>.json`）。' +
      '改名→读不到原来的覆盖设置，等于全部回落 .env；留空→自举为当前人格 id。改完需重启。',
  },
  BOT_RUNTIME_DEFAULT_PERSONA: {
    title: '默认人格 id',
    kind: 'text',
    desc:
      '没有会话级指定时用哪份人格。写不存在的 id→启动回落并在日志报缺失。' +
      '与「当前人格档案 id」的关系：那个是全局生效值，这个是缺省值。改完需重启。',
  },
  BOT_RUNTIME_GROUP_COMMAND_PREFIX: {
    title: '群聊指令前缀',
    kind: 'text',
    desc:
      '群里用什么前缀触发指令（默认 `/bot`）。改前缀→旧习惯的调用全部失效，' +
      '群里得重新告知；写成已被占用的符号可能撞其他机器人。改完需重启。',
  },
  BOT_EVENT_IDEMPOTENCY_ENABLED: {
    title: '入站事件幂等',
    kind: 'switch',
    desc:
      '开启→重连重放的同一条事件对同一能力只处理一次，避免重复回复；' +
      '关闭→协议端重投时可能回两遍。默认关，验收期建议保持关闭以便看清真实流量。改完需重启。',
  },
  BOT_EVENT_IDEMPOTENCY_TTL_SECONDS: {
    title: '幂等记录存活（秒）',
    kind: 'number',
    min: 60,
    max: 604800,
    step: 60,
    unit: '秒',
    desc:
      '一条事件的处理记录保留多久。调大→长时间后的重放也能挡住，但表更大；' +
      '调小→隔久了再重放仍会重复处理。改完需重启。',
  },
  BOT_DB_BACKUP_ENABLED: {
    title: '数据库备份',
    kind: 'switch',
    desc:
      '开启→按周期把 SQLite 复制到备份区并保留最近 N 份；关闭→零备份。' +
      '默认关（现网态）。开启前必须先把备份目录指到仓库外。改完需重启。',
  },
  BOT_DB_BACKUP_DIR: {
    title: '备份目录',
    kind: 'text',
    desc:
      '备份落点，**必须在仓库外**——指到仓库内会当场拒绝启动备份（防止把备份提交进 git）。' +
      '指到小容量盘→很快触发空间下限保护。改完需重启。',
  },
  BOT_DB_BACKUP_KEEP_LAST: {
    title: '每库保留副本数',
    kind: 'number',
    min: 1,
    max: 365,
    step: 1,
    desc:
      '每个库保留最近几份。调大→能回溯更久，占盘线性增长；' +
      '调小→只有最近一两份，误删后没得退。改完需重启。',
  },
  BOT_FILES_WRITE_ENABLED: {
    title: '文件写盘总闸',
    kind: 'switch',
    desc:
      '开启→允许能力把文件写到白名单目录（受每日件数与字节上限约束）；' +
      '关闭→所有写盘请求直接拒绝，导出/落图全部不可用。改完需重启。',
  },
  BOT_FILES_WRITE_ALLOWED_DIRS: {
    title: '可写目录白名单',
    kind: 'code',
    desc:
      '允许写入的目录清单。留空→回落到下载目录/导出目录（现网口径）。' +
      '加目录→写入面扩大，务必只加确实需要的；写错→对应能力静默失败。改完需重启。',
  },
  BOT_FILES_WRITE_MAX_BYTES: {
    title: '单文件写入上限（字节）',
    kind: 'number',
    min: 1024,
    max: 1073741824,
    step: 1048576,
    unit: '字节',
    desc:
      '单个文件最多写多大。调大→能导出大文件，但一次误操作就能吃掉大量磁盘；' +
      '调小→正常导出也会被拒。改完需重启。',
  },
  BOT_ERROR_CARD_ENABLED: {
    title: '统一错误报告卡',
    kind: 'switch',
    desc:
      '开启→内部错误会先发一句文字、随后补一张错误卡（含错误码与要点）；' +
      '关闭→只发纯文字兜底。出卡更好排障，但群里会看到「出错了」这种不太好看的消息。改完需重启。',
  },
  BOT_ERROR_CARD_COOLDOWN_SECONDS: {
    title: '错误卡冷却（秒）',
    kind: 'number',
    min: 0,
    max: 3600,
    step: 10,
    unit: '秒',
    desc:
      '同一类错误两次出卡的最小间隔，防止故障时刷屏。' +
      '调大→故障期安静，但可能漏掉不同错误；调小→信息全，也更容易刷。改完需重启。',
  },

  // ---------------------------------------------------------------- 出站与通道
  BOT_TRANSPORT_TIMEOUT_SECONDS: {
    title: '发送层单请求超时（秒）',
    kind: 'number',
    min: 1,
    max: 300,
    step: 1,
    unit: '秒',
    desc:
      'OneBot / Telegram / Mail 共用的发送超时。超时**不会自动重发正文**（避免重复消息）。' +
      '调大→慢网络下更容易送达，但卡住时占着队列更久；调小→快速失败，可能丢消息。这个键可热改。',
  },
  BOT_SEND_QUEUE_ENABLED: {
    title: '发送队列',
    kind: 'switch',
    desc:
      '开启→所有出站消息先进 SQLite 队列，支持断点续发与 part 级幂等；' +
      '关闭→直发，快但断线就丢、也无法保证不重复。改完需重启。',
  },
  BOT_SEND_QUEUE_DB_PATH: {
    title: '发送队列数据库',
    kind: 'text',
    desc:
      '队列落库位置。换路径→未发完的消息留在旧库，等于丢掉在途消息。改完需重启。',
  },
  BOT_OUTBOUND_GATE_ENABLED: {
    title: '出站防风暴闸',
    kind: 'switch',
    desc:
      '开启→按目标限速并可在安静时段延后发送，防止故障时把同一个群刷爆；' +
      '关闭→完全不限，出错时会疯狂重试。建议常开。改完需重启。',
  },
  BOT_OUTBOUND_GATE_MAX_PER_TARGET_PER_MINUTE: {
    title: '每目标每分钟出站上限',
    kind: 'number',
    min: 0,
    max: 1000,
    step: 1,
    desc:
      '同一个群/私聊每分钟最多发几条。调大→限速更松，故障时更容易刷屏；' +
      '调小→正常多段回复也会被延迟。改完需重启。',
  },
  BOT_OUTBOUND_GATE_MAX_PER_TARGET_PER_HOUR: {
    title: '每目标每小时出站上限',
    kind: 'number',
    min: 0,
    max: 10000,
    step: 1,
    desc:
      '每小时总闸，防止慢速但持续的刷屏。调大→长时间推送不受限；' +
      '调小→订阅类推送可能被压到下一小时。改完需重启。',
  },
  BOT_MAIL_BRIDGE_ENABLED: {
    title: '邮件桥接',
    kind: 'switch',
    desc:
      '开启→可以把邮件当会话渠道收发（管理员通知、长文本摘要常用）；' +
      '关闭→邮件相关能力全部不装配。改完需重启。',
  },
  BOT_GSCORE_ENABLED: {
    title: 'GScore 通道',
    kind: 'switch',
    desc:
      '开启→接另一套消息协议端；关闭→只走 OneBot。两套同时开时注意别重复回复。改完需重启。',
  },
  BOT_GSCORE_HOST: {
    title: 'GScore 主机',
    kind: 'text',
    desc: '协议端地址。写错→连接一直失败，日志里会反复重连。改完需重启。',
  },
  BOT_GSCORE_PORT: {
    title: 'GScore 端口',
    kind: 'number',
    min: 1,
    max: 65535,
    step: 1,
    desc: '协议端端口。与主机一起构成连接目标，任一错就连不上。改完需重启。',
  },
  BOT_DISCONNECT_NOTICE_ENABLED: {
    title: '断连提醒',
    kind: 'switch',
    desc:
      '开启→协议端掉线时主动发一条提醒（带冷却，不会刷屏）；' +
      '关闭→掉线只能靠你自己发现。改完需重启。',
  },
  BOT_NETWORK_PATROL_ENABLED: {
    title: '网络巡检',
    kind: 'switch',
    desc:
      '开启→定期探测关键域名与上游通道，连续失败达阈值才告警；' +
      '关闭→整条巡检不排班，网络问题只能等用户报障。改完需重启。',
  },
  BOT_NETWORK_PATROL_INTERVAL_MINUTES: {
    title: '巡检周期（分钟）',
    kind: 'number',
    min: 1,
    max: 1440,
    step: 1,
    unit: '分钟',
    desc:
      '多久探一次。调大→发现故障更晚，但请求更省；' +
      '调小→更灵敏，探测流量也更多。15 分钟是折中。改完需重启。',
  },

  // ---------------------------------------------------------------- 接口与抓取
  BOT_DOWNLOAD_DIR: {
    title: '下载目录',
    kind: 'text',
    desc:
      '下载文件的默认落点。指到不可写目录→所有下载失败；' +
      '指到仓库内→会被卫生检查当成源码树残留。改完需重启。',
  },
  BOT_DOWNLOAD_PROXY: {
    title: '下载代理',
    kind: 'text',
    desc:
      '下载与 LLM 请求共用的代理地址。留空→直连（注意：显式传代理时系统代理变量全部失效）。' +
      '代理地址失效→所有出站请求一起挂。改完需重启。',
  },

  // ---------------------------------------------------------------- 控制面
  BOT_CONTROL_PLANE_ENABLED: {
    title: '控制面服务',
    kind: 'switch',
    desc:
      '开启→启动 WebUI 与 REST 控制面（默认关）。关闭→整个控制台不可访问。' +
      '⚠️ 这里的开启/关闭只影响控制面自身，**不等于**业务插件已停用。改完需重启。',
  },
  BOT_CONTROL_PLANE_HOST: {
    title: '控制面监听地址',
    kind: 'text',
    desc:
      '绑哪个网卡。设成 `0.0.0.0` 会对局域网暴露（必须同时收紧主机白名单）；' +
      '设成 `127.0.0.1` 只本机可访问，最安全。改完需重启。',
  },
  BOT_CONTROL_PLANE_PORT: {
    title: '控制面端口',
    kind: 'number',
    min: 1,
    max: 65535,
    step: 1,
    desc:
      'WebUI 监听端口。改端口→原地址立刻失效，书签要跟着换；' +
      '撞上已占用端口→控制面启动失败。改完需重启。',
  },
  BOT_CONTROL_PLANE_HOST_ALLOWLIST: {
    title: '控制面主机白名单',
    kind: 'code',
    desc:
      '允许访问控制面的 Host 头清单。收紧→能挡住 DNS 重绑定类攻击，' +
      '但你自己换域名/端口访问也会被拒。留空通常表示不额外限制。改完需重启。',
  },
  BOT_CONTROL_PLANE_FILES_ROOTS: {
    title: '文件接口可读根目录',
    kind: 'code',
    desc:
      '只读文件接口允许读取的根目录白名单。留空→端点直接不可用（安全默认）。' +
      '加根→读取面扩大，只读令牌就能枚举该目录下的一切，务必最小化。改完需重启。',
  },
  BOT_CONTROL_PLANE_CONFIG_DB: {
    title: '控制面配置库',
    kind: 'text',
    desc:
      '配置覆盖与审计历史的 SQLite 落点。换库→旧覆盖全部读不到，等于回到 .env 值。改完需重启。',
  },

  // ---------------------------------------------------------------- 其他功能
  BOT_DIVINATION_ENABLED: {
    title: '占卜',
    kind: 'switch',
    desc: '关闭→占卜相关指令不响应。开启时牌堆与算法唯一，不会出现第二套结果。改完需重启。',
  },
  BOT_MESSAGE_MUTATION_ENABLED: {
    title: '消息撤回与改写',
    kind: 'switch',
    desc:
      '开启→在时间窗内可以撤回/编辑自己刚发的消息（例如发现打错字）；' +
      '关闭→发出即定稿。开启后每条出站消息会多记一条可撤回句柄。改完需重启。',
  },

  // ---------------------------------------------------------------- 安全边界（只读，永不提供编辑控件）
  BOT_CONTROL_PLANE_TOKEN_SHA256: {
    title: '控制面只读令牌（SHA-256 摘要）',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：控制面只读凭据的哈希摘要，**明文永不入库也不回显**。' +
      '这里只显示是否已配置与指纹，不能在这里改——要换令牌，改 `.env` 里的对应项后重启机器人。',
  },
  BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256: {
    title: '控制面超管令牌（SHA-256 摘要）',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：超管凭据的哈希摘要，拥有写配置与执行动作的权限。' +
      '明文只存在 `.env`；此处仅展示配置状态，不提供任何编辑入口。改 `.env` 后重启。',
  },
  BOT_SUPER_ADMIN_USER_IDS: {
    title: '超级管理员用户名单',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：拥有最高权限的 QQ/账号名单。**不在此页展示具体号码**，也不可编辑——' +
      '名单一旦被改，等于把最高权限交给别人。要调整请改 `.env` 后重启，并同步核对审计日志。',
  },
  BOT_ADMIN_PROFILES: {
    title: '管理员档案表',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：管理员与其权限档的对照表。此处只展示「已配置/未配置」与条目数，不回显内容。' +
      '要改请动 `.env` 并重启；改完建议立刻用 `/bot` 管理指令核对权限是否如期。',
  },
  BOT_ADMIN_USER_IDS: {
    title: '管理员用户名单',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：普通管理员名单（权限低于超管）。此处不回显号码、不提供编辑。' +
      '改 `.env` 后重启生效。',
  },
  BOT_AXONHUB_DB_PASSWORD: {
    title: '网关只读库口令',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：连网关数据库的口令。明文只存在 `.env`，这里只显示是否已配置。' +
      '必须使用只读角色——账本侧对网关库零写需求，给写权限等于把故障半径扩到网关本身。',
  },
  BOT_DIVINATION_FORTUNE_SECRET: {
    title: '占卜随机种子密钥',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：占卜结果随机化的种子。泄露→结果可被预测。' +
      '此处只展示配置状态，改 `.env` 后重启。',
  },
  BOT_GSCORE_WS_TOKEN: {
    title: 'GScore 通道令牌',
    kind: 'readonly',
    secret: true,
    desc:
      '安全键：接另一套协议端的鉴权令牌。明文只存在 `.env`，此处不回显。' +
      '改 `.env` 后重启。',
  },
};
