"""小红书 x-s 签名入口（诚实占位，不做假实现）。

edith.xiaohongshu.com 的部分接口需要 x-s 签名头；当前项目尚未接入
MIT/Apache 许可的签名实现或自研实现。这里只保留未来直连的调用面，
``sign`` 明确抛 NotImplementedError，防止任何链路误以为签名可用。
"""

from __future__ import annotations


class XhsSigner:
    """x-s 签名器占位：``available=False`` 且调用即失败。"""

    available = False
    reason = "未接入 x-s 签名算法（需 MIT/Apache 实现或自研）"

    def sign(self, headers: dict, params: dict) -> None:
        raise NotImplementedError(self.reason)