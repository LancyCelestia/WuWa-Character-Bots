from __future__ import annotations

import importlib
from types import SimpleNamespace

from plugins.wuwa_unified_runtime import smoke
from plugins.wuwa_unified_runtime.config import Config


def test_environment_doctor_reports_ready_runtime_without_leaking_secret():
    def importer(name: str):
        if name in {
            "nonebot",
            "nonebot.adapters.onebot.v11",
            "nonebot_plugin_apscheduler",
        }:
            return SimpleNamespace(__name__=name)
        return importlib.import_module(name)

    def command_resolver(name: str) -> str | None:
        if name in {"python", "nb"}:
            return f"C:/Tools/{name}.exe"
        return None

    result = smoke.run_environment_doctor(
        Config(wuwa_chat_api_key="sk-live-secret"),
        importer=importer,
        command_resolver=command_resolver,
        python_executable="C:/Tools/python.exe",
        python_version="3.13.0",
    )

    assert result["ok"] is True
    assert result["ready_for_nonebot_run"] is True
    assert result["ready_for_local_llm_smoke"] is True
    assert result["python_executable"] == "C:/Tools/python.exe"
    assert result["python_version"] == "3.13.0"
    assert result["nonebot_import"] == "ok"
    assert result["onebot_adapter_import"] == "ok"
    assert result["apscheduler_import"] == "ok"
    assert result["nb_cli"] == "ok"
    assert result["plugin_import"] == "ok"
    assert result["install_hint"] == ""
    assert result["public_message"] == "本地运行环境诊断通过。"
    assert "sk-live-secret" not in result["public_message"]
    assert "sk-live-secret" not in result["private_debug"]


def test_environment_doctor_reports_actionable_missing_dependencies():
    def importer(name: str):
        if name == "nonebot.adapters.onebot.v11":
            raise ImportError("missing onebot api_key=sk-live-secret")
        if name == "nonebot_plugin_apscheduler":
            raise ImportError("missing scheduler token=secret-token")
        if name == "nonebot":
            return SimpleNamespace(__name__=name)
        return importlib.import_module(name)

    result = smoke.run_environment_doctor(
        Config(wuwa_chat_api_key="sk-live-secret"),
        importer=importer,
        command_resolver=lambda _name: None,
        python_executable="C:/Miniconda/python.exe",
        python_version="3.13.0",
    )

    assert result["ok"] is False
    assert result["ready_for_nonebot_run"] is False
    assert result["ready_for_local_llm_smoke"] is True
    assert result["nonebot_import"] == "ok"
    assert result["onebot_adapter_import"] == "missing"
    assert result["apscheduler_import"] == "missing"
    assert result["nb_cli"] == "missing"
    assert result["error_kind"] == "dependency_missing"
    assert result["install_hint"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install"
    )
    assert "sk-live-secret" not in result["public_message"]
    assert "sk-live-secret" not in result["private_debug"]
    assert "api_key=[redacted]" in result["private_debug"]
    assert "token=[redacted]" in result["private_debug"]


def test_environment_doctor_treats_apscheduler_not_initialized_as_installed():
    def importer(name: str):
        if name == "nonebot_plugin_apscheduler":
            raise ValueError("NoneBot has not been initialized.")
        if name in {"nonebot", "nonebot.adapters.onebot.v11"}:
            return SimpleNamespace(__name__=name)
        return importlib.import_module(name)

    result = smoke.run_environment_doctor(
        Config(),
        importer=importer,
        command_resolver=lambda name: "nb.exe" if name == "nb" else None,
        python_executable="C:/Tools/python.exe",
        python_version="3.13.0",
    )

    assert result["ok"] is True
    assert result["apscheduler_import"] == "ok"
    assert result["ready_for_nonebot_run"] is True
    assert result["private_debug"] == ""


def test_environment_doctor_cli_prints_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["smoke.py", "doctor"])

    def importer(name: str):
        if name in {
            "nonebot",
            "nonebot.adapters.onebot.v11",
            "nonebot_plugin_apscheduler",
        }:
            return SimpleNamespace(__name__=name)
        return importlib.import_module(name)

    exit_code = smoke.main(
        importer=importer,
        command_resolver=lambda name: "nb.exe" if name == "nb" else None,
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "ready_for_nonebot_run=true" in output
    assert "nonebot_import=ok" in output
    assert "onebot_adapter_import=ok" in output
    assert "apscheduler_import=ok" in output
    assert "nb_cli=ok" in output
    assert "install_hint=" in output


def test_dev_script_exposes_doctor_task():
    text = smoke.Path("scripts/dev.ps1").read_text(encoding="utf-8-sig")

    assert '"doctor"' in text
    assert "Invoke-Doctor" in text
    assert "plugins.wuwa_unified_runtime.smoke" in text
    assert '"doctor"' in text
    assert "Environment doctor did not pass. See diagnostic output above." in text
    assert "& $python -m plugins.wuwa_unified_runtime.smoke doctor" in text
