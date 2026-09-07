"""抓取「历史上的今天」全年事件并补全百度百科词条摘要，构建本地知识库。

数据源（均为百度百科公开接口，无需鉴权）：
- 事件列表 https://baike.baidu.com/cms/home/eventsOnHistory/{MM}.json（每月 1 次）
- 词条摘要 https://baike.baidu.com/api/openapi/BaikeLemmaCardApi（每条事件 1 次）

输出：{BOT_RUNTIME_DATA_DIR}/today_history_kb/
- events/{MM}.json   原始月度事件（带 desc/link/cover）
- days/{MM-DD}.json  每日知识条目（含词条摘要；失败条目写 limitation）
- md/th-{MM}.md      汇出为每月 Markdown（--export-md，供 BOT_KNOWLEDGE_FILES 入库）

支持断点续跑：已存在的 events/*.json 与 days/*.json 自动跳过（残缺文件重抓）。
用法（须设 PYTHONDONTWRITEBYTECODE=1）：
    python scripts/today_history_kb.py [--months 1,2] [--days 0830] [--sleep 0.35] [--export-md]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import runtime_data_dir

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChatBot-KB/1.0"}
_TIMEOUT = 10.0
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_SUFFIX_RE = re.compile(
    r"(出生|逝世|去世|诞生|发生|爆发|成立|开通|竣工|首播|上映|发射|发表|签订"
    r"|建成|通车|通航|就任|获奖|试爆|成功|运转|落成|开馆|失事|坠毁)$"
)


def _strip_html(value: str) -> str:
    return _TAG_RE.sub("", value or "").strip()


def _get_json(url: str, retries: int = 2) -> dict:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(1.5)
    assert last is not None
    raise last


def _fetch_month(month: str) -> dict[str, list]:
    raw = _get_json(f"https://baike.baidu.com/cms/home/eventsOnHistory/{month}.json")
    block = (raw or {}).get(month) or {}
    return {day: items for day, items in block.items() if isinstance(items, list)}


def _keyword(event: dict) -> str:
    link = str(event.get("link") or "")
    if "/item/" in link:
        keyword = urllib.parse.unquote(
            link.split("/item/", 1)[1].split("?")[0].split("/")[0]
        )
        if keyword:
            return keyword
    title = _TITLE_SUFFIX_RE.sub("", _strip_html(str(event.get("title") or "")))
    return title


def _fetch_abstract(keyword: str) -> dict | None:
    url = (
        "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi"
        "?scope=103&format=json&appid=379020"
        f"&bk_key={urllib.parse.quote(keyword)}&bk_length=600"
    )
    try:
        card = _get_json(url)
    except (OSError, ValueError):
        return None
    abstract = _strip_html(str(card.get("abstract") or ""))
    key = str(card.get("key") or "")
    if not key or not abstract:
        return None
    return {
        "keyword": key,
        "abstract": abstract,
        "abstract_url": f"https://baike.baidu.com/item/{urllib.parse.quote(key)}",
    }


def crawl(months: list[str], day_filter: set[str] | None, sleep_seconds: float) -> None:
    kb_dir = runtime_data_dir() / "today_history_kb"
    events_dir = kb_dir / "events"
    days_dir = kb_dir / "days"
    for directory in (events_dir, days_dir):
        directory.mkdir(parents=True, exist_ok=True)

    abstract_cache: dict[str, dict | None] = {}
    total_events = 0
    total_days = 0
    for month in months:
        events_path = events_dir / f"{month}.json"
        if events_path.exists():
            month_days = json.loads(events_path.read_text(encoding="utf-8"))
        else:
            month_days = _fetch_month(month)
            events_path.write_text(
                json.dumps(month_days, ensure_ascii=False), encoding="utf-8"
            )
            print(f"events/{month}.json: {len(month_days)} days", flush=True)
            time.sleep(sleep_seconds)
        for day_key in sorted(month_days):
            if day_filter and day_key not in day_filter:
                continue
            day_tag = f"{day_key[:2]}-{day_key[2:]}"
            out_path = days_dir / f"{day_tag}.json"
            if out_path.exists():
                try:
                    json.loads(out_path.read_text(encoding="utf-8"))
                    continue
                except (OSError, ValueError):
                    pass  # 中断产生的残缺文件：重抓。
            entries = []
            for event in month_days[day_key]:
                keyword = _keyword(event)
                card = None
                if keyword:
                    if keyword not in abstract_cache:
                        card = _fetch_abstract(keyword)
                        abstract_cache[keyword] = card
                        time.sleep(sleep_seconds)
                    else:
                        card = abstract_cache[keyword]
                entry = {
                    "year": str(event.get("year") or ""),
                    "title": _strip_html(str(event.get("title") or "")),
                    "desc": _strip_html(str(event.get("desc") or "")),
                    "link": str(event.get("link") or ""),
                    "cover": str(event.get("cover") or ""),
                }
                if card:
                    entry.update(card)
                else:
                    entry["limitation"] = "abstract_unavailable"
                entries.append(entry)
            out_path.write_text(
                json.dumps(
                    {"date": day_key, "source": "baike.baidu.com", "events": entries},
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
            total_days += 1
            total_events += len(entries)
            print(f"{day_tag}: {len(entries)} events", flush=True)
    print(f"DONE days={total_days} events={total_events}", flush=True)


def export_markdown(kb_dir: Path | None = None) -> int:
    """把 days/*.json 汇出为每月一个 Markdown 知识文件（供 BOT_KNOWLEDGE_FILES 入库）。

    每条事件两行（标题行 + 正文行）：切块按段落聚合，事件不会被从中间切断。
    """
    kb_dir = kb_dir or (runtime_data_dir() / "today_history_kb")
    md_dir = kb_dir / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[tuple[str, dict]]] = {}
    for path in sorted((kb_dir / "days").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("events", []):
            by_month.setdefault(path.stem[:2], []).append((path.stem, entry))
    for month, events in sorted(by_month.items()):
        lines = [f"# 历史上的今天 · {int(month)}月（资料来源：百度百科）"]
        for day_tag, entry in events:
            digits = day_tag.replace("-", "")
            month_num, day_num = int(digits[:2]), int(digits[2:])
            year = str(entry.get("year") or "").strip()
            title = str(entry.get("title") or "").strip()
            if year.startswith("-") and year[1:].isdigit():
                heading = f"公元前{year[1:]}年{month_num}月{day_num}日：{title}"
            elif year.isdigit():
                heading = f"{year}年{month_num}月{day_num}日：{title}"
            else:
                heading = f"（{year}）{month_num}月{day_num}日：{title}"
            body = str(entry.get("abstract") or entry.get("desc") or "").strip()
            lines += [f"## {heading}", body, ""]
        out = md_dir / f"th-{month}.md"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(by_month)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", default="", help="仅抓取这些天（逗号分隔 MM-DD 或 MMDD）；默认全年"
    )
    parser.add_argument(
        "--months", default="", help="仅抓这些月（逗号分隔 1-12）；默认全年"
    )
    parser.add_argument("--sleep", type=float, default=0.35, help="请求间隔秒")
    parser.add_argument(
        "--export-md",
        action="store_true",
        help="不抓取，仅把 days/*.json 汇出为每月 Markdown（md/th-*.md）",
    )
    args = parser.parse_args()
    if args.export_md:
        print(f"exported {export_markdown()} monthly md files", flush=True)
        return
    day_filter = {
        part.strip().replace("-", "") for part in args.days.split(",") if part.strip()
    }
    months = [f"{int(part):02d}" for part in args.months.split(",") if part.strip()]
    crawl(
        months or [f"{value:02d}" for value in range(1, 13)],
        day_filter or None,
        max(0.1, args.sleep),
    )


if __name__ == "__main__":
    main()
