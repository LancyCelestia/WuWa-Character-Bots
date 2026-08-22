import contextlib
from dataclasses import dataclass
from typing import Any

import httpx
from nonebot import logger
from playwright._impl._api_structures import Position
from playwright.async_api import Page, Response


@dataclass
class CaptchaData:
    captcha_id: str
    points: list[list[int]]
    rectangles: list[list[int]]
    yolo_data: list[list[int]]
    time: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaptchaData":
        return cls(
            captcha_id=data["captcha_id"],
            points=data.get("points", []),
            rectangles=data.get("rectangles", []),
            yolo_data=data.get("yolo_data", []),
            time=data.get("time", 0),
        )


class CaptchaInfer:
    def __init__(self, captcha_server: str, token: str):
        self.captcha_server = f"{captcha_server}/captcha/select"
        self.token = token
        self.captcha_image_body: bytes | None = None
        self.last_captcha_id: str | None = None

    async def _captcha_api_report(self, captcha_id: str):
        async with httpx.AsyncClient() as client:
            captcha_req = await client.post(
                f"{self.captcha_server}/report",
                timeout=10,
                json={"captcha_id": captcha_id, "token": self.token},
            )
            logger.info(f"[Captcha] Report Result: {captcha_req.json()}")

    async def _captcha_api_request(self, image: bytes) -> CaptchaData:
        async with httpx.AsyncClient() as client:
            captcha_req = await client.post(
                f"{self.captcha_server}/bytes",
                timeout=10,
                data={"token": self.token},
                files={"img_file": image},
            )
            payload = captcha_req.json()
            logger.info(f"[Captcha] Get Resolve Result: {payload}")
            data = payload.get("data")
            if not data:
                raise RuntimeError("Captcha service returned empty data")
            parsed = CaptchaData.from_dict(data)
            self.last_captcha_id = parsed.captcha_id
            return parsed

    async def _captcha_image_callback(self, response: Response):
        logger.info(f"[Captcha] 获取验证码图片：{response.url}")
        self.captcha_image_body = await response.body()

    async def solve_captcha(self, page: Page, url: str):
        page.on(
            "response",
            lambda response: self._captcha_image_callback(response)
            if response.url.startswith("https://static.geetest.com/captcha_v3/")
            else None,
        )
        with contextlib.suppress(TimeoutError):
            await page.goto(url, wait_until="networkidle", timeout=10000)

        while self.captcha_image_body:
            logger.info("[Captcha] 检测到验证码，开始识别")
            captcha_image = await page.query_selector(".geetest_item_img")
            assert captcha_image
            captcha_size = await captcha_image.bounding_box()
            assert captcha_size

            data = await self._captcha_api_request(self.captcha_image_body)

            click_points = data.points
            if len(click_points) != len(set(map(tuple, click_points))):
                logger.warning("[Captcha] 点击点有重复，识别失败，正在重试")
                await self._captcha_api_report(data.captcha_id)
                await page.click(".geetest_refresh")
                await page.wait_for_timeout(2000)
                continue

            logger.warning(f"[Captcha] 识别到 {len(click_points)} 个点击点")
            origin_image_size = 344, 384

            for point in click_points:
                real_click_points = {
                    "x": point[0] * captcha_size["width"] / origin_image_size[0],
                    "y": point[1] * captcha_size["height"] / origin_image_size[1],
                }
                logger.info(f"[Captcha] 点击坐标：{real_click_points}")
                try:
                    await captcha_image.click(
                        position=Position(**real_click_points), timeout=1000
                    )
                except Exception as e:
                    logger.error(f"[Captcha] 点击失败：{e}")
                    await self._captcha_api_report(data.captcha_id)
                    await page.reload()
                    continue
                logger.info("[Captcha] 点击完成")
                await page.wait_for_timeout(600)
            await page.wait_for_timeout(400)
            await page.click(".geetest_commit_tip")
            geetest_up = await page.wait_for_selector(".geetest_up", state="visible")
            assert geetest_up
            geetest_result = await geetest_up.text_content() or ""
            if "验证成功" in geetest_result:
                logger.success(f"[Captcha] 极验网页 Tip：{geetest_result}")
                await page.wait_for_timeout(2000)
                self.captcha_image_body = None
            else:
                logger.warning("[Captcha] 极验验证失败，正在重试")
                await self._captcha_api_report(data.captcha_id)
                old_captcha_body = self.captcha_image_body
                while old_captcha_body == self.captcha_image_body:
                    await page.wait_for_timeout(200)

        return page
