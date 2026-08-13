from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory


def _alembic(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["APP_SECRET_KEY"] = "migration-test-only-secret"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _head_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def test_custom_role_is_not_expanded_by_forward_repairs(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'custom-role-upgrade.db'}"
    _alembic(database_url, "0005_system_promotion_domains")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        role_id = connection.execute(
            sa.text(
                """
                INSERT INTO user_groups
                    (name, system_key, description, is_builtin, enabled, created_at, updated_at)
                VALUES
                    ('migration custom role', NULL, NULL, 0, 1,
                     '2020-01-01 00:00:00', '2020-01-01 00:00:00')
                """
            )
        ).lastrowid
        leaf_id = connection.execute(
            sa.text(
                "SELECT id FROM system_menus WHERE public_id = 'menu_promotion_templates'"
            )
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO role_menu_permissions
                    (role_id, menu_id, created_at, updated_at)
                VALUES
                    (:role_id, :menu_id, '2020-01-01 00:00:00', '2020-01-01 00:00:00')
                """
            ),
            {"role_id": role_id, "menu_id": leaf_id},
        )
        configured_role_id = connection.execute(
            sa.text(
                """
                INSERT INTO user_groups
                    (name, system_key, description, is_builtin, enabled, created_at, updated_at)
                VALUES
                    ('configured custom role', NULL, NULL, 0, 1,
                     '2020-01-02 00:00:00', '2020-01-02 00:00:00')
                """
            )
        ).lastrowid
        connection.execute(
            sa.text(
                """
                INSERT INTO role_menu_permissions
                    (role_id, menu_id, created_at, updated_at)
                VALUES
                    (:role_id, :menu_id, '2020-01-02 00:00:00', '2020-01-02 00:00:00')
                """
            ),
            {"role_id": configured_role_id, "menu_id": leaf_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO role_action_permissions
                    (role_id, permission_key, created_at, updated_at)
                VALUES
                    (:role_id, 'promotion.templates.manage',
                     '2020-01-02 00:00:00', '2020-01-02 00:00:00')
                """
            ),
            {"role_id": configured_role_id},
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        menu_ids = set(
            connection.execute(
                sa.text(
                    """
                    SELECT m.public_id
                    FROM role_menu_permissions AS rp
                    JOIN system_menus AS m ON m.id = rp.menu_id
                    WHERE rp.role_id = :role_id
                    """
                ),
                {"role_id": role_id},
            ).scalars()
        )
        actions = list(
            connection.execute(
                sa.text(
                    "SELECT permission_key FROM role_action_permissions WHERE role_id = :role_id"
                ),
                {"role_id": role_id},
            ).scalars()
        )
        version = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        configured_actions = list(
            connection.execute(
                sa.text(
                    "SELECT permission_key FROM role_action_permissions WHERE role_id = :role_id"
                ),
                {"role_id": configured_role_id},
            ).scalars()
        )
    engine.dispose()

    assert menu_ids == {
        "menu_promotion",
        "menu_promotion_management",
        "menu_promotion_templates",
    }
    assert actions == []
    assert configured_actions == ["promotion.templates.manage"]
    assert version == _head_revision()
