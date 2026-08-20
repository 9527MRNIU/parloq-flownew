from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("baota_api.py")
SPEC = importlib.util.spec_from_file_location("parloq_baota_api", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
BAOTA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BAOTA)


class BaoTaDeploymentTests(unittest.TestCase):
    def test_signature_matches_baota_contract(self) -> None:
        token_hash = hashlib.md5(b"secret").hexdigest()
        client = BAOTA.BaoTaClient("https://127.0.0.1:10049", token_hash)
        signed = client.signed({"path": "/tmp/example"})
        expected = hashlib.md5(
            (str(signed["request_time"]) + token_hash).encode()
        ).hexdigest()
        self.assertEqual(signed["request_token"], expected)
        self.assertEqual(signed["path"], "/tmp/example")

    def test_release_script_uses_profile_and_preserves_data(self) -> None:
        script = BAOTA.release_script(
            commit="a" * 40,
            short_sha="a" * 12,
            archive="/tmp/parloq.tar",
            checksum="b" * 64,
            api_image="parloq-api:a",
            web_image="parloq-web:a",
            gateway_image="parloq-gateway:a",
            status_file="/tmp/parloq-status.json",
            compose_content="services:\n  api:\n    image: parloq-api:a\n",
        )
        self.assertIn("--profile migration", script)
        self.assertIn("run --interactive=false -T --rm migrate", script)
        self.assertIn("wa-gateway api api-worker web", script)
        self.assertIn("write_status '{\"status\":\"success\"", script)
        self.assertNotIn('write_status "{\\"status\\"', script)
        self.assertNotIn(" down ", script)
        self.assertNotIn("down -v", script)
        self.assertNotIn("/data/waba", script)
        self.assertIn('compose_backup=', script)
        self.assertIn('base64 -d >"${compose_candidate}"', script)
        self.assertIn('cp -p "${compose_backup}" "${compose_file}"', script)

    def test_release_script_rejects_unsafe_image_reference(self) -> None:
        with self.assertRaises(BAOTA.BaoTaError):
            BAOTA.release_script(
                commit="a" * 40,
                short_sha="a" * 12,
                archive="/tmp/parloq.tar",
                checksum="b" * 64,
                api_image="parloq-api:a;touch /tmp/no",
                web_image="parloq-web:a",
                gateway_image="parloq-gateway:a",
                status_file="/tmp/parloq-status.json",
                compose_content="services:\n  api:\n    image: parloq-api:a\n",
            )

    def test_bitly_migration_is_a_read_only_waba_to_parloq_pipe(self) -> None:
        script = BAOTA.bitly_migration_script(
            status_file="/tmp/bitly-status.json",
            migration_id="1786900000",
        )
        self.assertIn("exec -T rocket-worker python -c", script)
        self.assertIn("python -m app.maintenance.import_waba_bitly", script)
        self.assertIn("/www/server/panel/data/compose/waba", script)
        self.assertIn("write_status '{\"status\":\"failed\"", script)
        self.assertNotIn("docker compose up", script)
        self.assertNotIn("docker compose down", script)
        self.assertNotIn("token_secret_payload =", script)
        compile(BAOTA.WABA_BITLY_EXPORTER_SOURCE, "<waba-bitly-exporter>", "exec")
        compile(BAOTA.BITLY_RESULT_WRITER_SOURCE, "<bitly-result-writer>", "exec")

    def test_security_configuration_script_updates_only_security_keys(self) -> None:
        script = BAOTA.security_configuration_script(
            security_file="/tmp/security.env",
            checksum="b" * 64,
            status_file="/tmp/security-status.json",
            configuration_id="1786900000",
        )
        for key in BAOTA.SECURITY_ENV_KEYS:
            self.assertIn(key, script)
        self.assertIn('cp -p "${env_file}" "${backup}"', script)
        self.assertIn('docker compose --env-file "${candidate}"', script)
        self.assertNotIn("PARLOQ_API_IMAGE", script)
        self.assertNotIn("docker compose up", script)
        self.assertNotIn("/data/waba", script)
        embedded_python = re.search(r"<<'PY'\n(.*?)\nPY\n", script, re.DOTALL)
        self.assertIsNotNone(embedded_python)
        compile(embedded_python.group(1), "<security-configuration>", "exec")

    def test_load_security_settings_accepts_valid_keyring(self) -> None:
        encoded_key = base64.urlsafe_b64encode(b"k" * 32).decode()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "security.env"
            path.write_text(
                "TURNSTILE_SITE_KEY=site-key-value\n"
                "TURNSTILE_SECRET_KEY=secret-key-value\n"
                "DATA_ENCRYPTION_ACTIVE_KEY_ID=primary-2026-08\n"
                f"DATA_ENCRYPTION_KEYS={json.dumps({'primary-2026-08': encoded_key})}\n",
                encoding="utf-8",
            )
            values = BAOTA.load_security_settings(path)
        self.assertEqual(values["DATA_ENCRYPTION_ACTIVE_KEY_ID"], "primary-2026-08")

    def test_load_security_settings_rejects_unexpected_keys(self) -> None:
        encoded_key = base64.urlsafe_b64encode(b"k" * 32).decode()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "security.env"
            path.write_text(
                "TURNSTILE_SITE_KEY=site-key-value\n"
                "TURNSTILE_SECRET_KEY=secret-key-value\n"
                "DATA_ENCRYPTION_ACTIVE_KEY_ID=primary\n"
                f"DATA_ENCRYPTION_KEYS={json.dumps({'primary': encoded_key})}\n"
                "POSTGRES_PASSWORD=must-not-be-accepted\n",
                encoding="utf-8",
            )
            with self.assertRaises(BAOTA.BaoTaError):
                BAOTA.load_security_settings(path)


if __name__ == "__main__":
    unittest.main()
