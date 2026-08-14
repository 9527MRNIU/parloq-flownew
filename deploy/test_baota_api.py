from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
