"""V2.1 错误注册表：全系统错误码单一注册源（S2 协议席）。

合同来源：
- docs/design/backend-v2-implementation-guide.md §6 错误表（「错误目录为单一注册源」）
- docs/design/backend-v2-product-extensions.md 补充错误集中注册段

设计约束（V21-CORE-001）：
- 本模块只依赖标准库（dataclasses/datetime/uuid/random），连 pydantic 都不碰；
  error_envelope 产出的 dict 由 contracts/envelope.py 的严格模型负责校验，
  两侧契约漂移会被 tests/test_contracts_v21.py 的往返断言拦下。
- 每条注册：code / http 状态（delivery_unknown 按规范以任务/part 状态暴露，
  不映射顶层 HTTP，故为 None）/ retryable 默认 / 人话 message 模板
  （守岸人语气、不泄露内部细节、可操作）。
- 旧码兼容映射留接口：LEGACY_CODE_ALIASES + resolve_code；别名目标在导入期
  自检必须存在于注册表，防漂移。

E1（2026-10-02）错误话术升变体池：
- `message_template` **逐字不动**——它是错误目录里的规范句，也是
  `tests/test_copy_single_source.py` 在册重复簇的 home（改了＝别人登记的簇凭空
  消失，另一份副本还活着），更是 OpenAPI `ERROR_RESPONSES` 派生的取材处。
- 变体不住在枚内，住在**失败族池** `ERROR_COPY_POOLS`：41 枚码按失败语义收进
  `ERROR_COPY_FAMILY` 的 10 个族，每族 ≥15 条语气外壳，壳里只有一个 `{detail}`
  槽，槽内填该码的规范句（先插值占位符、再装壳）。这样做的三条理由：
  ①41×15＝615 句逐码手写既不可核也不可信，族壳是能被门数清楚的最小单位；
  ②码级语义（可操作指引）一条不许在换壳时丢失，所以细节句永远整句在场；
  ③`random.choice(池)` 是本仓既有的取句原身之一（见
  `docs/design/outbound-template-unification-spec.md` §一.2 四套并存清单 ①），
  本席**不新增第五套选池 API**；`errors.py` 受"只依赖标准库"契约约束，
  键控游标那份（`domains/assistant/daily/store/daily_assist.py:pick_variant`）
  请进来就是破坏契约并留一条跨域装配环，故不引。取句语义统一（会话游标
  vs 随机 vs 稳定散列）在该规格 §四.3 仍是**待用户裁定项**，本席不擅自定调。
- 导入期自检只查**结构**（族在册、槽恰一次、码全覆盖），条数下限交给 pytest 门
  `tests/test_error_copy_pool_gate.py`——条数是一篇文案的事，不该让生产启动为它抛错。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class UnknownErrorCodeError(KeyError):
    """请求了注册表中不存在的错误码。"""


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    # None = 不映射顶层 HTTP（如 delivery_unknown：按任务/part 状态暴露）。
    http_status: int | None
    retryable: bool
    # 人话模板；{占位符} 由调用方字段插值，缺失占位符保持字面量不抛错。
    message_template: str


_ERROR_SPECS: tuple[ErrorSpec, ...] = (
    # ---- 主规范 §6 错误表 ----
    ErrorSpec("unauthenticated", 401, False, "我还认不出你是谁，请先完成登录再来找我吧。"),
    ErrorSpec("permission_denied", 403, False, "这件事超出了你现在的权限，先到这里为止了。"),
    ErrorSpec("resource_not_found", 404, False, "要找的东西不存在，或者不属于你能看到的范围。"),
    ErrorSpec("validation_error", 422, False, "有些内容没有通过检查，请按提示修正后再试一次。"),
    ErrorSpec("unsupported_parameter", 422, False, "这个选项这里用不上，请核对可用的参数。"),
    ErrorSpec("content_rejected", 422, False, "这份内容我没有办法受理，请调整后再发给我。"),
    ErrorSpec("unsupported_format", 415, False, "这种格式我还读不了，请换成支持的格式。"),
    ErrorSpec("version_conflict", 409, False, "内容刚被更新过了（当前版本 {expected_version}），请刷新最新状态再操作。"),
    ErrorSpec("idempotency_conflict", 409, False, "这个请求键已经绑定过别的内容，请换一个键或核对原文。"),
    ErrorSpec("confirmation_required", 409, False, "这一步需要你先确认才能继续，请先完成确认。"),
    ErrorSpec("confirmation_expired", 409, False, "确认已经过期了，请重新确认一次。"),
    ErrorSpec("feature_disabled", 409, False, "这个功能现在处于关闭状态，请先启用后再使用。"),
    ErrorSpec("cancel_not_supported", 409, False, "这件事不支持取消，我只能如实告诉你，不会假装取消成功。"),
    ErrorSpec("rate_limited", 429, True, "节奏有点太快了，稍等片刻再来找我就好。"),
    ErrorSpec("capacity_exceeded", 429, True, "现在有点忙不过来，请稍后再试。"),
    ErrorSpec("dependency_unavailable", 503, True, "上游服务暂时不在，我先停在这里，等恢复了再继续。"),
    ErrorSpec("sandbox_unavailable", 503, True, "隔离沙盒暂时不可用，相关操作先停下来了。"),
    ErrorSpec("provider_auth_failed", 503, False, "上游的凭据没有通过验证，需要管理员检查后再继续。"),
    ErrorSpec("storage_unavailable", 503, True, "存储暂时不可用，相关写入先停下了，稍后会恢复。"),
    ErrorSpec("provider_rate_limited", 503, True, "上游在限流，我会按它的节奏等待，稍后再继续。"),
    ErrorSpec("resource_limit_exceeded", 503, True, "资源额度用完了，等回收释放之后再继续。"),
    ErrorSpec("integrity_mismatch", 503, False, "数据校验对不上，相关内容已隔离保存，请先排查来源。"),
    ErrorSpec("reload_failed", 503, True, "这次重载没有完成，旧版本仍在正常服务，可以再试一次。"),
    ErrorSpec("rollback_failed", 503, False, "回退没有成功，系统已停在安全状态，请尽快人工处理。"),
    ErrorSpec("deadline_exceeded", 504, True, "等得太久了，这次先停在这里，需要的话可以重新发起。"),
    ErrorSpec("output_contract_violation", 502, False, "这次输出没有通过格式检查，已按约定做了兜底处理。"),
    ErrorSpec("delivery_unknown", None, False, "发送结果还不确定，需要先对账确认，而不是盲目重发。"),
    # ---- 扩展补充码（backend-v2-product-extensions.md）----
    ErrorSpec("usage_inconsistent", 502, False, "用量账目对不上，先挂起核对，不会把异常掩盖成零。"),
    ErrorSpec("price_unavailable", 503, False, "这个模型暂时没有可靠价格，付费任务先不受理。"),
    ErrorSpec("budget_exceeded", 429, False, "预算已经用完了，需要新的授权才能继续。"),
    ErrorSpec("affinity_unit_mismatch", 422, False, "好感度数据的计量单位对不上，先停在这里，不做折算猜测。"),
    ErrorSpec("affinity_evidence_missing", 409, False, "这次好感度变化缺少依据，先按中性处理，不凭空加减。"),
    ErrorSpec("invalid_spread", 422, False, "这次的牌面组合不成立，请重新抽取一次。"),
    ErrorSpec("deck_integrity_mismatch", 503, False, "牌库校验对不上，先停用整理，不拿坏牌占卜。"),
    ErrorSpec("schedule_cycle", 422, False, "安排里存在循环依赖，请先解开这个环。"),
    ErrorSpec("missing_calendar", 409, False, "缺少对应的日历，请先补齐再来安排。"),
    ErrorSpec("ambiguous_local_time", 422, False, "这个时间点有歧义，请指定得更明确一些。"),
    ErrorSpec("schedule_conflict", 409, False, "这个安排和已有日程冲突，请调整一下时间。"),
    ErrorSpec("occurrence_expired", 409, False, "这一项已经过期了，请重新创建新的安排。"),
    ErrorSpec("unsupported_platform_capability", 422, False, "这个平台暂时做不到这件事，我不会假装发送成功。"),
    ErrorSpec("acceptance_authorization_expired", 403, False, "验收授权已经过期，请重新授权后再继续。"),
)

ERROR_REGISTRY: dict[str, ErrorSpec] = {spec.code: spec for spec in _ERROR_SPECS}

# ---------------------------------------------------------------------------
# 失败族话术壳（E1 2026-10-02）：错误目录的规范句是「事实」，族壳是「怎么说」。
# 壳里唯一的槽是 ``{detail}``，装该码的规范句；每族 ≥15 条由
# ``tests/test_error_copy_pool_gate.py`` 数着（低于下限即红，新增族不足即红）。
# 语气纪律：长句、不指责用户、意象一条最多一处且只用设定内名词（潮/浪/岸/夜/光
# 一类语素），日常话混在里头；绝不出现异常名、路径、配置键名。
# ---------------------------------------------------------------------------

#: 族壳池（族键 → 变体）。第一条恒为 ``"{detail}"``＝裸规范句，是文案快照与
#: 逐字节对拍的锚（改它=改契约，走 ``tests/test_user_copy_pool.py`` 同法快照）。
ERROR_COPY_POOLS: dict[str, tuple[str, ...]] = {
    # 身份与权限：认不出、越不过、授权过期。
    "identity": (
        "{detail}",
        "这一步我先停在门口。{detail}",
        "我认不得人就不办事，这是我给自己定的规矩。{detail}",
        "不是守岸人不肯帮你，是我这边真推不开这扇门。{detail}",
        "先把此刻的状态如实说清楚。{detail}",
        "这条请求我接住了，但没有让它往前走。{detail}",
        "越过去并不难，难的是越过去那一步我没法替你负责。{detail}",
        "这件事我不能装作已经允许了。{detail}",
        "名分不到的地方，我只做名分之内的部分。{detail}",
        "先别急，问题不在你说了什么。{detail}",
        "我核对过两遍，这一条的凭据落不到我能承认的位置。{detail}",
        "潮水往哪边走是它的事，我只按该认的认。{detail}",
        "我把话说得直白一些。{detail}",
        "等我认清是谁在问，这一段马上接着往下走。{detail}",
        "这一条我先记着，等到能应的时候一定应。{detail}",
    ),
    # 可见范围：找不到，或不在你能看的这一侧。
    "visibility": (
        "{detail}",
        "我顺着你给的方向找了一圈，那里是空的。{detail}",
        "先把我找到的结果报给你。{detail}",
        "我没有编一个「存在」的样子出来。{detail}",
        "这一条我没能定位到，不该由我猜。{detail}",
        "能翻的范围我翻过两遍了。{detail}",
        "看不见的东西，我不会假装看见。{detail}",
        "先如实说一句。{detail}",
        "它也许在别人的视野里，只是不在我们这一侧。{detail}",
        "找不到的时候我只报找不到，多写的每一句都是编。{detail}",
        "浪把这一格带走的时候没留记号。{detail}",
        "这一条我手里没有对应的档案。{detail}",
        "换个说法我再找一次，好吗。{detail}",
        "把标识再给我一次，我从头对一遍。{detail}",
        "线索我留在原处了，接着往下走要新的抓手。{detail}",
    ),
    # 输入不合检查：内容、参数、格式、时间口径与单位。
    "input_validation": (
        "{detail}",
        "内容我读了，卡在了检查这一关。{detail}",
        "先不猜你要什么，把不合的地方说清楚。{detail}",
        "这一步我没有替你改写，改写就容易改错意思。{detail}",
        "我把不合的地方留下了原样。{detail}",
        "照着提示补一处就能过，不必重来。{detail}",
        "这里差一点就能成，差的那一点是有形的。{detail}",
        "这一处我拿不准你的意思，猜对了也是错。{detail}",
        "单位对不齐时我不硬凑，凑出来的齐是假的。{detail}",
        "我照着给的形态摆过一次，摆不成。{detail}",
        "这一处我不肯替你猜着补齐。{detail}",
        "不是不想按你说的做，是这样做出来的东西我不敢交。{detail}",
        "把这一处再讲明确些，我立刻接着办。{detail}",
        "我先停在检查线上，不带着毛病往下走。{detail}",
        "这条我记下了形态，等你补一处就能重跑。{detail}",
    ),
    # 状态冲突：版本、幂等键、确认、日程撞车与过期。
    "state_conflict": (
        "{detail}",
        "状态刚变过，我不敢拿旧的往下写。{detail}",
        "先停一秒，这里有两个版本在抢同一个位置。{detail}",
        "这一条我不覆盖别人的结果，也不让人覆盖你。{detail}",
        "确认这一步是给你留的，我替不了。{detail}",
        "过期不是失败，是它等到了新的一轮。{detail}",
        "再点一次确认，我这边立刻接上。{detail}",
        "我把这一条按原样收着，没有偷偷改。{detail}",
        "两件事撞在同一处，我只好不选边。{detail}",
        "结成的环我不硬拆，拆的时候会把你的意思拆丢。{detail}",
        "把这一处理顺，剩下的我一路替你走完。{detail}",
        "同一刻挂着两件，我不敢替你挑哪件作数。{detail}",
        "这一条过了它的时刻，新的我另外起。{detail}",
        "缺的那一样补上，这一段就能落。{detail}",
        "先照最新的样子刷新一次，再往下走。{detail}",
    ),
    # 能力边界：功能关着、不支持取消、平台做不到。
    "capability_boundary": (
        "{detail}",
        "这一扇门现在是关的，我没有钥匙。{detail}",
        "开关不在我这一侧，所以我先说明现状。{detail}",
        "这件事此刻做不到，我不做样子给你看。{detail}",
        "假装成功比失败更难收拾，我不做。{detail}",
        "我如实回你，不改成你爱听的形状。{detail}",
        "把它启用之后，这一段我立刻接着办。{detail}",
        "平台的边界在这里，我这一侧没有另一条路。{detail}",
        "取消这一支我确实没有，所以我不答「已取消」。{detail}",
        "能做的那部分我先做，做不到的原样说。{detail}",
        "这一条要等它被打开，等的时候我不替你猜。{detail}",
        "先跟你交底。{detail}",
        "我把这条边界守在原地，不往里挪半步。{detail}",
        "换一个能做到的入口，我陪你再试一次。{detail}",
        "这件事我不会含含糊糊地应下来。{detail}",
    ),
    # 节奏与容量：限流、超载、额度与预算。
    "throughput": (
        "{detail}",
        "我先把手放慢一些。{detail}",
        "这一条我接住了，只是没能立刻送出去。{detail}",
        "排队不是拒绝，等一下就到。{detail}",
        "同一刻的话太多，我一条一条渡。{detail}",
        "额度见底的时候我不硬撑，硬撑就要出错。{detail}",
        "等一会儿再叫我，我还在这儿。{detail}",
        "这一刻的浪有点挤，我先让它们在前面排好。{detail}",
        "我把这一条留在了队列里，没有丢。{detail}",
        "该在的那一格里还空着，我等它补上就继续。{detail}",
        "慢一点不要紧，走歪了才要紧。{detail}",
        "先缓这口气，下一条我照单接。{detail}",
        "这一轮我腾不出手，下一轮一定有你。{detail}",
        "把节奏松一松，我就能把事办稳。{detail}",
        "资源回收回来之后，这一段自动能走。{detail}",
    ),
    # 上游与依赖：服务不在、沙盒不可用、凭据、存储与校验。
    "dependency": (
        "{detail}",
        "我这边稳的，是外面那一跳此刻没应。{detail}",
        "上游没回话，我就不假装它回了。{detail}",
        "这一条我停在依赖前，不带着未知往下写。{detail}",
        "等它回来，我接着把这一段做完。{detail}",
        "没有那道保险的时候，我不让事情裸着往前走。{detail}",
        "这一关的门没开，我没有硬闯。{detail}",
        "落不下去的时候，我先把已经有的内容保住。{detail}",
        "没核对过的结果，我不往前递。{detail}",
        "坏了的那一份我留在原地等查，不拿来用。{detail}",
        "这一处要有人看一眼，我在这一侧看不清。{detail}",
        "我把这次的痕迹留在日志里，等会儿就能对。{detail}",
        "潮退下去的时候船会搁浅，等它回来就好。{detail}",
        "这一跳我重试过了，还是没通。{detail}",
        "先按现状告诉你，坏消息也是消息。{detail}",
    ),
    # 重载与回退：热重载、回滚。
    "lifecycle": (
        "{detail}",
        "新版本没能站起来，旧的还在守着。{detail}",
        "我没有让半成品接你的话。{detail}",
        "这一步要人来推一下，我推不动那一侧。{detail}",
        "状态我停在安全的那一边，没有继续试。{detail}",
        "宁可慢一轮，也不让你在坏的版本里等。{detail}",
        "重载这一趟没走完，我再等一次机会。{detail}",
        "我先保住已经在跑的那一份。{detail}",
        "退不回去的时候，最要紧的是别再动。{detail}",
        "这一处需要有人看一眼再继续。{detail}",
        "我把现场原样留着，改动没有落下去。{detail}",
        "等管理员那边点一下头，这条路就通。{detail}",
        "先如实报这一轮的结局。{detail}",
        "这条线我拦住了，没让它把旧的冲掉。{detail}",
        "安全的位置我守着，等新的指令。{detail}",
    ),
    # 时限：整条链路等过头。
    "deadline": (
        "{detail}",
        "这一条我把时间用完了才停。{detail}",
        "等到最后一刻还是没回音，我先收住。{detail}",
        "不是不办了，是这一轮的钟走完了。{detail}",
        "重发一次，我从头再走这一趟。{detail}",
        "我不让一条已经超时的请求继续占着位置。{detail}",
        "每一跳都没能在预算里回来。{detail}",
        "再试一次，有时候只是慢了一步。{detail}",
        "夜里的潮会有错过的时刻，下一班还在。{detail}",
        "先停在这里，比拖到出错要好。{detail}",
        "这条我先记下起止，回头能查。{detail}",
        "链上哪一跳慢，日志里有痕迹。{detail}",
        "给我一次重新发起的机会。{detail}",
        "这一次的时间不是我愿意花完的。{detail}",
        "如实报一句。{detail}",
    ),
    # 契约与账目：输出不合契约、用量、价格、投递未知。
    "contract": (
        "{detail}",
        "形状不对的东西我不往外递。{detail}",
        "这一份我兜住了，没让它原样出去。{detail}",
        "账目对不上时，我宁可挂着也不写零。{detail}",
        "没有可靠数的时候，我不编一个填进去。{detail}",
        "发没发出去这件事，我不敢替你确认。{detail}",
        "先对账，再决定要不要重发，这是两回事。{detail}",
        "回执没读到的那一段，我留着待核。{detail}",
        "付费的那一条我先按住，等一个可靠的数。{detail}",
        "这一跳的返回不合契约，我按缺席记。{detail}",
        "宁可空着，不拿估算冒充报价。{detail}",
        "把这次的原样留了档，下次能对着查。{detail}",
        "结果未知的时候，重发是第二个风险。{detail}",
        "我先说清楚我确切知道的边界。{detail}",
        "这一条要走到能对账那一步才算完。{detail}",
    ),
}

#: 41 枚注册码 → 失败族（族壳只换语气，不改语义；语义住 ``message_template``）。
ERROR_COPY_FAMILY: dict[str, str] = {
    "unauthenticated": "identity",
    "permission_denied": "identity",
    "acceptance_authorization_expired": "identity",
    "resource_not_found": "visibility",
    "validation_error": "input_validation",
    "unsupported_parameter": "input_validation",
    "content_rejected": "input_validation",
    "unsupported_format": "input_validation",
    "ambiguous_local_time": "input_validation",
    "affinity_unit_mismatch": "input_validation",
    "invalid_spread": "input_validation",
    "schedule_cycle": "input_validation",
    "version_conflict": "state_conflict",
    "idempotency_conflict": "state_conflict",
    "confirmation_required": "state_conflict",
    "confirmation_expired": "state_conflict",
    "schedule_conflict": "state_conflict",
    "occurrence_expired": "state_conflict",
    "missing_calendar": "state_conflict",
    "affinity_evidence_missing": "state_conflict",
    "feature_disabled": "capability_boundary",
    "cancel_not_supported": "capability_boundary",
    "unsupported_platform_capability": "capability_boundary",
    "rate_limited": "throughput",
    "capacity_exceeded": "throughput",
    "provider_rate_limited": "throughput",
    "budget_exceeded": "throughput",
    "resource_limit_exceeded": "throughput",
    "dependency_unavailable": "dependency",
    "sandbox_unavailable": "dependency",
    "provider_auth_failed": "dependency",
    "storage_unavailable": "dependency",
    "integrity_mismatch": "dependency",
    "deck_integrity_mismatch": "dependency",
    "reload_failed": "lifecycle",
    "rollback_failed": "lifecycle",
    "deadline_exceeded": "deadline",
    "output_contract_violation": "contract",
    "usage_inconsistent": "contract",
    "price_unavailable": "contract",
    "delivery_unknown": "contract",
}

# 旧码兼容映射：{旧码: 现行码}。目标必须在 ERROR_REGISTRY 中（下方导入期自检）。
LEGACY_CODE_ALIASES: dict[str, str] = {}

for _alias, _target in LEGACY_CODE_ALIASES.items():
    if _target not in ERROR_REGISTRY:
        raise RuntimeError(f"旧码别名 {_alias!r} 指向未注册的错误码 {_target!r}")

# 结构自检（E1）：只查形态，条数下限归 pytest 门（文案量不该让启动抛错）。
# ①每枚注册码必须落进一个在册族——漏一枚＝那条错误话术在池外裸奔单句；
# ②每条壳必须恰好一次 ``{detail}``——零次会吞掉码级语义，两次以上多半是笔误；
# ③不许有没被任何码引用的族（幽灵池会骗过「按族数条数」的门）。
for _code in ERROR_REGISTRY:
    _family = ERROR_COPY_FAMILY.get(_code)
    if _family not in ERROR_COPY_POOLS:
        raise RuntimeError(f"错误码 {_code!r} 未登记失败族或族未注册：{_family!r}")
for _family, _variants in ERROR_COPY_POOLS.items():
    if not any(value == _family for value in ERROR_COPY_FAMILY.values()):
        raise RuntimeError(f"失败族 {_family!r} 没有任何错误码引用（幽灵池）")
    if _variants and _variants[0] != "{detail}":
        raise RuntimeError(f"失败族 {_family!r} 首条必须是裸 \"{{detail}}\"（快照锚）")
    for _variant in _variants:
        if _variant.count("{detail}") != 1:
            raise RuntimeError(f"失败族 {_family!r} 的壳必须恰含一处 {{detail}}：{_variant!r}")
        _stripped = _variant.replace("{detail}", "")
        if "{" in _stripped or "}" in _stripped:
            raise RuntimeError(f"失败族 {_family!r} 的壳带了 detail 之外的占位符：{_variant!r}")


def iter_error_codes() -> tuple[str, ...]:
    return tuple(ERROR_REGISTRY)


def get_error_spec(code: str) -> ErrorSpec:
    spec = ERROR_REGISTRY.get(resolve_code(code))
    if spec is None:  # pragma: no cover - resolve_code 已保证
        raise UnknownErrorCodeError(code)
    return spec


def resolve_code(code: str) -> str:
    """旧码 -> 现行码；未注册码抛 UnknownErrorCodeError。"""
    canonical = LEGACY_CODE_ALIASES.get(code, code)
    if canonical not in ERROR_REGISTRY:
        raise UnknownErrorCodeError(code)
    return canonical


class _SafeDict(dict):
    """模板插值安全兜底：缺失占位符保持 {字面量}，不抛 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def new_request_id() -> str:
    return f"req_{uuid4().hex[:12]}"


def new_trace_id() -> str:
    return f"trace_{uuid4().hex[:12]}"


def new_debug_id() -> str:
    return f"dbg_{uuid4().hex[:12]}"


def render_error_message(code: str, **template_fields: Any) -> str:
    """族壳轮换取句的**唯一**出口（给不构造完整错误体的投影面用）。

    存在的理由：`divination/api/errors.py` 这类投影只取一句人话、不建错误体，
    过去直读 ``spec.message_template``＝永远同一句的第二通路。要轮换取句，
    只能走这里，不许在能力文件里再抄一份「取壳 + 填槽」。
    """
    return _render_message(get_error_spec(code), None, template_fields)


def _render_message(spec: ErrorSpec, override: str | None, fields: dict[str, Any]) -> str:
    if override is not None:
        normalized = override.strip()
        if not normalized:
            raise ValueError("message 覆盖不能为空白")
        return normalized
    # 先插值码级细节（缺占位符保持字面量不抛错，语义与 V21-CORE-001 一致），
    # 再套族壳：细节句永远整句在场，换的只是说法，绝不换事实。
    detail = spec.message_template.format_map(_SafeDict(fields)) if fields else spec.message_template
    pool = ERROR_COPY_POOLS.get(ERROR_COPY_FAMILY.get(spec.code, ""), ())
    if not pool:  # 未入族（导入期自检已拦死，这里只是给未来留不抛的退路）。
        return detail
    return random.choice(pool).format_map(_SafeDict({"detail": detail}))


def error_body(
    code: str,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    debug_id: str | None = None,
    message: str | None = None,
    retryable: bool | None = None,
    field_errors: list[dict[str, str]] | None = None,
    **template_fields: Any,
) -> dict[str, Any]:
    """构造 §6 七键错误体（dict 形态，由 envelope.ErrorBody 校验契约）。"""
    spec = get_error_spec(code)
    return {
        "code": spec.code,
        "message": _render_message(spec, message, template_fields),
        "request_id": request_id or new_request_id(),
        "trace_id": trace_id or new_trace_id(),
        "debug_id": debug_id or new_debug_id(),
        "retryable": spec.retryable if retryable is None else bool(retryable),
        "field_errors": list(field_errors) if field_errors else [],
    }


def error_envelope(
    code: str,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    debug_id: str | None = None,
    message: str | None = None,
    retryable: bool | None = None,
    field_errors: list[dict[str, str]] | None = None,
    **template_fields: Any,
) -> dict[str, Any]:
    """构造完整错误 envelope（data=None；meta 与 error 的 ID 保持一致传播）。"""
    body = error_body(
        code,
        request_id=request_id,
        trace_id=trace_id,
        debug_id=debug_id,
        message=message,
        retryable=retryable,
        field_errors=field_errors,
        **template_fields,
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return {
        "data": None,
        "error": body,
        "meta": {
            "request_id": body["request_id"],
            "trace_id": body["trace_id"],
            "schema_version": "v1",
            "generated_at": generated_at,
        },
    }
