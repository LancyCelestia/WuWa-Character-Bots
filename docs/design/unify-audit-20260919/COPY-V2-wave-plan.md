# 出站文案 v2 · 批次单（COPY-V2 wave plan）

> 金样本：`COPY-V2-voice-brief.md` §三 私聊失败池 20 条（用户 2026-09-20 03:1x 批「可以的」）。
> **写手开工前必读两份**：①本批次单 ②`COPY-V2-voice-brief.md`（§一 可用意象表 / §二 十条硬约束）。
> 人格档案（只读，禁写）：`Documents\Documents\AI提示词与人格\AI智能体有关材料\鸣潮 AI智能体有关材料\`
> 下 `守岸人档案.md`、`守岸人人格设定.md`、`守岸人人格档案.md`。
> 交付形态：**先交文案稿文档**，实现走 `docs/design/outbound-template-unification-spec.md` 的 P2 批次，
> 迁移时旧句保留在快照测试里作对照，新句进模板文件。

## 一、批次划分（一族一 owner，禁止两席写同族）

| 批 | 族 | 现→目标 | 长度档 | 变量 | 落点（正身） |
|---|---|---|---|---|---|
| C1 | 私聊人格失败池 | 12→20 | 短-中 | 无 | `chat_reply/capabilities/chat.py:617-630` **已交（金样本）** |
| C2 | 群聊能力失败 ack | 12→18 | 短（群里要轻） | 无 | `chat_reply/capabilities/user_copy.py:73-86` |
| C3 | 管理员门禁池 | 12→18 | 短-中 | `{action}` | `user_copy.py:36-49` |
| C4 | 数据源临时失败池 | 5→15 | 短 | `{reason}` | `user_copy.py:57-63` |
| C5 | 错误卡人话区 + 冷却池 | 4→16 / 12→18 | 中 | `{exc}` | `ops/monitor/error_report.py:78-104` |
| C6 | 错误卡求助指引（**双版本各 8**） | 2→8+8 | 长·信息密集 | 无 | `error_report.py:111-120`（卡页脚版与纯文本版**不许合并**） |
| C7 | 提醒到点五型 | 各 1→各 6-8 | 长 | `{text}` | `schedule/store/reminders.py:662-706` |
| C8 | 到点吃什么开场 | 6→15 | 短-中 | `{name}{suffix}` | 根 `__init__.py:3299-3318` |
| C9 | 早报／晚报七池 | 各 3-4→各 8-12 | 中-长 | `{n}` 等 | `assistant/daily/store/daily_assist.py:268-330` |
| C10 | 收件箱命令面池 | 各 2-4→各 8 | 短-中 | `{line}` 等 | `assistant/daily/capabilities/daily_assist.py:30-78` |
| C11 | 群摘要 digest 开场 | 1→10 | 中 | 无 | 根 `__init__.py:3135` |
| C12 | 校园转发前缀 | 1→6 | 短（前缀性质） | 无 | `assistant/campus/capabilities/campus.py:32` |
| C13 | Mail 命令回执 + 新邮件通知模板 | 单点→通知 8 变体 | 中-长 | `{sender}{subject}{preview}` | `transport/mail/mail_bridge.py` |
| C14 | 运营告警可见字段（天气预警卡等） | 保持结构，措辞校一轮 | 字段式 | 无 | `ops/monitor/alerts.py:63-68` 等（**这是给管理员看的，克制优先于抒情**） |

**优先级**：C2-C5（失败与门禁面，用户最常撞到）→ C7-C10（每日推送，量最大）→ C6/C11-C14。

## 二、每席交付要求

1. 只写**你自己的一个 doc**：`docs/design/unify-audit-20260919/COPY-V2-<批次号>.md`，
   逐条给：`变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量`。
2. **交稿前跑机械自查**（脚本落 `%TEMP%`，结果贴进 doc）：
   - 禁用族零命中：`我在这 / 我在这里 / 接住你 / 我接住了 / 在这等你 / 随时叫我`；
   - 禁口语零命中：`对不住 / 别往心里去 / 不嫌麻烦 / 有点乱 / 赶紧`；
   - 条数达标、起手式不重复、句长有起伏（给 min/max/均值）；
   - 变量占位符与旧句**逐字一致**（`{exc}` 不许写成 `{error}`）。
3. **不许新增事实**：文案里每个"我会做 X"都要能在代码里找到路径。已核实可写：错误卡两段式补发、
   冷却期降级纯文本、提醒到点投递、digest 白名单推送；**已核实不可写**：自动重试、主动追问、跨会话记住承诺。
4. **只读源码**，本批不动任何 `.py`（落地在 P2 统一做）；禁改 `personas/**`、`docs/rendering-contract.md`、
   `HANDBOOK.md`、`webui/**`、`domains/render/**`。
5. 禁 git 写（本树共享**同一 git 索引**）、禁 `--write` 三件套、禁 `npm run build`、禁再派子代理、
   全程 `BOT_AUTOSYNC=0`（哈希册已被自动钩子抢跑过一次）。

## 三、已知会撞的地方（写手不要重复劳动）

- `user_copy.py` 头部有 7 族**豁免登记**（订阅族权限句、`group_info.py` 卖萌体、`__init__.py`「只有管理员才能…」族等），
  属他席或禁碰域，**本批不改、不入池**，只在 doc 里登记"待该域批次处理"。
- 反注入命中时的用户可见反应**目前没有独立话术**（TPL1-b 正在核实这条事实），C 批不要替它发明。
- `describeReason` 的"未知码原样上屏"策略是用户挂起裁定项 R-2，**不许顺手藏码**。
