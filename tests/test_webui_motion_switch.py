"""动效总开关的名单一致性门（W18 R4）。

一手证据（`webui/scripts/shoot.mjs` + `document.getAnimations()`，1440×900）::

    默认            total=12  running=11
    data-motion=off total=7   running=7
                    名单 = glaze-breathe×3、mark-breathe×1、iris-shift×3

也就是说「外观页把动效关到底」之后，**7 个无限动画照常在跑**。用户看到的是
侧栏釉瑚还在缓慢喘、品牌标还在呼吸、虹彩还在流转 —— 开关是假的。

根因不是「忘了关」，而是**两套名单**：
  · `@media (prefers-reduced-motion: reduce)` 那份是**全的**；
  · `:root[data-motion='off']` 那份只列了一部分类名，而且**扫不到 `@utility`
    内部的 `&::before` 动画**（`window` 的釉瑚光、`mark-breathe` 的呼吸都是这种形态）。

还有一层更隐蔽的：`:root[data-motion='off'] * { animation-duration: 0.01ms !important }`
**并不能停掉 `infinite` 动画** —— 它把周期压到 0.01ms，于是动画以约 10 万次/秒
重放，CPU 消耗比不关还高。真正的停止只有 `animation: none`。

本件判据：`index.css` 里每一个含 `animation: … infinite` 的**宿主**，都必须出现在
`:root[data-motion='off']` 与 `@media (prefers-reduced-motion: reduce)` 两份
`animation: none` 名单里。新增一个无限动画却忘了加名单 ⇒ 当场红。
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "webui" / "src" / "index.css"


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _balanced(css: str, open_brace: int) -> tuple[str, int]:
    """从 `{` 位置开始按花括号配平，返回 (块体, 结束位置)。"""
    depth = 0
    for pos in range(open_brace, len(css)):
        char = css[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace + 1 : pos], pos
    raise AssertionError("规则块没有闭合")


def _infinite_hosts(css: str) -> set[str]:
    """扫出所有「宿主选择器含 animation: … infinite」的类。

    两种形态都要认：
      ① 普通规则 `.foo::after { animation: … infinite }`
      ② `@utility foo { &::before { animation: … infinite } }`
         —— 编译后宿主是 `.foo::before`，而它在源码里写作嵌套的 `&`。
    """
    hosts: set[str] = set()

    # ① 普通规则：行首非 @ 非注释的选择器 { … }
    for match in re.finditer(r"(?m)^([^\n@/*][^{}\n]*?)\{([^{}]*)\}", css):
        selector, body = match.group(1).strip(), match.group(2)
        if "animation:" not in body or "infinite" not in body:
            continue
        for one in selector.split(","):
            one = one.strip()
            # `&::before` 是 @utility 的嵌套形态，由 ② 单独收；这里跳过。
            if one and "data-motion" not in one and "reduced-motion" not in one and "&" not in one:
                hosts.add(one)

    # ② @utility 块：顶层 animation 或嵌套 & 伪元素的 animation
    for match in re.finditer(r"(?m)^@utility\s+([a-zA-Z][\w-]*)\s*\{", css):
        name = match.group(1)
        body, _ = _balanced(css, match.end() - 1)
        # 顶层 animation（块体里不在 & 子块内的部分：粗判——先剥掉所有嵌套块）
        flat = re.sub(r"&[^{}]*\{[^{}]*\}", "", body)
        if "animation:" in flat and "infinite" in flat:
            hosts.add(f".{name}")
        # 嵌套 & 伪元素
        for sub in re.finditer(r"(&[^{}]*?)\{([^{}]*)\}", body):
            pseudo, sub_body = sub.group(1).strip(), sub.group(2)
            if "animation:" in sub_body and "infinite" in sub_body:
                suffix = pseudo.replace("&", "").strip()
                hosts.add(f".{name}{suffix}" if suffix.startswith(":") else f".{name}")
        # `&` 单独成块（不带伪元素）时就是宿主类本身
        if re.search(r"(?m)^\s*&\s*\{", body):
            hosts.discard(f".{name}&")

    return hosts


def _none_list(css: str, marker: str) -> set[str]:
    """取某条 `animation: none` 名单规则的选择器集合（按首个 `}` 截断）。"""
    idx = css.find(marker)
    assert idx >= 0, f"找不到名单起点 {marker!r}"
    end = css.index("}", idx)
    chunk = css[idx:end]
    return {line.strip().rstrip(",").strip() for line in chunk.splitlines() if line.strip()}


def _motion_off_list(css: str) -> set[str]:
    listed = _none_list(css, ":root[data-motion='off'] .aurora-blob")
    return {item.split("] ", 1)[-1] for item in listed}


def _reduce_list(css: str) -> set[str]:
    listed = _none_list(css, "@media (prefers-reduced-motion: reduce) {")
    return listed


def _covered(host: str, listed: set[str]) -> bool:
    """名单是否覆盖该宿主。

    三种覆盖形态：
      ① 逐字相等（`.mark-breathe` / `.brand-ring::after`）；
      ② 「基类 + 后缀」——宿主 `.aurora-blob-a` 由名单里的 `.aurora-blob` 覆盖
         （同一套 animation 的三条变体，清单只列基类是合理的）；
      ③ `a.active::after` 这类组合选择器：只要名单里有 `a.active` 或 `.active` 就算。
    """
    if host in listed:
        return True
    if host.startswith(".") and "::" not in host:
        base = host.rsplit("-", 1)[0]
        if base in listed:
            return True
    if host.endswith(("::before", "::after")):
        base = host.rsplit("::", 1)[0]
        if base in listed:
            return True
    return "a.active" in host and any(
        "a.active" in item or ".active" in item for item in listed
    )


def test_every_infinite_animation_host_is_in_the_motion_off_list() -> None:
    css = _css()
    hosts = _infinite_hosts(css)
    listed = _motion_off_list(css)
    missing = sorted(h for h in hosts if not _covered(h, listed))
    assert missing == [], (
        "以下无限动画没有进 data-motion='off' 的 animation:none 名单 —— "
        "用户关掉动效后它们仍在跑（而且被 0.01ms 的 duration 逼成 10 万次/秒重放）：\n  "
        + "\n  ".join(missing)
    )


def test_motion_off_duration_hack_alone_cannot_stop_infinite_animations() -> None:
    """`animation-duration: 0.01ms` 是**兜底**不是停播：它让 infinite 动画更费 CPU。

    这条不是断言「不许写 0.01ms」（它对 transition 与有限次动画是对的），
    而是钉住「必须有 animation:none 名单，不能只靠 duration 压缩」。
    """
    css = _css()
    assert "animation-duration: 0.01ms !important" in css, (
        "兜底还在（对 transition 与一次性动画有用）；如果被删了请同步复核此处判据"
    )
    listed = _motion_off_list(css)
    assert len(listed) >= 12, (
        f"animation:none 名单只有 {len(listed)} 条 —— 太少，说明大部分无限动画被漏掉"
    )


def test_reduce_media_block_also_lists_the_same_infinite_hosts() -> None:
    """`prefers-reduced-motion` 那份名单也要覆盖（它是无障碍底线）。"""
    css = _css()
    hosts = _infinite_hosts(css)
    listed = _reduce_list(css)
    missing = sorted(h for h in hosts if not _covered(h, listed))
    assert missing == [], (
        "以下无限动画没进 prefers-reduced-motion 的 animation:none 名单：\n  "
        + "\n  ".join(missing)
    )
