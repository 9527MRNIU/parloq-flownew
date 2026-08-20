from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("release-production.sh")
COMPOSE = Path(__file__).with_name("docker-compose.production.yml")
WEB_DIR = Path(__file__).parents[1] / "apps" / "web"


class ProductionReleaseScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.web_dockerfile = (WEB_DIR / "Dockerfile").read_text(encoding="utf-8")
        cls.web_nginx = (WEB_DIR / "nginx.production.conf").read_text(
            encoding="utf-8"
        )
        cls.web_origin_entrypoint = (WEB_DIR / "management-origin.envsh").read_text(
            encoding="utf-8"
        )

    def test_script_is_valid_bash(self) -> None:
        checked = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_release_builds_locally_and_writes_only_through_baota(self) -> None:
        self.assertIn('PARLOQ_BUILD_PLATFORM="linux/amd64"', self.script)
        self.assertIn('build-production-images.sh"', self.script)
        self.assertIn('docker image save --output "${archive}"', self.script)
        self.assertIn('shasum -a 256 "${archive}"', self.script)
        self.assertIn('baota_api.py"', self.script)
        self.assertIn('--env-file "${BAOTA_ENV_FILE}" status', self.script)
        self.assertIn('--env-file "${BAOTA_ENV_FILE}" release', self.script)
        self.assertNotIn("ssh ", self.script)
        self.assertNotIn("scp ", self.script)
        self.assertNotIn("flock", self.script)
        self.assertNotIn("/www/server", self.script)

    def test_release_requires_clean_synced_main(self) -> None:
        self.assertIn('git branch --show-current)" = "main"', self.script)
        self.assertIn("git diff --quiet", self.script)
        self.assertIn("git ls-files --others --exclude-standard", self.script)
        self.assertIn("git fetch origin main", self.script)
        self.assertIn("git rev-parse origin/main", self.script)

    def test_release_uses_immutable_server_image_tags_and_cleans_archive(self) -> None:
        self.assertIn('api_image="parloq-flow-api-server:${short_sha}"', self.script)
        self.assertIn('web_image="parloq-flow-web-server:${short_sha}"', self.script)
        self.assertIn(
            'gateway_image="parloq-flow-wa-gateway-server:${short_sha}"',
            self.script,
        )
        self.assertIn('docker image tag "${built_api_image}" "${api_image}"', self.script)
        self.assertIn('rm -f -- "${archive}"', self.script)

    def test_compose_uses_preloaded_images_without_server_builds(self) -> None:
        self.assertNotIn("build:", self.compose)
        self.assertGreaterEqual(self.compose.count("pull_policy: never"), 5)
        self.assertIn("PARLOQ_API_IMAGE", self.compose)
        self.assertIn("PARLOQ_WEB_IMAGE", self.compose)
        self.assertIn("PARLOQ_WA_GATEWAY_IMAGE", self.compose)

    def test_release_is_isolated_from_waba_and_preserves_data(self) -> None:
        self.assertNotIn("/data/waba", self.script)
        self.assertNotIn("/data/waba", self.compose)
        self.assertNotIn("down -v", self.script)
        self.assertNotIn("docker compose down", self.script)
        self.assertNotIn("/data/parloq-flow", self.script)

    def test_management_origin_is_runtime_configuration(self) -> None:
        self.assertIn("MANAGEMENT_ORIGIN", self.compose)
        self.assertIn("MANAGEMENT_ORIGIN", self.web_origin_entrypoint)
        self.assertIn("MANAGEMENT_HOST", self.web_origin_entrypoint)
        self.assertIn("/etc/nginx/templates/default.conf.template", self.web_dockerfile)
        self.assertIn("${MANAGEMENT_HOST}", self.web_nginx)
        self.assertNotIn("server_name center.parloq.com", self.web_nginx)
        self.assertIn("$http_x_forwarded_host", self.web_nginx)
        self.assertIn('"127.0.0.1" 1;', self.web_nginx)


if __name__ == "__main__":
    unittest.main()
