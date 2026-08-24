from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("release-production.sh")
COMPOSE = Path(__file__).with_name("docker-compose.production.yml")
WEB_DIR = Path(__file__).parents[1] / "apps" / "web"
NGINX_REFERENCE = Path(__file__).with_name("nginx.center.parloq.com.conf")
PUBLIC_DATA_SCRIPT = Path(__file__).with_name("public-data-access.sh")


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
        cls.nginx_reference = NGINX_REFERENCE.read_text(encoding="utf-8")
        cls.public_data_script = PUBLIC_DATA_SCRIPT.read_text(encoding="utf-8")

    def test_script_is_valid_bash(self) -> None:
        checked = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_release_cli_documents_branch_selection(self) -> None:
        checked = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("--branch <remote-branch>", checked.stdout)
        self.assertIn("uses main by default", checked.stdout)

    def test_release_cli_rejects_duplicate_branch_arguments(self) -> None:
        checked = subprocess.run(
            ["bash", str(SCRIPT), "--branch", "main", "--branch", "feature"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("--branch may only be provided once", checked.stderr)

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

    def test_first_run_prompts_and_persists_management_origin(self) -> None:
        self.assertIn("configure_management_origin", self.script)
        self.assertIn("MANAGEMENT_ORIGIN", self.script)
        self.assertIn("管理后台域名", self.script)
        self.assertIn('chmod 600 "${management_origin_candidate}"', self.script)
        self.assertIn('"${management_origin}/api/auth/security', self.script)
        self.assertIn("public management SPA did not load", self.script)

    def test_first_authenticated_redis_release_prompts_and_persists_password(self) -> None:
        self.assertIn("configure_redis_password", self.script)
        self.assertIn("REDIS_PASSWORD", self.script)
        self.assertIn("Redis 密码", self.script)
        self.assertIn('chmod 600 "${redis_password_candidate}"', self.script)
        self.assertIn("redis://:${REDIS_PASSWORD:?REDIS_PASSWORD is required}@redis:6379/0", self.compose)
        self.assertIn("--requirepass", self.compose)
        self.assertIn("REDISCLI_AUTH", self.compose)
        rollback_body = self.script.split("rollback() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("redis || true", rollback_body)

    def test_management_origin_is_runtime_configuration(self) -> None:
        self.assertIn("MANAGEMENT_ORIGIN", self.compose)
        self.assertIn("MANAGEMENT_ORIGIN", self.web_origin_entrypoint)
        self.assertIn("MANAGEMENT_HOST", self.web_origin_entrypoint)
        self.assertIn("/etc/nginx/templates/default.conf.template", self.web_dockerfile)
        self.assertIn("${MANAGEMENT_HOST}", self.web_nginx)
        self.assertNotIn("server_name center.parloq.com", self.web_nginx)
        self.assertIn("$http_x_forwarded_host", self.web_nginx)
        self.assertIn('"127.0.0.1" 1;', self.web_nginx)
        self.assertIn("BaoTa loopback Host mode", self.script)

    def test_template_video_upload_body_limit_reaches_both_proxies(self) -> None:
        self.assertEqual(self.web_nginx.count("client_max_body_size 64m;"), 2)
        self.assertIn("client_max_body_size 64m;", self.nginx_reference)
        self.assertNotIn("client_max_body_size 12m;", self.web_nginx)
        self.assertNotIn("client_max_body_size 12m;", self.nginx_reference)

    def test_cloudflare_network_headers_reach_the_api(self) -> None:
        forwarded_for_count = self.web_nginx.count(
            "proxy_set_header X-Forwarded-For"
        )
        self.assertEqual(
            self.web_nginx.count("proxy_set_header CF-Connecting-IP"),
            forwarded_for_count,
        )
        self.assertEqual(
            self.web_nginx.count("proxy_set_header CF-IPCountry"),
            forwarded_for_count,
        )
        self.assertIn(
            "proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;",
            self.nginx_reference,
        )
        self.assertIn(
            "proxy_set_header CF-IPCountry $http_cf_ipcountry;",
            self.nginx_reference,
        )

    def test_compose_builds_from_the_server_checkout(self) -> None:
        self.assertIn("PARLOQ_SOURCE_ROOT", self.compose)
        self.assertNotIn("https://github.com", self.compose)
        self.assertNotIn("GIT_AUTH_TOKEN", self.compose)
        self.assertIn("up -d --build --remove-orphans --wait", self.script)

    def test_release_selects_only_real_remote_branches(self) -> None:
        self.assertIn("git_with_auth ls-remote --heads origin", self.script)
        self.assertIn('REMOTE_BRANCHES=("main")', self.script)
        self.assertIn("可发布的远程分支", self.script)
        self.assertIn('release_branch="main"', self.script)
        self.assertIn("remote branch does not exist", self.script)
        self.assertIn('git check-ref-format --branch "${branch_name}"', self.script)
        self.assertIn('target_refspec="+refs/heads/${release_branch}:${target_ref}"', self.script)

    def test_release_keeps_main_as_controller_and_builds_from_a_worktree(self) -> None:
        self.assertIn('production updates must run from main', self.script)
        self.assertIn('git merge --ff-only origin/main', self.script)
        self.assertIn('git worktree add --detach "${RELEASE_SOURCE_DIR}"', self.script)
        self.assertIn('git -C "${RELEASE_SOURCE_DIR}" switch --detach', self.script)
        self.assertIn(
            'update_env PARLOQ_SOURCE_ROOT "${RELEASE_SOURCE_DIR}"', self.script
        )
        self.assertIn(
            'MANAGED_COMPOSE_FILE="${RELEASE_SOURCE_DIR}/deploy/docker-compose.production.yml"',
            self.script,
        )

    def test_release_records_selected_branch_and_immutable_commit(self) -> None:
        self.assertIn('update_env PARLOQ_GIT_BRANCH "${release_branch}"', self.script)
        self.assertIn('update_env PARLOQ_GIT_REF "${head_sha}"', self.script)
        self.assertIn('head_sha="${target_sha}"', self.script)
        self.assertIn('revision="$(docker inspect', self.script)

    def test_release_is_isolated_from_waba_and_preserves_data(self) -> None:
        self.assertNotIn("/data/waba", self.script)
        self.assertNotIn("/data/waba", self.compose)
        self.assertNotIn("down -v", self.script)
        self.assertNotIn("docker compose down", self.script)

    def test_public_data_access_is_isolated_and_does_not_restart_services(self) -> None:
        self.assertNotIn("/data/waba", self.public_data_script)
        self.assertNotIn("docker compose", self.public_data_script)
        self.assertNotIn("docker restart", self.public_data_script)
        self.assertNotIn("docker stop", self.public_data_script)
        self.assertIn('PROJECT_NAME="${PARLOQ_COMPOSE_PROJECT:-parloq-flow}"', self.public_data_script)

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
