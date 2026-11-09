"""控制面 Bearer 令牌生成器（W18 R1 修复件）。

为什么需要本件（一手证据）：`.env` 里只有两枚 SHA-256 摘要
（``BOT_CONTROL_PLANE_TOKEN_SHA256`` / ``BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256``），
而摘要不可逆；仓库里原本**没有任何**面向运维的令牌生成入口
（``grep -rn token_urlsafe --include=*.py .`` 只命中 actions / credential_service /
workspaces 三处**业务**令牌，与控制面登录无关）。规格写的是「明文只在生成时展示一次」
（``docs/design/control-plane-api.md:127``），但那个「展示一次」从来没有落点。

本件只做一件事：**生成 → 打印明文 → 打印摘要 → 告诉用户粘到哪一行**。
不改后端任何逻辑、不写 .env、不写库、不联网。

用法（在仓库根）::

    # 生成一对（管理令牌 + 超管令牌）
    python scripts/control_plane_token.py

    # 只生成一枚
    python scripts/control_plane_token.py --kind admin

    # 拿已有明文反查摘要（复现/校验用，不打印新明文）
    python scripts/control_plane_token.py --from-token '<你手上的明文>'

    # 校验某个明文是否与 .env 里已配置的摘要匹配（不打印摘要本身）
    python scripts/control_plane_token.py --verify '<明文>'

退出码：0＝成功；1＝参数/校验失败。明文**只进 stdout**，不落盘、不进日志。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import secrets
import sys
from pathlib import Path

# Windows 控制台默认 GBK，本件全中文输出 ⇒ 不改码就吐乱码（本席实跑撞到过）。
# 拿不到可重配的流（被重定向成非文本流等）就按现状输出，不影响功能，故 suppress。
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]

#: 令牌熵（字节）。规格原文 `secrets.token_urlsafe(32)` ⇒ 43 个 URL-safe 字符。
TOKEN_BYTES = 32

#: `.env` 里两枚令牌的键名（顺序即打印顺序）。
ENV_KEYS = {
    "admin": "BOT_CONTROL_PLANE_TOKEN_SHA256",
    "super": "BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256",
}


def hash_token(token: str) -> str:
    """令牌明文 → SHA-256 十六进制小写。

    与 ``plugins/bot_unified_runtime/control_plane/auth.py:hash_token`` 必须逐字一致
    （后端用同一函数比较，任何差异都会导致「配了却永远 401」）。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate() -> str:
    """生成一枚新令牌明文（URL-safe，无需再转义即可进 Bearer 头）。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def read_env_digests(env_path: Path | None = None) -> dict[str, str]:
    """从 `.env` 读两枚已配置摘要；缺键/缺文件返回空串。只读，绝不写。"""
    path = env_path or (ROOT / ".env")
    out = {key: "" for key in ENV_KEYS.values()}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name in out:
            out[name] = value.strip()
    return out


def _print_token(kind: str) -> tuple[str, str]:
    token = generate()
    digest = hash_token(token)
    key = ENV_KEYS[kind]
    label = "管理令牌（读+写）" if kind == "admin" else "超管令牌（写操作，必须与管理令牌不同）"
    print(f"── {label} ──────────────────────────────────────────")
    print(f"明文（只显示这一次，请立刻保存到密码管理器）：\n  {token}")
    print(f"\n摘要（粘到 .env 的这一行）：\n  {key}={digest}")
    print()
    return token, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成控制面 Bearer 令牌（明文 + SHA-256 摘要）",
        epilog="明文只进 stdout；本脚本不写 .env、不写库、不联网。",
    )
    parser.add_argument(
        "--kind",
        choices=("admin", "super", "both"),
        default="both",
        help="生成哪一枚（缺省 both）",
    )
    parser.add_argument("--from-token", metavar="明文", help="给定明文，只算摘要（不生成新的）")
    parser.add_argument("--verify", metavar="明文", help="校验明文是否与 .env 已配置摘要匹配")
    args = parser.parse_args(argv)

    if args.from_token:
        token = args.from_token.strip()
        if not token:
            print("错误：--from-token 不能为空。", file=sys.stderr)
            return 1
        print(f"{hash_token(token)}")
        return 0

    if args.verify:
        token = args.verify.strip()
        if not token:
            print("错误：--verify 不能为空。", file=sys.stderr)
            return 1
        digests = read_env_digests()
        matched = [key for key, value in digests.items() if value and hash_token(token) == value.lower()]
        if not matched:
            print("不匹配：该明文与 .env 里任何一枚摘要都不相等。", file=sys.stderr)
            configured = [key for key, value in digests.items() if value]
            if configured:
                print(f"已配置的键：{', '.join(configured)}", file=sys.stderr)
            else:
                print("（.env 里两枚摘要都是空的——控制面会整体降级 503。）", file=sys.stderr)
            return 1
        print(f"匹配：{', '.join(matched)}")
        return 0

    kinds = ("admin", "super") if args.kind == "both" else (args.kind,)

    print("=" * 72)
    print("控制面 Bearer 令牌生成")
    print("=" * 72)
    print()

    digests: dict[str, str] = {}
    for kind in kinds:
        _, digest = _print_token(kind)
        digests[kind] = digest

    # 两枚必须不同：后端对「相同则写操作被禁用」有硬判（.env 注释原文）。
    if len(digests) == 2 and digests["admin"] == digests["super"]:
        print("🔴 两枚摘要相同 —— 这不可能由随机生成产生，请重新运行。", file=sys.stderr)
        return 1

    current = read_env_digests()
    print("=" * 72)
    print("下一步")
    print("=" * 72)
    for kind in kinds:
        key = ENV_KEYS[kind]
        old = current.get(key, "")
        state = "（当前为空）" if not old else "（当前已有值，将被替换）"
        print(f"  1. 打开 .env，把 {key} 改成上面那行 {state}")
    print("  2. 重启 bot（配置在装配期读入，热改不生效）")
    print("  3. 打开 /console/ → 右下角设置 → 粘贴**明文**（不是摘要）")
    print()
    print("⚠️ 明文丢了就得重跑本脚本 + 重启 bot。摘要不可逆，没有找回路径。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
