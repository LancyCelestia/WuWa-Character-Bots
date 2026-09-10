"""GitHub 仓库链接解析（github.com/{owner}/{repo} 及其子路径）。

数据源（未认证公开 REST API，UA 必填，限长读取 + 超时，限额 60 次/h·IP）：

- ``GET https://api.github.com/repos/{owner}/{repo}``：仓库元数据
  （全名/描述/星标/Fork/开放 Issue/主语言/topics/许可证/更新时间/默认分支）；
- ``GET https://api.github.com/repos/{owner}/{repo}/readme``（``Accept:
  application/vnd.github+json``）：base64 README，剥离 Markdown 后取前
  ~500 字纯文本摘要。

链接归一化：``tree/blob/releases/issues/pull`` 等子路径统一归到仓库主页；
``.git`` 后缀、结尾斜杠一并剥掉。``github.com/features``、``/topics`` 等
GitHub 自有页面不是仓库，``match_github_repo`` 返回 None（注册层的宽匹配
由此兜住，非仓库链接直接走通用 og 兜底）。README 是可选增强：拉取失败只
少一段摘要，不影响元数据卡片；仓库元数据接口失败按解析失败约定抛
``ParseHttpError``，由上层降级。
"""

from __future__ import annotations

import base64
import re
from typing import Any

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

# 注册层建议使用的 URL 模式（宽匹配，非仓库自有页由 parse 内部再校验）。
GITHUB_URL_PATTERNS: tuple[str, ...] = (
    r"github\.com/[0-9A-Za-z][0-9A-Za-z-]{0,38}/[0-9A-Za-z_.-]+(?:/[^\s]*)?",
)

# owner/repo 段提取：owner 规则同 GitHub 用户名（字母开头，可含单连字符）；
# repo 段允许点/下划线（next.js、electron/.github 等）。
_REPO_RE = re.compile(
    r"github\.com/(?P<owner>[0-9A-Za-z][0-9A-Za-z-]{0,38})"
    r"/(?P<repo>[0-9A-Za-z_.-]+?)(?:\.git)?(?=[/?#:\s]|$)",
    re.IGNORECASE,
)

# GitHub 自有非仓库首段：命中即不算仓库链接（features 只有单段也不会被
# _REPO_RE 命中，但 features/enterprise 之类可以带子路径，必须显式排除）。
_RESERVED_FIRST_SEGMENTS = frozenset(
    {
        "about", "account", "apps", "collections", "codereview",
        "contact", "customer-stories", "dashboard", "developer",
        "enterprise", "events", "explore", "features", "features-preview",
        "gist", "gists", "git", "join", "login", "logout", "marketplace",
        "new", "notifications", "organizations", "orgs", "pricing",
        "readme", "search", "security", "settings", "showcases", "site",
        "sponsors", "topics", "trending", "update",
    }
)

# 单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。
_GITHUB_TIMEOUT_SECONDS = 10.0
_MAX_PAYLOAD_BYTES = 1024 * 1024
_README_EXCERPT_CHARS = 500

_GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _github_get_json(url: str) -> Any:
    """仓库/README 接口统一出口（UA 由 http_util 默认携带，GitHub 必填）。"""
    return http_get_json(
        url,
        timeout=_GITHUB_TIMEOUT_SECONDS,
        extra_headers=_GITHUB_API_HEADERS,
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def match_github_repo(url: str) -> tuple[str, str] | None:
    """从任意 github.com 链接提取 (owner, repo)；非仓库链接返回 None。"""
    match = _REPO_RE.search(url or "")
    if not match:
        return None
    owner = match.group("owner")
    if owner.lower() in _RESERVED_FIRST_SEGMENTS:
        return None
    repo = match.group("repo").rstrip(".")
    if not repo or repo.lower() == ".git":
        return None
    return owner, repo


def _markdown_excerpt(markdown: str, limit: int = _README_EXCERPT_CHARS) -> str:
    """README Markdown → 纯文本摘要：丢代码块/图片/HTML/裸链接，留正文。"""
    text = markdown or ""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)  # 围栏代码块整体丢弃
    text = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", text)  # 行内代码只留内容
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # 图片
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # 链接只留文本
    text = re.sub(r"<[^>]+>", " ", text)  # HTML 标签
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)  # 标题井号
    text = re.sub(r"https?://\S+", " ", text)  # 剩余裸链接
    text = re.sub(r"[*_~|>]+", "", text)  # 强调/引用符号
    lines = [line.strip() for line in text.splitlines()]
    text = re.sub(r"\s{2,}", " ", " ".join(line for line in lines if line)).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _decode_readme(payload: Any) -> str:
    """README 响应 → Markdown 文本（base64 内容解码；异常返回空）。"""
    if not isinstance(payload, dict):
        return ""
    raw_content = payload.get("content")
    if not isinstance(raw_content, str) or not raw_content:
        return ""
    if str(payload.get("encoding") or "") != "base64":
        return raw_content
    try:
        # validate=True：非法字符直接抛 ValueError（b64decode 默认会静默
        # 丢弃非法字符再解码，坏内容反而得到乱码，不如显式失败）。
        raw = base64.b64decode(raw_content, validate=True)
    except (ValueError, TypeError):
        return ""
    return raw.decode("utf-8", errors="replace")


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except ValueError:
        return 0


def _license_name(meta: dict[str, Any]) -> str:
    license_data = meta.get("license")
    if not isinstance(license_data, dict):
        return ""
    return str(license_data.get("name") or "").strip()


def parse_github(url: str) -> ParsedContent:
    """GitHub 仓库卡片：REST 元数据 + README 摘要，归一到仓库主页。"""
    slug = match_github_repo(url)
    if slug is None:
        raise ParseHttpError(f"github: not a repository link: {url}")
    owner, repo = slug
    api_base = f"https://api.github.com/repos/{owner}/{repo}"
    meta = _github_get_json(api_base)
    if not isinstance(meta, dict):
        raise ParseHttpError(f"github: unexpected repo payload for {owner}/{repo}")

    full_name = str(meta.get("full_name") or "").strip() or f"{owner}/{repo}"
    description = str(meta.get("description") or "").strip()

    readme_text = ""
    try:
        readme_text = _decode_readme(_github_get_json(f"{api_base}/readme"))
    except ParseHttpError:
        pass  # README 可选（空仓库/私有分支 404）：只少摘要，不影响卡片。
    excerpt = _markdown_excerpt(readme_text)

    raw_topics = meta.get("topics")
    topics = [
        str(topic).strip()
        for topic in (raw_topics if isinstance(raw_topics, list) else [])
        if str(topic).strip()
    ]
    stats: dict[str, Any] = {
        "星标": _as_int(meta.get("stargazers_count")),
        "Fork": _as_int(meta.get("forks_count")),
        "开放Issue": _as_int(meta.get("open_issues_count")),
    }
    language = str(meta.get("language") or "").strip()
    if language:
        stats["主语言"] = language
    license_name = _license_name(meta)
    if license_name:
        stats["许可证"] = license_name
    updated_at = str(meta.get("updated_at") or "").strip()
    if updated_at:
        stats["最近更新"] = updated_at[:10]

    detail: dict[str, Any] = {
        "author": {"name": str((meta.get("owner") or {}).get("login") or owner)},
        "default_branch": str(meta.get("default_branch") or "").strip(),
    }
    homepage = str(meta.get("homepage") or "").strip()
    if homepage:
        detail["homepage"] = homepage

    return build_parsed_content(
        platform="github",
        item_id=f"{owner}/{repo}" if f"{owner}/{repo}" != full_name else full_name,
        item_kind="repo",
        title=full_name,
        author_name=str((meta.get("owner") or {}).get("login") or owner),
        summary=description,
        body=excerpt,
        canonical_url=str(meta.get("html_url") or "").strip()
        or f"https://github.com/{owner}/{repo}",
        stats=stats,
        parse_depth="deep",
        page_type="repo",
        detail=detail,
        tags=topics,
    )
