from __future__ import annotations

from types import SimpleNamespace

from app import database


class _SessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


class _AlembicConfig:
    def __init__(self, path: str) -> None:
        self.path = path
        self.options: dict[str, str] = {}

    def set_main_option(self, key: str, value: str) -> None:
        self.options[key] = value


def test_auto_migrate_runs_before_initial_data_seed(monkeypatch) -> None:
    events: list[str] = []
    config_holder: list[_AlembicConfig] = []

    def make_config(path: str) -> _AlembicConfig:
        config = _AlembicConfig(path)
        config_holder.append(config)
        return config

    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(
            auto_create_tables=False,
            auto_migrate=True,
            database_url="postgresql+psycopg://example",
        ),
    )
    monkeypatch.setattr(database, "Config", make_config)
    monkeypatch.setattr(
        database,
        "inspect",
        lambda _engine: SimpleNamespace(get_table_names=lambda: ["alembic_version"]),
    )
    monkeypatch.setattr(
        database.command,
        "upgrade",
        lambda _config, target: events.append(f"migrate:{target}"),
    )
    monkeypatch.setattr(database, "SessionLocal", _SessionContext)
    monkeypatch.setattr(
        database,
        "seed_initial_data",
        lambda _session: events.append("seed"),
    )

    database.init_database()

    assert events == ["migrate:head", "seed"]
    assert config_holder[0].options["sqlalchemy.url"] == (
        "postgresql+psycopg://example"
    )
