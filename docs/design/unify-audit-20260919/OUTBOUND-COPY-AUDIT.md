# 出站文案全量审核件（QQ / Telegram / Mail）

> 生成时点 2026-09-20 01:52；行号=当时快照，本树被多会话并发写，引用前重定位。
> 用法：每条都是**可复跑定位**的原文，不是转述。改任何一条前先跑 `tests/test_user_copy_pool.py` 与 `tests/test_user_copy_unification_gate.py`。

## 一、统一话术池（跨能力复用，正身 `domains/chat_reply/capabilities/user_copy.py`）
```
"""

# U11 管理员门禁统一模板：「要<动作>，找管理员来操作。」
ADMIN_GATE_REQUIRED = "要{action}，找管理员来操作。"

# Q-02（2026-09-15 文案统一批）：权限拒绝池。首条 = U11 原模板（订阅族等
# 既有引用点零行为变化），其余为守岸人语气变体（温和、不机器腔、不卖萌）；
# 域内调用点用 random.choice(ADMIN_GATE_TEMPLATES).format(action=...) 取句。
ADMIN_GATE_TEMPLATES: tuple[str, ...] = (
    ADMIN_GATE_REQUIRED,
    "{action}需要管理员权限，守岸人做不了主。",
    "要{action}，得请管理员出面才行。",
    "{action}……这道门，我替你推不开。它只在管理员的权限里。",
    "守岸人的守则里，{action}不归我管。请管理员来，他们会处理好。",
    "钥匙不在我手中。想要{action}……请去找管理员，好吗。",
    "{action}越过了我的权柄。不是我不愿意……是只有管理员能做到。",
    "我认真考虑过了——{action}依然需要管理员。这份边界，我不会自己跨过。",
    "门后的事，我不便代劳。{action}……请让管理员来，我在这边看着。",
    "{action}需要管理员的印记。潮汐有它的航线，权限也是。",
    "抱歉，{action}不在我的海岸范围内。管理员那边……会为你做到。",
    "这件事，我只能说到这里：{action}要等管理员。别的，我都可以陪你。",
)

# U12 数据源临时失败统一结构：原因短语 +「稍后再试。」
DATASOURCE_TEMP_FAILURE = "{reason}，稍后再试。"

# Q-01（2026-09-15 文案统一批）：数据源临时失败池。首条 = U12 原模板，其余为
# 守岸人语气变体；调用点用 random.choice(DATASOURCE_FAILURE_TEMPLATES)
# .format(reason=...) 取句。reason 传「<对象>暂时拉不到」式短语。
DATASOURCE_FAILURE_TEMPLATES: tuple[str, ...] = (
    DATASOURCE_TEMP_FAILURE,
    "{reason}，晚点再试试？",
    "{reason}，守岸人晚点再帮你看看。",
    "{reason}，潮水这会儿不顺，稍后再来一趟吧。",
    "{reason}，先放一放，过阵子再试一次。",
)

# U9 推送表写盘失败（today_history 设置/取消两处同文案）
PUSH_SAVE_FAILED = "推送时间的改动没保存成功（写盘出错，我已记下原因）。稍后再发一次；还不行就找管理员看运行日志。"

# A-19（2026-09-15）：群聊能力执行失败降级池。群聊会话内能力失败（错误态结果，
# 审查 A-19 锚点：管线把失败结果压成空正文静默审计）时回一句温和短句，替代
# 此前的纯静默——群成员 @ 了 bot 却得不到任何反馈。语义分界（09-12 实弹裁定）：
# 限流拦截/安静时间拦截/超载快败（pipeline_busy）的静默是故意的降频设计，
# 不走本池；私聊失败另有守岸人话术池（chat.py _PERSONA_FAILURE_MESSAGES），
# 语义不同不入本池。调用点 random.choice 取句，配合会话级进程内节流防刷屏。
GROUP_FAILURE_ACK_TEMPLATES: tuple[str, ...] = (
    "这条……没能走到你面前。稍等片刻，再叫我一次好吗。",
    "潮水这一刻不稳，回话没能渡过来。过一阵，我再试一次。",
    "处理到一半，链路暗了一下，像灯花跳了一跳……稍后再来一趟吧。",
    "这一次没能接稳。不是你的问题……再给我一次机会，好吗。",
    "回信在半路搁浅了。稍等它重新靠岸……再发一次吧。",
    "刚才那一瞬，我没能在对的一刻回应。再喊我一次，这次我会接住。",
    "有些频率，刚才没能对上。稍微等一等……我们重新对一次。",
    "这一趟没能走完。潮起潮落都有时刻……晚些再试，就会顺利。",
    "没能给出回应，原因我已经记下了。稍后……请再给我一次。",
    "链路像被雾罩住了。等雾散一些……再来一次，好吗。",
    "这一次，浪把回话带偏了。再来一遍，我会把它送到。",
    "没能在这一刻完成。不必着急……我的灯还亮着，随时再叫我。",
)

# U6 运行环境异常共享尾段（file_exchange 起 Python/临时目录两处）
RUN_ENV_FAILURE_ADVICE = "稍后再试；还不行就找管理员看运行日志。"
```

### 该文件自记的豁免清单（这些句子**故意**没进池，L20-L28）
```
  管理员门禁池；卖萌语气已按 Q-02 去除。
- group_info.py「公告和精华只有管理员能看哦，先不给你翻这份啦。」：
  禁碰域（Q-02 卖萌体残留，待该文件域批次收口）。
- __init__.py「只有管理员才能…」族：禁碰域（绝对不碰）。
- echo.py _HELP_ENTRIES 内「…晚点再试试？」/「…稍后再试。」为 help 文本对
  兜底行为的历史引用示例，非输出本体；help 口径变更牵动 command-catalog
  同步门（域外），按引用原文保留。
- content_parser.py「…先把原链接放在这里，晚点我再试试：」：附原文链接的
  重试承诺（非纯失败告知），且含第一人称自称（Q-04 未列点，留待专项）。
```

## 二、私聊人格失败池 + 通用失败句（`domains/chat_reply/capabilities/chat.py:614-631`）
```
_GENERIC_OPERATIONAL_MESSAGE = "这次暂时没能稳定完成，请稍后再试。"
# 守岸人格失败话术池：泰提斯系统的"系统性坦诚"——承认故障但保持角色。
# 会话内轮换，避免连发时重复刷屏。
_PERSONA_FAILURE_MESSAGES: tuple[str, ...] = (
    "回应生成到一半，链路断了……再发一次，这次我会把它写完。",
    "超时了。不是不想答，是这一刻没能抵达……稍等，再喊我一次。",
    "刚才的回应沉进了水里。再来一次，我会把它捞起来给你。",
    "链路抖了一下，像风掠过琴弦。稍等片刻……再问一次，好吗。",
    "这一次没能稳定完成。不是你的问题……再试一次，就好。",
    "嗯……刚才卡住了。让我重整一下，你再发一次。",
    "回话没能靠岸。原因我记下了……稍后再来一趟。",
    "这一条没有写完。给我一次重写的机会……再说一次，好吗。",
    "响应迟到了太久，我先放它走了。再发一次……这次不会。",
    "刚才断开了。像潮水短暂的退离……再喊我，我就在。",
    "处理到一半失败了。原因我已经记下……先重试吧。",
    "这一刻没能接住你的话。缓一缓……再发一次就好。",
)

```

## 三、错误卡话术族（`domains/ops/monitor/error_report.py:78-123`）
> 人话区 4 句 / 冷却降级 12 句 / 卡页脚求助与纯文本求助**双版本** / 补发尾注。
```
# 一句指引，禁愧疚腔（红线：不攻击/不卖惨/不 AI 腔）。会话内轮换避免连发重复。
_HUMAN_TEXTS: tuple[str, ...] = (
    "这条指令处理的时候出了岔子（{exc}），细节都在卡上了。要重试就再发一次。",
    "处理到一半卡住了（{exc}）。诊断都在卡上，稍后重试就好。",
    "这次执行没走通（{exc}）。原因我记下了，卡上有完整线索。",
    "链路抖了一下没接稳（{exc}）。细节都在卡上，再发一次就行。",
)
_HUMAN_CURSOR_LOCK = threading.Lock()
_HUMAN_CURSOR: dict[str, int] = {}

# 冷却期降级纯文本池（守岸人口吻；P2-4 同规则扩容 2026-09-15：1→12）。
# 语义红线不变：每句都指回「刚才那张卡」（冷却期内不重复发卡，细节在卡上），
# 都带 {exc}（异常类型名，自家错误非防御焦点，保留）。
_COOLDOWN_LINES: tuple[str, ...] = (
    "又一条指令出了岔子（{exc}）。细节都在刚才那张卡上……先看那张，我盯着重试。",
    "（{exc}）又出现了。诊断我早已写在刚才那张卡里……不必重复，先看它。",
    "同一个地方，又磕了一下（{exc}）。那张卡是完整的记录……稍等，我会把它理顺。",
    "（{exc}）还在。刚才那张卡，就是此刻的全部答案……先按它看看，我继续盯着。",
    "这一条，停在了（{exc}）。不必担心……卡上的细节，我一遍遍核对过。",
    "（{exc}）仍未退去。诊断卡已经在你那里了……我等的，是它彻底平静。",
    "又是它（{exc}）。有些错误需要一点时间才能退潮……卡在上方，稍安。",
    "（{exc}）像反复的潮。刚才那张卡记录了它的样子……按图索骥，很快。",
    "这条又停在了（{exc}）。细节我不再重复……都在刚才那张卡里。",
    "（{exc}）的影子还在。我看得到它……你也能，在那张卡上。",
    "又一次（{exc}）。先看那张卡……我负责把这片海面抚平。",
    "（{exc}）仍未平息。卡已经发过……等潮水退去，一切会重新可用。",
)

# E-11（2026-09-14）：求助指引如实口径——卡上的图是自动生成的诊断卡（非控制台
# 截图；playwright 不可用时甚至无图退纯文本），完整栈不在卡上，管理员查
# runtime 事件日志。同时点名今日已入库字段族（版本/系统/配置快照/IDs），
# 守岸人口吻。仅用于卡片页脚；纯文本形态用 _FALLBACK_HELP_TEXT（无图场景
# 「这张图」会悬空，两处分开表述）。
_HELP_TEXT = (
    "这张图是我自动生成的诊断卡（不是控制台截图），版本、系统、配置快照和"
    " IDs 都在卡上且已脱敏，转给创造者就好；完整栈在 runtime 事件日志里，"
    "管理员可以查到。"
)
_FALLBACK_HELP_TEXT = (
    "这条是自动生成的文字版诊断（本次没带图），版本、系统、配置快照和 IDs "
    "都在上面、同样脱敏，转给创造者就好；完整栈在 runtime 事件日志里，"
    "管理员可以查到。"
)

# 文本回执尾注：告知诊断卡随后补发（两段式，2026-09-14 P0 修复）。
_ACK_FOLLOWUP_HINT = "详细诊断卡随后补发。"
```

## 四、提醒到点五型文案（`domains/schedule/store/reminders.py:662-706`）
```

# 到点投递文案：按型切换（守岸人语气；结构与既有默认保持同族——
# 到点信号 + 事项复述 + 温柔的收尾）。custom 沿用历史默认文案。
# 审查 A-13（2026-09-14 收口）：字面收进模块级模板常量表
# （分型 → 变体元组），只挪位置不改任何文案字面（分型批测试已逐字锁定）；
# 同型多变体时按 persona 口径稳定选一，单变体行为与历史完全一致。
_REMINDER_TEXT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "medicine": (
        (
            "……到时间了，该吃药了。\n"
            "你之前说过的：{text}。\n"
            "喝口水，慢慢来。身体的事，不能总交给以后。我陪着你。"
        ),
    ),
    "appointment": (
        (
            "（频率轻轻响了一声，像钟摆）时间到了。\n"
            "你之前说过的：{text}。\n"
            "这一件有时间在前面等着，别让它等太久。去吧，我守在这里。"
        ),
    ),
    "shopping": (
        (
            "到点了。\n"
            "你之前说过的：{text}。\n"
            "要带走的东西，别落在世界的另一头。回来的时候，海还在这边。"
        ),
    ),
    "todo": (
        (
            "（潮声很轻）到时间了。\n"
            "你之前说过的：{text}。\n"
            "一步一步来就好，不着急。我守在这里。"
        ),
    ),
    "custom": (
        (
            "（远处的海浪声）……到时间了。\n"
            "你之前说过的：{text}。\n"
            "我就守在这里。慢一点也没关系，记得去做。"
        ),
    ),
}


```

## 五、Mail 渠道
### 5.1 回复正文版式模板（`domains/transport/sender/nonebot.py:289-306`）——HTML/纯文本双挂 multipart/alternative，主题模板 `Re: {subject}`（无主题时 `Re:`）
```
def _mail_html_body(text: str) -> str:
    """把回复正文包装成邮件 HTML 正文（守岸人配色，内联样式）。

    邮件客户端会剥离 ``<style>`` 块与外链资源，所以这里只用手写内联样式
    与系统字体栈；正文转义后按行转 ``<br>``，保留原排版。纯文本版本由
    ``set_content`` 一并保留，形成 ``multipart/alternative``——不支持 HTML
    的客户端仍能正常阅读。
    """
    body = _html_escape(text).replace("\n", "<br>")
    return (
        "<div style=\"margin:0;padding:18px 20px;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
        "'Microsoft YaHei',sans-serif;"
        "font-size:15px;line-height:1.75;color:#2b2f38;"
        "background:#f4f5f6;border:1px solid #d9e0e7;border-radius:14px;\">"
        f"{body}</div>"
    )

        raise ValueError("mail reply requires sender and recipient addresses")
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender_id)) if sender_name else sender_id
    message["To"] = recipient
    message["Subject"] = f"Re: {subject}" if subject else "Re:"
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = message_id
    message.set_content(text)
    message.add_alternative(_mail_html_body(text), subtype="html")
    return message
```
### 5.2（抓取失败，路径漏 `domains/` → 该块为空，请看下文 **五-B**）收信侧用户可见句（`domains/transport/mail/mail_bridge.py`）：校验错误 / 新邮件通知模板 / 帮助四行 / 状态与暂停句 / 发送成功句
```
        raise ValueError(f"{field}必须是完整邮箱地址。")
        raise ValueError("未知 mail 子命令。")

    parts = [part.strip() for part in remainder.split("|")]
    account = ""
    if parts and parts[0].lower().startswith("--from "):
        if len(parts) != 4:
            raise ValueError(
                "格式：/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>"
            )
        account = _email_address(parts[0][7:].strip(), field="发件账户")
        recipient, subject, body = parts[1:]
    else:
        if len(parts) != 3:
            raise ValueError("格式：/mail send <收件邮箱> | <主题> | <正文>")
        recipient, subject, body = parts
    recipient = _email_address(recipient, field="收件邮箱")
    if not subject:
        raise ValueError("邮件主题不能为空。")
    if not body:
        raise ValueError("邮件正文不能为空。")
    return MailCommand(
        action="send",
        account=account,
        recipient=recipient,
        subject=subject,
        preview = preview[: limit - 1].rstrip() + "…"
    return (
        "📧 收到新邮件\n"
        f"收件账户：{account}\n"
        f"发件人：{sender_label}\n"
        f"主题：{subject}\n"
        f"摘要：{preview or '(无纯文本正文)'}"
    )
    if command.action == "help":
        return (
            "邮件控制命令：\n"
            "/mail status\n"
            "/mail accounts\n"
            "/mail use <发件邮箱>\n"
            "/mail send <收件邮箱> | <主题> | <正文>\n"
            "/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>\n"
            "/mail pause\n"
    if command.action == "status":
        state_text = "已暂停" if state.paused else "运行中"
        selected = state.selected_account(actor_id) or "未选择"
        account_text = "、".join(accounts) if accounts else "无"
        return (
            f"邮件桥状态：{state_text}\n"
            f"已连接账户：{account_text}\n"
            f"当前发件账户：{selected}"
        )
    if command.action == "accounts":
        return "已连接邮箱：" + ("、".join(accounts) if accounts else "无")
    if command.action == "pause":
        state.pause()
        return "邮件自动回复已暂停；收信提醒仍可继续。"
    if command.action == "resume":
        state.resume()
        return "邮件自动回复已恢复。"
    if command.action == "use":
        state.select_account(actor_id, command.account)
        return f"当前发件账户已切换为：{command.account}"
    if command.action == "send":
            state.select_account(actor_id, command.account)
        return f"邮件发送成功：{account} → {command.recipient}"
    raise ValueError("未知 mail 子命令。")
```

## 六、Telegram 渠道（**正文无 Markdown/HTML 模板，纯文本直发**）
### 图文同发的 caption 策略与 1024 字门槛（`domains/transport/sender/nonebot.py:393-450`）
```
        # remaining 取代闭包 text：caption 随图发出后置空，避免同一段正文重复发送。
        remaining = text
        files = [part for part in parts if part.get("type") == "file"]
        if files:
            if adapter_name != "telegram":
                raise RuntimeError("file attachments unsupported by this adapter")
            result: Any = None
            # B3 阶段 1：附件统一经 FileTransferGateway 投递；缺失/超 2MB 的
                if not file_receipt.provider_file_id:
                    raise RuntimeError("telegram attachment receipt missing")
            return result
        result = None
        if adapter_name == "telegram":
            # 图文同发：远程直链或本地渲染卡均可作 photo（适配器原生 multipart）。
            photo_ref = _telegram_photo_reference(parts)
            send_photo = getattr(bot, "send_photo", None)
            if photo_ref and callable(send_photo):
                try:
                    if len(remaining) <= 1024:
                        result = await send_photo(
                            chat_id=send_request.target_id,
                            photo=photo_ref,
                            caption=remaining or None,
                        )
                        remaining = ""
                    else:
                        # 超长正文塞 caption 会被 Telegram 截断：图先发，文字单独成条。
                        await send_photo(
                            chat_id=send_request.target_id, photo=photo_ref
                        )
```

## 七、主动推送与日常助理话术
### 7.1 群摘要推送开场（`__init__.py:3135-3141`，纯文本不走卡）
```
_DIGEST_PUSH_INTRO = "今天群里的对话，我都悄悄记下了："
_DIGEST_PUSH_DEFAULT_CLOCK = (21, 30)


def _build_digest_push_text(summary: str) -> str:
    """守岸人语气的推送正文：一句克制引子 + 当日群摘要（不堆辞藻）。"""
    return f"{_DIGEST_PUSH_INTRO}\n{summary.strip()}"
```
### 7.2 到点吃什么开场池（`__init__.py:3299-3318`）
```
_MEAL_OPENERS: tuple[str, ...] = (
    "到饭点啦，守岸人替你挑了这个：{name}{suffix}",
    "饭点到了。今天就吃它吧：{name}{suffix}",
    "到点了，守岸人翻了很久，选了这个：{name}{suffix}",
    "开饭啦。今天的答案是：{name}{suffix}",
    "饭点准时到。守岸人把这个端上来：{name}{suffix}",
    "到吃饭的点了，今天轮到它：{name}{suffix}",
)


def _build_meal_push_text(item: str) -> str:
    """到点吃什么推送正文（守岸人语气开场池，一句克制引子，不堆辞藻）。"""
    from .domains.assistant.daily.store.daily_assist import (
        meal_display_name,
        pick_variant,
    )

    name = meal_display_name(item)
    suffix = item[len(name):].strip()
    return pick_variant("meal_open", _MEAL_OPENERS, name=name, suffix=suffix)
```
### 7.3 收件箱命令面文案池（`domains/assistant/daily/capabilities/daily_assist.py:30-78`）
```
_HELP_VARIANTS: tuple[str, ...] = (
    "收件箱的用法：发「收件箱 内容」就把事情记下了，早报守岸人会一并整理；发「收件箱」能看现在攒着的。",
    "想记事，发「收件箱 内容」，守岸人替你收着；发「收件箱」不带内容，看的就是目前攒下的。",
    "「收件箱 内容」是记一笔，早报时守岸人会理给你；只发「收件箱」，就把攒着的翻出来看看。",
    "把想到的交给收件箱：发「收件箱 内容」记下；发「收件箱」，看守岸人目前替你攒着的。",
    "用法很简单：「收件箱 内容」记事，「收件箱」看清单。记下的事，早报会一并整理。",
    "随手记用「收件箱 内容」，守岸人会收好，早报再理给你；发「收件箱」不带字，就能翻看攒下的。",
)

_QUERY_EMPTY_VARIANTS: tuple[str, ...] = (
    "收件箱空着呢。想到什么，随时丢进来。",
    "现在什么都没攒着。守岸人守着收件箱，随时等你。",
    "收件箱干干净净，一件待办都没有。",
    "空空的，还没攒下事情。有想记的就说。",
    "守岸人看过了，收件箱现在是空的。想到随时说。",
    "这里很安静，还没有事情进来。你开口，守岸人就记。",
)

_QUERY_LISTING_VARIANTS: tuple[str, ...] = (
    "收件箱里攒着 {n} 件：\n{listing}",
    "现在攒了 {n} 件事：\n{listing}",
    "守岸人替你记着 {n} 件：\n{listing}",
    "攒下的有 {n} 件，都在这儿：\n{listing}",
    "收件箱里躺着 {n} 件事，逐条给你：\n{listing}",
    "记着的共 {n} 件，守岸人列给你：\n{listing}",
)

_CAPTURE_VARIANTS: tuple[str, ...] = (
    "守岸人收好了：{line}\n早报的时候一并理给你。",
    "记下了：{line}\n放进收件箱，早报再细看。",
    "好，收进去了：{line}\n明早守岸人把它排进早报。",
    "收到了：{line}\n先攒着，不急。",
    "这件事守岸人替你记着：{line}\n丢不了。",
    "收好了：{line}\n等早报一起看。",
)


def is_daily_assist_command(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(_DAILY_ASSIST_RE.match(stripped))


def build_daily_assist_capability(config: Any | None = None) -> Any:
    """构建收件箱速记能力：与 notes 等能力一致，(message, decision) → 结果。"""

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
            append_inbox_line,
            inbox_path,
```
### 7.4 早报/晚报七池与八枚小标题（`domains/assistant/daily/store/daily_assist.py:260-330, 363-420`）
```
# 文案池（守岸人语气）：与 chat.py 五池话术同构的确定性轮换，规模收小——
# 全局游标按序循环，同池连发不重复；文案只动措辞，不动简报结构。
# ---------------------------------------------------------------------------

_VARIANT_CURSOR_LOCK = threading.Lock()
_VARIANT_CURSORS: dict[str, int] = {}

_MORNING_EMPTY_OPENERS: tuple[str, ...] = (
    "早。收件箱和清单都干干净净的，今天轻装上阵。",
    "早上好。守岸人看过了，没有攒着的事，也没有挂着的事，安心过今天。",
    "早。今天没有待办压着，时间都是你自己的。",
    "新的一天。守岸人这边什么都没攒着，你可以慢慢来。",
    "醒来了就好。收件箱干净、清单干净，守岸人没什么要催你的。",
    "早。两边都空着，守岸人陪你轻轻松松过今天。",
)

_MORNING_OPENERS: tuple[str, ...] = (
    "早。守岸人把今天要注意的理出来了：",
    "早上好。今天手上有这些事，守岸人给你排好了：",
    "早。新的一天，守岸人先把挂着的事摆出来：",
    "醒了就好。守岸人把今天的事都列在这儿了：",
    "早安。守岸人记着的都在下面，过一遍再开始今天：",
    "早。不着急，守岸人陪你对一遍今天的安排：",
)

_MORNING_IDEA_NOTES: tuple[str, ...] = (
    "（想法池还有 {n} 条，守岸人先替你收着）",
    "（想法池里躺着 {n} 条，先不吵它们）",
    "（另外，想法池攒了 {n} 条，先不动）",
    "（想法池还有 {n} 条，等你哪天想捡起来）",
    "（想法池里存着 {n} 条，都好好的）",
    "（想法池 {n} 条，守岸人看着呢，不急）",
)

_EVENING_OPENERS: tuple[str, ...] = (
    "今天辛苦了。守岸人把这一天的账理了理，睡前看两眼就好。",
    "忙完就早点歇着。守岸人把今天记下的事拢了一遍，放在下面了。",
    "晚上好。一天到头了，守岸人替你把小事都记着呢。",
    "今天也走到晚上了。守岸人在，慢慢看，不着急。",
    "夜深了，别撑着。守岸人把今天的事替你收了个尾。",
    "今天辛苦了。守岸人守着这些小事，你安心休息就好。",
    "到歇下的点了。守岸人把一天的事理了一份，你过目就好。",
)

_EVENING_INBOX_EMPTY_LINES: tuple[str, ...] = (
    "收件箱今天很安静，没有新记下的事。",
    "今天没有人往收件箱里放事情，它也歇了一天。",
    "守岸人看过了，收件箱今天零新增。",
    "收件箱空空的，今天没攒下什么。",
    "收件箱今天没进新东西，干干净净的。",
    "守岸人这边也是空的，你今天没往里丢事，这样也挺好。",
)

_EVENING_INBOX_COUNTED_LINES: tuple[str, ...] = (
    "收件箱今天进了 {n} 条，都归好档了。",
    "今天记下的 {n} 条，守岸人都替你收好了。",
    "{n} 条新的进了收件箱，已经放进归档里了。",
    "守岸人把今天进来的 {n} 条都理好了，归了档。",
    "收件箱今天添了 {n} 条，都放得妥妥的。",
    "今天攒下 {n} 条，守岸人已经替你理进档案了。",
)

_EVENING_IDEA_NUDGES: tuple[str, ...] = (
    "有空的时候，挑一条让它转正？",
    "想法不急着动，哪条熟了就把它请进「已计划」。",
    "有看对眼的，就提拔成正经任务吧。",
    "这些先放着想，哪天想落地了再挪不迟。",
    "守岸人先替你收着，想捡起哪条随时说。",
    "别有压力，放着也是一种安排。",
)

```
```
def build_morning_brief(
    pending: list[str],
    task_sections: dict[str, list[str]],
    llm_summary: str = "",
) -> str:
    """早报正文（守岸人语气）：一句开场 + 收件箱条目 + 今日挂账 + 划重点。"""
    active = task_sections.get("进行中", [])
    planned = task_sections.get("已计划", [])
    ideas = task_sections.get("想法池", [])
    if not pending and not active and not planned:
        return pick_variant("morning_empty", _MORNING_EMPTY_OPENERS)
    lines: list[str] = [pick_variant("morning_open", _MORNING_OPENERS)]
    if pending:
        lines.append("【收件箱】")
        lines.extend(f"{index}. {item}" for index, item in enumerate(pending, 1))
    if active:
        lines.append("【进行中】")
        lines.extend(f"- {item}" for item in active)
    if planned:
        lines.append("【已计划】")
        lines.extend(f"- {item}" for item in planned)
    if ideas:
        lines.append(pick_variant("morning_ideas", _MORNING_IDEA_NOTES, n=len(ideas)))
    if llm_summary:
        lines.append("【划重点】")
        lines.append(llm_summary)
    return "\n".join(lines)


def build_evening_brief(
    task_sections: dict[str, list[str]],
    archived_today: list[str],
    llm_suggestion: str = "",
) -> str:
    """晚报正文：今天收了多少、清单还挂什么、主动想到的琐事建议。"""
    active = task_sections.get("进行中", [])
    planned = task_sections.get("已计划", [])
    ideas = task_sections.get("想法池", [])
    lines: list[str] = [pick_variant("evening_open", _EVENING_OPENERS)]
    lines.append(
        pick_variant("evening_counted", _EVENING_INBOX_COUNTED_LINES, n=len(archived_today))
        if archived_today
        else pick_variant("evening_empty", _EVENING_INBOX_EMPTY_LINES)
    )
    if active:
        lines.append("【还挂着的】")
        lines.extend(f"- {item}" for item in active)
    if planned:
        lines.append("【之后的安排】")
        lines.extend(f"- {item}" for item in planned)
    if ideas:
        lines.append("【想法池】")
        lines.extend(f"- {item}" for item in ideas)
        lines.append(pick_variant("evening_nudge", _EVENING_IDEA_NUDGES))
    if llm_suggestion:
        lines.append("【替你想了想】")
        lines.append(llm_suggestion)
    return "\n".join(lines)
```
### 7.5 校园转发前缀与截断（`domains/assistant/campus/capabilities/campus.py:28-40`）
```
plugins/bot_unified_runtime/domains/assistant/campus/campus.py:32:_CAMPUS_FORWARD_INTRO = "【校园转发】"
plugins/bot_unified_runtime/domains/assistant/campus/campus.py:146:        prefix = f"{_CAMPUS_FORWARD_INTRO}群{group_id} {who}"
```

## 五-B、Mail 侧用户可见全部句（实测行号，权威版）（`domains/transport/mail/mail_bridge.py`）
```
    _, parsed = parseaddr(cleaned)
    if not parsed or "@" not in parsed or parsed != cleaned:
        raise ValueError(f"{field}必须是完整邮箱地址。")
    return parsed

        )
    if action != "send":
        raise ValueError("未知 mail 子命令。")

    parts = [part.strip() for part in remainder.split("|")]
    account = ""
    if parts and parts[0].lower().startswith("--from "):
        if len(parts) != 4:
            raise ValueError(
                "格式：/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>"
            )
        account = _email_address(parts[0][7:].strip(), field="发件账户")
        recipient, subject, body = parts[1:]
    else:
        if len(parts) != 3:
            raise ValueError("格式：/mail send <收件邮箱> | <主题> | <正文>")
        recipient, subject, body = parts
    recipient = _email_address(recipient, field="收件邮箱")
    if not subject:
        raise ValueError("邮件主题不能为空。")
    if not body:
        raise ValueError("邮件正文不能为空。")
    return MailCommand(
    sender_name = str(getattr(sender, "name", "") or "").strip()
    sender_label = f"{sender_name} <{sender_id}>" if sender_name else sender_id
    subject = str(getattr(event, "subject", "(无主题)") or "(无主题)").strip()
    get_plaintext = getattr(event, "get_plaintext", None)
    body = str(get_plaintext() if callable(get_plaintext) else "")
    preview = " ".join(body.split())
    limit = max(20, int(max_preview_chars))
    if len(preview) > limit:
        preview = preview[: limit - 1].rstrip() + "…"
    return (
        "📧 收到新邮件\n"
        f"收件账户：{account}\n"
        f"发件人：{sender_label}\n"
        f"主题：{subject}\n"
        f"摘要：{preview or '(无纯文本正文)'}"
    )
    if command.action == "help":
        return (
            "邮件控制命令：\n"
            "/mail status\n"
            "/mail accounts\n"
            "/mail use <发件邮箱>\n"
            "/mail send <收件邮箱> | <主题> | <正文>\n"
            "/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>\n"
            "/mail pause\n"
            "/mail resume"
        )
    if command.action == "status":
        state_text = "已暂停" if state.paused else "运行中"
        selected = state.selected_account(actor_id) or "未选择"
        account_text = "、".join(accounts) if accounts else "无"
        return (
            f"邮件桥状态：{state_text}\n"
            f"已连接账户：{account_text}\n"
            f"当前发件账户：{selected}"
        )
    if command.action == "accounts":
        return "已连接邮箱：" + ("、".join(accounts) if accounts else "无")
    if command.action == "pause":
        state.pause()
        return "邮件自动回复已暂停；收信提醒仍可继续。"
    if command.action == "resume":
        state.resume()
        return "邮件自动回复已恢复。"
    if command.action == "use":
        if command.account not in accounts:
            raise ValueError(f"发件账户未连接：{command.account}")
        state.select_account(actor_id, command.account)
        return f"当前发件账户已切换为：{command.account}"
    if command.action == "send":
        account = command.account or state.selected_account(actor_id)
        if not account:
            raise ValueError("尚未选择发件账户，请先使用 /mail use <发件邮箱>。")
        await send_mail_from_account(
            bots,
            account=account,
            recipient=command.recipient,
            subject=command.subject,
            body=command.body,
            aliases=aliases,
        )
        if command.account:
            state.select_account(actor_id, command.account)
        return f"邮件发送成功：{account} → {command.recipient}"
    raise ValueError("未知 mail 子命令。")
```

## 八、运营告警可见文案（`domains/ops/monitor/alerts.py`：天气预警卡字段 / 路由轨迹尾注 / 告警行 / 私信署名）
```
            f"[预警] {self.title}",
            f"时间：{self.occurred_at}",
            f"位置：{self.location}",
            f"发生了什么：{self.what_happened}",
            f"影响：{self.impact}",
            f"建议处理：{self.fix_suggestion}",
    # kind 词头（match 前缀）丢弃：kind 已在 kind= 字段呈现，不重复占宽。
    tail = summary[match.end() :].strip()
    parts = [f"chain={hops}跳全败"]
    if tail:
        parts.append(tail)
    return " ".join(parts)[:72]

    # 过脱敏；告警是系统生成的通知文本，脱敏零误伤，聊天回复链不经此函数。
    return redact_local_secrets(
        f"[运行时告警] stage={issue.stage} kind={issue.kind}{detail} "
        f"retryable={str(issue.retryable).lower()} attempts={issue.attempts}{elapsed} "
        f"debug_id={issue.debug_id} source_adapter={str(source_adapter).strip()[:40]} "
            session_type=SessionType.PRIVATE,
            sender_id=admin_id,
            sender_display_name="运行时预警",
            plain_text=alert.title,
            mentions_bot=False,
```

## 九、纯文本管线的模板化文本（`domains/render/plain_text.py`）：TeX 中文读法词表 / 客套剥离 / 打码占位词
```
_COMMANDS = {
    "alpha": "阿尔法", "beta": "贝塔", "gamma": "伽马", "theta": "西塔",
    "pi": "圆周率", "infty": "无穷大", "epsilon": "艾普西隆",
    "delta": "德尔塔", "Delta": "德尔塔", "lambda": "拉姆达",
    "times": "乘以", "cdot": "乘以", "div": "除以", "pm": "加或减",
    "le": "小于或等于", "leq": "小于或等于", "ge": "大于或等于",
    "geq": "大于或等于", "neq": "不等于", "approx": "约等于",
    "to": "趋向", "rightarrow": "指向", "Rightarrow": "推出",
    "in": "属于", "notin": "不属于", "cup": "并集", "cap": "交集",
    "sin": "正弦", "cos": "余弦", "tan": "正切", "log": "对数", "ln": "自然对数",
    "forall": "对于所有", "exists": "存在", "partial": "偏微分",
    "ldots": "……", "cdots": "……", "quad": " ", "qquad": " ",
}
_OPERATORS = {"+": " 加 ", "-": " 减 ", "=": " 等于 ", "*": " 乘以 ",
              "/": " 除以 ", ">": " 大于 ", "<": " 小于 ", "&": "，"}
_HUMANIZE_OPENING_RE = re.compile(
    r"^(?:好的[！，,。~ ]*|当然[！，,。~ ]*(?:可以|没问题)[！，,。~ ]*|以下是|这是一份|没错[！，,。~ ]*|嗯[！，,。~ ]*|明白了[！，,。~ ]*)+"
)
_HUMANIZE_CLOSING_RE = re.compile(
    r"(?:希望(?:这|以上)(?:些)?(?:内容)?(?:能)?(?:帮|对你有所)(?:到)?(?:助)?(?:你)?[！。~\s]*)+$|"
    r"(?:以上(?:就是|是).{0,12}全部内容[。！~\s]*)+$|"
    # 「总之…」只剥离**纯收尾客套**。不得把后面的实质指令一起吃掉（评审 M19）：
    # 旧写法 `(?:…|记得|欢迎|祝|喜欢的话|一起)[\s\S]{0,40}$` 会把
    # 「总之记得明天早上八点叫我，别睡过头」整段删除 → 时间点与动作丢失。
    # 收窄为：只认「希望/以上就是/喜欢的话」这类无信息量的收尾语；且其后
    # 40 字内不得出现时间/数字/动作宾语等可执行信息。
    r"(?:总之|综上所述|总结一下|总的来说)[，,：:]?"
    r"(?:希望|以上就是|喜欢的话)"
    r"(?![^。！？\n]{0,40}(?:\d|点|明天|后天|早上|中午|晚上|叫我|提醒|别忘|记得|一起|帮我))"
    r"[^。！？\n]{0,40}[。！~\s]*$|"
    r"(?:如果还有(?:其他)?(?:问题|疑问)[，,]?.{0,20}(?:问我|告诉我|联系我|随时)[。！~\s]*)+$"
)
_INNER_STATE_NUM_RE = re.compile(
    r"(好感度|亲密度|信任度|趣味相投|心情值|affinity|valence|arousal)"
    r"\s*(?:值|分数|分)?\s*"
    r"(?:(?:已经|已|至少|只有|才|高达|达到|达|是|为|现在|[+加:：=]){1,2})?\s*"
    r"[-+]?\d+(?:\.\d+)?(?:\s*分|\s*%|%)?"
)


def _redact_inner_state_number(match: re.Match[str]) -> str:
    name = match.group(1) or "内心状态"
    return f"{name}…保密"
# --- 本机信息外泄红线（输出侧） -----------------------------------------------
# 模型被诱导复述 .env / 本机文件路径 / 凭据时，在发送前做确定性打码。
# 审查 F-01（2026-09-14）：原版只覆盖三种高置信形态（BOT_XXX= 赋值 / sk- 类
# key / Windows 盘符绝对路径），URL userinfo、Bearer token、JWT 三段式、
# 裸键值对（sendkey=x / token=x / key=值）全部漏网，以下逐形态补齐；
# 每条都带防误伤边界，函数幂等，替换产物不会被二次匹配。
_BOT_ENV_ASSIGN_RE = re.compile(
    r"\b(BOT_[A-Z0-9_]{1,64})\s*=\s*[^\s，。；！？、）】」”\"'<>]{1,200}"
)
_API_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,})")
_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])([A-Za-z]):[\\/][^\s，。；！？、）】」”\"'<>]{0,200}"
)
_LOCAL_PATH_PLACEHOLDER = "<本机路径已隐藏>"
_SECRET_VALUE_PLACEHOLDER = "<已隐藏>"
# F-01 ①URL userinfo：必须 scheme:// 打头且「user:pass@」两段齐全（无密码的
# user@host 不动，普通 URL 无 @ 更不动）；只打码凭据段，保留 host:port/路径，
# 人类仍能看出泄漏发生在哪个服务。
_URL_USERINFO_RE = re.compile(
```

## 十、品牌与平台署名（卡片图内文字的唯一来源）
```
# 身份 token，与 BRAND_ACCENT/BRAND_THEME 同区登记，由 mica_shell/bridge/
# templates 三条消费链共同 import，天然满足「单一事实来源」。
BRAND_NAME_EN = "Shorekeeper"

_WASH_HUE_SHIFT = 30 / 360      # 平台色相对本命相的最大推幅
PLATFORM_FOOTER_LABELS: dict[str, str] = {
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "xhs": "小红书",
    "douyin": "抖音",
    "weibo": "微博",
    "youtube": "YouTube",
    "twitter": "Twitter/X",
    "x": "Twitter/X",
    "pixiv": "Pixiv",
    "lofter": "LOFTER",
    "spotify": "Spotify",
    "apple_music": "Apple Music",
    "facebook": "Facebook",
    "instagram": "Instagram",
}
--- CAP1 胶囊（同一文件的注入实现见 mica_shell.py:279-380）---
```

## 十一、`/bot commands` 机器可读目录头（`domains/chat_reply/capabilities/echo.py`）
```
255:    # /bot commands：命令目录（机器可读），与 help 总览分开，不渲染卡片。
2454:# 提取共享同一份数据，防止帮助页与命令目录漂移。只登记有条目文本或项目文档依据的事实。
3513:_COMMANDS_CATALOG_QUERY = frozenset({"commands", "cmds", "命令", "命令列表", "命令目录"})
    """`/bot commands` 命令目录：机器可读纯文本，不走帮助卡渲染。

    自动生成，数据源两处，新增能力无需改本函数：
    - runtime.base_router 路由注册表（确定性路由：kind/capability/优先级）；
    - echo._HELP_ENTRIES（帮助模块：主题/别名/可见性）。
    行格式：区段头 `[名称] 字段 | 字段 | …`，数据行以 ` | ` 分隔。
    非管理员只列公开模块（与帮助总览同门控）；路由表为公开路由语义，全列。
    """
    from plugins.bot_unified_runtime.runtime.base_router import (
        list_route_rules_for_audit,
    )

    rules = sorted(list_route_rules_for_audit(), key=lambda item: int(item["priority"]))
    lines = [
        "命令目录 v1（机器可读：区段头 [名称]，数据行「字段 | 字段 | …」；模块详情 /bot help 模块名）",
```

## 十二、卡片图内文案（7 张 Jinja 模板的短行中文原文；>200 字符的 DOM 长行已滤掉，那些是结构不是文案）
### universal_card.html
```
3: mica-glass v1 2026-09-12：外壳换「釉瑚云母 + 液态玻璃 + 渐变漂移」背景层
4: （釉瑚洗由 bridge 按 --accent 派生注入；色斑/动画/随机相位见 .drift-* 与底部内联
5: 脚本）；内部版式、文字、结构不变。
41: 不在此处声明**——本模板另有一个视频卡块 :root，两者都是全局选择器，
42: 重复声明同一 token 会被契约测试判为「族内重复定义」。公共段由视频卡块
43: 唯一提供（同值，且 CSS 变量按使用处求值，与声明顺序无关）。#}
48: 不随平台色派生（链接可点性语义优先）；X 认证徽章蓝为徽章品牌语义。 */
51: 语义不随平台色派生（热评色条已占用 --accent，置顶徽章必须与之区分）。
52: 浅底 wash 优先由 color-mix 从主 token 掺白派生：
53: 装扮徽章底=12% 掺白（=#fff3e0）、置顶卡底=5% 掺白（≈#fffbf0）。 */
86: （不透明基础层，对齐官方 Mica「opaque base + 低不透明内容层」分层）。 */
102: （::before 叠 wash-1/wash-3 两枚柔光，::after 一枚 wash-2），第三枚 52s 斑由
103: DOM `<span class="drift-blob drift-c">` 承载（伪元素只有两枚；与视频分支
104: drift-c 同类同参，见门 2「色斑恒 3 枚」）；mica-stage 截图外壳与
105: video-card-shell 内层 .card 均被 :not 排除。
106: 内容全部抬到 z-index:1（仅定位，不改动版式），色斑垫底。 */
140: 下一条「子元素抬升」只应作用于内容，不该把色斑也抬到内容层。 */
371: 底色= --amber-strong 12% 掺白（=#fff3e0），收敛自模板内联样式的写死色。 */
444: wave-2 收口：散值 0.55 并入主档渐变（0.66→0.44，均值不变）。 */
594: P3-20 收口：平值 0.55 并入主档渐变（GLASS_MAIN 0.66→0.44）+ 规范描边，与
595: .glass 双背景写法逐结构一致。 */
736: 0.55 并入主档渐变（GLASS_MAIN 0.66→0.44）+ 规范描边，与 .glass 双背景
737: 写法逐结构一致。 */
911: .footer-bot-name/.footer-parser-text 两组散块）全部退役——组件样式由
912: bridge 注入的 capsule_css（mica_shell.brand_capsule_css 单一产出）供给，
913: DOM 由 capsule_html 供给（见文件尾部两处页脚摆位）。 */
929: （摆位规则留在 .footer-bottom 与视频页脚 .footer-bot-pill 两处）。 #}
936: |safe 必需：token 块含 --font-family 的双引号，autoescape 会转成 &#34;，
937: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
941: L2 面板级阴影给摘要/页脚胶囊等大件；辉光只作背景层；相邻色块三档表面
942: zebra 交替保证区分度；区分线=平台色 22% 清晰细线。 */
952: 外圈柔光由生产侧 alpha 裁剪 + 8px 余量承载。 */
972: 末层不透明托底（vis2r 修复①）：半透明 wash 直接叠在深色聊天窗上会透黑，
973: 先铺一层近白实底再透 wash，保住云母质感又不透窗。 */
997: 无 backdrop-filter（透明截图下无物可糊）；漂移色斑从玻璃后透出。 */
1000: 「粉里透蓝、蓝里透粉」；内高光渐变描边保留玻璃感。 */
1011: 三枚大型柔光色斑 = wash-1（主色斑，--accent 本相 ≤32% 混入透出平台色）/ wash-2 / wash-3，
1012: 46s/52s/58s 交错漂移+呼吸（alternate），半透明互相透过（无硬边界），
1013: 相位由 :root --phase（payload digest 钉帧）驱动；动画元素全部在 .card 内（截图裁剪安全）。 */
1016: 色斑（::before/::after，见上方「mica-glass」专项段）的 reduced-motion 关停
1017: 须另行同构保留（test_phase_determinism_2 伪元素守卫回归锁）。 */
1023: 占卜结果卡（platform="divination"）常显微版；其他通用卡缺省不渲染=零影响。
1024: 纯 CSS 静态星点：零 animation、零 JS；摆位/粒径/透明度由 --phase（payload
1025: digest，E01 已钉帧）在 Jinja 侧确定性派生（D0，同 payload 同构图）。
1026: 三通道：wash-2 星空紫 / 白 / --accent-light；alpha 0.06–0.35、粒径 2–5px、≤24 枚；
1027: 只走 background 径向渐变，不触两枚阴影 token 铁律。 */
1098: .footer-bot-pill 退化为**摆位容器**（类名保留=test_universal_card_visual 的
1099: 页脚分界锁），自身玻璃底/描边/阴影退役——胶囊自带玻璃+辉光+soft 阴影，
1100: 双层背景会打架。视频卡为大号卡体，经下列摆位微调放大胶囊一档。 */
1107: （metric-value/author-stat/author-id/author-row-timestamp/footer-media-id 既有）。 */
1138: 零影响；摆位由 --phase（payload digest）确定性派生，同 payload 同构图。 #}
1668: 「feature 空则显 Shorekeeper」占位语义作废——英文名常驻）。 #}
```
### finance_card.html
```
2: 釉瑚云母 + 液态玻璃 + 渐变漂移底（--wash-* 由 bridge 按 --accent 派生注入，
3: 金融卡无平台语境 → 守岸人品牌 accent → 纯本命洗）；分节列表 + 每行
4: （名称/数值/涨跌徽章/走势 SVG 或「暂无历史走势数据」文案）；走势 SVG 由
5: sources.finance_chart 预生成（bridge 只放行 <svg>…</svg> 整体），模板零逻辑；
6: 任何区块缺数据静默隐藏；无 <meta viewport>（全仓截图契约铁律）、body 透明
7: （omit_background 依赖）、字重 ≤700、动画仅在 .card 内、分级阴影 token；
8: 根元素带 .card（元素截图契约）。
9: vis4（2026-09-13）：行瓦片三档表面 zebra（--surface-a/b 本命淡蓝/星空紫）；
10: 分隔线统一 --divider-line；页脚胶囊叠 --glow-accent 辉光背景层。 #}
18: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
21: 产出 --semantic-danger/--semantic-success，值册 theme_tokens.SEMANTIC_*）；
22: A 股红涨绿跌语义不变，只换值的来源。 #}
26: L2 面板级阴影入册（box-shadow 档位受 vis2 瓦片审计门锁定，瓦片维持 soft 档）；
27: 辉光只作背景层；相邻色块三档表面 zebra 交替保证区分度；
28: 区分线=平台色 22% 清晰细线。 */
55: decor_css 键（mica_shell.mica_decor_css() 单一产出：三枚 46/52/58s 交错
56: 漂移+呼吸；手抄副本退役）。C13/G9 reduced-motion 关停语义由生成器内建
57: （选择器与动画声明同构、源序其后必胜）。DOM 侧 blobs_html 同法（三枚
58: .drift-blob span 的容器，原 DRIFT_BLOBS_HTML 字面）。 #}
71: 与 affinity/song 的 .glass 同配方：半透明白 + 1px 内高光渐变描边）。 */
93: 产出、bridge 注入；此前本面 .bot-foot 手抄副本退役，仅留摆位。 */
```
### market_card.html
```
2: （--wash-* 由 bridge._derive_wash_tokens 注入，守岸人本命基底）；
3: 分组网格 + 每指数行（名称/点位/涨跌额/涨跌徽章/30 日收盘折线 SVG）；
4: 折线由 Python 侧预生成 polyline points，模板零逻辑；任何区块缺数据
5: 静默隐藏；无 <meta viewport>（UI 铁律）、body 透明（omit_background 依赖）、
6: 字重 ≤700、动画仅在 .card 内、两枚阴影 token。
7: C 方向统一（2026-09-12）：根元素带 .card（render_backends 元素截图
8: 选择器契约）；无历史走势的指数展示
9: trend_note（MOEX「暂无历史走势数据」），不伪造折线；脚注展示数据源/
10: 数据时间/延迟提示。
11: vis4（2026-09-13）：指数瓦片三档表面 zebra（--surface-a/b 本命淡蓝/星空紫）；
12: 分隔线统一 --divider-line；页脚胶囊叠 --glow-accent 辉光背景层。 #}
20: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
23: 产出 --semantic-danger/--semantic-success，值册 theme_tokens.SEMANTIC_*）；
24: A 股红涨绿跌语义不变，只换值的来源。 #}
28: L2 面板级阴影入册（box-shadow 档位受 vis2 瓦片审计门锁定，瓦片维持 soft 档）；
29: 辉光只作背景层；相邻色块三档表面 zebra 交替保证区分度；
30: 区分线=平台色 22% 清晰细线。 */
57: decor_css 键（mica_shell.mica_decor_css() 单一产出：三枚 46/52/58s 交错
58: 漂移+呼吸；手抄副本退役）。C13/G9 reduced-motion 关停语义由生成器内建
59: （选择器与动画声明同构、源序其后必胜）。DOM 侧 blobs_html 同法（三枚
60: .drift-blob span 的容器，原 DRIFT_BLOBS_HTML 字面）。 #}
71: 与 affinity/song 的 .glass 同配方：半透明白 + 1px 内高光渐变描边）。 */
96: 单一产出、bridge 注入（辉光背景层+玻璃页脚档+pill 圆角全部 var() 消费
97: root tokens）；此处只留摆位。此前本面 .bot-foot 手抄副本退役。 */
```
### affinity_card.html
```
2: 走 --accent / color-mix 派生；阴影=分级族 token；body 透明（截图 omit_background 依赖）。
3: mica-glass v1 2026-09-12：视觉层换「釉瑚云母 + 液态玻璃 + 渐变漂移」——
4: 底色/色斑用 --wash-*（釉瑚云母底主题 token，全卡统一，bridge 按 --accent 派生注入；
5: 工艺出处=用户裁定），--accent 退为徽章/进度/档位 accent；面板半透明白玻璃 +
6: 1px 内高光渐变描边；三枚 wash 柔光色斑缓慢漂移（内联脚本随机相位）；
7: 档位/排行循环渲染，不写死行数与档名，payload 契约不变。
8: vis4（2026-09-13）：相邻瓦片/面板三档表面 zebra（--surface-a/b 本命淡蓝/星空紫）；
9: 分隔线统一 --divider-line；页脚胶囊叠 --glow-accent 辉光背景层。
10: v21r3（2026-09-18 misc 席）：C4 语义色删本地私设改消费 root tokens 单源；
11: C3 行面 0.62→0.66 + 描边归一三档（accent 着色保留）。
12: v21r3 通水（2026-09-19 misc2 席）：色斑 CSS/DOM 换血生成器单源（bridge
13: ._vis4_context 注入 decor_css/blobs_html）；壳层/.glass 主规则仍手写
14: （受 visual_audit 门钉字面约束，归 GATES 门演进后切换）。 #}
22: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
31: L2 面板级阴影入册（box-shadow 档位受 vis2 瓦片审计门锁定，瓦片维持 soft 档）；
32: 辉光只作背景层；相邻色块三档表面 zebra 交替保证区分度；
33: 区分线=平台色 22% 清晰细线。 */
42: v21r3 C4：值本已合规（=SCORE_HOT/SCORE_COLD），本地私设删除，
43: 改消费 root tokens 单源（render_root_tokens 注入 --score-hot/--score-cold）。 */
55: wash-3 只作第三色透底（不透明基础层）；色斑垫底、内容抬升 ===== */
77: 注入 decor_css；三斑几何/时长/keyframes/reduced-motion 生成器产出）。 */
80: 纯 CSS 静态星点：零 animation、零 JS；摆位/粒径/透明度由 --phase（payload
81: digest，E01 已钉帧）在 Jinja 侧确定性派生（D0，同 payload 同构图）。
82: 三通道：wash-2 星空紫 / 白 / --accent-light；alpha 0.06–0.35、粒径 2–5px、≤24 枚、
83: 总覆盖 ≤ 卡面 8%；只走 background 径向渐变，不触两枚阴影 token 铁律。 */
191: 产出、bridge 注入；此前本面 .bot-foot 手抄副本退役，仅留摆位。 */
200: bot_to_user ≥ 50（挚友/独一份）为「高级位档」触发；摆位由 --phase
201: （payload digest）确定性派生，同 payload 同构图。 #}
```
### error_card.html
```
2: 统一诊断卡。云母契约全门：釉瑚云母 + 液态玻璃 + 渐变漂移底（--wash-* 由
3: bridge 按 ERROR_THEME 派生注入，mist 保持守岸人本命打底，--accent=语义红强调）；
4: 头部徽标「运行异常」+守岸人徽记 → 人话区 → 触发回显 → 栈摘录（等宽暗底）→
5: 触发方法/配置快照/版本构建/平台协议/IDs 分区（玻璃瓦片 zebra）→ 求助指引
6: 辉光页脚。无 <meta viewport>（全仓截图契约铁律）、body 透明（omit_background
7: 依赖）、字重 ≤700、动画仅在 .card 内、分级阴影 token、根元素带 .card
8: （元素截图契约）。 v21r3（2026-09-18 misc 席）：C2 补第三枚 drift-c（52s，
9: wash_blob_mix=24 豁免保持）；C7 行高 1.65→1.6；E03 字距 0.04/0.08→0.06em、
10: IDs 数值 tabular-nums；C9/C5 玻璃/遮罩/等宽改消费 root tokens 单源。
11: v21r3 通水（2026-09-19 misc2 席）：色斑 CSS/DOM 换血生成器单源（bridge
12: ._vis4_context 注入 decor_css/blobs_html）。wash_blob_mix=24 豁免不受影响：
13: 该参数只作用于 :root 的 --wash-blob-1 token（bridge 对本卡 _card_root_tokens
14: 传 24，测试锁 test_mica_shell::test_root_tokens_wash_blob_mix_parametrizable），
15: 生成器 drift-a 渐变消费 var(--wash-blob-1)，混合比随 token 走，decor 键无需
16: 参数化；壳层仍手写（归壳层席）。 #}
24: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
36: （theme_tokens.MONO_FONT_STACK 经 render_root_tokens 注入 --font-mono）。 */
56: 注入 decor_css；wash_blob_mix=24 豁免走 :root token 面，见头注释）。 */
113: 产出、bridge 注入；本卡额外留求助文案（在胶囊右侧）。此前 .bot-foot 手抄
114: 副本（bf-avatar/bf-dot/bf-name/help-text 合体）退役。 */
```
### mermaid_card.html
```
2: 走 --accent 派生 token；Mica 铁律 —— 无 <meta viewport>、.card 用 fit-content、
3: body 透明（截图 omit_background 依赖）、分级阴影族 token、字重≤700。
4: mermaid.min.js 的 src 保持 jsDelivr CDN URL 不变（模板零分叉），传输层由
5: render_backends 渲染期 page.route() 拦截换血为本地素材
7: 落盘；素材缺失即放行网络），startOnLoad 自动把 code 渲成 SVG。
8: mica-glass v1 2026-09-12：釉瑚云母底（bridge 按中性灰派生的 --wash-* 注入；
9: 工艺出处=用户裁定）+ 1px 内高光渐变描边 + 三枚 wash 柔光色斑缓慢漂移
10: （--phase 由 root tokens 钉帧）。
11: v21r3（2026-09-18 misc 席）：色斑由双伪元素改三枚 DOM 斑（C2 恒 3 枚
12: 46/52/58s；动画仍在 .card 子树内，fit-content 壳零版面影响）。
13: v21r3 通水（2026-09-19 misc2 席）：decor_css 换血生成器单源——
14: bridge._vis4_context 注入 decor_css（mica_shell 缺省实例）。
15: v21r3 回归（2026-09-19 misc3 席）：本卡色斑复位 .card::before/::after
16: 伪元素两斑——契约钉死 mermaid 是伪元素特例（test_rendering_contract
18: test_phase_determinism_2 伪元素守卫两回归锁：默认观感动画必须真跑、
19: prefers-reduced-motion 必须真关停）；blobs_html DOM 斑不再入卡
20: （防双斑叠印），decor_css 保留=keyframes mica-drift-a/b 单源供给。
21: vis4（2026-09-13）：外壳与页脚迁社交卡标准——页脚胶囊叠 --glow-accent
22: 辉光背景层 + L2 面板级阴影（mermaid 不在 vis2 瓦片审计门清单内）；
23: SVG 图形内部零触碰。 #}
31: FONT_FAMILY_STACK 全栈逐字字面量（GATES 门 8 白名单按归一化逐字比对）。
32: 通水后可换血为 bridge 注入的模板变量（INTG 裁决）。 #}
43: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
48: L2 面板级阴影给页脚胶囊等大件；辉光只作背景层；三档表面 zebra 备用；
49: 区分线=平台色 22% 清晰细线。 */
89: 几何/渐变/时长/相位延迟与 mica_shell 生成器 drift-a/drift-b 同构；
90: keyframes 单源消费下方 decor_css 产出（mica-drift-a/b）。
91: reduced-motion 守卫与基线同特异性 (0,1,1) 且源序靠后（同特异性靠
92: 源序取胜，防 finance/market 型死 CSS）；本守卫必须先于 decor_css
93: 的 DOM 斑守卫出现（test_phase_determinism_2 取首个 media 块断言）。 */
125: 注入 decor_css；@keyframes mica-drift-a/b 供上方伪元素消费；其 DOM 斑
126: 规则/守卫在本卡无 DOM 命中，属生成器整层供给的惰性面，零视觉影响）。 */
141: 产出、bridge 注入；此前本面 .bot-foot 手抄副本退役（本卡头像位首次补齐——
142: bridge 经 bot_avatar_uri 单一入口取图，缺失自动回「守」字圆点）。 */
```
### song_candidates.html
```
3: 釉瑚云母底（bridge 按 --accent 派生的邻近 pastel 洗，禁纯色）+ 液态玻璃面板
4: （半透明白 + 1px 内高光渐变描边，无 backdrop-filter）+ wash 三枚柔光色斑
5: 缓慢漂移；--accent 退为 accent；payload 契约与 DOM 数据绑定结构原样保留。
6: vis4（2026-09-13）：候选行三档表面 zebra（--surface-a/b 本命淡蓝/星空紫）；
7: 分隔线统一 --divider-line；.foot 与页脚胶囊叠 --glow-accent 辉光背景层。
8: v21r3（2026-09-18 misc 席）：C3 玻璃主档 0.68→0.66、页脚档归一 GLASS_FOOT
9: （0.68/0.50→0.66/0.46）；C8 字号 12.5→12px。
10: v21r3 通水（2026-09-19 misc2 席）：色斑 CSS/DOM 换血生成器单源（bridge
11: ._vis4_context 注入 decor_css/blobs_html）；壳层/.glass 主规则仍手写
12: （受 visual_audit 门钉字面约束，归 GATES 门演进后切换）。 -->
18: 底色/色斑唯一来源：--wash-*（釉瑚云母底主题 token，全卡统一，
19: bridge._derive_wash_tokens 按 --accent 派生注入；工艺出处=用户裁定）；
21: 阴影=分级族 token（shell/soft 固有两枚 + vis4 panel 级经 bridge 注入）。 */
24: 而 <style> 内的实体不会被解码 → 字体族静默失效。#}
29: L2 面板级阴影入册（box-shadow 档位受 vis2 瓦片审计门锁定，瓦片维持 soft 档）；
30: 辉光只作背景层；相邻色块三档表面 zebra 交替保证区分度；
31: 区分线=平台色 22% 清晰细线。 */
65: 色斑垫底，玻璃内容抬升 ===== */
87: 注入 decor_css；三斑几何/时长/keyframes/reduced-motion 生成器产出）。 */
221: border/阴影沿用 .glass 既有配方）。 */
229: 产出、bridge 注入；此前本面 .bot-foot 手抄副本退役，仅留摆位。 */
```

## 十三、最容易漂的「多份真相」点（审核时优先打这几处）
1. **统计标签四处各一份**：`universal_card.html` L1342-1362（主块）/ L1526-1534（转发块）/ L1587-1593（再转发块）三份手写「播放/弹幕/赞/收藏/硬币/评论/转发…」，而 `bridge.py:557-590` 另有一整套「平台×指标」标签注册表 + `:594-596` 抖音覆盖表（shares→「分享」）。同一语义四份真相，注册表改了模板不会跟。
2. **ID 标签两套命名**：`bridge.py:1052-1058` 用「动态ID/番剧ID/商品ID/视频ID」（带 ID 后缀），`universal_card.html:1266-1271` 用「动态/帖子/视频/直播/空间/收藏夹」（不带）。同一张卡两行相邻而口径不同。
3. **bot 中文名缺省值散落**：`bridge.py:1509/1585/1642/1727/1796` 五处 `or "守岸人"` 字面量 + `templates.py:140` + `usage_cards.py:83`，而 `BRAND_THEME.display_name` 才是登记过的单一来源（`bridge.py:1537` 已用它，其余没用）。
4. **英文名旧兜底未收**：`theme_tokens.py:42 BRAND_NAME_EN="Shorekeeper"` 是 CAP1 新立的单一源，但 `templates.py:204` 与 `universal_card.html:1227` 仍各写一份 `"Shorekeeper"` 兜底 → 收口进行中的已知残余。
5. **页脚胶囊四份 DOM**（收口中）：`universal_card.html:1227` footer-bot-pill、`templates.py:195-205`、`usage_cards.py:208-212`、`error_card.html:197-198` bot-foot → 唯一实现已落在 `mica_shell.py:307-380 brand_capsule_html/css`。
6. **「五池」实际住三个文件**：人格失败池 `chat.py:617-630`、错误卡冷却池 `error_report.py:91-104`、管理员门禁池 + 数据源失败池 + 群失败 ack 池 `user_copy.py:29-91`。查「哪些话术是池、哪些是单点」必须三处一起看。
7. **`output/plain_text.py` 只有 1-3 行，是垫片**；真身在 `domains/render/plain_text.py`。按旧路径改文案＝改了个空壳，看起来生效其实没生效（v21r2 垫片退役未完工期内的通用陷阱）。
8. **求助指引是有意双份**：`error_report.py:111-120` 卡页脚版与纯文本版措辞不同（无图时「这张图」会悬空）。这不是漂，是设计——别顺手合并。
9. **`/bot commands` 机器可读格式**（`echo.py:3517-3531`）与 `/bot help` 卡、`COMMANDS.md`、`docs/command-catalog.md` 四路同源不同体，改 `_HELP_ENTRIES` 会牵动生成物同步门。

## 十四、本次审核口径（哪些**不是**出站文案）
- `personas/**` 与 `character/providers.py` 13 分区 = 发给 LLM 的提示词，不是发给用户的模板。
- `result_unknown` / SendQueue part 幂等 / `runtime/alerts` 台账 = 内部语义，无用户可见句子。
- Telegram 侧**不存在** Markdown/HTML 转换模板与链接预览开关文案（正文纯文本直发）；长文分段由 `domains/render/renderer.py` chunks 完成，不在适配层。
- 每日通讯总结（digest）**不走邮件**、无邮件主题模板；邮件唯一主题模板是回复侧 `Re: {subject}`（`nonebot.py:316-320`）。
