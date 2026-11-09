// 分组定义：顺序即设置页侧栏顺序（常用域在前）。
// 计数是生成期快照，仅用于侧栏徽标；运行时以实际条目为准（`config-presentation.ts` 现算）。
export interface ConfigGroup {
  id: string;
  name: string;
  desc: string;
}

export const CONFIG_GROUPS: ConfigGroup[] = [
  { id: "chat", name: "聊天对话", desc: "模型、温度、上下文预算与开火判定" },
  { id: "reply", name: "回复策略", desc: "篇幅、风格、折句与细节档" },
  { id: "persona", name: "人格与称谓", desc: "人格档案、称谓偏好、口头禅与世界观" },
  { id: "affinity", name: "好感度与情绪", desc: "八档数值、心情双轴、互动权重" },
  { id: "memory", name: "记忆与知识", desc: "长期记忆、抽取、嵌入与知识库" },
  { id: "web", name: "联网检索", desc: "搜索引擎、置信度、ACG 竖源与抓页" },
  { id: "tts", name: "语音合成", desc: "GPT-SoVITS 参数、自动语音与缓存" },
  { id: "media", name: "多模态与媒体", desc: "视觉、语音识别、视频理解与归档" },
  { id: "meme", name: "表情与贴纸", desc: "表情包库、随机图与主动贴表情" },
  { id: "poke", name: "戳一戳", desc: "戳回去、冷却、好感增量" },
  { id: "rate", name: "限流与安静时段", desc: "群限流、免打扰与豁免角色" },
  { id: "group", name: "群聊与共享", desc: "群黑白名单、共享上下文与摘要推送" },
  { id: "subscribe", name: "订阅与快报", desc: "RSS、事件订阅、每日快报" },
  { id: "music", name: "点歌", desc: "点歌模式、平台与曲库" },
  { id: "weather", name: "天气", desc: "NMC 主源与 Open-Meteo 兜底" },
  { id: "finance", name: "金融行情", desc: "股指、个股、汇率、大宗与北向" },
  { id: "schedule", name: "日程与笔记", desc: "提醒、日程、备忘录与授时" },
  { id: "campus", name: "校园", desc: "校园通知监听与转发" },
  { id: "emergency", name: "紧急信息", desc: "紧急事件订阅与出站闸" },
  { id: "content", name: "内容解析", desc: "链接解析、路由与平台白名单" },
  { id: "render", name: "卡片渲染", desc: "模板、并发与等待预算" },
  { id: "outbound", name: "出站与通道", desc: "发送队列、邮件、Telegram、网关" },
  { id: "api", name: "接口与抓取", desc: "HTTP 客户端、下载、代理与超时" },
  { id: "runtime", name: "运行时与运维", desc: "数据根、日志、数据库、审计与自检" },
  { id: "control", name: "控制面", desc: "WebUI 服务、鉴权与工作区" },
  { id: "model", name: "模型与提示", desc: "模型注册表、优先级组、提示词" },
  { id: "misc", name: "其他功能", desc: "占卜、鹦鹉、世界书等零散开关" },
];
