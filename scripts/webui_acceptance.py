#!/usr/bin/env python3
"""守岸人 WebUI 端到端目验脚本（playwright 无头，零第三方依赖除 playwright）。

对 webui/dist 单文件构建逐页驱动：hash 路由切页 → 等待「数据在场」或「优雅降级态」
标志文案 → 断言非白屏 + 控制台无非白名单错误 → 全页截图。

用法：
    python scripts/webui_acceptance.py                          # 默认 dist + MOCKUI 缺省端口 8743
    python scripts/webui_acceptance.py --api http://127.0.0.1:8742 --token <Bearer>
    python scripts/webui_acceptance.py --pages calls,logs --json

判定（每页二选一，自动归类模式）：
    data     = 数据态标志文案出现（如 calls 页「窗口内调用」）
    graceful = 优雅降级态标志出现（加载失败/暂无数据/未配置令牌…）且页面非白屏
两者皆无 / 白屏 / 非白名单控制台错误 / 未捕获 JS 异常 → FAIL。

控制台噪声白名单（只豁免浏览器网络层资源报错，豁免理由：API 不可达/无令牌 503/401
正是「优雅态验收」的预期输入，UI 侧由 SemanticState 四态如实呈现；JS 异常永不豁免）：
    - "Failed to load resource: ..."（含 net::ERR_CONNECTION_REFUSED / HTTP 503 / 401 等）
    - favicon 加载失败（本 dist 已用 data: URI，属遗留防御）

API 基址注入：dist 的 api-client 从 localStorage `webui:baseUrl` 读覆盖值（见
webui/src/lib/api-client.ts），脚本经 context.add_init_script 在页面脚本运行前写入
（file:// 下 Chromium 允许 localStorage）；令牌同理写 `webui:bearer` / `webui:bearer:ro`。
若 init 探测发现 localStorage 不可用，自动回退为本地极简静态包装页（stdlib http.server，
向 dist HTML 头部注入同一段 localStorage 预置脚本后同端口伺服）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

# 每页注册表：route=hash 路由；ok=数据态标志文案（任一命中即 data 模式）；
# graceful_extra=该页特有降级文案（通用四态文案所有页共享，见 COMMON_GRACEFUL）。
# ok 文案取自 webui/src/locales/zh-CN/common.json，均为「仅在数据 ok 分支渲染」的段落标题。
PAGE_SPECS: list[dict] = [
    {"name": "dashboard", "route": "/", "ok": ["在线", "降级"], "graceful_extra": []},
    {"name": "calls", "route": "/calls", "ok": ["窗口内调用"], "graceful_extra": []},
    {"name": "tokens", "route": "/tokens", "ok": ["窗口总量"], "graceful_extra": []},
    {"name": "latency", "route": "/latency", "ok": ["渠道（"], "graceful_extra": []},
    {"name": "affinity", "route": "/affinity", "ok": ["好感度排行"], "graceful_extra": []},
    {
        "name": "logs",
        "route": "/logs",
        # 真数据证据=事件行 DOM 在场（rows>0 才渲染 aria-live 容器）或心跳文案（仅 open+有心跳）。
        # 注意「已连接，等待事件…」是空态文案（connected 含 connecting/reconnecting），不作 ok 标记。
        "ok": ["心跳"],
        "ok_dom": "[aria-live='polite'] div",
        "graceful_extra": ["未连接", "连接中", "重连中", "已连接，等待事件", "连接被拒"],
    },
    # 二期三页（dist 2026-09-19 03:14 起已构建）：ok 标记全部取「仅数据分支渲染」的证据——
    # 词条卡内容（别名行/文本块数/表情数/检索源启用徽章）、插件组卡徽章、图谱画布+图例。
    {
        "name": "knowledge",
        "route": "/knowledge",
        "ok": ["别名：", "个文本块", "条表情", "启用中"],
        "graceful_extra": ["知识库目录未部署", "知识库数据源均未启用", "该集合暂无词条", "没有匹配"],
    },
    {
        "name": "plugins",
        "route": "/plugins",
        # 注意「要重启」出现在页面副标题（常驻），绝不可作 ok 标记。
        "ok": ["热更新即可", "暂无条目", "该组清单暂不可用"],
        "graceful_extra": ["插件目录未部署"],
    },
    {
        "name": "memory-graph",
        "route": "/memory-graph",
        "ok": ["关联图谱", "图例"],
        "ok_dom": "canvas",
        "graceful_extra": ["记忆图谱未部署", "该时间窗内无记忆关联数据"],
    },
]

# 通用优雅降级文案（SemanticState 四态 + logs 静息），见 webui/src/components/semantic/semantic-state.tsx。
COMMON_GRACEFUL = ["加载失败", "暂无数据", "控制面未配置访问令牌", "令牌无效或无权限"]
SHELL_MARKER = "守岸人控制台"
MIN_BODY_CHARS = 30
NOISE_RE = re.compile(r"Failed to load resource|net::ERR_|favicon", re.IGNORECASE)

# 页内求值：只找**独立成节点**的脏值，避免把正文里的单词误判成违例。
VALUE_PROBE_JS = """() => {
  const dirty = new Set(['NaN', 'undefined', 'Infinity', '-Infinity', 'Invalid Date', '[object Object]', 'null']);
  const bad = [];
  for (const node of document.querySelectorAll('main *')) {
    if (node.children.length) continue;
    const text = (node.textContent || '').trim();
    if (dirty.has(text)) bad.push(text);
    if (bad.length >= 20) break;
  }
  return bad;
}"""
STORAGE_PRELUDE = """
(() => {{
    try {{
        {sets}
        window.__uiaccStorageOk = true;
    }} catch (e) {{
        window.__uiaccStorageOk = false;
    }}
}})();
"""


class _WrapperHandler(BaseHTTPRequestHandler):
    """极简静态包装页：同端口伺服注入了 localStorage 预置脚本的 dist HTML（仅回退用）。"""

    html = ""
    server: ThreadingHTTPServer

    def do_GET(self) -> None:
        body = self.html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # 静默，产物零落盘
        return


def start_wrapper_server(dist_html: str, storage_js: str) -> tuple[ThreadingHTTPServer, str]:
    """把 dist/index.html 头部注入 localStorage 预置脚本后起本地伺服（127.0.0.1 随机端口）。"""
    injected = re.sub(r"(<head[^>]*>)", rf"\1<script>{storage_js}</script>", dist_html, count=1)
    if injected == dist_html:  # 无 <head>（理论不可达）：整体前置
        injected = f"<script>{storage_js}</script>" + dist_html
    _WrapperHandler.html = injected
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WrapperHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def build_storage_js(api: str | None, token: str | None, ro_token: str | None) -> str:
    sets = []
    if api:
        sets.append(f"localStorage.setItem('webui:baseUrl', {json.dumps(api.rstrip('/'))});")
    if token:
        sets.append(f"localStorage.setItem('webui:bearer', {json.dumps(token)});")
    if ro_token:
        sets.append(f"localStorage.setItem('webui:bearer:ro', {json.dumps(ro_token)});")
    return STORAGE_PRELUDE.format(sets="".join(sets))


def _text_visible(page: Page, text: str) -> bool:
    try:
        return page.get_by_text(text, exact=False).first.is_visible()
    except PlaywrightError:  # 页面跳转/销毁瞬间的 stale 引用：按不可见处理
        return False


def wait_any_text(page: Page, texts: list[str], timeout_s: float) -> str | None:
    """轮询等待任一文案可见（避开 skeleton 瞬态与 react-query 有限重试的时序抖动）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for text in texts:
            if _text_visible(page, text):
                return text
        time.sleep(0.25)
    return None


def wait_any_dom(page: Page, css: str, timeout_s: float) -> str | None:
    """轮询等待任一 CSS 选择器命中（返回命中选择器；不适用即 None）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if page.locator(css).first.is_visible():
                return css
        except PlaywrightError:
            pass
        time.sleep(0.25)
    return None


def run(args: argparse.Namespace) -> tuple[list[dict], str]:
    dist = Path(args.dist).resolve()
    if not dist.exists():
        raise SystemExit(f"[uiacc] dist 不存在: {dist}")
    # 验收对象是**产物**：dist 落后于 src 时，一张绿单证明的是已经不存在的代码。
    src_root = dist.parent.parent / "src"
    if src_root.is_dir() and not args.allow_stale_dist:
        newest_src = max((f.stat().st_mtime for f in src_root.rglob("*") if f.is_file()), default=0.0)
        lag = newest_src - dist.stat().st_mtime
        if lag > 2:
            raise SystemExit(
                f"[uiacc] dist 落后 src {int(lag)}s（dist={int(dist.stat().st_mtime)} / "
                f"newest_src={int(newest_src)}）——先 `cd webui && npm run build` 再验收"
            )
    shot_dir = Path(args.shot_dir).expanduser()
    shot_dir.mkdir(parents=True, exist_ok=True)

    names = parse_pages(args.pages)
    specs = [s for s in PAGE_SPECS if s["name"] in names]

    storage_js = build_storage_js(args.api, args.token, args.ro_token)
    results: list[dict] = []
    wrapper: ThreadingHTTPServer | None = None
    base_uri = dist.as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900})
        context.add_init_script(storage_js)

        probe = context.new_page()
        probe.goto(base_uri + "#/", wait_until="load")
        if not wait_any_text(probe, [SHELL_MARKER], 15):
            probe.screenshot(path=str(shot_dir / "_app-shell-dead.png"), full_page=True)
            raise SystemExit("[uiacc] 应用壳未挂载（守岸人控制台 标题未见），dist 或构建损坏；截图 _app-shell-dead.png")
        storage_ok = probe.evaluate("() => window.__uiaccStorageOk !== false")
        # file:// 下 TanStack Link 会把 href 绝对化（/C:/...index.html#/calls），
        # 故统一解析成 hash 分量再比对路由（http 下为 #/xxx，两态通吃）。
        nav_eval = (
            "() => Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => { try { return new URL(a.getAttribute('href'), location.href).hash } catch { return '' } })"
            ".filter(h => h.startsWith('#/'))"
        )
        nav_hrefs = probe.evaluate(nav_eval)
        if not storage_ok and args.api:
            # file:// localStorage 受限 → 回退静态包装页伺服（注入同一段预置脚本）。
            wrapper, wrapper_url = start_wrapper_server(dist.read_text(encoding="utf-8"), storage_js)
            base_uri = wrapper_url
            note = f"file:// localStorage 不可用，回退包装页 {wrapper_url}"
            print(f"[uiacc] {note}")
            probe.goto(base_uri + "#/", wait_until="load")
            wait_any_text(probe, [SHELL_MARKER], 15)
            nav_hrefs = probe.evaluate(nav_eval)
        probe.close()

        for spec in specs:
            results.append(
                check_page(
                    context,
                    base_uri,
                    spec,
                    nav_hrefs,
                    shot_dir,
                    args.timeout,
                    api_origin=(args.api or base_uri).rstrip("/"),
                    expect=args.expect,
                )
            )
        browser.close()
    if wrapper is not None:
        wrapper.shutdown()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dist": str(dist),
        "api": args.api or "(同源)",
        "token": bool(args.token or args.ro_token),
        "shot_dir": str(shot_dir),
        "pages": results,
    }
    return results, json.dumps(summary, ensure_ascii=False, indent=2)


def check_page(
    context: BrowserContext,
    base_uri: str,
    spec: dict,
    nav_hrefs: list[str],
    shot_dir: Path,
    timeout_s: float,
    *,
    api_origin: str = "",
    expect: str = "any",
) -> dict:
    name, route = spec["name"], spec["route"]
    result: dict = {"page": name, "route": route, "status": "FAIL", "mode": None, "marker": None,
                    "fatal_console": [], "noise_console": 0, "screenshot": None, "reason": "",
                    "real_responses": 0}
    errors: list[dict] = []
    responses: list[tuple[int, str]] = []
    page = context.new_page()
    page.on("console", lambda m: errors.append({"kind": "console", "text": m.text}) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append({"kind": "pageerror", "text": str(e)}))
    # 数据态宣称必须能被**出网证据**背书：只看 DOM 文本的话，一页手写 HTML 贴上标志字串就能骗过整轮。
    page.on("response", lambda r: responses.append((r.status, r.url)))

    try:
        page.goto(f"{base_uri}#{route}", wait_until="load")
        if not wait_any_text(page, [SHELL_MARKER], timeout_s):
            result["reason"] = "应用壳未挂载"
            return result

        if f"#{route}" not in nav_hrefs:
            # 路由未构建（二期在飞）：记录现场即 SKIP，不算失败也不挡退出码。
            result["status"] = "SKIP"
            result["reason"] = "路由未构建（导航无该链接，二期在飞）"
            return result

        ok_marker = wait_any_text(page, spec["ok"], timeout_s)
        if ok_marker is None and spec.get("ok_dom"):
            # DOM 级数据标记（如 logs 事件行）：随文本轮询同窗口等待。
            ok_marker = wait_any_dom(page, spec["ok_dom"], timeout_s)
        graceful_marker = None if ok_marker else wait_any_text(
            page, COMMON_GRACEFUL + spec["graceful_extra"], timeout_s
        )
        result["marker"] = ok_marker or graceful_marker
        result["mode"] = "data" if ok_marker else ("graceful" if graceful_marker else None)

        body_text = ""
        try:
            body_text = page.locator("main").inner_text(timeout=3000)
        except PlaywrightError:
            body_text = page.locator("body").inner_text(timeout=3000)
        blank = len(body_text.strip()) < MIN_BODY_CHARS

        shot = shot_dir / f"{name}.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshot"] = str(shot)

        for e in errors:
            if e["kind"] == "pageerror" or not NOISE_RE.search(e["text"]):
                result["fatal_console"].append(f"{e['kind']}: {e['text'][:300]}")
            else:
                result["noise_console"] += 1

        # 数据态必须出过网：E2（一页零请求的手写 HTML）与 E6（页内 fetch 垫片伪造响应）在此双双失效。
        # 只认 /api/ 命名空间的响应——文档自身的 200 不算证据，否则同源包装页会自证清白。
        real_api = [url for status, url in responses if status == 200 and "/api/" in url and url.startswith(api_origin)]
        result["real_responses"] = len(real_api)
        violations = page.evaluate(VALUE_PROBE_JS) if result["mode"] else []

        if result["mode"] is None:
            result["reason"] = f"数据态/优雅态标志均未出现（{timeout_s}s）；body {len(body_text.strip())} 字"
        elif violations:
            # 结构合法但语义不可能（NaN/undefined/[object Object] 直接印在页上）——两种模式都查。
            result["reason"] = f"值域探针违例 {len(violations)} 条：{violations[:5]}"
        elif ok_marker and not real_api:
            result["reason"] = (
                f"mode=data 但窗口内零真实 /api/ 200 响应（api={api_origin}，捕获响应 {len(responses)} 条）"
                "——夹具/降级/页内垫片冒充数据态"
            )
        elif blank:
            result["reason"] = f"页面近白屏（main 文本 {len(body_text.strip())} 字 < {MIN_BODY_CHARS}）"
        elif result["fatal_console"]:
            result["reason"] = f"非白名单控制台错误 {len(result['fatal_console'])} 条"
        elif expect != "any" and result["mode"] != expect:
            result["reason"] = f"mode={result['mode']} 不满足 --expect {expect}"
        else:
            result["status"] = "PASS"
            detail = "数据态标志在场" if ok_marker else f"优雅降级态在场（{graceful_marker}）非白屏"
            evidence = f"/api/ 真响应 {result['real_responses']} 条" if ok_marker else "未取数据"
            result["reason"] = f"{detail}；{evidence}；白名单网络噪声 {result['noise_console']} 条"
    except PlaywrightError as exc:  # playwright 异常（页崩溃等）→ FAIL 带因
        result["reason"] = f"驱动异常: {exc}"
    finally:
        page.close()
    return result


def parse_pages(value: str) -> set[str]:
    all_names = {s["name"] for s in PAGE_SPECS}
    if value.strip().lower() == "all":
        return all_names
    names = {n.strip() for n in value.split(",") if n.strip()}
    unknown = names - all_names
    if unknown:
        raise SystemExit(f"[uiacc] 未知页名: {sorted(unknown)}；可选: {sorted(all_names)}")
    return names


def print_table(results: list[dict], allow_skip: bool = False) -> int:
    print()
    print(f"{'页':<14}{'路由':<16}{'结果':<7}{'模式':<10}摘要")
    print("-" * 100)
    fails = 0
    for r in results:
        mark = {"PASS": "PASS", "SKIP": "SKIP", "FAIL": "FAIL"}[r["status"]]
        if r["status"] == "FAIL":
            fails += 1
        mode = r["mode"] or "-"
        print(f"{r['page']:<14}{r['route']:<16}{mark:<7}{mode:<10}{r['reason']}")
        if r["fatal_console"]:
            for line in r["fatal_console"][:3]:
                print(f"{'':<47}└ {line}")
    skips = sum(1 for r in results if r["status"] == "SKIP")
    print("-" * 100)
    print(f"合计 {len(results)} 页：PASS {sum(1 for r in results if r['status'] == 'PASS')} / "
          f"SKIP {skips} / FAIL {fails}")
    # SKIP 默认计红：「这页还没构建」从来不是「验收通过」的理由（F4-b E4 实证旧行为）。
    if skips and not allow_skip:
        print("→ SKIP 视为未通过；确认在飞可加 --allow-skip 放行")
    return 1 if (fails or (skips and not allow_skip)) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="守岸人 WebUI 端到端目验（playwright 无头）")
    parser.add_argument("--dist", default="webui/dist/index.html", help="dist 单文件路径")
    parser.add_argument("--api", default="http://127.0.0.1:8743",
                        help="控制面/mock API 基址（写入 localStorage webui:baseUrl；空串=同源）")
    parser.add_argument("--token", default=None, help="Bearer 主令牌（可选，写 webui:bearer）")
    parser.add_argument("--ro-token", default=None, help="Bearer 只读令牌（可选，写 webui:bearer:ro）")
    parser.add_argument("--pages", default="all",
                        help="all 或逗号列表: dashboard,calls,tokens,latency,affinity,logs,knowledge,plugins,memory-graph")
    parser.add_argument("--shot-dir", default=os.path.join(tempfile.gettempdir(), "webui-acceptance"),
                        help="截图输出目录（默认 %%TEMP%%/webui-acceptance）")
    parser.add_argument("--timeout", type=float, default=20.0, help="单页标志等待秒数")
    parser.add_argument("--expect", choices=["any", "data", "graceful"], default="any",
                        help="把数据态升格为判定量：data=每页必须真取到数据（真后端验收必带），"
                             "graceful=整轮按降级态验收；缺省 any 只保证不白屏")
    parser.add_argument("--allow-skip", action="store_true",
                        help="放行 SKIP（默认计红：路由未构建不算验收通过）")
    parser.add_argument("--allow-stale-dist", action="store_true",
                        help="放行 dist 落后 src（默认拒跑：绿单会证明已不存在的代码）")
    parser.add_argument("--json", action="store_true", help="额外输出 JSON 摘要到 stdout")
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台中文表

    results, payload = run(args)
    code = print_table(results, allow_skip=args.allow_skip)
    if args.json:
        print(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
