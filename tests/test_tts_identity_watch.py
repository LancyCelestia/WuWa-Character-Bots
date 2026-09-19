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
# 接线：run_all 第 10 项 + main exit 码与 --json 沿既有门风格
# ---------------------------------------------------------------------------

def all_subproc_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (0, "[绿] OK", ""))


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


def test_run_all_wires_tts_voice_as_tenth_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = _make_full_project(tmp_path, CANONICAL_YAML)
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    results = prc.run_all(root)
    ids = [r.id for r in results]
    assert len(ids) == 10
    assert ids[-1] == "tts_voice"
    assert next(r for r in results if r.id == "tts_voice").status == PASS


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
