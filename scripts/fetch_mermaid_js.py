"""一次性素材落盘工具：mermaid@11 min.js → card_render_assets/mermaid/。

渲染素材本地化（F1，asset-audit-report.md 缺口最高优先）：mermaid_card.html
的 script src 保持 jsDelivr CDN URL 不变，render_backends 渲染期以
page.route() 拦截该 URL 用本地字节 fulfill（传输层换血，模板零分叉）；
本工具负责把真身下载落盘并校验。

- 版本固定：默认 URL 钉死具体版本；模板里浮动的大版本 URL（mermaid@11）
  由拦截层兜底——模板 URL 一旦漂出本工具钉住的字节也只影响内容版本，
  拦截按 URL 精确匹配，不匹配即放行网络（回退现状，不炸）。
- 校验（拒收即不落盘）：大小阈值 + 首字节非 HTML + 含 mermaid 标记
  （复用 render_backends.validate_mermaid_asset_bytes，与渲染侧同一标准）；
  sha256 sidecar（``mermaid.min.js.sha256``，sha256sum 兼容两空格格式）。
- 幂等：文件已存在且校验通过（sidecar 哈希吻合，或文件本身合格时就地
  补写 sidecar，不打网络）→ 跳过；``--force`` 强制重拉。

用法：
    python scripts/fetch_mermaid_js.py            # 缺失才下载
    python scripts/fetch_mermaid_js.py --force    # 强制重拉
    python scripts/fetch_mermaid_js.py --check    # 只校验不下载
退出码：0 = 落盘/已就绪；1 = 下载或校验失败。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.domains.render.render_backends import (
    mermaid_asset_dir,
    validate_mermaid_asset_bytes,
)

# 版本固定：jsDelivr data API 对 specifier=11 的 resolved 版本（2026-09-14）。
DEFAULT_MERMAID_URL = (
    "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
)
_FETCH_HEADERS = {"User-Agent": "curl/8.0.1", "Accept": "*/*"}
_FETCH_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def download(url: str) -> bytes:
    """拉取远端字节（直连 + curl 形态极简头，与 ORB 取回同型）。"""
    request = urllib.request.Request(url, headers=_FETCH_HEADERS)
    with _FETCH_OPENER.open(request, timeout=60) as response:
        return response.read(64 * 1024 * 1024)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar_path(target: Path) -> Path:
    return target.with_name(target.name + ".sha256")


def _read_sidecar_hash(target: Path) -> str | None:
    try:
        first_line = _sidecar_path(target).read_text(encoding="ascii").split()[0]
    except (OSError, IndexError):
        return None
    return first_line if len(first_line) == 64 else None


def _write_sidecar(target: Path, digest: str) -> None:
    _sidecar_path(target).write_text(f"{digest}  {target.name}\n", encoding="ascii")


def local_ready(target: Path) -> bool:
    """本地文件校验通过即就绪；sidecar 缺失/漂移就地补写（零网络自愈）。"""
    try:
        data = target.read_bytes()
    except OSError:
        return False
    if validate_mermaid_asset_bytes(data) is None:
        return False
    digest = sha256_of(data)
    if _read_sidecar_hash(target) != digest:
        _write_sidecar(target, digest)
    return True


def fetch(
    url: str = DEFAULT_MERMAID_URL,
    dest_dir: Path | None = None,
    *,
    force: bool = False,
    checker: Callable[[str], bytes] = download,
) -> tuple[Path | None, str | None, bool]:
    """确保本地素材就绪；返回 (落盘路径, sha256, skipped)。

    失败返回 (None, None, False)；拒收（校验不过）不写任何字节。
    ``checker`` 参数供测试替身注入，免除真实网络。
    """
    target = (dest_dir or mermaid_asset_dir()) / "mermaid.min.js"
    if not force and local_ready(target):
        digest = _read_sidecar_hash(target) or sha256_of(target.read_bytes())
        return target, digest, True
    data = checker(url)
    validated = validate_mermaid_asset_bytes(data)
    if validated is None:
        return None, None, False
    digest = sha256_of(validated)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(validated)
    os.replace(tmp, target)
    _write_sidecar(target, digest)
    return target, digest, False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mermaid.min.js 素材落盘工具")
    parser.add_argument(
        "--url", default=DEFAULT_MERMAID_URL, help="版本固定的 dist min.js URL"
    )
    parser.add_argument(
        "--dest", default="", help="覆盖目标素材目录（缺省走标准解析链）"
    )
    parser.add_argument("--force", action="store_true", help="已就绪也强制重拉")
    parser.add_argument(
        "--check", action="store_true", help="只校验本地现状，不发起下载"
    )
    args = parser.parse_args(argv)
    target = (Path(args.dest).expanduser() if args.dest else mermaid_asset_dir()) / (
        "mermaid.min.js"
    )
    if args.check:
        if local_ready(target):
            print(f"OK {target} sha256={_read_sidecar_hash(target)}")
            return 0
        print(f"NOT-READY {target}", file=sys.stderr)
        return 1
    try:
        target, digest, skipped = fetch(args.url, args.dest or None, force=args.force)
    except Exception as exc:  # noqa: BLE001 - 网络失败按工具失败退出。
        print(f"FETCH-FAILED {exc}", file=sys.stderr)
        return 1
    if target is None or digest is None:
        print("REJECTED 下载内容未通过收货校验（大小/HTML 错误页/标记缺失），未落盘", file=sys.stderr)
        return 1
    print(
        f"{'SKIP(ready)' if skipped else 'FETCHED'} {target} "
        f"bytes={target.stat().st_size} sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
