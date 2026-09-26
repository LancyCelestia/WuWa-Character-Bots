"""跨能力触发冲突修复回归：meme random / meme stats 唯一归属 bot.meme_library。

触发规格体检（tests/test_trigger_spec.py KNOWN_CONFLICT_WORDS）钉出的冲突 ×2：
「meme random」「meme stats」同时命中 bot.meme（表情生成：裸 ``meme`` 前缀
把后续词吃成 rest）与 bot.meme_library（随机表情/表情库统计）。

语义裁定（与触发规格一致）：
- 「meme random」「meme stats」→ 表情收库（bot.meme_library）；
- 「表情 <模板>」「meme <文字>」→ 表情生成（bot.meme）。
双方既有样例零回归。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities.meme import (
    is_meme_command,
    parse_meme_command,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    is_meme_library_command,
    parse_meme_library_command,
)

# 冲突探针（与 extract_trigger_words 的 verified probe 同口径：裸词 + 斜杠变体）。
LIBRARY_ONLY = [
    "meme random",
    "meme stats",
    "/meme random",
    "/meme stats",
    # 复数误拼兜底（_STATS_RE 的 memes? stats 款，同 memes? random）。
    "memes stats",
    "/memes stats",
]

# 既有 meme 生成样例（回归锁定：负向前瞻不得误伤）。
GENERATION_ONLY = [
    "meme",
    "memes",
    "/meme",
    "meme generate",
    "meme petpet 可爱",
    "meme help",
    "/表情 petpet 可爱",
    "表情 文字表情 早上好｜晚上好",
]


@pytest.mark.parametrize("sample", LIBRARY_ONLY)
def test_library_commands_unique_to_meme_library(sample: str) -> None:
    """meme random / meme stats 只归表情收库，表情生成不得抢匹配。"""
    assert is_meme_library_command(sample)
    assert not is_meme_command(sample), f"{sample!r} 被表情生成抢匹配"


@pytest.mark.parametrize("sample", GENERATION_ONLY)
def test_generation_samples_still_unique_to_meme(sample: str) -> None:
    """表情生成既有样例照旧唯一命中 bot.meme。"""
    assert is_meme_command(sample)
    assert not is_meme_library_command(sample)


def test_parse_split_is_clean() -> None:
    """解析层口径一致：收库两命令可解析，生成侧视为非命令。"""
    assert parse_meme_library_command("meme random") == ("pick", "")
    assert parse_meme_library_command("meme random 可爱") == ("pick", "可爱")
    assert parse_meme_library_command("meme stats") == ("stats", "")
    assert parse_meme_library_command("memes stats") == ("stats", "")
    # 胶合不触发（右边界纪律）：statsx/随机 x 类不得借道。
    assert not is_meme_library_command("memes statsx")
    with pytest.raises(ValueError):
        parse_meme_command("meme random")
    with pytest.raises(ValueError):
        parse_meme_command("meme stats")
