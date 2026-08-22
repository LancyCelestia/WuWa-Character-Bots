"""Project configuration contract tests for the SQLite ORM base and startup docs."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_postgresql_orm_extra():
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "nonebot-plugin-orm[postgresql]>=0.8.3" in text


def test_env_example_declares_postgresql_database_url():
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SQLALCHEMY_DATABASE_URL=postgresql+asyncpg://" in text


def test_startup_docs_use_current_nb_commands():
    for name in ("docs/napcat-setup.md", "docs/acceptance-manual.md"):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "nb run --env-file" not in text, name
        assert "nb orm upgrade" in text, name
        assert "nb orm check" in text, name


def test_napcat_docs_use_websocket_client_driver():
    for name in ("docs/napcat-setup.md", "docs/acceptance-manual.md"):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "~fastapi+~httpx+~websockets" in text, name
