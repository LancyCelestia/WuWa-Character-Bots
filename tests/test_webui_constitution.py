"""WebUI 前端三门常驻回归：版式宪法 / tsc 编译 / 图布局确定性 / package.json 入口一致性。

此前三门只存在于人肉命令里，`tests/` 对它们零接线（F4 席实跑 grep 为 0 命中）。
常驻化按硬依赖处理：**缺 node 即 FAIL，不许 skip**——skip 化等于门消失。

三门本体（cwd=webui/）：
  1) node scripts/layout-constitution.mjs
  2) node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json
     node node_modules/typescript/bin/tsc --noEmit -p tsconfig.node.json
  3) node --test --test-reporter=tap src/lib/graph-layout.test.ts

零缓存纪律：门内绝不跑 `tsc -b`（它写 node_modules/.tmp/*.tsbuildinfo）；
`--noEmit -p <project>` 形态零写入。绝不跑 `npm install` / `npm run build`。
禁用 `-p .`：root tsconfig files 为空，零文件空转必假绿。

编码：子进程按 bytes 捕获再手工 utf-8 解码（宪法门绿文案含中文，Windows
locale 下 text=True 有乱码风险）；node --test 取 TAP 形态（摘要行纯 ASCII）。
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui"
NODE = shutil.which("node")

# 按仓库惯例继承 os.environ 后定点覆盖，不暗改机器级 node 配置。
GATE_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}

# node 直跑 JS 入口，绕开 Windows .bin/tsc.cmd 垫片（cmd 包装层丢 stderr 语义）。
TSC_BIN = "node_modules/typescript/bin/tsc"


def _require_node() -> str:
    if NODE is None:
        pytest.fail(
            "常驻门硬依赖 node（skip 化等于门消失）。请安装 Node ≥23.6"
            "（type stripping 原生）并确保其在 PATH，随后复跑本文件。"
        )
    return NODE


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=str(WEBUI),
        capture_output=True,
        timeout=timeout,
        env=GATE_ENV,
        check=False,
    )


def _run_checked(name: str, args: list[str], timeout: int) -> tuple[str, str]:
    try:
        proc = _run(args, timeout)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"").decode("utf-8", errors="replace")
        pytest.fail(f"{name} 超时（>{timeout}s），命令={args}\n已捕获输出：\n{partial}")
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, (
        f"{name} 红：exit={proc.returncode}，命令={args}，cwd={WEBUI}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    return stdout, stderr


def test_layout_constitution_gate() -> None:
    node = _require_node()
    script = WEBUI / "scripts/layout-constitution.mjs"
    assert script.is_file(), f"宪法门脚本缺失：{script}"
    stdout, _ = _run_checked("版式宪法门", [node, "scripts/layout-constitution.mjs"], 60)
    # 仅 rc==0 不够——再锚定绿文案，防脚本被改成空转恒真。
    assert "全部通过" in stdout, f"宪法门 exit 0 但 stdout 无绿文案：\n{stdout}"


def test_tsc_typecheck_all_projects() -> None:
    node = _require_node()
    tsc = WEBUI / TSC_BIN
    assert tsc.is_file(), (
        f"typescript 包缺失：{tsc}——常驻门不代跑安装（离线纪律），"
        "请在 webui/ 人工 npm install 后复跑。"
    )
    for project in ("tsconfig.app.json", "tsconfig.node.json"):
        assert (WEBUI / project).is_file(), f"{WEBUI / project} 缺失"
        _run_checked(f"tsc --noEmit -p {project}", [node, str(tsc), "--noEmit", "-p", project], 180)


def test_pure_function_tests() -> None:
    """前端纯函数确定性单测：跑通配而非点名单个文件——新增测试文件不得静默不跑。"""
    node = _require_node()
    cases = sorted((WEBUI / "src").glob("**/*.test.ts"))
    assert len(cases) >= 2, f"src/**/*.test.ts 只匹配到 {len(cases)} 个文件（纯函数测试被删了？）"
    stdout, _ = _run_checked(
        "node --test src/**/*.test.ts",
        [node, "--test", "--test-reporter=tap", "src/**/*.test.ts"],
        120,
    )
    assert "# fail 0" in stdout, f"node --test 有失败用例：\n{stdout}"
    assert "# cancelled 0" in stdout, f"node --test 有取消用例：\n{stdout}"
    match = re.search(r"^# pass (\d+)$", stdout, re.MULTILINE)
    assert match is not None, f"TAP 摘要行缺失（reporter 形态变了？Node 版本漂移？）：\n{stdout}"
    passed = int(match.group(1))
    # 下限而非定值：加用例不砸门，删到基线以下才红。
    assert passed >= 29, f"pass 数 {passed} < 29（2026-09-19 UNI1 基线 graph-layout 7 + semantics 14 + labels 8，不应回退）"


def test_package_json_entries_match_gates() -> None:
    pkg = json.loads((WEBUI / "package.json").read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})
    assert "layout-constitution.mjs" in scripts.get("build", ""), (
        "build 不再前置宪法门——产物将绕过版式约束"
    )
    assert "layout-constitution.mjs" in scripts.get("lint:layout", "")
    test_entry = scripts.get("test", "")
    assert "node --test" in test_entry and "src/**/*.test.ts" in test_entry, (
        f"scripts.test 必须跑通配（点名单文件会让新增测试静默不跑）：{test_entry!r}"
    )
    check = scripts.get("check", "")
    for needle in ("typecheck", "lint:layout", "test"):
        assert needle in check, f"scripts.check 应链 {needle}：{check!r}"


def _load_webui_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multifile_build_and_lazy_routes() -> None:
    config = (WEBUI / "vite.config.ts").read_text(encoding="utf-8")
    assert re.search(r"base:\s*['\"]/ui/['\"]", config)
    assert "viteSingleFile" not in config and "vite-plugin-singlefile" not in config
    assert "tailwindcss()" in config and "react()" in config
    assert "'/api/v1'" in config and "'/admin/api/v1'" in config
    index = (WEBUI / "index.html").read_text(encoding="utf-8")
    assert "script-src 'self';" in index
    assert "script-src 'self' 'unsafe-inline'" not in index
    assert "style-src 'self' 'unsafe-inline'" in index
    router = (WEBUI / "src/router.tsx").read_text(encoding="utf-8")
    pages = ("dashboard", "calls", "tokens", "latency", "affinity", "logs", "knowledge", "plugins", "memory-graph")
    for page in pages:
        assert f"import('@/pages/{page}')" in router
        assert not re.search(rf"^import .* from ['\"]@/pages/{page}['\"]", router, re.MULTILINE)
    assert router.count("lazyRouteComponent(") == len(pages)
    assert "validateSearchFor<{ collection?: string }>('/knowledge')" in router
    assert "errorComponent: RootErrorComponent" in router


def test_dev_refresh_csp_transform_without_server() -> None:
    snippet = r"""
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import configFor from './vite.config.ts';
const source = readFileSync('index.html', 'utf8');
assert.ok(source.includes("script-src 'self';"));
const env = command => ({ command, mode: command === 'serve' ? 'development' : 'production' });
const build = configFor(env('build'));
assert.ok(!build.plugins.flat(Infinity).some(p => p?.name === 'webui:dev-csp'));
const dev = configFor(env('serve'));
const plugins = dev.plugins.flat(Infinity).filter(Boolean);
const csp = plugins.find(p => p.name === 'webui:dev-csp');
assert.equal(csp.apply, 'serve');
assert.equal(csp.transformIndexHtml.order, 'post');
const refresh = plugins.find(p => p.name === 'vite:react-refresh');
plugins.find(p => p.name === 'vite:react-babel').configResolved({ base: '/ui/', root: process.cwd(), isProduction: false, command: 'serve', server: {}, experimental: {}, plugins });
const tags = refresh.transformIndexHtml();
assert.equal(tags.length, 1);
assert.ok(tags[0].children.includes('/ui/@react-refresh'));
const input = source.replace('</head>', `<script type="module">${tags[0].children}</script></head>`);
const first = csp.transformIndexHtml.handler(input, {});
const second = csp.transformIndexHtml.handler(input, {});
const nonce = /script-src 'self' 'nonce-([^']+)';/.exec(first)?.[1];
assert.ok(nonce && /^[A-Za-z0-9+/=]+$/.test(nonce));
assert.notEqual(first, second);
assert.ok(first.includes(`<script type="module" nonce="${nonce}">`));
assert.ok(first.includes('injectIntoGlobalHook'));
assert.ok(!first.includes("script-src 'self' 'unsafe-inline'"));
assert.ok(first.includes("style-src 'self' 'unsafe-inline'"));
console.log('dev CSP transform passed');
"""
    stdout, _ = _run_checked("dev React Refresh CSP transform", [_require_node(), "--input-type=module", "-e", snippet], 60)
    assert "dev CSP transform passed" in stdout


@pytest.mark.parametrize("script,handler_name", [
    ("webui_mock_server", "MockHandler"), ("webui_acceptance", "_WrapperHandler"),
])
def test_dist_handlers_serve_real_assets_without_listening(tmp_path: Path, script: str, handler_name: str) -> None:
    module = _load_webui_script(script)
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    html = '<html><head><script type="module" src="/ui/assets/app.js"></script><link rel="stylesheet" href="/ui/assets/app.css"></head><body>UI</body></html>'
    (dist / "index.html").write_text(html, encoding="utf-8")
    (assets / "app.js").write_bytes(b"export const realAsset = 1;")
    (assets / "app.css").write_bytes(b"body { color: red; }")
    (tmp_path / "outside.js").write_bytes(b"must not leak")

    def request(path: str, method: str = "GET"):
        handler = object.__new__(getattr(module, handler_name))
        handler.path, handler.command = path, method
        handler.server = SimpleNamespace(dist_root=dist, bearer_mode=False, delay_ms=0)
        handler.wfile = io.BytesIO()
        handler.headers = {}
        headers = {}
        status = []
        handler.send_response = status.append
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        getattr(handler, f"do_{method}")()
        return status[0], headers, handler.wfile.getvalue()

    status, headers, body = request("/ui/")
    assert status == 200 and body == html.encode()
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"].startswith("text/html")
    assert not re.search(r"(?:src|href)=[\"'](?:https?:)?//", html)
    status, headers, _ = request("/ui")
    assert status == 307 and headers["Location"] == "/ui/"
    for name, mime in (("app.js", "javascript"), ("app.css", "text/css")):
        status, headers, body = request(f"/ui/assets/{name}?v=1")
        assert status == 200 and body == (assets / name).read_bytes()
        assert mime in headers["Content-Type"]
        assert int(headers["Content-Length"]) == len(body)
        assert request(f"/ui/assets/{name}", "HEAD")[2] == b""
    for path in ("/ui/assets/missing.js", "/ui/unknown", "/unknown", "/ui/../outside.js", "/ui/assets/%2e%2e/%2e%2e/outside.js", "/ui/assets/..%5c..%5coutside.js", "/ui/assets/C:%5coutside.js"):
        status, headers, body = request(path)
        assert status == 404, path
        assert body != html.encode() and b"must not leak" not in body
    # Resolve substitutes model links without requiring Windows symlink privilege.
    real_resolve = Path.resolve
    private = dist / "private.txt"
    private.write_bytes(b"private dist file must not leak")
    with pytest.MonkeyPatch.context() as patch:
        def linked_resolve(self, *args, **kwargs):
            if self == assets / "link.txt":
                return real_resolve(private)
            if self == assets / "outside.txt":
                return real_resolve(tmp_path / "outside.js")
            return real_resolve(self, *args, **kwargs)
        patch.setattr(Path, "resolve", linked_resolve)
        assert request("/ui/assets/link.txt")[0] == 404
        assert request("/ui/assets/outside.txt")[0] == 404
    with pytest.MonkeyPatch.context() as patch:
        def escaped_assets_resolve(self, *args, **kwargs):
            if self == assets:
                return real_resolve(tmp_path)
            return real_resolve(self, *args, **kwargs)
        patch.setattr(Path, "resolve", escaped_assets_resolve)
        assert request("/ui/assets/app.js")[0] == 404
    (dist / "index.html").unlink()
    assert request("/ui/")[0] == 404
    assert request("/ui")[0] == 404


# ---------------------------------------------------------------------------
# 门 5（行为锁）：真身 cn() 必须真的折叠 fs-*。
# 专治 tailwind-merge 3.x 的静默失效陷阱——顶层 classGroups 会被 mergeConfigs 丢弃、
# 组名写错也不报错，两种情况下 tsc/宪法门全绿而版式冲突照旧。故只断言行为，不读源码。
# ---------------------------------------------------------------------------

_CN_BEHAVIOR_SNIPPET = """
const { cn } = await import('./src/lib/utils.ts');
console.log(JSON.stringify({
  baseVsLadder: cn('leading-none font-semibold', 'fs-card'),
  sameGroup: cn('fs-caption', 'fs-body'),
  colorSafe: cn('text-muted-foreground fs-body', 'fs-caption'),
}));
"""


def test_cn_merges_type_ladder_classes() -> None:
    node = _require_node()
    stdout, stderr = _run_checked(
        "cn() 行为锁",
        [node, "--input-type=module", "-e", _CN_BEHAVIOR_SNIPPET],
        60,
    )
    try:
        merged = json.loads(stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        pytest.fail(f"cn() 行为锁输出不可解析：{exc}\nstdout={stdout}\nstderr={stderr}")
    # ①组件基类行高类必须被调用方字号折叠掉（旧 P1-1 那一族的结构性根治）。
    assert merged["baseVsLadder"] == "font-semibold fs-card", (
        f"基类行高未被 fs-* 折叠 → merger 配置静默失效：{merged['baseVsLadder']!r}"
    )
    # ②同组两条字号折叠为「后者胜」=调用方胜。
    assert merged["sameGroup"] == "fs-body", f"同组字号未折叠：{merged['sameGroup']!r}"
    # ③颜色组不得被误伤（字号组与颜色组必须互不干扰）。
    assert "text-muted-foreground" in merged["colorSafe"], (
        f"注册 fs-* 后误删颜色类：{merged['colorSafe']!r}"
    )
    assert merged["colorSafe"].split().count("fs-caption") == 1, (
        f"字号档位折叠异常：{merged['colorSafe']!r}"
    )
