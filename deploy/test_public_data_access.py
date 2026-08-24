from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


SCRIPT = Path(__file__).with_name("public-data-access.sh")


class PublicDataAccessScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT.read_text(encoding="utf-8")

    def test_script_is_valid_bash(self) -> None:
        checked = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_menu_contains_exactly_the_three_requested_operations(self) -> None:
        menu = self._run_sourced("show_menu")
        self.assertEqual(menu.returncode, 0, menu.stderr)
        operation_lines = [
            line for line in menu.stdout.splitlines() if line[:2] in {"1)", "2)", "3)"}
        ]
        self.assertEqual(operation_lines, ["1) 状态", "2) 打开", "3) 关闭"])
        self.assertNotIn("来源 IP", menu.stdout)

    def test_opening_uses_random_ports_and_baota_security_rules(self) -> None:
        self.assertIn('PORT_MIN="${PARLOQ_PUBLIC_PORT_MIN:-20000}"', self.script)
        self.assertIn('PORT_MAX="${PARLOQ_PUBLIC_PORT_MAX:-29999}"', self.script)
        self.assertIn("choose_random_port", self.script)
        self.assertIn("/usr/bin/btpython", self.script)
        self.assertIn("AddAcceptPort", self.script)
        self.assertIn("DelAcceptPort", self.script)
        self.assertIn("BaoTa Security rule", self.script)
        self.assertNotIn("iptables", self.script)
        self.assertNotIn("ufw", self.script.lower())

    def test_random_port_selection_stays_in_range_and_avoids_duplicate(self) -> None:
        selected = self._run_sourced(
            textwrap.dedent(
                """\
                port_available() { return 0; }
                baota_firewall() { return 0; }
                first="$(choose_random_port)"
                second="$(choose_random_port "${first}")"
                printf '%s %s' "${first}" "${second}"
                """
            ),
            {
                "PARLOQ_PUBLIC_PORT_MIN": "24100",
                "PARLOQ_PUBLIC_PORT_MAX": "24110",
            },
        )
        self.assertEqual(selected.returncode, 0, selected.stderr)
        first, second = map(int, selected.stdout.split())
        self.assertIn(first, range(24100, 24111))
        self.assertIn(second, range(24100, 24111))
        self.assertNotEqual(first, second)

    def test_connection_output_never_prints_production_passwords(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            postgres_password = "postgres-secret-that-must-not-be-printed"
            redis_password = "redis-secret-that-must-not-be-printed"
            env_file.write_text(
                textwrap.dedent(
                    f"""\
                    POSTGRES_DB=parloq_flow
                    POSTGRES_USER=parloq_flow
                    POSTGRES_PASSWORD={postgres_password}
                    REDIS_PASSWORD={redis_password}
                    """
                ),
                encoding="utf-8",
            )
            shown = self._run_sourced(
                "show_connection_info 24123 28765",
                {
                    "PARLOQ_ENV_FILE": str(env_file),
                    "PARLOQ_PUBLIC_HOST": "216.106.185.81",
                },
            )

        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn(postgres_password, shown.stdout)
        self.assertNotIn(redis_password, shown.stdout)
        self.assertIn("postgresql://parloq_flow:<POSTGRES_PASSWORD>@", shown.stdout)
        self.assertIn("redis://:<REDIS_PASSWORD>@", shown.stdout)
        self.assertIn("216.106.185.81:24123", shown.stdout)
        self.assertIn("216.106.185.81:28765", shown.stdout)
        self.assertIn("0.0.0.0/0", shown.stdout)

    def test_connection_host_is_detected_per_server(self) -> None:
        self.assertIn('PUBLIC_HOST="${PARLOQ_PUBLIC_HOST:-}"', self.script)
        self.assertIn("ip -4 route get 1.1.1.1", self.script)
        self.assertNotIn('PARLOQ_PUBLIC_HOST:-216.106.185.81', self.script)
        detected = self._run_sourced(
            "ip() { printf '1.1.1.1 via 203.0.113.1 dev eth0 src 203.0.113.25 uid 0\\n'; }; "
            "PUBLIC_HOST=''; resolve_public_host"
        )
        self.assertEqual(detected.returncode, 0, detected.stderr)
        self.assertEqual(detected.stdout, "203.0.113.25")

    def test_close_removes_owned_baota_rules_before_proxy(self) -> None:
        close_body = self.script.split("close_access() {", 1)[1].split("\n}", 1)[0]
        self.assertIn(
            'baota_firewall delete "${POSTGRES_PORT}" "${POSTGRES_RULE_REMARK}"',
            close_body,
        )
        self.assertIn(
            'baota_firewall delete "${REDIS_PORT}" "${REDIS_RULE_REMARK}"',
            close_body,
        )
        self.assertIn("stop_owned_forwarder", close_body)
        self.assertLess(close_body.index("baota_firewall delete"), close_body.index("stop_owned_forwarder"))
        self.assertNotIn("docker", close_body)

    def test_proxy_targets_only_parloq_postgres_and_redis(self) -> None:
        self.assertIn('PROJECT_NAME="${PARLOQ_COMPOSE_PROJECT:-parloq-flow}"', self.script)
        self.assertIn("healthy_container_ip postgres", self.script)
        self.assertIn("healthy_container_ip redis", self.script)
        self.assertNotIn("/data/waba", self.script)
        self.assertNotIn("docker compose", self.script)
        self.assertNotIn("docker restart", self.script)
        self.assertNotIn("docker stop", self.script)

    def _run_sourced(
        self,
        command: str,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(extra_environment or {})
        return subprocess.run(
            ["bash", "-c", 'source "$1"; eval "$2"', "bash", str(SCRIPT), command],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )


if __name__ == "__main__":
    unittest.main()
