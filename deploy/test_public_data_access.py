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
        self.assertIn("1) 状态", menu.stdout)
        self.assertIn("2) 打开", menu.stdout)
        self.assertIn("3) 关闭", menu.stdout)
        self.assertNotIn("来源 IP", menu.stdout)

    def test_opening_uses_owned_temporary_nat_and_forward_chains(self) -> None:
        self.assertIn('NAT_CHAIN="PARLOQ_PUB_DATA_NAT"', self.script)
        self.assertIn('FORWARD_CHAIN="PARLOQ_PUB_DATA_FWD"', self.script)
        self.assertIn("-j DNAT --to-destination", self.script)
        self.assertIn("-I DOCKER-USER 1", self.script)
        self.assertIn("来源范围：0.0.0.0/0", self.script)
        self.assertNotIn("--allow", self.script)

    def test_generated_rules_forward_both_public_ports_to_expected_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            calls_file = Path(temporary_directory) / "iptables.calls"
            invoked = self._run_sourced(
                textwrap.dedent(
                    f"""\
                    iptables() {{
                      printf '%s\\n' "$*" >>{calls_file!s}
                      return 0
                    }}
                    install_access_rules 172.20.0.3 172.20.0.2
                    """
                )
            )
            calls = calls_file.read_text(encoding="utf-8")

        self.assertEqual(invoked.returncode, 0, invoked.stderr)
        self.assertIn(
            "-t nat -A PARLOQ_PUB_DATA_NAT -p tcp --dport 5432 "
            "-j DNAT --to-destination 172.20.0.3:5432",
            calls,
        )
        self.assertIn(
            "-t nat -A PARLOQ_PUB_DATA_NAT -p tcp --dport 6379 "
            "-j DNAT --to-destination 172.20.0.2:6379",
            calls,
        )
        self.assertIn("-t filter -I DOCKER-USER 1 -j PARLOQ_PUB_DATA_FWD", calls)

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
                "show_connection_info",
                {"PARLOQ_ENV_FILE": str(env_file)},
            )

        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn(postgres_password, shown.stdout)
        self.assertNotIn(redis_password, shown.stdout)
        self.assertIn("postgresql://parloq_flow:<POSTGRES_PASSWORD>@", shown.stdout)
        self.assertIn("redis://:<REDIS_PASSWORD>@", shown.stdout)
        self.assertIn("216.106.185.81:5432", shown.stdout)
        self.assertIn("216.106.185.81:6379", shown.stdout)

    def test_close_only_removes_owned_rules_and_runtime_state(self) -> None:
        close_body = self.script.split("close_access() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("remove_access_rules", close_body)
        self.assertIn("STATE_FILE", close_body)
        self.assertNotIn("docker", close_body)
        self.assertNotIn("ufw", close_body)

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
