"""A duplicate launch must not initialize another API worker or alter active jobs."""

import errno
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "nbim_launcher", Path(__file__).resolve().parents[1] / "run.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def socket(self, busy):
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
        if busy:
            sock.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
        return sock

    def opener(self, title="STEM · NBIM voting workspace"):
        opener = Mock()
        responses = [
            io.StringIO('{"status":"ok"}'),
            io.StringIO('{"info":{"title":"' + title + '"}}'),
        ]
        opener.open.side_effect = responses
        return opener

    def test_free_port_proceeds_without_http_calls(self):
        with (
            patch.object(launcher.socket, "socket", return_value=self.socket(False)),
            patch.object(launcher, "build_opener") as http,
        ):
            self.assertFalse(launcher.app_already_running(8765))
            http.assert_not_called()

    def test_existing_app_exits_before_building_or_starting_another_worker(self):
        with (
            patch.object(launcher.socket, "socket", return_value=self.socket(True)),
            patch.object(launcher, "build_opener", return_value=self.opener()),
            patch.object(launcher.sys, "argv", ["run.py"]),
            patch.object(launcher, "build_frontend") as build,
            patch.object(launcher.subprocess, "call") as start,
        ):
            self.assertEqual(launcher.main(), 0)
            build.assert_not_called()
            start.assert_not_called()

    def test_other_server_is_not_treated_as_our_app(self):
        with (
            patch.object(launcher.socket, "socket", return_value=self.socket(True)),
            patch.object(launcher, "build_opener", return_value=self.opener("Other app")),
        ):
            with self.assertRaisesRegex(RuntimeError, "port 8766"):
                launcher.app_already_running(8765)

    def test_unresponsive_port_has_an_actionable_error(self):
        opener = Mock()
        opener.open.side_effect = TimeoutError()
        with (
            patch.object(launcher.socket, "socket", return_value=self.socket(True)),
            patch.object(launcher, "build_opener", return_value=opener),
        ):
            with self.assertRaisesRegex(RuntimeError, "Port 8765 er opptatt"):
                launcher.app_already_running(8765)


if __name__ == "__main__":
    unittest.main()
