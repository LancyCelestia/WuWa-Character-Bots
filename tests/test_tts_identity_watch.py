"""T60 · M-12 bot 侧音色守望回归：check_tts_voice_identity 五态判定矩阵.

全离线：tmp_path 造假引擎目录（GPT_SoVITS/configs/tts_infer.yaml + 假权重桩）
+ 造假项目根（.env + scripts/tts_voice_baseline.json），零真实引擎、零网络。

覆盖矩阵（任务书规定五态 + 边界补齐）：
  正常 → PASS；custom 换底模路径 → FAIL；权重文件不存在 → FAIL；
  yaml 哈希漂移但语义对 → FAIL（提示复核基线）；引擎目录缺 → SKIP；
  另补：TTS 未启用 SKIP / 基线册缺失 FAIL / yaml 丢失 FAIL / yaml 半截 FAIL /
  custom 段缺失 FAIL / run_all 第 10 项接线与 main exit 码传播。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import pre_restart_check as prc

PASS, SKIP, FAIL = prc.PASS, prc.SKIP, prc.FAIL

GPT_REL = "GPT_weights_v2ProPlus/shorekeeper_e15.ckpt"
SOVITS_REL = "SoVITS_weights_v2ProPlus/shorekeeper_e8_s1144.pth"
BOTTOM_T2S = "GPT_SoVITS/pretrained_models/s1v3.ckpt"  # 真 yaml v2ProPlus 段的底模路径

# 仿引擎真身形态：custom 段（生产在跑的权重）+ 一个非 custom 段（底模路径），
# 证明守望只读 custom、不被其余段带偏。
CANONICAL_YAML = f"""custom:
  bert_base_path: GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
  cnhuhbert_base_path: GPT_SoVITS/pretrained_models/chinese-hubert-base
  device: cuda
  is_half: true
  t2s_weights_path: {GPT_REL}
  version: v2ProPlus
  vits_weights_path: {SOVITS_REL}
v2ProPlus:
  bert_base_path: GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
  cnhuhbert_base_path: GPT_SoVITS/pretrained_models/chinese-hubert-base
  device: cpu
  is_half: false
  t2s_weights_path: {BOTTOM_T2S}
  version: v2ProPlus
  vits_weights_path: GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth
"""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_engine(
    tmp_path: Path,
    yaml_text: str = CANONICAL_YAML,
    *,
    with_weights: bool = True,
    with_yaml: bool = True,
) -> Path:
    """造假引擎目录：configs/tts_infer.yaml + 两权重桩（字节无关，只证实存）."""
    engine = tmp_path / "GPT-SoVITS-Engine"
    configs = engine / "GPT_SoVITS" / "configs"
    configs.mkdir(parents=True)
    if with_yaml:
        # write_bytes：钉 LF 字节落盘——write_text 在 Windows 会把 \n 翻译成 CRLF，
        # 与 sha256_text(文本) 错位，导致正常态误报哈希漂移
        (configs / "tts_infer.yaml").write_bytes(yaml_text.encode("utf-8"))
    if with_weights:
        (engine / GPT_REL).parent.mkdir(parents=True)
        (engine / GPT_REL).write_bytes(b"gpt-stub-bytes")
        (engine / SOVITS_REL).parent.mkdir(parents=True)
        (engine / SOVITS_REL).write_bytes(b"sovits-stub-bytes")
    return engine


def make_watch_project(
    tmp_path: Path,
    yaml_text: str = CANONICAL_YAML,
    *,
    enabled: str = "true",
    with_weights: bool = True,
    with_yaml: bool = True,
    with_baseline: bool = True,
    baseline_sha256: str | None = None,
) -> tuple[Path, Path]:
    """造假项目根（.env 指向假引擎）+ 基线册（默认按 yaml_text 现算哈希）.

    baseline_sha256：显式给基线锚（哈希漂移测试用它把基线钉在原版字节上，
    引擎侧 yaml_text 单独漂移——基线与引擎是两个独立事实源）.
    """
    engine = make_engine(
        tmp_path, yaml_text, with_weights=with_weights, with_yaml=with_yaml
    )
    root = tmp_path / "proj"
    root.mkdir()
    (root / "scripts").mkdir()
    if with_baseline:
        (root / "scripts" / "tts_voice_baseline.json").write_text(
            json.dumps(
                {
                    "yaml_relative_path": "GPT_SoVITS/configs/tts_infer.yaml",
                    "yaml_sha256": baseline_sha256 or sha256_text(yaml_text),
                    "gpt_weights_path": GPT_REL,
                    "sovits_weights_path": SOVITS_REL,
                }
            ),
            encoding="utf-8",
        )
    (root / ".env").write_text(
        f"BOT_TTS_ENABLED={enabled}\nBOT_TTS_GPTSOVITS_DIR={engine.as_posix()}\n",
        encoding="utf-8",
    )
    return root, engine


def run_check(root: Path) -> prc.CheckResult:
    return prc.check_tts_voice_identity(prc.load_env(root), root)


# ---------------------------------------------------------------------------
# 规定矩阵五态
# ---------------------------------------------------------------------------

def test_voice_identity_pass_normal(tmp_path: Path) -> None:
    root, _ = make_watch_project(tmp_path)
    result = run_check(root)
    assert result.status == PASS
    assert "音色正常" in result.message
    assert "shorekeeper" in result.message


def test_voice_identity_fail_swapped_to_base_model(tmp_path: Path) -> None:
    poisoned = CANONICAL_YAML.replace(f"t2s_weights_path: {GPT_REL}",
                                      f"t2s_weights_path: {BOTTOM_T2S}")
    root, _ = make_watch_project(tmp_path, poisoned)
    result = run_check(root)
    assert result.status == FAIL
    assert "疑似换底模" in result.message
    assert "shorekeeper" in result.message
    assert "save_configs" in result.fix_hint  # T53 写回面提示必须在场


def test_voice_identity_fail_weight_file_missing(tmp_path: Path) -> None:
    root, _ = make_watch_project(tmp_path, with_weights=False)
    result = run_check(root)
    assert result.status == FAIL
    assert "权重文件丢失" in result.message
    assert GPT_REL in result.message or SOVITS_REL in result.message


def test_voice_identity_fail_hash_drift_semantic_ok(tmp_path: Path) -> None:
    # device cuda→cpu：引擎合法回写也会造出的那种字节漂移，custom 语义不动；
    # 基线仍锚在原版字节（基线与引擎是两个独立事实源，漂移才可被对表抓出）
    drifted = CANONICAL_YAML.replace("device: cuda", "device: cpu")
    root, _ = make_watch_project(
        tmp_path, drifted, baseline_sha256=sha256_text(CANONICAL_YAML)
    )
    result = run_check(root)
    assert result.status == FAIL
    assert "yaml 被改" in result.message
    assert "语义仍是守岸人" in result.message
    assert "复核" in result.fix_hint and "重录基线" in result.fix_hint


def test_voice_identity_skip_engine_dir_missing(tmp_path: Path) -> None:
    root, engine = make_watch_project(tmp_path)
    import shutil

    shutil.rmtree(engine)
    result = run_check(root)
    assert result.status == SKIP
    assert "引擎目录不存在" in result.message


# ---------------------------------------------------------------------------
# 边界补齐
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enabled", ["false", ""])
def test_voice_identity_skip_tts_disabled(tmp_path: Path, enabled: str) -> None:
    root, _ = make_watch_project(tmp_path, enabled=enabled)
    result = run_check(root)
    assert result.status == SKIP
    assert "BOT_TTS_ENABLED" in result.message


def test_voice_identity_fail_baseline_missing(tmp_path: Path) -> None:
    root, _ = make_watch_project(tmp_path, with_baseline=False)
    result = run_check(root)
    assert result.status == FAIL
    assert "基线" in result.message
    assert "tts_voice_baseline.json" in result.message


def test_voice_identity_fail_yaml_missing(tmp_path: Path) -> None:
    root, _ = make_watch_project(tmp_path, with_yaml=False)
    result = run_check(root)
    assert result.status == FAIL
    assert "yaml 丢失" in result.message


def test_voice_identity_fail_yaml_half_written(tmp_path: Path) -> None:
    root, _ = make_watch_project(tmp_path, yaml_text="custom: [oops, 半截")
    result = run_check(root)
    assert result.status == FAIL
    assert "解析失败" in result.message


def test_voice_identity_fail_custom_section_missing(tmp_path: Path) -> None:
    root, _ = make_watch_project(
        tmp_path, yaml_text="v2ProPlus:\n  version: v2ProPlus\n"
    )
    result = run_check(root)
    assert result.status == FAIL
    assert "custom" in result.message


def test_voice_identity_fail_baseline_missing_field(tmp_path: Path) -> None:
    root, _ = make_watch_project(tmp_path)
    baseline = root / "scripts" / "tts_voice_baseline.json"
    data = json.loads(baseline.read_text(encoding="utf-8"))
    del data["yaml_sha256"]
    baseline.write_text(json.dumps(data), encoding="utf-8")
    result = run_check(root)
    assert result.status == FAIL
    assert "yaml_sha256" in result.message


# ---------------------------------------------------------------------------
# 接线：run_all 在册注册（派生式判据）+ main exit 码与 --json 沿既有门风格
# ---------------------------------------------------------------------------

def all_subproc_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (0, "[绿] OK", ""))


@pytest.fixture(autouse=True)
def _drop_ambient_runtime_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """假项目根只由 ``tmp_path`` 决定 ⇒ 宿主进程 env 的数据根必须摘掉（同 test_pre_restart_check.py）。

    ``prc.load_env``＝「os.environ 优先于文件」，而 conftest 的 L1 Runtime 根隔离装配
    （2026-09-30）会在进程 env 放一枚空隔离根，顶掉夹具 ``.env`` 里的
    ``BOT_RUNTIME_DATA_DIR`` ⇒ ``env_paths`` 那项由 PASS 飘 FAIL，
    ``test_main_exit_code_propagates_voice_fail`` 的「唯一 FAIL＝tts_voice」当场红。
    只读存在性检查，不开库、不碰生产根。
    """
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)


def _make_full_project(tmp_path: Path, yaml_text: str) -> tuple[Path, Path]:
    """在 watch 项目上补齐既有九项的最小通过面（env_paths 需要）."""
    root, engine = make_watch_project(tmp_path, yaml_text)
    data_root = tmp_path / "rt_data"
    data_root.mkdir()
    wiki = tmp_path / "crawl_wiki"
    wiki.mkdir()
    persona = data_root / "persona"
    persona.mkdir()
    persona_file = persona / "守岸人_核心人格.md"
    persona_file.write_text("人格正文", encoding="utf-8")
    qx_dir = root / "plugins" / "bot_unified_runtime" / "domains" / "weather" / "assets"
    qx_dir.mkdir(parents=True)
    (qx_dir / "qx.json").write_text("{}", encoding="utf-8")
    env_lines = (
        f"BOT_RUNTIME_DATA_DIR={data_root.as_posix()}\n"
        f"BOT_KB_WIKI_ROOT={wiki.as_posix()}\n"
        f'BOT_PERSONA_FILES=["{persona_file.as_posix()}"]\n'
        f"BOT_KNOWLEDGE_DB_PATH={(data_root / 'kb.sqlite3').as_posix()}\n"
    )
    env_path = root / ".env"
    env_path.write_text(env_path.read_text(encoding="utf-8") + env_lines, encoding="utf-8")
    return root, engine


def _assert_voice_wiring(mod: object, root: Path) -> None:
    """派生式判据（S146）：锁「tts_voice 已接进 run_all、在册次序可预期」，

    **不锁「总共恰好 N 项」**——N 是随体检项增长漂移的计数（历史 7→10→11→12→13，
    写死过一次就红过一次；本件旧判据 len(ids)==10 正是第 11/12 项那两席没做
    「处处跟随」留下的存量红）。项数与 id 序一律现算自被测真身的声明侧清单
    ``mod.declared_item_ids()``（= pre_restart_check docstring 编号节），
    与 AGENTS.md 铁律 10 / test_narrative_docs_defer_volatile_counts 同哲学。

    三条腿：
      (c) run_all 注册序 == 声明侧派生值（存在性+次序+项数一次性对账，非字面量）；
      (a) 目标项 tts_voice 在其中；
      (b) 相对次序符合既有约定：文档序里 tts_voice 紧跟前邻 control_plane。
    """
    results = mod.run_all(root)  # type: ignore[attr-defined]
    ids = [r.id for r in results]
    declared = mod.declared_item_ids()  # type: ignore[attr-defined]
    assert declared and len(declared) == len(set(declared)), f"声明侧清单可疑：{declared}"
    assert ids == declared, f"run_all 注册序与 docstring 在册清单漂移：{ids} != {declared}"
    assert "tts_voice" in ids, "tts_voice 没有接进 run_all（或 id 被改名）"
    assert ids.index("tts_voice") == ids.index("control_plane") + 1, (
        f"tts_voice 不再紧跟 control_plane（在册相邻约定被打破）：{ids}"
    )
    voice = next(r for r in results if r.id == "tts_voice")
    assert voice.status == PASS


def test_run_all_wires_tts_voice_as_tenth_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 函数名保留历史命名（"tenth" 是它入册时的序号；节点 id 被文档引用过，
    # 改名会漂测试坐标——同 tests/test_pre_restart_check.py:489 的先例口径）。
    root, _ = _make_full_project(tmp_path, CANONICAL_YAML)
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    _assert_voice_wiring(prc, root)


def test_main_exit_code_propagates_voice_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _make_full_project(
        tmp_path, CANONICAL_YAML.replace(f"vits_weights_path: {SOVITS_REL}",
                                         "vits_weights_path: GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth")
    )
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    assert prc.main(["--json", "--project-root", str(root)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 1
    failed = [r for r in payload["results"] if r["status"] == FAIL]
    assert [r["id"] for r in failed] == ["tts_voice"]
    assert failed[0]["fix_hint"]


# ---------------------------------------------------------------------------
# 注毒自证（S146）：证明上面的派生判据是活锁，不是「改完 10 换 13」的恒真空锁
# ---------------------------------------------------------------------------

def _load_poisoned_copy(tmp_path: Path, name: str, source: str) -> object:
    """把注毒后的 pre_restart_check 源码装成独立模块——只打副本，真身零接触.

    write_bytes 钉字节落盘（文本模式在 Windows 会翻行尾——本窗刚有人栽过）；
    模块名不带 scripts 前缀避免覆盖 sys.modules 里的真身，副本内部的
    `from scripts…` 绝对导入仍解析到仓库真件，桩环境行为一致。
    """
    import importlib.util

    copy_path = tmp_path / f"{name}.py"
    copy_path.write_bytes(source.encode("utf-8"))
    spec = importlib.util.spec_from_file_location(name, copy_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass 建类时按 __module__ 反查 sys.modules——不入册则 CheckResult/
    # RegistryView/AnnPairVerdict 三枚 frozen dataclass 当场炸（实跑撞过）；
    # exec 完即摘，不在 sys.modules 里给其他测试留幽灵模块。
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def test_voice_wiring_lock_is_live_not_vacuous(tmp_path: Path) -> None:
    """三发注毒（全在 tmp 副本上）：①摘掉 tts_voice 注册必红；②挪到队尾必红；
    ③文档清单与 run_all 同步长出第 14 项必绿（下一席正确加项不再踩雷——这正是
    把写死的 len==10 换成派生式要买到的东西）。真身文件全程只读，前后 sha256
    自证零接触。"""
    import hashlib

    real = PROJECT_ROOT / "scripts" / "pre_restart_check.py"
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    source = real.read_text(encoding="utf-8")

    voice_call = "        check_tts_voice_identity(env, project_root),\n"
    # 2026-10-03 施工席20：队尾锚原钉死 ann_pair 一行；在飞真身把 kb_domain_anchor
    # 注册在其后 ⇒ 队尾漂移。改**现算队尾**（取注册面最后一行 check_* 调用，规则 10
    # 同哲学），真身再长项本毒不再错位；count==1 自证留在下方循环里。
    tail_call = next(
        ln for ln in reversed(source.splitlines(keepends=True))
        if ln.startswith("        check_") and ln.endswith(",\n")
    )
    doc_anchor = "\n用法：\n"
    for label, needle in (("voice_call", voice_call), ("tail_call", tail_call), ("doc_anchor", doc_anchor)):
        assert source.count(needle) == 1, f"注毒锚点失配（{label}）：体检注册面已变形，请同步更新本锁"

    root, _ = _make_full_project(tmp_path, CANONICAL_YAML)

    def wired(module: object) -> object:
        module.run_cmd = lambda args, cwd, timeout=600: (0, "[绿] OK", "")  # type: ignore[attr-defined]
        module.probe_tcp = lambda host, port, timeout=2.0: True  # type: ignore[attr-defined]
        return module

    # ① 目标项被摘掉（注册面删一行，声明侧不动）→ 必须红
    removed = _load_poisoned_copy(tmp_path, "s146_poison_removed", source.replace(voice_call, ""))
    with pytest.raises(AssertionError):
        _assert_voice_wiring(wired(removed), root)

    # ② 次序被打乱（tts_voice 挪到队尾，声明侧不动）→ 必须红
    scrambled_src = source.replace(voice_call, "").replace(tail_call, tail_call + voice_call)
    scrambled = _load_poisoned_copy(tmp_path, "s146_poison_scrambled", scrambled_src)
    with pytest.raises(AssertionError):
        _assert_voice_wiring(wired(scrambled), root)

    # ③ 一致扩展（docstring 编号清单 + run_all 同步长出下一项）→ 必须绿
    # 2026-10-03 施工席20 归因：原毒硬编码「第 14 项」，与在飞落库的真第 14 项
    # （kb_domain_anchor）撞号 ⇒ 编号清单变 [1..14, 14] 而红。按本锁自身口径
    # （项数现算自声明侧，规则 10）改为**派生下一号**：真身再长项本毒不再撞号。
    next_num = len(prc.declared_item_ids()) + 1
    extended_src = (
        source.replace(doc_anchor, f"  {next_num}. dummy_probe  注毒用例附加项（S146 一致性扩展自证，非真检查）\n" + doc_anchor)
        .replace(tail_call, tail_call + "        check_dummy_probe(env, project_root),\n")
        .replace(
            "def run_all(",
            "def check_dummy_probe(env: dict[str, str], project_root: Path) -> CheckResult:\n"
            "    return CheckResult(\"dummy_probe\", \"注毒附加项\", PASS, \"x\")\n\n\n"
            "def run_all(",
        )
    )
    extended = _load_poisoned_copy(tmp_path, "s146_poison_extended", extended_src)
    _assert_voice_wiring(wired(extended), root)  # 不抛=绿；抛了说明雷只是换了个埋法

    after = hashlib.sha256(real.read_bytes()).hexdigest()
    assert after == before, "真身在注毒过程中被改动——立即停手排查"
