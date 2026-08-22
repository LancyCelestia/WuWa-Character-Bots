from dataclasses import dataclass

import httpx

WEB_DYNAMIC_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class WebDynamicError(RuntimeError):
    def __init__(self, code, msg, data=None):
        super().__init__(f"{code} {msg}")
        self.code = code
        self.msg = msg
        self.data = data


@dataclass(slots=True)
class WebDynamicItem:
    dynamic_id: int
    dynamic_type: str
    author_name: str


def parse_web_dynamic_items(payload: dict) -> list[WebDynamicItem]:
    items = payload.get("data", {}).get("items") or []
    parsed_items = []
    for item in items:
        dynamic_id = item.get("id_str")
        modules = item.get("modules") or {}
        author_name = (modules.get("module_author") or {}).get("name")
        dynamic_type = item.get("type") or ""
        if not dynamic_id or not author_name:
            continue
        try:
            parsed_items.append(
                WebDynamicItem(
                    dynamic_id=int(dynamic_id),
                    dynamic_type=dynamic_type,
                    author_name=author_name,
                )
            )
        except (TypeError, ValueError):
            continue
    return parsed_items


def parse_web_dynamic_payload(payload: dict) -> list[WebDynamicItem]:
    if payload.get("code") != 0:
        raise WebDynamicError(
            payload.get("code"),
            payload.get("message") or "unknown error",
            payload.get("data"),
        )
    return parse_web_dynamic_items(payload)


async def get_user_dynamics_web(
    uid: int,
    cookies: dict[str, str],
    *,
    proxy: str | None = None,
    user_agent: str | None = None,
    timeout: int = 10,
) -> list[WebDynamicItem]:
    headers = {
        "User-Agent": user_agent or DEFAULT_BROWSER_USER_AGENT,
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://space.bilibili.com",
    }
    async with httpx.AsyncClient(
        proxy=proxy,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        response = await client.get(WEB_DYNAMIC_URL, params={"host_mid": uid})
    return parse_web_dynamic_payload(response.json())
