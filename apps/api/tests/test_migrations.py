from __future__ import annotations

import json
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


def test_revision_ids_fit_postgresql_alembic_version_column() -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    revisions = ScriptDirectory.from_config(config).walk_revisions()

    assert all(len(revision.revision) <= 32 for revision in revisions)


def test_channel_launch_at_column_removal_is_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'channel-launch-at.db'}"
    _alembic(database_url, "0053_pixel_runtime_config")
    engine = sa.create_engine(database_url)
    assert "launch_at" in {
        column["name"]
        for column in sa.inspect(engine).get_columns("promotion_channels")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    assert "launch_at" not in {
        column["name"]
        for column in sa.inspect(engine).get_columns("promotion_channels")
    }
    engine.dispose()

    _alembic_downgrade(database_url, "0053_pixel_runtime_config")
    engine = sa.create_engine(database_url)
    assert "launch_at" in {
        column["name"]
        for column in sa.inspect(engine).get_columns("promotion_channels")
    }
    engine.dispose()


def test_menu_management_removal_is_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'menu-management.db'}"
    _alembic(database_url, "0055_optional_totp_mfa")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT 1 FROM system_menus "
                "WHERE public_id = 'menu_system_menus'"
            )
        ).scalar_one() == 1
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT 1 FROM system_menus "
                "WHERE public_id = 'menu_system_menus'"
            )
        ).scalar_one_or_none() is None
        assert connection.execute(
            sa.text(
                "SELECT 1 FROM role_menu_permissions AS permission "
                "JOIN system_menus AS menu ON menu.id = permission.menu_id "
                "WHERE menu.public_id = 'menu_system_menus'"
            )
        ).scalar_one_or_none() is None
    engine.dispose()

    _alembic_downgrade(database_url, "0055_optional_totp_mfa")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        restored = connection.execute(
            sa.text(
                "SELECT route_path, permission_key, sort_order "
                "FROM system_menus WHERE public_id = 'menu_system_menus'"
            )
        ).one()
        assert restored == ("/system/menus", "system.menus.manage", 905)
        assigned_roles = connection.execute(
            sa.text(
                "SELECT role.system_key FROM role_menu_permissions AS permission "
                "JOIN user_groups AS role ON role.id = permission.role_id "
                "JOIN system_menus AS menu ON menu.id = permission.menu_id "
                "WHERE menu.public_id = 'menu_system_menus'"
            )
        ).scalars().all()
        assert assigned_roles == ["admin"]
    engine.dispose()

def test_promotion_monitoring_menu_migration_is_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'promotion-monitoring.db'}"
    _alembic(database_url, "0056_remove_menu_management")
    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        menu = connection.execute(
            sa.text(
                "SELECT name, route_path, permission_key, sort_order "
                "FROM system_menus "
                "WHERE public_id = 'menu_promotion_visit_monitoring'"
            )
        ).one()
        assert menu == (
            "访问监控",
            "/promotion/monitoring",
            "promotion.monitoring.read",
            121,
        )
        roles = connection.execute(
            sa.text(
                "SELECT role.system_key FROM role_menu_permissions AS permission "
                "JOIN user_groups AS role ON role.id = permission.role_id "
                "JOIN system_menus AS menu ON menu.id = permission.menu_id "
                "WHERE menu.public_id = 'menu_promotion_visit_monitoring' "
                "ORDER BY role.system_key"
            )
        ).scalars().all()
        # A fresh migration-only database has the built-in admin role; the
        # application bootstrap creates the optional operator role later.
        assert roles == ["admin"]
    engine.dispose()

    _alembic_downgrade(database_url, "0056_remove_menu_management")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT 1 FROM system_menus "
                "WHERE public_id = 'menu_promotion_visit_monitoring'"
            )
        ).scalar_one_or_none() is None
        sibling_orders = connection.execute(
            sa.text(
                "SELECT public_id, sort_order FROM system_menus "
                "WHERE public_id IN "
                "('menu_promotion_statistics', 'menu_promotion_trends') "
                "ORDER BY sort_order"
            )
        ).all()
        assert sibling_orders == [
            ("menu_promotion_statistics", 121),
            ("menu_promotion_trends", 122),
        ]
    engine.dispose()


def test_promotion_network_context_migration_is_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'promotion-network.db'}"
    _alembic(database_url, "0057_visit_monitoring")
    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    expected = {"source_ip", "visitor_country_code", "network_source"}
    for table in (
        "promotion_events",
        "promotion_integration_events",
        "account_pairing_attempts",
    ):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert expected <= columns
    engine.dispose()

    _alembic_downgrade(database_url, "0057_visit_monitoring")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    for table in (
        "promotion_events",
        "promotion_integration_events",
        "account_pairing_attempts",
    ):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert expected.isdisjoint(columns)
    engine.dispose()


def test_promotion_request_context_migration_is_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'promotion-request-context.db'}"
    _alembic(database_url, "0058_promotion_network_context")
    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    for table in (
        "promotion_events",
        "promotion_integration_events",
        "account_pairing_attempts",
    ):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "request_context_json" in columns
    engine.dispose()

    _alembic_downgrade(database_url, "0058_promotion_network_context")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    for table in (
        "promotion_events",
        "promotion_integration_events",
        "account_pairing_attempts",
    ):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "request_context_json" not in columns
    engine.dispose()


def test_promotion_visitor_migration_backfills_existing_fingerprints(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'promotion-visitors.db'}"
    _alembic(database_url, "0060_thumbmark_fingerprints")
    engine = sa.create_engine(database_url)
    fingerprint_hash = "a" * 64
    with engine.begin() as connection:
        tenant_id = connection.execute(
            sa.text("SELECT id FROM user_accounts ORDER BY id LIMIT 1")
        ).scalar_one()
        template_id = connection.execute(
            sa.text(
                """
                INSERT INTO promotion_templates
                    (public_id, name, manifest_json, index_html, created_by)
                VALUES
                    ('migration-template', 'migration template', '{}',
                     '<html></html>', :tenant_id)
                """
            ),
            {"tenant_id": tenant_id},
        ).lastrowid
        channel_id = connection.execute(
            sa.text(
                """
                INSERT INTO promotion_channels
                    (public_id, name, country_code, template_id, slug, created_by)
                VALUES
                    ('migration-channel', 'migration channel', 'US',
                     :template_id, 'migration-channel', :tenant_id)
                """
            ),
            {"template_id": template_id, "tenant_id": tenant_id},
        ).lastrowid
        connection.execute(
            sa.text(
                """
                INSERT INTO promotion_events
                    (public_id, channel_id, event_type, idempotency_key,
                     occurred_at, metadata_json, visitor_id,
                     visitor_fingerprint_hash, fingerprint_version,
                     fingerprint_quality)
                VALUES
                    ('migration-event', :channel_id, 'page_view',
                     'migration-event-key', :occurred_at, '{}',
                     'browser-visitor', :fingerprint_hash,
                     'thumbmarkjs/1.10.1', 'high')
                """
            ),
            {
                "channel_id": channel_id,
                "occurred_at": datetime(2026, 8, 24, tzinfo=UTC),
                "fingerprint_hash": fingerprint_hash,
            },
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    event_columns = {
        column["name"] for column in inspector.get_columns("promotion_events")
    }
    assert "promotion_visitor_id" in event_columns
    assert "visitor_id" not in event_columns
    assert "visitor_fingerprint_hash" not in event_columns
    with engine.connect() as connection:
        visitor = connection.execute(
            sa.text(
                """
                SELECT v.tenant_id, v.fingerprint_hash,
                       v.fingerprint_version, v.fingerprint_quality,
                       e.promotion_visitor_id
                FROM promotion_events e
                JOIN promotion_visitors v ON v.id = e.promotion_visitor_id
                WHERE e.public_id = 'migration-event'
                """
            )
        ).one()
    assert visitor.tenant_id == tenant_id
    assert visitor.fingerprint_hash == fingerprint_hash
    assert visitor.fingerprint_version == "thumbmarkjs/1.10.1"
    assert visitor.fingerprint_quality == "high"
    assert visitor.promotion_visitor_id is not None
    engine.dispose()


def test_phone_country_migration_repairs_all_number_country_tables(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phone-countries.db'}"
    _alembic(database_url, "0061_server_promotion_visitors")
    engine = sa.create_engine(database_url)
    now = datetime(2026, 8, 24, tzinfo=UTC)
    with engine.begin() as connection:
        tenant_id = connection.execute(
            sa.text("SELECT id FROM user_accounts ORDER BY id LIMIT 1")
        ).scalar_one()
        protocol_id = connection.execute(
            sa.text("SELECT id FROM protocol_nodes ORDER BY id LIMIT 1")
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO personal_accounts
                    (id, public_id, name, phone_e164, country_code,
                     created_by, protocol_id)
                VALUES
                    (9100000000000001, 'migration-cn-account', 'CN account',
                     '+8613187071551', 'US', :tenant_id, :protocol_id)
                """
            ),
            {"tenant_id": tenant_id, "protocol_id": protocol_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO promotion_templates
                    (id, public_id, name, manifest_json, index_html, created_by)
                VALUES
                    (9100000000000002, 'migration-country-template',
                     'country template', '{}', '<html></html>', :tenant_id)
                """
            ),
            {"tenant_id": tenant_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO promotion_channels
                    (id, public_id, name, country_code, template_id, slug,
                     created_by)
                VALUES
                    (9100000000000003, 'migration-country-channel',
                     'US target channel', 'US', 9100000000000002,
                     'migration-country-channel', :tenant_id)
                """
            ),
            {"tenant_id": tenant_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO promotion_leads
                    (id, public_id, channel_id, phone_e164, country_code,
                     first_seen_at, last_seen_at)
                VALUES
                    (9100000000000004, 'migration-cn-lead',
                     9100000000000003, '+8613800138000', 'US',
                     :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO data_packages
                    (id, public_id, name, created_by)
                VALUES
                    (9100000000000005, 'migration-country-package',
                     'country package', :tenant_id)
                """
            ),
            {"tenant_id": tenant_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO data_package_recipients
                    (id, public_id, data_package_id, phone_e164,
                     country_code, variables_json)
                VALUES
                    (9100000000000006, 'migration-de-recipient',
                     9100000000000005, '+4915123456789', 'US', '{}')
                """
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT country_code FROM personal_accounts "
                "WHERE id = 9100000000000001"
            )
        ).scalar_one() == "CN"
        assert connection.execute(
            sa.text(
                "SELECT country_code FROM promotion_leads "
                "WHERE id = 9100000000000004"
            )
        ).scalar_one() == "CN"
        assert connection.execute(
            sa.text(
                "SELECT country_code FROM data_package_recipients "
                "WHERE id = 9100000000000006"
            )
        ).scalar_one() == "DE"
    engine.dispose()


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
                SELECT g.id, g.name, g.description
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


def test_protocol_pairing_rate_limit_policy_migration_is_reversible(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'protocol-rate-limits.db'}"
    _alembic(database_url, "0034_account_admission_sync")
    engine = sa.create_engine(database_url)
    assert "rate_limit_policy_json" not in {
        column["name"]
        for column in sa.inspect(engine).get_columns("protocol_nodes")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    columns = {
        column["name"]: column
        for column in sa.inspect(engine).get_columns("protocol_nodes")
    }
    assert columns["rate_limit_policy_json"]["nullable"] is False
    engine.dispose()

    _alembic_downgrade(database_url, "0034_account_admission_sync")
    engine = sa.create_engine(database_url)
    assert "rate_limit_policy_json" not in {
        column["name"]
        for column in sa.inspect(engine).get_columns("protocol_nodes")
    }
    engine.dispose()


def test_unused_metadata_sync_policy_fields_are_pruned(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'sync-policy-pruning.db'}"
    _alembic(database_url, "0068_proxy_health_cooldown")
    engine = sa.create_engine(database_url)
    legacy_policy = {
        "avatar": True,
        "profileStatus": False,
        "businessProfile": True,
        "groupSummary": True,
        "groupDetails": False,
        "contacts": False,
        "chats": False,
        "messageHistory": False,
        "privacySettings": True,
        "blocklist": True,
    }
    with engine.begin() as connection:
        protocol_id = connection.execute(
            sa.text("SELECT id FROM protocol_nodes ORDER BY id LIMIT 1")
        ).scalar_one()
        connection.execute(
            sa.text(
                "UPDATE protocol_nodes SET sync_policy_json=:policy "
                "WHERE id=:protocol_id"
            ),
            {
                "policy": json.dumps(legacy_policy),
                "protocol_id": protocol_id,
            },
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        policy = connection.execute(
            sa.text(
                "SELECT sync_policy_json FROM protocol_nodes "
                "WHERE id=:protocol_id"
            ),
            {"protocol_id": protocol_id},
        ).scalar_one()
    engine.dispose()
    decoded = json.loads(policy) if isinstance(policy, str) else policy
    assert set(decoded).isdisjoint(
        {
            "profileStatus",
            "businessProfile",
            "privacySettings",
            "blocklist",
        }
    )


def test_account_resource_sync_migration_rewrites_policy_and_is_reversible(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'account-resource-sync.db'}"
    _alembic(database_url, "0074_marketing_navigation")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        protocol_id = connection.execute(
            sa.text("SELECT id FROM protocol_nodes ORDER BY id LIMIT 1")
        ).scalar_one()
        connection.execute(
            sa.text(
                "UPDATE protocol_nodes SET sync_policy_json=:policy "
                "WHERE id=:protocol_id"
            ),
            {
                "policy": json.dumps(
                    {
                        "closeOnline": False,
                        "avatar": True,
                        "groupSummary": True,
                        "groupDetails": False,
                        "contacts": False,
                        "chats": True,
                        "messageHistory": True,
                    }
                ),
                "protocol_id": protocol_id,
            },
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert {"account_contacts", "account_whatsapp_groups"}.issubset(
        set(inspector.get_table_names())
    )
    personal_columns = {
        column["name"] for column in inspector.get_columns("personal_accounts")
    }
    assert {
        "unique_group_member_count",
        "wa_platform_raw",
        "account_type",
        "device_os",
        "resource_sync_state_json",
    }.issubset(personal_columns)
    with engine.connect() as connection:
        stored = connection.execute(
            sa.text(
                "SELECT sync_policy_json FROM protocol_nodes "
                "WHERE id=:protocol_id"
            ),
            {"protocol_id": protocol_id},
        ).scalar_one()
    engine.dispose()
    decoded = json.loads(stored) if isinstance(stored, str) else stored
    assert decoded == {
        "closeOnline": False,
        "avatar": True,
        "groupDetails": True,
        "contacts": False,
    }

    _alembic_downgrade(database_url, "0074_marketing_navigation")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "account_contacts" not in inspector.get_table_names()
    assert "account_whatsapp_groups" not in inspector.get_table_names()
    assert "unique_group_member_count" not in {
        column["name"] for column in inspector.get_columns("personal_accounts")
    }
    engine.dispose()


def test_sticky_delivery_schema_repair_fills_columns_after_stamped_drift(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'sticky-delivery-repair.db'}"
    _alembic(database_url, "0035_developer_docs")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.text("DROP INDEX ix_personal_accounts_sending_cooldown_until")
        )
        connection.execute(
            sa.text("ALTER TABLE personal_accounts DROP COLUMN sending_cooldown_until")
        )
        connection.execute(
            sa.text("DROP INDEX ix_data_package_recipients_package_revision")
        )
        connection.execute(
            sa.text("DROP INDEX ix_data_package_recipients_removed_revision")
        )
        connection.execute(
            sa.text("ALTER TABLE data_package_recipients DROP COLUMN package_revision")
        )
        connection.execute(
            sa.text("ALTER TABLE data_package_recipients DROP COLUMN removed_revision")
        )
        connection.execute(
            sa.text("ALTER TABLE hyperlink_tasks DROP COLUMN skipped_count")
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "sending_cooldown_until" in {
        column["name"] for column in inspector.get_columns("personal_accounts")
    }
    assert {"package_revision", "removed_revision"} <= {
        column["name"]
        for column in inspector.get_columns("data_package_recipients")
    }
    assert "skipped_count" in {
        column["name"] for column in inspector.get_columns("hyperlink_tasks")
    }
    assert {
        "ix_data_package_recipients_package_revision",
        "ix_data_package_recipients_removed_revision",
    } <= {
        index["name"]
        for index in inspector.get_indexes("data_package_recipients")
    }
    assert "ix_personal_accounts_sending_cooldown_until" in {
        index["name"] for index in inspector.get_indexes("personal_accounts")
    }
    engine.dispose()


def test_pairing_rate_limit_default_migration_preserves_custom_rules(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pairing-rate-defaults.db'}"
    _alembic(database_url, "0036_sticky_delivery_repair")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    protocols = sa.Table("protocol_nodes", metadata, autoload_with=engine)
    old_policy = {
        "ipStart": {"maxRequests": 20, "windowSeconds": 600},
        "phoneAttempt": {"maxRequests": 3, "windowSeconds": 600},
        "channelAttempt": {"maxRequests": 100, "windowSeconds": 60},
        "cancel": {"maxRequests": 10, "windowSeconds": 60},
    }
    custom_policy = {
        **old_policy,
        "ipStart": {"maxRequests": 7, "windowSeconds": 700},
        "channelAttempt": {"maxRequests": 80, "windowSeconds": 120},
    }
    with engine.begin() as connection:
        original = connection.execute(sa.select(protocols).limit(1)).mappings().one()
        original_id = original["id"]
        connection.execute(
            protocols.update()
            .where(protocols.c.id == original_id)
            .values(rate_limit_policy_json=old_policy)
        )
        custom_id = connection.execute(sa.select(sa.func.max(protocols.c.id))).scalar_one() + 1
        custom_row = dict(original)
        custom_row.update(
            id=custom_id,
            public_id="proto_custom_pairing_defaults",
            name="Custom pairing defaults",
            rate_limit_policy_json=custom_policy,
        )
        connection.execute(protocols.insert().values(**custom_row))
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    protocols = sa.Table("protocol_nodes", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        migrated = connection.execute(
            sa.select(protocols.c.rate_limit_policy_json).where(
                protocols.c.id == original_id
            )
        ).scalar_one()
        customized = connection.execute(
            sa.select(protocols.c.rate_limit_policy_json).where(
                protocols.c.id == custom_id
            )
        ).scalar_one()
    engine.dispose()

    assert migrated["ipStart"] == {"maxRequests": 5, "windowSeconds": 600}
    assert migrated["phoneAttempt"] == {
        "maxRequests": 5,
        "windowSeconds": 600,
    }
    assert migrated["cancel"] == {"maxRequests": 5, "windowSeconds": 600}
    assert migrated["channelAttempt"] == {
        "maxRequests": None,
        "windowSeconds": 60,
    }
    assert customized["ipStart"] == {"maxRequests": 7, "windowSeconds": 700}
    assert customized["phoneAttempt"] == {
        "maxRequests": 5,
        "windowSeconds": 600,
    }
    assert customized["cancel"] == {
        "maxRequests": 5,
        "windowSeconds": 600,
    }
    assert customized["channelAttempt"] == {
        "maxRequests": 80,
        "windowSeconds": 120,
    }


def test_device_fingerprint_migration_adds_nullable_audit_fields_and_policy(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'device-fingerprints.db'}"
    _alembic(database_url, "0041_domain_order_status")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "visitor_fingerprint_hash" not in {
        column["name"] for column in inspector.get_columns("promotion_events")
    }
    policies = sa.Table(
        "promotion_template_policies", sa.MetaData(), autoload_with=engine
    )
    users = sa.Table("user_accounts", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        owner_id = connection.execute(sa.select(users.c.id).limit(1)).scalar_one()
        policy_id = 9_000_000_001
        connection.execute(
            policies.insert().values(
                id=policy_id,
                created_by=owner_id,
                device_signals="enhanced",
            )
        )
    engine.dispose()

    _alembic(database_url, "0042_device_fingerprints")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    for table in ("promotion_events", "account_pairing_attempts"):
        assert {
            "visitor_fingerprint_hash",
            "fingerprint_version",
            "fingerprint_quality",
        } <= {column["name"] for column in inspector.get_columns(table)}
    assert "ix_promotion_events_channel_fingerprint" in {
        index["name"] for index in inspector.get_indexes("promotion_events")
    }
    assert "ix_account_pairing_attempts_channel_fingerprint_created" in {
        index["name"]
        for index in inspector.get_indexes("account_pairing_attempts")
    }
    policies = sa.Table(
        "promotion_template_policies", sa.MetaData(), autoload_with=engine
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(policies.c.device_signals).where(
                    policies.c.id == policy_id
                )
            ).scalar_one()
            == "fingerprint"
        )
    engine.dispose()

    _alembic_downgrade(database_url, "0041_domain_order_status")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "visitor_fingerprint_hash" not in {
        column["name"] for column in inspector.get_columns("promotion_events")
    }
    policies = sa.Table(
        "promotion_template_policies", sa.MetaData(), autoload_with=engine
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(policies.c.device_signals).where(
                    policies.c.id == policy_id
                )
            ).scalar_one()
            == "enhanced"
        )
    engine.dispose()


def test_thumbmark_migration_removes_configurable_device_signals(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'thumbmark-fingerprints.db'}"
    _alembic(database_url, "0059_promotion_request_context")
    engine = sa.create_engine(database_url)
    assert "device_signals" in {
        column["name"]
        for column in sa.inspect(engine).get_columns("promotion_template_policies")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    assert "device_signals" not in {
        column["name"]
        for column in sa.inspect(engine).get_columns("promotion_template_policies")
    }
    engine.dispose()

    _alembic_downgrade(database_url, "0059_promotion_request_context")
    engine = sa.create_engine(database_url)
    policies = sa.Table(
        "promotion_template_policies", sa.MetaData(), autoload_with=engine
    )
    assert "device_signals" in policies.c
    with engine.connect() as connection:
        assert set(connection.execute(sa.select(policies.c.device_signals)).scalars()) <= {
            "fingerprint"
        }
    engine.dispose()


def test_promotion_event_rate_limit_policy_migration_is_reversible(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'event-rate-limits.db'}"
    _alembic(database_url, "0048_integration_feedback")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "event_rate_limit_policy_json" not in {
        column["name"]
        for column in inspector.get_columns("promotion_template_policies")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    policies = sa.Table(
        "promotion_template_policies", sa.MetaData(), autoload_with=engine
    )
    assert "event_rate_limit_policy_json" in policies.c
    with engine.connect() as connection:
        values = connection.execute(
            sa.select(policies.c.event_rate_limit_policy_json)
        ).scalars().all()
        assert all(value == {} for value in values)
    engine.dispose()

    _alembic_downgrade(database_url, "0048_integration_feedback")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "event_rate_limit_policy_json" not in {
        column["name"]
        for column in inspector.get_columns("promotion_template_policies")
    }
    engine.dispose()


def test_meta_domain_monitoring_migration_adds_reversible_channel_state(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'meta-domain-monitoring.db'}"
    _alembic(database_url, "0042_device_fingerprints")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "meta_domain_blocked" not in {
        column["name"] for column in inspector.get_columns("promotion_channels")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert {"meta_domain_blocked", "meta_domain_blocked_at"} <= {
        column["name"] for column in inspector.get_columns("promotion_channels")
    }
    engine.dispose()

    _alembic_downgrade(database_url, "0042_device_fingerprints")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "meta_domain_blocked" not in {
        column["name"] for column in inspector.get_columns("promotion_channels")
    }
    engine.dispose()


def test_pairing_observability_migration_repairs_missing_intake_menu(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pairing-observability.db'}"
    _alembic(database_url, "0043_meta_domain_monitoring")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        menu_id = connection.execute(
            sa.text(
                "SELECT id FROM system_menus "
                "WHERE public_id = 'menu_resources_account_intake'"
            )
        ).scalar_one()
        connection.execute(
            sa.text(
                "DELETE FROM role_menu_permissions WHERE menu_id = :menu_id"
            ),
            {"menu_id": menu_id},
        )
        connection.execute(
            sa.text("DELETE FROM system_menus WHERE id = :menu_id"),
            {"menu_id": menu_id},
        )
        connection.execute(
            sa.text(
                "UPDATE system_menus SET sort_order = 314 "
                "WHERE public_id = 'menu_resources_accounts_export'"
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        menu = connection.execute(
            sa.text(
                "SELECT id, route_path, permission_key, enabled, visible "
                "FROM system_menus "
                "WHERE public_id = 'menu_resources_account_intake'"
            )
        ).mappings().one()
        assert menu["route_path"] == "/resources/accounts/intake"
        assert menu["permission_key"] == "resources.account_intake.read"
        assert bool(menu["enabled"]) is True
        assert bool(menu["visible"]) is True
        granted_roles = set(
            connection.execute(
                sa.text(
                    "SELECT user_groups.system_key "
                    "FROM role_menu_permissions "
                    "JOIN user_groups "
                    "ON user_groups.id = role_menu_permissions.role_id "
                    "WHERE role_menu_permissions.menu_id = :menu_id"
                ),
                {"menu_id": menu["id"]},
            ).scalars()
        )
        expected_roles = set(
            connection.execute(
                sa.text(
                    "SELECT system_key FROM user_groups "
                    "WHERE system_key IN ('admin', 'operator')"
                )
            ).scalars()
        )
        assert expected_roles <= granted_roles
    engine.dispose()


def test_system_configuration_migration_adds_admin_only_menu_and_storage(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'system-configuration.db'}"
    _alembic(database_url, "0037_pairing_rate_defaults")
    engine = sa.create_engine(database_url)
    assert "system_credentials" not in sa.inspect(engine).get_table_names()
    # Production databases can retain this legacy sibling-order constraint.
    # Keep it in the migration fixture so reordering must be collision-safe.
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_system_menu_parent_order_test "
                "ON system_menus(parent_id, sort_order)"
            )
        )
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "system_credentials" in inspector.get_table_names()
    assert "system_platform_configurations" in inspector.get_table_names()
    assert {
        "id",
        "platform_key",
        "credential_key",
        "value_ciphertext",
        "value_fingerprint",
        "value_last4",
        "updated_by",
    } <= {
        column["name"] for column in inspector.get_columns("system_credentials")
    }
    assert {
        "id",
        "platform_key",
        "enabled",
        "settings_json",
        "last_test_status",
        "last_test_message",
        "last_test_at",
        "updated_by",
    } <= {
        column["name"]
        for column in inspector.get_columns("system_platform_configurations")
    }
    with engine.connect() as connection:
        menu_rows = connection.execute(
            sa.text(
                "SELECT public_id, sort_order FROM system_menus "
                "WHERE public_id IN "
                "('menu_system_developer_docs', 'menu_system_configuration', "
                "'menu_system_menus') ORDER BY sort_order"
            )
        ).all()
        assert menu_rows == [
            ("menu_system_developer_docs", 903),
            ("menu_system_configuration", 904),
        ]
        assigned_roles = connection.execute(
            sa.text(
                "SELECT g.system_key FROM role_menu_permissions AS permission "
                "JOIN user_groups AS g ON g.id = permission.role_id "
                "JOIN system_menus AS menu ON menu.id = permission.menu_id "
                "WHERE menu.public_id = 'menu_system_configuration'"
            )
        ).scalars().all()
        assert assigned_roles == ["admin"]
    engine.dispose()

    _alembic_downgrade(database_url, "0037_pairing_rate_defaults")
    engine = sa.create_engine(database_url)
    assert "system_credentials" not in sa.inspect(engine).get_table_names()
    assert "system_platform_configurations" not in sa.inspect(engine).get_table_names()
    with engine.connect() as connection:
        restored_menu_rows = connection.execute(
            sa.text(
                "SELECT public_id, sort_order FROM system_menus "
                "WHERE public_id IN "
                "('menu_system_developer_docs', 'menu_system_configuration', "
                "'menu_system_menus') ORDER BY sort_order"
            )
        ).all()
    engine.dispose()
    assert restored_menu_rows == [
        ("menu_system_menus", 903),
        ("menu_system_developer_docs", 904),
    ]


def test_bitly_pool_analytics_columns_are_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'bitly-pool-analytics.db'}"
    _alembic(database_url, "0051_repository_cache")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "last_error" not in {
        column["name"]
        for column in inspector.get_columns("bitly_provider_accounts")
    }
    assert "click_count" not in {
        column["name"] for column in inspector.get_columns("direct_short_links")
    }
    engine.dispose()

    _alembic(database_url, "0052_bitly_pool_analytics")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert {"last_error", "cooldown_until", "last_used_at"} <= {
        column["name"]
        for column in inspector.get_columns("bitly_provider_accounts")
    }
    assert {"click_count", "clicks_synced_at"} <= {
        column["name"] for column in inspector.get_columns("direct_short_links")
    }
    engine.dispose()

    _alembic_downgrade(database_url, "0051_repository_cache")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "last_error" not in {
        column["name"]
        for column in inspector.get_columns("bitly_provider_accounts")
    }
    assert "click_count" not in {
        column["name"] for column in inspector.get_columns("direct_short_links")
    }
    engine.dispose()


def test_account_avatar_cache_columns_are_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'account-avatar-cache.db'}"
    avatar_columns = {
        "avatar_source_url",
        "avatar_content_type",
        "avatar_size",
        "avatar_sha256",
        "avatar_content",
        "avatar_fetched_at",
    }
    _alembic(database_url, "0069_prune_sync_policy")
    engine = sa.create_engine(database_url)
    assert avatar_columns.isdisjoint(
        {column["name"] for column in sa.inspect(engine).get_columns("personal_accounts")}
    )
    engine.dispose()

    _alembic(database_url, "0070_account_avatar_cache")
    engine = sa.create_engine(database_url)
    assert avatar_columns <= {
        column["name"]
        for column in sa.inspect(engine).get_columns("personal_accounts")
    }
    engine.dispose()

    _alembic_downgrade(database_url, "0069_prune_sync_policy")
    engine = sa.create_engine(database_url)
    assert avatar_columns.isdisjoint(
        {column["name"] for column in sa.inspect(engine).get_columns("personal_accounts")}
    )
    engine.dispose()


def test_marketing_navigation_migration_is_reversible(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'marketing-navigation.db'}"
    _alembic(database_url, "0073_account_retirement")
    _alembic(database_url, "head")

    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        menu = connection.execute(
            sa.text(
                "SELECT child.name, child.route_path, child.permission_key, "
                "child.sort_order, parent.public_id AS parent_public_id "
                "FROM system_menus AS child "
                "JOIN system_menus AS parent ON parent.id = child.parent_id "
                "WHERE child.public_id = 'menu_marketing_contact'"
            )
        ).one()
        assert menu == (
            "好友营销",
            "/contact-marketing",
            "marketing.contact_marketing.read",
            240,
            "menu_marketing",
        )
        group_name = connection.execute(
            sa.text(
                "SELECT name FROM system_menus "
                "WHERE public_id = 'menu_marketing_group'"
            )
        ).scalar_one()
        assert group_name == "群组营销"
        assigned_roles = connection.execute(
            sa.text(
                "SELECT role.system_key "
                "FROM role_menu_permissions AS permission "
                "JOIN user_groups AS role ON role.id = permission.role_id "
                "JOIN system_menus AS menu ON menu.id = permission.menu_id "
                "WHERE menu.public_id = 'menu_marketing_contact' "
                "ORDER BY role.system_key"
            )
        ).scalars().all()
        assert assigned_roles == ["admin"]
    engine.dispose()

    _alembic_downgrade(database_url, "0073_account_retirement")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT 1 FROM system_menus "
                "WHERE public_id = 'menu_marketing_contact'"
            )
        ).scalar_one_or_none() is None
        assert connection.execute(
            sa.text(
                "SELECT name FROM system_menus "
                "WHERE public_id = 'menu_marketing_group'"
            )
        ).scalar_one() == "拉群营销"
    engine.dispose()


def test_protocol_pairing_code_migration_keeps_existing_nodes_unconfigured(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'protocol-pairing-code.db'}"
    _alembic(database_url, "0078_provider_domain_cache")
    engine = sa.create_engine(database_url)
    before_columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("protocol_nodes")
    }
    assert "pairing_code_mode" not in before_columns
    with engine.connect() as connection:
        protocol_id = connection.execute(
            sa.text("SELECT id FROM protocol_nodes ORDER BY id LIMIT 1")
        ).scalar_one()
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    columns = {
        column["name"]: column
        for column in sa.inspect(engine).get_columns("protocol_nodes")
    }
    assert columns["pairing_code_mode"]["nullable"] is True
    assert columns["fixed_pairing_code"]["nullable"] is True
    with engine.connect() as connection:
        configured = connection.execute(
            sa.text(
                "SELECT pairing_code_mode, fixed_pairing_code "
                "FROM protocol_nodes WHERE id = :protocol_id"
            ),
            {"protocol_id": protocol_id},
        ).one()
    assert configured == (None, None)
    engine.dispose()

    _alembic_downgrade(database_url, "0078_provider_domain_cache")
    engine = sa.create_engine(database_url)
    downgraded_columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("protocol_nodes")
    }
    assert "pairing_code_mode" not in downgraded_columns
    assert "fixed_pairing_code" not in downgraded_columns
    engine.dispose()


def test_metadata_sync_window_migration_updates_the_pending_queue_index(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'metadata-sync-window.db'}"
    _alembic(database_url, "0079_protocol_pairing_codes")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "available_at" not in {
        column["name"]
        for column in inspector.get_columns("account_metadata_sync_jobs")
    }
    engine.dispose()

    _alembic(database_url, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("account_metadata_sync_jobs")
    }
    assert columns["available_at"]["nullable"] is False
    pending_index = next(
        index
        for index in inspector.get_indexes("account_metadata_sync_jobs")
        if index["name"] == "ix_account_metadata_sync_jobs_pending"
    )
    assert pending_index["column_names"] == [
        "status",
        "available_at",
        "created_at",
    ]
    engine.dispose()

    _alembic_downgrade(database_url, "0079_protocol_pairing_codes")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "available_at" not in {
        column["name"]
        for column in inspector.get_columns("account_metadata_sync_jobs")
    }
    pending_index = next(
        index
        for index in inspector.get_indexes("account_metadata_sync_jobs")
        if index["name"] == "ix_account_metadata_sync_jobs_pending"
    )
    assert pending_index["column_names"] == ["status", "created_at"]
    engine.dispose()
