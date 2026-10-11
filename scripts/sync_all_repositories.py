"""分库远端同步与发布（主人 2026-10-11 常令："主项目和所有一级子功能各建独立 git 库、上传 GitHub、**每次 push 都要更新**"）。

为什么要这么一把尺（不是又一条旁支）
------------------------------------
15 座一级功能库由库工厂从**声明源**派生实体；但"实体落盘"与"远端在册"是两件事：
工厂一直只打印 `PLANNED-GIT-COMMANDS.txt` 而不执行，于是主仓前进了、库的 HEAD 停在旧提交上，
而任何尺都看不见这件事（它不在测试树里，也不在文档门里）。这一件把那条断口变成**可判据**：
先核身（有无 `.git`／远端属主对不对／ahead-behind／脏度／未预期残骸），再按显式授权发布。

三态（禁把不可判折成绿）
------------------------
`0`＝全部同步干净（GREEN）；`1`＝存在漂移或未授权状态（RED，逐枚点名）；
`2`＝**不可判**：仓外库根不在场（HEAD 轴抽取副本、换机器检出）——没有证据不等于没人干活。

安全边界（写死，不接受参数放宽）
--------------------------------
- 读侧默认：`--check` 不写任何东西，也不联网（`git fetch` 都不跑，见 `_state` 的口径说明）。
- 写侧只在**显式** `--publish` 时开：逐座 `add/commit/tag/push`，🔴 **绝不对主仓做 commit**——
  主仓的提交是逐文件显式动作（AGENTS 规则 4），本件对主仓只 push 已有 HEAD。
- 拒发布条件：库里出现未预期残骸（`.env*`/`*.key`/`data/`/`__pycache__`）、远端属主不是
  `EXPECTED_OWNER`、版本抬了却没有对应 tag 且该 tag 已存在但指向别的对象。
- 网络：本机 git 不吃系统代理 ⇒ 需要时由 `--proxy` 逐条注入 `-c`，**不写进任何 git 配置**。

成员名册不在这里重复声明：座次名册＝库工厂投影（`ChatBot_Libs/MANIFEST.md` 的成员行，
只认第二列反引号里的 kebab slug，不看表头字样），与 `scripts/pre_restart_check.py` 同一条抓法。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DEFAULT = Path(__file__).resolve().parents[1]
LIBS_DIRNAME = "ChatBot_Libs"
MANIFEST_NAME = "MANIFEST.md"
#: 分库必须挂在她的账号下、且除主仓外全部私有（主人 2026-10-11 裁定 2 甲）。
EXPECTED_OWNER = "LancyCelestia"
#: 远端 URL 里允许出现的宿主（只允许 github.com；别的宿主＝有人把库指到别处去，当场红）。
ALLOWED_HOSTS = ("github.com",)
#: kebab slug 形状（与库工厂/板块门同形）。
KEBAB_CELL_RE = re.compile(r"^`([a-z0-9][a-z0-9_-]*)`$")
#: 库里与主仓**同路径比字节**的那一层（工厂就是把这一层逐枚拷过去的；册/工具件不比）。
SNAPSHOT_SOURCE_ROOT = "plugins"
#: 库里绝不许出现的残骸（发布前逐枚点名并拒绝）。
FORBIDDEN_PATTERNS: tuple[str, ...] = (
    ".env", ".env.local", "id_rsa", ".pem", ".key", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "node_modules",
)
FORBIDDEN_SUFFIXES: tuple[str, ...] = (".sqlite3", ".sqlite", ".db", ".pkl", ".faiss", ".index", ".log")
#: 允许出现在库工作树里的文件名（库工厂自己写的那几本册＋成员＋包层）。
ALLOWED_ROOT_NAMES: frozenset[str] = frozenset({
    "pyproject.toml", "VERSION", "workspace-lib.manifest.json", "PLANNED-GIT-COMMANDS.txt",
    "README.md", ".gitignore", "MANIFEST.md", "SNAPSHOT-STAMP.txt", "requirements-compose.txt",
    "plugins", "tests", "docs", "scripts", ".git",
})


def _run(argv: list[str], cwd: Path, proxy: str | None = None,
         config: tuple[str, ...] = ()) -> tuple[int, str]:
    """跑一条 git 命令。`config` 是 `k=v` 串，**只挂在这条命令上**（`git -c k=v …`）。

    🔴 `-c` 必须排在子命令之前：把 `-c` 放进 argv 头部会让 `CreateProcess` 拿 `-c` 当可执行文件
    （本机实犯：`--publish` 第一次就在 commit 腿上直接崩进程）。代理同理走 config，不拼字符串。
    """
    cmd = list(argv)
    if cmd[:1] != ["git"]:
        raise ValueError(f"本尺只跑 git 命令，收到 {cmd[:2]}")
    pairs = list(config)
    if proxy and cmd[1] in ("push", "fetch", "ls-remote"):
        pairs.append(f"http.proxy={proxy}")
    for pair in pairs:
        cmd[1:1] = ["-c", pair]
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _git(repo: Path, *args: str, proxy: str | None = None,
         config: tuple[str, ...] = ()) -> tuple[int, str]:
    return _run(["git", *args], repo, proxy, config)


def _identity_args(repo: Path) -> tuple[str, ...]:
    """这座仓有没有自己的身份？没有就返回两枚 `k=v`，由 `_run` 挂成 `git -c k=v …`。

    分库是 `git init` 出来的、通常没有 user.name/user.email ⇒ 裸 `git commit` 直接失败。
    🔴 不用 `git config user.name ...`（那是写配置，越界）；`-c` 只对这一条命令生效。
    """
    have = True
    for key in ("user.name", "user.email"):
        rc, value = _git(repo, "config", "--get", key)
        have = have and rc == 0 and bool(value.strip())
    if have:
        return ()
    name_rc, name = _git(REPO_DEFAULT, "config", "--get", "user.name")
    mail_rc, mail = _git(REPO_DEFAULT, "config", "--get", "user.email")
    if name_rc != 0 or mail_rc != 0 or not name or not mail:
        return ()  # 主仓也读不到 ⇒ 让 git 自己报"who you are"，本件不猜身份
    return (f"user.name={name}", f"user.email={mail}")


def _manifest_slugs(libs_root: Path) -> list[str]:
    """座次名册＝库工厂投影的成员行（只认形状不认表头字样；表头改过名，靠表头取列的消费者瞎过）。"""
    manifest = libs_root / MANIFEST_NAME
    if not manifest.is_file():
        return []
    slugs: list[str] = []
    with open(manifest, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            hit = KEBAB_CELL_RE.match(cells[1])
            if hit and hit.group(1) not in slugs:
                slugs.append(hit.group(1))
    return slugs


def _residue(lib_dir: Path) -> list[str]:
    """库里出现未预期残骸 ⇒ 拒发布（比"顺手 commit 进去"便宜一万倍）。"""
    bad: list[str] = []
    for path in sorted(lib_dir.rglob("*")):
        if ".git" in path.parts:
            continue
        rel = path.relative_to(lib_dir).as_posix()
        lowered = rel.lower()
        if any(token in lowered for token in FORBIDDEN_PATTERNS):
            bad.append(f"{rel}（命中禁词残骸）")
        elif lowered.endswith(FORBIDDEN_SUFFIXES):
            bad.append(f"{rel}（运行数据形态后缀＝生产件不该进分库）")
        elif len(path.parts) == 1 and path.name not in ALLOWED_ROOT_NAMES:
            bad.append(f"{rel}（库根层出现未登记名）")
    return bad


def _git_blob_sha(data: bytes) -> str:
    """git 的 blob 哈希＝`sha1("blob <len>\\0" + 内容)`，与 `git ls-tree` 那列 objectname 同形。

    🔴 先把 CRLF 折回 LF 再哈希，且**折形之后**再算长度（同一枚文件的头部字节数必须与它哈希的内容一致）。
    主仓工作树里根 `__init__.py` 这类文件是 **CRLF**（实测 12006 枚 `\\r`），而 HEAD 的 blob 由
    `.gitattributes` 归一成 LF ⇒ 逐字节比会判"每一座库都旧"，而真正旧不旧跟换行符无关。
    本面要的是**内容**新旧，换行形态不算内容（本席首跑就整面误报过 11 座）。
    """
    normalized = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(normalized) + normalized).hexdigest()


def _head_blobs(repo: Path) -> dict[str, str] | None:
    """主仓 **HEAD** 那棵树的 `相对路径 → blob sha`（一次 `ls-tree`，零逐枚子进程）。

    🔴 比对轴必须是 HEAD、不是工作树：库实体是工厂按名册从主仓取的**派生物**，
    拿在飞的未提交改动当基准，就会把"别人正在写那枚文件"读成"这座库是旧的"
    （本席 2026-10-11 首跑就是这样误点名了一枚 `news_feeds.py`，实为别席在飞半件）。
    读不出（非检出／命令坏／空树）⇒ `None`＝失明，调用方禁默认"一致"。
    """
    rc, text = _git(repo, "-c", "core.quotePath=false", "ls-tree", "-r", "HEAD",
                    "--format=%(objectname)\t%(path)")
    if rc != 0 or not text.strip():
        return None
    blobs: dict[str, str] = {}
    for line in text.splitlines():
        head, sep, path = line.partition("\t")
        if sep and path.strip():
            blobs[path.strip().replace("\\", "/")] = head.strip()
    return blobs or None


def _content_drift(lib_dir: Path, head_blobs: dict[str, str] | None) -> dict[str, object]:
    """库里的 `plugins/**` 副本 vs 主仓 **HEAD** 那棵树 ⇒「源前进了、库没重生成」唯一可判读数。

    为什么不拿 `SNAPSHOT-STAMP.txt` 里那行 HEAD 直接比：stamp 记的是工厂**当时**的取数口径
    （`caliber=worktree`），主仓后续哪怕只提交文档，stamp 也会永远不一致＝**恒红**；反过来
    stamp 一致也证明不了内容一致（工厂产物被手工改过就看不出来）。本面判**实体内容**：
    内容没变就不是旧库，内容变了就逐枚点名。桥接件 `__init__.py` 按设计是源 init 的逐字节
    副本 ⇒ 同一条比法顺带罩住"桥接件被改成垫片"那一族（裁定①的形状门在 `pre_restart_check` 腿C）。

    🔴 `mirrored=0`（三座适配器空壳今天零实体）**只登记不判**：没有副本可比＝没有证据，
    既不产红也不进 undecidable 名册（否则整把尺会因为壳子而永久不可判，那是把"没货"读成"坏了"）。
    成员数对不对是 `pre_restart_check.library_roster` 那格的轴，不在本面重复建第二把尺。
    """
    mirrored_root = lib_dir / SNAPSHOT_SOURCE_ROOT
    mirrored = sorted(p for p in mirrored_root.rglob("*") if p.is_file()) \
        if mirrored_root.is_dir() else []
    out: dict[str, object] = {"mirrored": len(mirrored), "axis": "HEAD"}
    if head_blobs is None:
        out["blind"] = "HEAD_AXIS_UNREADABLE（主仓 HEAD 那棵树读不出＝没有证据，不判新旧）"
        return out
    differing: list[str] = []
    absent: list[str] = []
    for src in mirrored:
        rel = src.relative_to(lib_dir).as_posix()
        twin_sha = head_blobs.get(rel)
        if twin_sha is None:
            absent.append(rel)
            continue
        try:
            if _git_blob_sha(src.read_bytes()) != twin_sha:
                differing.append(rel)
        except OSError:
            differing.append(rel)
    out.update({
        "differing_count": len(differing),
        "differing": differing[:3],
        "absent_count": len(absent),
        "absent_in_head": absent[:3],
    })
    return out


def _state(repo: Path, proxy: str | None) -> dict[str, object]:
    """一座的本地读数：branch/HEAD/ahead/behind/dirty/origin。

    🔴 口径如实：**不跑 fetch**。ahead/behind 取的是"本地 HEAD ⇄ 本地记的 origin/<branch>"，
    它回答的是"我这边的提交推没推上去"（＝她要的那件事），不回答"远端有没有别人的新提交"。
    要后者得联网 fetch，那是 `--publish` 那一步之前由人做的动作，不由默认读数冒充。
    """
    out: dict[str, object] = {"path": str(repo), "is_git": False}
    rc, head = _git(repo, "rev-parse", "--short", "HEAD", proxy=proxy)
    if rc != 0:
        return out
    out["is_git"] = True
    out["head"] = head
    rc, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", proxy=proxy)
    out["branch"] = branch if rc == 0 else "?"
    rc, url = _git(repo, "remote", "get-url", "origin", proxy=proxy)
    out["origin"] = url if rc == 0 else ""
    out["origin_ok"] = rc == 0 and any(host in url for host in ALLOWED_HOSTS) and f"/{EXPECTED_OWNER}/" in url
    rc, counts = _git(repo, "rev-list", "--left-right", "--count", "HEAD...@{u}", proxy=proxy)
    ahead = behind = None
    if rc == 0 and "\t" in counts:
        a, _, b = counts.partition("\t")
        ahead, behind = int(a), int(b)
    out["ahead"] = ahead
    out["behind_upstream"] = behind
    rc, dirty = _git(repo, "status", "--porcelain", proxy=proxy)
    out["dirty"] = len([x for x in (dirty or "").splitlines() if x.strip()]) if rc == 0 else None
    rc, tags = _git(repo, "tag", "--list", proxy=proxy)
    out["tags"] = len([x for x in (tags or "").splitlines() if x.strip()]) if rc == 0 else None
    version_file = repo / "VERSION"
    out["version"] = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else None
    return out


def _commit_message(main_head: str, stamp: str) -> str:
    return f"chore(sync): 库实体同步（主仓 HEAD={main_head}，{stamp}，由 scripts/sync_all_repositories.py --publish）"


def _publish_lib(lib_dir: Path, slug: str, state: dict[str, object], main_head: str,
                 stamp: str, proxy: str | None, do: bool) -> dict[str, object]:
    """一座的发布腿。``do=False`` 时只打印将要执行的命令（演练档，零副作用）。"""
    plan: list[str] = ["git add -A"]
    if state["dirty"]:
        plan.append(f'git commit -m "{_commit_message(main_head, stamp)}"')
    version = str(state.get("version") or "")
    tag = f"{slug}/v{version}" if version else ""
    branch = str(state.get("branch") or "main")
    if tag:
        rc, listed = _git(lib_dir, "tag", "--list", tag, proxy=proxy)
        if not (listed or "").strip():
            plan.append(f"git tag {tag}")
    plan.append(f"git push origin refs/heads/{branch}:refs/heads/{branch}")
    if tag and f"git tag {tag}" in plan:
        plan.append(f"git push origin refs/tags/{tag}:refs/tags/{tag}")
    result: dict[str, object] = {"slug": slug, "plan": plan, "ran": [], "rc": 0}
    if not do:
        result["mode"] = "dry-run"
        return result
    steps: list[tuple[str, int, str]] = []
    if state["dirty"]:
        # 分库**没有**全局 git 身份（本机实犯：`git commit` 报 Please tell me who you are）。
        # 只在这一条命令上 `-c` 注入，绝不写任何一层的 git config。
        identity = _identity_args(lib_dir)
        rc, text = _run(["git", "add", "-A"], lib_dir, proxy)
        steps.append(("git add -A", rc, text[:200]))
        if rc == 0:
            rc, text = _run(["git", "commit", "-m", _commit_message(main_head, stamp)],
                            lib_dir, proxy, identity)
            steps.append(("git commit", rc, text[:200]))
        if rc != 0:
            result["rc"] = rc
            result["failed_step"] = f"commit: {text[:220]}"
            return result
    if tag:
        rc, listed = _git(lib_dir, "tag", "--list", tag, proxy=proxy)
        if not (listed or "").strip():
            steps.append(("tag", *_git(lib_dir, "tag", tag, proxy=proxy)))
    if str(state.get("ahead") or 0) != "0" or result["rc"] == 0:
        steps.append(("push-branch", *_git(lib_dir, "push", "origin",
                                           f"refs/heads/{branch}:refs/heads/{branch}", proxy=proxy)))
        if tag and any(name == "tag" for name, _, _ in steps):
            steps.append(("push-tag", *_git(lib_dir, "push", "origin",
                                            f"refs/tags/{tag}:refs/tags/{tag}", proxy=proxy)))
    for name, rc, text in steps:
        if rc != 0:
            result["rc"] = rc
            result["failed_step"] = f"{name}: {text[:220]}"
            break
    result["ran"] = [f"{name} rc={rc}" for name, rc, _ in steps]
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--check", action="store_true", help="只读核身（默认动作），有漂移 rc=1")
    ap.add_argument("--publish", action="store_true",
                    help="真正逐座 add/commit/tag/push（主人常令：每次 push 都要更新）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，零副作用")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--proxy", default="", help="可选：逐条注入 http.proxy（不写 git 配置）")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    libs_root = repo.parent / LIBS_DIRNAME
    payload: dict[str, object] = {
        "ruler": "sync_all_repositories",
        "repo": str(repo),
        "libs_root": str(libs_root),
        "libs_root_present": libs_root.is_dir(),
        "expected_owner": EXPECTED_OWNER,
        "mode": "publish" if args.publish else ("dry-run" if args.dry_run else "check"),
        "main": {}, "libs": [], "reds": [], "undecidable": [],
    }
    if not libs_root.is_dir():
        # 仓外库根不在场＝没有证据（HEAD 轴抽取副本/换机器检出），绝不产红也绝不产绿。
        payload["undecidable"].append(f"RULER_ABSENT:{libs_root}（仓外库根不在场）")
        payload["verdict"] = "UNDECIDABLE"
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if args.json
              else f"UNDECIDABLE 仓外库根不在场：{libs_root}")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    main_state = _state(repo, args.proxy or None)
    payload["main"] = main_state
    if not main_state.get("is_git"):
        payload["undecidable"].append("NO_GIT_AXIS_COPY:主仓读数取不到 .git（仓外副本按定义失明）")
        payload["verdict"] = "UNDECIDABLE"
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if args.json else "UNDECIDABLE 无 git 轴")
        return 2
    if main_state.get("origin_ok") is not True:
        payload["reds"].append(f"MAIN_ORIGIN_OWNER:主仓 origin 不是 {EXPECTED_OWNER}@{ALLOWED_HOSTS}"
                               f"（实为 {main_state.get('origin')}）")

    slugs = _manifest_slugs(libs_root)
    if not slugs:
        payload["reds"].append(f"ROSTER_EMPTY:{MANIFEST_NAME} 读不出任何 kebab slug＝名册投影没了")
    head_blobs = _head_blobs(repo)
    if head_blobs is None:
        payload["undecidable"].append("HEAD_AXIS_UNREADABLE:主仓 HEAD 树读不出＝实体新旧轴整体失明（不判红不判绿）")
    main_head = str(main_state.get("head") or "?")
    # 🔴 脏窗禁发布：工厂的取数口是**工作树字节**（`--caliber head` 只收窄成员宇宙，不改取字节的方式），
    # 所以主仓一 dirty，库副本里就烤着别席的半件；此时 `--publish`＝把未验证的在飞内容烙进她的私有库历史
    # （一次误提交要重写历史才摘得掉，与本件"残骸即拒发"同一口径）。读数照量，发布腿一律拒。
    main_dirty = int(main_state.get("dirty") or 0)
    dirty_window = main_dirty > 0
    payload["main_dirty"] = main_dirty
    if dirty_window and (args.publish or args.dry_run):
        payload["reds"].append(
            f"PUBLISH_REFUSED:MAIN_DIRTY_WINDOW（主仓工作树脏 {main_dirty} 枚＝库里副本含在飞内容，"
            "等安静窗再 --publish；本件绝不在脏窗里把别人半件烙进她的库）")
    for slug in slugs:
        lib_dir = libs_root / slug
        if not lib_dir.is_dir():
            payload["reds"].append(f"LIB_DIR_ABSENT:{slug}")
            continue
        state = _state(lib_dir, args.proxy or None)
        entry: dict[str, object] = {"slug": slug, **state}
        residue = _residue(lib_dir)
        if residue:
            entry["residue"] = residue
        if state.get("is_git") is not True:
            payload["reds"].append(f"LIB_NO_GIT:{slug}（一级功能库没有自己的 .git＝常令未成立）")
        elif state.get("origin_ok") is not True:
            payload["reds"].append(f"LIB_ORIGIN_OWNER:{slug}（origin={state.get('origin')}，"
                                   f"须为 {EXPECTED_OWNER} @ {ALLOWED_HOSTS[0]}）")
        if state.get("ahead"):
            payload["reds"].append(f"LIB_AHEAD:{slug}（本地领先远端 {state['ahead']} 枚＝"
                                   "\"每次 push 都要更新\"未成立）")
        # 库的内容是**派生物**：工作树脏＝工厂重生成后没提交，等于这座的远端还是上一版。
        # 主仓的脏另有语义（人在写），所以本件只对库判脏，绝不对主仓判脏、更不代提交。
        if state.get("dirty"):
            payload["reds"].append(f"LIB_DIRTY:{slug}（工作树脏 {state['dirty']} 枚＝实体已变而远端未更新；"
                                   "发布腿＝--publish，或她逐座 commit）")
        version = state.get("version")
        tag = f"{slug}/v{version}" if version else ""
        if tag and (state.get("tags") or 0) == 0:
            payload["reds"].append(f"LIB_UNTAGGED:{slug}（有 VERSION={version} 却一枚 tag 都没有）")
        entry["expected_tag"] = tag
        # 实体新旧轴（ahead/dirty 判不了这一条：库把自己的旧内容提交得干干净净、照样 ahead=0）
        drift = _content_drift(lib_dir, head_blobs)
        entry["content"] = drift
        if drift.get("blind"):
            payload["undecidable"].append(f"CONTENT_AXIS_BLIND:{slug}（主仓 HEAD 树读不出＝不判新旧）")
        elif drift["differing_count"] or drift["absent_count"]:
            head = (drift["differing"] + drift["absent_in_head"])[0]
            payload["reds"].append(
                f"LIB_STALE_CONTENT:{slug}（{drift['differing_count']} 枚与主仓 **HEAD** 不同"
                f"／{drift['absent_count']} 枚 HEAD 已无该文件；首枚 {head}）"
                "＝重跑库工厂再 --publish，本件不代生成")
        elif drift["mirrored"] == 0:
            entry["content_blind"] = "NO_MIRRORED_FILES（壳库零实体＝本面无证据也不判红）"
        payload["libs"].append(entry)
        if (args.publish or args.dry_run) and not dirty_window:
            if residue:
                # 🔴 有残骸就拒发：`git add -A` 在库里会把"根层未登记名"一起烙进她的私有仓历史，
                # 那正是本件要防的那一型（一次误提交＝要重写历史才能摘掉）。
                entry["publish"] = {"mode": "refused", "rc": 1,
                                    "why": f"残骸 {len(residue)} 枚未清（首枚：{residue[0]}）"}
                payload["reds"].append(f"PUBLISH_REFUSED:{slug}（先清残骸再谈发布）")
                continue
            outcome = _publish_lib(lib_dir, slug, state, main_head, stamp,
                                   args.proxy or None, do=args.publish)
            entry["publish"] = outcome
            if outcome["rc"] != 0:
                payload["reds"].append(f"PUBLISH_FAILED:{slug}（{outcome.get('failed_step', '')}）")

    if str(main_state.get("ahead") or 0) != "0":
        if args.publish:
            rc, text = _git(repo, "push", "origin",
                            f"refs/heads/{main_state.get('branch')}:refs/heads/{main_state.get('branch')}",
                            proxy=args.proxy or None)
            payload["main_publish"] = {"rc": rc, "text": text[:240]}
            if rc != 0:
                payload["reds"].append(f"MAIN_PUSH_FAILED:{text[:160]}")
        else:
            payload["reds"].append(f"MAIN_AHEAD:主仓本地领先远端 {main_state['ahead']} 枚（--publish 才推；"
                                   "本件从不对主仓 commit）")

    payload["counts"] = {
        "libs": len(slugs),
        "reds": len(payload["reds"]),
        "undecidable": len(payload["undecidable"]),
    }
    payload["verdict"] = "RED" if payload["reds"] else ("UNDECIDABLE" if payload["undecidable"] else "GREEN")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"分库远端同步：verdict={payload['verdict']} 库={len(slugs)} 红={len(payload['reds'])} "
              f"不可判={len(payload['undecidable'])} 模式={payload['mode']}")
        for line in payload["reds"]:
            print("  红：", line)
        for line in payload["undecidable"]:
            print("  不可判：", line)
    return 1 if payload["reds"] else (2 if payload["undecidable"] else 0)


if __name__ == "__main__":
    sys.exit(main())
