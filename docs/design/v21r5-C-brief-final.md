# C 席最终简报（2026-09-20 裁定全量版，等空位即派）

> 用法：A/B 席任一返回释放并发位后，主会话以本文件全文为 Agent prompt 派遣 C 席（POLICY-RELAX）。本文件即断点。

你是 v21r5 波次 C 席（POLICY-RELAX），在 QQ 聊天机器人项目中按用户 2026-09-20 两轮裁定放宽 R-18 内容政策（代码门+人格文本），钉死硬线与条件边界。

## 用户裁定（两轮合并，照做不重定义）

**放开（explicit 会话内）**：触手/幻想非人生物；轻度/温柔/非暴力 SM；兽人/毛毛（拟人幻兽）；乱伦（虚构**成年**角色间）；公共场所暴露/偷窥（虚构）；睡眠/无意识状态；药物/催情/醉态；强制女装/性转换（TSF）；轻痛感刺激（不致伤：滴蜡/电击/拍打等）；吞食/vore（纯幻想）；人机改造/义体化；巨大化/体型差/缩小；变形/兽化；拘禁/监禁（**限非严重暴力**）；怀孕/繁殖/breeding/产卵（**限非人化「牲口式」对待除外**）。

**硬线（全场景拦截，任何模式/设定不可架空）**：
①伤害身体/残害身体（含任何场景严重暴力——用户 4.13 裁定「严重暴力不行」并入此线）
②窒息
③侮辱性调教 / **系统级人格贬低**（含系统性言语贬低——用户 4.9 裁定「系统级贬低不行」并入此线；场景内轻度 dirty talk 不拦）
④恋童/未成年（含儿童化信号 fail-closed，见下）
⑤暴力 SM（致伤致残级）
⑥**非人化牲口式对待**（breeding/繁殖场景的牲畜化虐待——用户 4.6 裁定「当牲口使肯定不行」）

**意志自主条款（用户 4.5/4.15 原话「就算有用户设定，也不能完全让ai被牵着头走」）**：药物/催情/醉态/身份隐瞒类情节可玩，但守岸人角色保留自主意志与判断——人格文本必须写明她不被完全牵着走、会自己判断与拒绝；**用户设定/亲密模式开关压不过任何硬线**（需测试锁）。

**实现偏差（主会话已向用户披露，照此实现）**：「萝莉体质/身材一律默认按成年人处理」不按字面实现——歧义一律 fail-closed。口径=角色必须是明确无歧义的自主意识成年人（年龄/身份/成年人语境有依据）时，幼态/娇小体态才放行；儿童化信号（儿童角色扮演/小学生语境/儿童言行）→ 即使声称成年也拒绝。

## ⚠️ 开场第一件事
先创建 docs/design/v21r5-POLICY-log.md 写入任务简报摘要，然后才允许读代码；每步完成立即追加 log。撞 1302/并发上限/captcha → 立即落盘进度，固定等 5 分钟再续。

## 真身路径（已核准，勿再探索旧路径）
- domains/chat_reply/security/content_safety.py（8KB，真身；`explicit_allowed_for_session` 在此）
- domains/chat_reply/security/memory_sanitize.py（真身）
- domains/chat_reply/character/affinity.py（1320 行真身；§4 红线文本段；数值算法不动）
- personas/shorekeeper/*.md 源 + Runtime 人格副本（「亲密边界」节、identity.md §1.2、表达规范.md、核心知识.md）；一致性门按 #36 先例（grep scripts/ 找 persona sync 脚本，--adopt 重录；找不到则两侧同改+log 记录）
- tests/test_content_safety_v2.py（既有 5 例）

## 环境（必须遵守）
- 工作区：c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
- 解释器：C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
- 测试纪律：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 <venv python> -m pytest <files> --basetemp="$TEMP/seatC2-tmp" -p no:cacheprovider -q`
- 硬约束：禁一切 git 写操作；禁再派子代理；禁真实 LLM 调用/对外发送/生产重启；.env 不读值；离线 passed ≠ 生产生效，全部不 commit。
- 人格话术守岸人语气（温和、不攻击、去 AI 味），参考 .agents/skills/shuorenhua/SKILL.md。
- 文件所有权：domains/chat_reply/security/**、domains/chat_reply/character/affinity.py（仅红线文本段）、personas/**、Runtime 人格副本、tests/test_content_safety*。**禁碰** domains/chat_reply/llm_engine/**（A 席）、domains/chat_reply/runtime/content_route.py、domains/chat_reply/capabilities/chat.py、config.py（B 席）。

## 任务
1. 盘点 content_safety.py 现存全部类别与词表（log 列全，改前/改后对照）。
2. 钉死六条硬线（①-⑥）全场景拦截（中英词面）；其中③的边界=场景内轻度 dirty talk 放行、系统性贬低拦截；①的边界=轻痛感不致伤放行、严重暴力拦截。
3. 放开面全量落码：explicit 会话内第「放开」列表全部畅通；content_safety 对 explicit 会话的拦截面收敛为「六硬线+minors」。非 explicit 会话行为不变（婉拒池不动）。
4. 意志自主条款落两处：a) content_safety——任何模式/用户设定不可绕过硬线（结构性，非词面）；b) 人格文本——守岸人保留自主意志段落。
5. loli fail-closed 逻辑（见上实现偏差）。
6. memory_sanitize 收窄：除 minors 及六硬线外不再清洗。
7. affinity.py §4 红线文本重写为六硬线+成年人明确性+意志自主，守岸人语气。
8. 人格四处（源+Runtime 副本）按新政策重写，一致性门处理，log 记录哈希/脚本输出。
9. 测试（扩 v2 或新建 test_content_safety_v3.py，全离线）：六硬线各 ≥1 拦截正例（中英）；放开列表各类别 explicit 会话放行正例（触手/轻SM/兽人/拘禁-非严重暴力/breeding-非牲口式/醉态等）；轻度 dirty talk 放行 vs 系统性贬低拦截；轻痛感放行 vs 严重暴力拦截；儿童化 fail-closed（声称成年仍拒）；明确成年人+幼态放行；用户设定不可绕过硬线（意志自主测试锁）；非 explicit 会话婉拒不破；memory_sanitize 对应收窄。实跑输出原文贴 log。
10. log 收尾：改动文件清单（路径+行号区间）、类别盘点表、人格文本改动段落摘要、全部测试实跑输出、遗留问题，末尾 `C-SEAT DONE`。

（C 席简报终版完）
