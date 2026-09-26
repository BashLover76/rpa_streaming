import os
import unittest
from unittest.mock import patch

from tools.admin_rpa_worker import build_rpa_command


class AdminRpaWorkerTests(unittest.TestCase):
    def test_builds_docker_runner_command(self):
        env = {
            "ADMIN_RPA_RUNNER": "docker",
            "ADMIN_RPA_COMPOSE_FILE": "/app/docker-compose.rpa.yml",
            "ADMIN_RPA_DOCKER_SERVICE": "rpa-job",
            "RPA_CDP_URL": "http://host.docker.internal:9222",
        }
        with patch.dict(os.environ, env, clear=False):
            command = build_rpa_command("disney_plus")
        self.assertEqual(
            command[:8],
            [
                "docker",
                "compose",
                "-f",
                "/app/docker-compose.rpa.yml",
                "run",
                "--build",
                "--rm",
                "rpa-job",
            ],
        )
        self.assertIn("--platform", command)
        self.assertIn("disney_plus", command)
        self.assertIn("--rpa-mode", command)
        self.assertEqual(command[command.index("--rpa-mode") + 1], "differential")
        self.assertIn("--no-auto-start-chrome", command)


if __name__ == "__main__":
    unittest.main()
