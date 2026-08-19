from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("release-production.sh")
COMPOSE = Path(__file__).with_name("docker-compose.production.yml")


class ProductionReleaseScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.compose = COMPOSE.read_text(encoding="utf-8")

    def test_script_is_valid_bash(self) -> None:
        checked = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_release_has_no_baota_api_or_ssh_dependency(self) -> None:
        self.assertNotIn("baota_api.py", self.script)
        self.assertNotIn("BAOTA_", self.script)
        self.assertNotIn("ssh ", self.script)
        self.assertNotIn("scp ", self.script)

    def test_first_run_prompts_and_saves_token_with_restricted_mode(self) -> None:
        self.assertIn("read -r -s", self.script)
        self.assertIn("github-token", self.script)
        self.assertIn('chmod 600 "${GITHUB_TOKEN_FILE}"', self.script)
        self.assertIn("GIT_ASKPASS", self.script)

    def test_compose_builds_from_the_server_checkout(self) -> None:
        self.assertIn("PARLOQ_SOURCE_ROOT", self.compose)
        self.assertNotIn("https://github.com", self.compose)
        self.assertNotIn("GIT_AUTH_TOKEN", self.compose)
        self.assertIn("up -d --build --remove-orphans --wait", self.script)

    def test_release_is_isolated_from_waba_and_preserves_data(self) -> None:
        self.assertNotIn("/data/waba", self.script)
        self.assertNotIn("/data/waba", self.compose)
        self.assertNotIn("down -v", self.script)
        self.assertNotIn("docker compose down", self.script)

    def test_cleanup_keeps_recent_and_running_parloq_images_only(self) -> None:
        self.assertIn('PARLOQ_IMAGE_RETENTION:-3', self.script)
        self.assertIn('docker ps -q --filter "ancestor=${image_id}"', self.script)
        self.assertIn('"parloq-flow-${component}-server"', self.script)
        self.assertIn('"parloq-flow-${component}-local"', self.script)
        self.assertNotIn("docker image prune", self.script)
        self.assertNotIn("docker system prune", self.script)
        self.assertNotIn("docker image rm --force", self.script)

    def test_cleanup_removes_only_expired_build_cache(self) -> None:
        self.assertIn('PARLOQ_BUILD_CACHE_MAX_AGE:-168h', self.script)
        self.assertIn(
            'docker builder prune --force --filter "until=${BUILD_CACHE_MAX_AGE}"',
            self.script,
        )


if __name__ == "__main__":
    unittest.main()
