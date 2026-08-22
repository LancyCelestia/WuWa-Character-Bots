import httpx


class BilibiliAPIError(RuntimeError):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(f"{code} {message}")
        self.code = code
        self.message = message
        self.data = data


async def request_bilibili_api(
    method: str,
    url: str,
    *,
    proxy: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    **kwargs,
):
    request_headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com/",
    }
    if headers:
        request_headers.update(headers)

    async with httpx.AsyncClient(
        proxy=proxy,
        headers=request_headers,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        response = await client.request(method, url, **kwargs)

    payload = response.json()
    if payload.get("code") != 0:
        raise BilibiliAPIError(
            payload.get("code", -1),
            payload.get("message") or payload.get("msg") or "unknown error",
            payload.get("data"),
        )
    return payload.get("data")


async def get_live_rooms_info_by_uids(
    uids: list[int],
    *,
    proxy: str | None = None,
) -> dict[str, dict]:
    data = await request_bilibili_api(
        "POST",
        "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
        proxy=proxy,
        json={"uids": uids},
    )
    return data or {}
