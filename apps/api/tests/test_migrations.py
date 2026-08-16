from __future__ import annotations

import os
from datetime import UTC, datetime
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


def _alembic_downgrade(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["APP_SECRET_KEY"] = "migration-test-only-secret"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "downgrade", revision],
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


def test_account_reference_ids_are_backfilled_and_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'account-reference-ids.db'}"
    _alembic(database_url, "0021_account_center_navigation")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    channel_id = 8_100_000_000_000_001
    account_id = 8_100_000_000_000_002
    template_id = 8_100_000_000_000_003
    hyperlink_template_id = 8_100_000_000_000_004
    strategy_id = 8_100_000_000_000_005
    package_id = 8_100_000_000_000_006
    task_id = 8_100_000_000_000_007
    with engine.begin() as connection:
        owner_id = connection.execute(
            sa.select(metadata.tables["user_accounts"].c.id).limit(1)
        ).scalar_one()
        protocol_id = connection.execute(
            sa.select(metadata.tables["protocol_nodes"].c.id).where(
                metadata.tables["protocol_nodes"].c.created_by == owner_id
            )
        ).scalar_one()
        connection.execute(
            metadata.tables["promotion_templates"].insert().values(
                id=template_id,
                public_id="ptpl_legacy_reference",
                name="migration template",
                manifest_json={},
                index_html="<html></html>",
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["promotion_channels"].insert().values(
                id=channel_id,
                public_id="pchn_legacy_reference",
                name="migration channel",
                country_code="US",
                template_id=template_id,
                slug="migration-reference-channel",
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["personal_accounts"].insert().values(
                id=account_id,
                public_id="wa_legacy_reference",
                name="migration account",
                source="landing_page",
                source_ref_type="promotion_channel",
                source_ref_id="pchn_legacy_reference",
                protocol_id=protocol_id,
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["hyperlink_templates"].insert().values(
                id=hyperlink_template_id,
                public_id="htpl_legacy_reference",
                name="migration hyperlink template",
                content_json={},
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["hyperlink_strategies"].insert().values(
                id=strategy_id,
                public_id="hstr_legacy_reference",
                name="migration strategy",
                rules_json={},
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["data_packages"].insert().values(
                id=package_id,
                public_id="hpkg_legacy_reference",
                name="migration package",
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["hyperlink_tasks"].insert().values(
                id=task_id,
                public_id="htsk_legacy_reference",
                name="migration task",
                template_id=hyperlink_template_id,
                strategy_id=strategy_id,
                data_package_id=package_id,
                account_public_ids=["wa_legacy_reference"],
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as connection:
        source_ref = connection.execute(
            sa.select(metadata.tables["personal_accounts"].c.source_ref_id).where(
                metadata.tables["personal_accounts"].c.id == account_id
            )
        ).scalar_one()
        account_refs = connection.execute(
            sa.select(metadata.tables["hyperlink_tasks"].c.account_public_ids).where(
                metadata.tables["hyperlink_tasks"].c.id == task_id
            )
        ).scalar_one()
    assert source_ref == str(channel_id)
    assert account_refs == [str(account_id)]
    engine.dispose()

    _alembic_downgrade(database_url, "0021_account_center_navigation")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as connection:
        source_ref = connection.execute(
            sa.select(metadata.tables["personal_accounts"].c.source_ref_id).where(
                metadata.tables["personal_accounts"].c.id == account_id
            )
        ).scalar_one()
        account_refs = connection.execute(
            sa.select(metadata.tables["hyperlink_tasks"].c.account_public_ids).where(
                metadata.tables["hyperlink_tasks"].c.id == task_id
            )
        ).scalar_one()
    engine.dispose()
    assert source_ref == "pchn_legacy_reference"
    assert account_refs == ["wa_legacy_reference"]


def test_dynamic_group_migration_preserves_legacy_fixed_tasks(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dynamic-group-tasks.db'}"
    _alembic(database_url, "0026_task_observability")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    task_id = 8_200_000_000_000_001
    template_id = 8_200_000_000_000_002
    strategy_id = 8_200_000_000_000_003
    package_id = 8_200_000_000_000_004
    now = datetime(2026, 8, 16, tzinfo=UTC)
    with engine.begin() as connection:
        owner_id = connection.execute(
            sa.select(metadata.tables["user_accounts"].c.id).limit(1)
        ).scalar_one()
        connection.execute(
            metadata.tables["hyperlink_templates"].insert().values(
                id=template_id,
                public_id="htpl_legacy_dynamic_migration",
                name="legacy migration template",
                content_json={},
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["hyperlink_strategies"].insert().values(
                id=strategy_id,
                public_id="hstr_legacy_dynamic_migration",
                name="legacy migration strategy",
                rules_json={},
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["data_packages"].insert().values(
                id=package_id,
                public_id="hpkg_legacy_dynamic_migration",
                name="legacy migration package",
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["hyperlink_tasks"].insert().values(
                id=task_id,
                public_id="htsk_legacy_dynamic_migration",
                name="legacy fixed sender task",
                template_id=template_id,
                strategy_id=strategy_id,
                data_package_id=package_id,
                account_public_ids=["8200000000000005"],
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(
                metadata.tables["hyperlink_tasks"].c.sender_mode,
                metadata.tables["hyperlink_tasks"].c.account_group_id,
                metadata.tables["hyperlink_tasks"].c.account_public_ids,
            ).where(metadata.tables["hyperlink_tasks"].c.id == task_id)
        ).one()
    engine.dispose()
    assert row.sender_mode == "legacy_fixed"
    assert row.account_group_id is None
    assert row.account_public_ids == ["8200000000000005"]


def test_global_material_library_migration_preserves_rows_and_permissions(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'global-materials.db'}"
    _alembic(database_url, "0022_account_reference_ids")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    old_materials = metadata.tables["hyperlink_materials"]
    users = metadata.tables["user_accounts"]
    material_id = 8_200_000_000_000_001
    now = datetime(2026, 8, 15, tzinfo=UTC)
    with engine.begin() as connection:
        owner_id = connection.execute(sa.select(users.c.id).limit(1)).scalar_one()
        connection.execute(
            old_materials.insert().values(
                id=material_id,
                public_id="hmat-global-migration",
                name="Preserved material",
                material_type="image",
                content_json={"url": "https://cdn.example.test/preserved.jpg"},
                enabled=True,
                archived_at=None,
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    with engine.connect() as connection:
        row = connection.execute(
            sa.text("SELECT id, name FROM materials WHERE id = :id"),
            {"id": material_id},
        ).one()
        menu = connection.execute(
            sa.text(
                """
                SELECT m.route_path, m.permission_key, p.public_id
                FROM system_menus AS m
                JOIN system_menus AS p ON p.id = m.parent_id
                WHERE m.public_id = 'menu_resources_materials'
                """
            )
        ).one()
        old_actions = connection.execute(
            sa.text(
                "SELECT count(*) FROM role_action_permissions "
                "WHERE permission_key = 'marketing.materials.manage'"
            )
        ).scalar_one()
        new_actions = connection.execute(
            sa.text(
                "SELECT count(*) FROM role_action_permissions "
                "WHERE permission_key = 'resources.materials.manage'"
            )
        ).scalar_one()
    assert "materials" in inspector.get_table_names()
    assert "hyperlink_materials" not in inspector.get_table_names()
    assert row == (material_id, "Preserved material")
    assert menu == (
        "/resources/materials",
        "resources.materials.read",
        "menu_resources",
    )
    assert old_actions == 0
    assert new_actions > 0
    engine.dispose()

    _alembic_downgrade(database_url, "0022_account_reference_ids")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    with engine.connect() as connection:
        restored = connection.execute(
            sa.text("SELECT id, name FROM hyperlink_materials WHERE id = :id"),
            {"id": material_id},
        ).one()
        menu = connection.execute(
            sa.text(
                """
                SELECT route_path, permission_key
                FROM system_menus
                WHERE public_id = 'menu_marketing_materials'
                """
            )
        ).one()
    assert "materials" not in inspector.get_table_names()
    assert "hyperlink_materials" in inspector.get_table_names()
    assert restored == (material_id, "Preserved material")
    assert menu == ("/hyperlink/materials", "marketing.materials.read")
    engine.dispose()


def test_managed_material_upload_columns_are_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'managed-materials.db'}"
    _alembic(database_url, "0023_global_material_library")
    engine = sa.create_engine(database_url)
    before = {column["name"] for column in sa.inspect(engine).get_columns("materials")}
    assert "content" not in before
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    after = {column["name"] for column in sa.inspect(engine).get_columns("materials")}
    assert {
        "file_name",
        "content_type",
        "file_size",
        "file_sha256",
        "content",
    }.issubset(after)
    assert "ix_materials_file_sha256" in {
        index["name"] for index in sa.inspect(engine).get_indexes("materials")
    }
    engine.dispose()

    _alembic_downgrade(database_url, "0023_global_material_library")
    engine = sa.create_engine(database_url)
    restored = {
        column["name"] for column in sa.inspect(engine).get_columns("materials")
    }
    engine.dispose()
    assert "content" not in restored


def test_text_material_roles_are_backfilled_and_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'text-material-roles.db'}"
    _alembic(database_url, "0024_managed_material_uploads")
    engine = sa.create_engine(database_url)
    material_id = 5218437194321920
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO materials (
                    id, public_id, name, material_type, content_json, enabled,
                    created_by, created_at, updated_at
                ) VALUES (
                    :id, :public_id, :name, 'text', :content_json, 1,
                    (SELECT id FROM user_accounts ORDER BY id LIMIT 1),
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "id": material_id,
                "public_id": "mat_text_role_history",
                "name": "Historical text",
                "content_json": '{"originalText":"Hello","translatedText":"你好"}',
            },
        )
    assert "text_role" not in {
        column["name"] for column in sa.inspect(engine).get_columns("materials")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "text_role" in {
        column["name"] for column in inspector.get_columns("materials")
    }
    assert "ix_materials_text_role" in {
        index["name"] for index in inspector.get_indexes("materials")
    }
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT text_role FROM materials WHERE id = :id"),
            {"id": material_id},
        ).scalar_one() == "body"
    engine.dispose()

    _alembic_downgrade(database_url, "0024_managed_material_uploads")
    engine = sa.create_engine(database_url)
    assert "text_role" not in {
        column["name"] for column in sa.inspect(engine).get_columns("materials")
    }
    engine.dispose()


def test_hyperlink_task_observability_columns_are_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'task-observability.db'}"
    _alembic(database_url, "0025_text_material_roles")
    engine = sa.create_engine(database_url)
    before_task = {
        column["name"]
        for column in sa.inspect(engine).get_columns("hyperlink_tasks")
    }
    before_delivery = {
        column["name"]
        for column in sa.inspect(engine).get_columns("hyperlink_task_deliveries")
    }
    assert "template_snapshot_json" not in before_task
    assert "submission_status" not in before_delivery
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    task_columns = {
        column["name"] for column in inspector.get_columns("hyperlink_tasks")
    }
    delivery_columns = {
        column["name"]
        for column in inspector.get_columns("hyperlink_task_deliveries")
    }
    assert {
        "template_name_snapshot",
        "template_snapshot_json",
        "submitting_count",
        "accepted_count",
        "submission_failed_count",
    }.issubset(task_columns)
    assert {
        "submission_status",
        "submitted_at",
        "submission_failed_at",
    }.issubset(delivery_columns)
    assert {
        "ix_hyperlink_task_deliveries_submission_status",
        "ix_hyperlink_task_deliveries_submitted_at",
    }.issubset(
        {index["name"] for index in inspector.get_indexes("hyperlink_task_deliveries")}
    )
    engine.dispose()

    _alembic_downgrade(database_url, "0025_text_material_roles")
    engine = sa.create_engine(database_url)
    restored_task = {
        column["name"]
        for column in sa.inspect(engine).get_columns("hyperlink_tasks")
    }
    restored_delivery = {
        column["name"]
        for column in sa.inspect(engine).get_columns("hyperlink_task_deliveries")
    }
    engine.dispose()
    assert "template_snapshot_json" not in restored_task
    assert "submission_status" not in restored_delivery


def test_legacy_promotion_channel_gets_a_default_account_group(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'channel-default-group.db'}"
    _alembic(database_url, "0028_channel_account_groups")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    now = datetime(2026, 8, 16, tzinfo=UTC)
    template_id = 8_300_000_000_000_001
    channel_id = 8_300_000_000_000_002
    with engine.begin() as connection:
        owner_id = connection.execute(
            sa.select(metadata.tables["user_accounts"].c.id).limit(1)
        ).scalar_one()
        connection.execute(
            metadata.tables["promotion_templates"].insert().values(
                id=template_id,
                public_id="ptpl_default_group_migration",
                name="default group migration template",
                version="1.0.0",
                status="available",
                manifest_json={},
                index_html="<html></html>",
                asset_count=0,
                total_size=0,
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            metadata.tables["promotion_channels"].insert().values(
                id=channel_id,
                public_id="pchn_default_group_migration",
                channel_type="facebook",
                name="legacy active channel",
                country_code="US",
                template_id=template_id,
                subdomain_prefix="",
                slug="legacy-default-group",
                locale_mode="auto",
                status="active",
                account_group_id=None,
                created_by=owner_id,
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        group = connection.execute(
            sa.text(
                """
                SELECT g.id, g.name, g.description, g.archived_at
                  FROM account_groups AS g
                  JOIN promotion_channels AS c ON c.account_group_id = g.id
                 WHERE c.id = :channel_id
                """
            ),
            {"channel_id": channel_id},
        ).one()
        group_count = connection.execute(
            sa.text(
                "SELECT count(*) FROM account_groups WHERE created_by = :owner_id"
            ),
            {"owner_id": owner_id},
        ).scalar_one()
        version = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    engine.dispose()

    assert group.name == "落地页账号"
    assert group.description == "推广渠道自动接入的账号分组"
    assert group.archived_at is None
    assert group_count == 1
    assert version == _head_revision()

    _alembic_downgrade(database_url, "0028_channel_account_groups")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT count(*) FROM account_groups WHERE id = :group_id"),
            {"group_id": group.id},
        ).scalar_one() == 1
    engine.dispose()
