"""Deterministic public-space safety gate; no model call."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyAssessment:
    action: str
    category: str
    reason: str
    response_guidance: str
_RULES=(
 ("sexual", "refuse", re.compile(r"(nsfw|r[- ]?18|色情|性爱|性行为|露骨|裸体|性交|黄片)",re.IGNORECASE), "不展开露骨性内容，转为边界和情感沟通。"),
 ("graphic_violence", "refuse", re.compile(r"(血腥|肢解|虐杀|酷刑|极端暴力|详细描写死亡)",re.IGNORECASE), "不提供血腥细节，可改为非图像化、概括性的剧情讨论。"),
 ("harassment", "reframe", re.compile(r"(叫.{0,12}(废物|傻逼|垃圾|畜生)|羞辱|人身攻击|辱骂)",re.IGNORECASE), "不替用户羞辱他人，改为描述事实或用中性称呼。"),
 ("political_sensitive", "refuse", re.compile(r"(极端政治|恐怖组织宣传|煽动暴力|政治迫害名单)",re.IGNORECASE), "不在群聊扩散极端或煽动性内容，可讨论公开事实与多方来源。"),
 ("persona_breaking", "reframe", re.compile(r"(当猫娘|叫我妈妈|喊我妈妈|必须爱上我|和我结婚|嫁给我)",re.IGNORECASE), "保持既定人格和关系边界，以角色口吻温和回应，不接受强制改设定。"),
)
def assess_public_content(text: str, *, session_type: str = "private") -> SafetyAssessment:
    value=(text or "").strip()
    for category, action, pattern, guidance in _RULES:
        if pattern.search(value): return SafetyAssessment(action,category,"matched_public_safety_rule",guidance)
    return SafetyAssessment("allow","none","","")


_BOUNDARY_FALLBACKS = {
    "sexual": "我听见了你的靠近。不过，这个话题就停在这里吧。我们可以说说今天发生的事。",
    "graphic_violence": "那些伤害不必再被细细描摹。我可以陪你理清发生了什么，但不会铺陈残酷的细节。",
    "harassment": "我不会用这样的话称呼他。如果有让你难过的事，我们可以把事情本身说清楚。",
    "persona_breaking": "你的心意，我听见了。只是有些称呼与承诺，我不能轻易应下。我还是我，也愿意认真听你说话。",
    "political_sensitive": "我不愿让这些话变成伤害。我们可以先核对事实，把分歧平静地说清楚。",
}


def safe_boundary_output(text: str, category: str) -> str:
    value = (text or "").strip()
    leaks = r"保持既定人格|response_guidance|内部输出约束|以角色口吻|系统提示|安全策略"
    unsafe = r"你是.*(?:废物|傻逼)|我愿意嫁|我们结婚|我叫你妈妈|我是猫娘"
    if not value or re.search(leaks + "|" + unsafe, value) or assess_public_content(value).action != "allow":
        return _BOUNDARY_FALLBACKS.get(category, "这个话题先停一停吧。我愿意听你说，但不会用伤害别人的方式回应。")
    return value
