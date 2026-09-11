"""Updating from the CLI: version fingerprint, comparison with upstream, command."""

from __future__ import annotations

import io
import contextlib
import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import __main__ as cli
from whisper_desk import update

HEAD = "60e53b1c0ffee0ddba11deadbeef0123456789ab"
OLDER = "51cca3200000000000000000000000000000abcd"
INSTALL_SH = Path(__file__).resolve().parent.parent / "install.sh"

FINGERPRINT = {
    "commit": OLDER,
    "ref": "main",
    "date": "2026-08-01T10:00:00Z",
    "repo": "SalvadorCardona/whisper-desk",
    "origin": "github",
}


def commit_payload(sha: str = HEAD, date: str = "2026-09-11T09:00:00Z") -> bytes:
    return json.dumps({"sha": sha, "commit": {"committer": {"date": date}}}).encode()


class FakeResponse(io.BytesIO):
    """What urlopen returns, as far as this module uses it."""

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class HttpErrorMixin:
    """Builds the HTTP errors GitHub answers with, and closes them afterwards.

    An HTTPError holds an open body: left to the garbage collector, it
    complains in the middle of the suite.
    """

    def http_error(self, code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError(
            "https://api.github.com", code, "no", {}, FakeResponse(b"")  # type: ignore[arg-type]
        )
        self.addCleanup(error.close)   # type: ignore[attr-defined]
        return error


class FingerprintTest(unittest.TestCase):
    def write(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".whisper-desk-version"
        path.write_text(content, encoding="utf-8")
        return path

    def test_key_value(self):
        path = self.write(f"commit={HEAD}\nref=main\ndate=2026-09-11T09:00:00Z\n")
        self.assertEqual(
            update.read_fingerprint(path),
            {"commit": HEAD, "ref": "main", "date": "2026-09-11T09:00:00Z"},
        )

    def test_blank_lines_and_comments_are_ignored(self):
        path = self.write(f"# whisper-desk\n\ncommit={HEAD}\nnonsense\n")
        self.assertEqual(update.read_fingerprint(path), {"commit": HEAD})

    def test_a_value_may_contain_an_equals_sign(self):
        path = self.write("src=/home/me/a=b\n")
        self.assertEqual(update.read_fingerprint(path)["src"], "/home/me/a=b")

    def test_unknown_is_the_same_as_absent(self):
        """install.sh writes "unknown" when git and the API both stay silent."""
        path = self.write("commit=unknown\nref=main\n")
        fingerprint = update.read_fingerprint(path)
        self.assertEqual(update.commit(fingerprint), "")
        self.assertEqual(update.ref(fingerprint), "main")

    def test_an_installation_without_a_fingerprint(self):
        self.assertEqual(update.read_fingerprint(Path("/nonexistent/version")), {})

    def test_the_defaults_hold_without_a_fingerprint(self):
        self.assertEqual(update.repo({}), update.DEFAULT_REPO)
        self.assertEqual(update.ref({}), update.DEFAULT_REF)
        self.assertEqual(update.commit({}), "")

    def test_describe(self):
        self.assertEqual(update.describe(FINGERPRINT), "main @ 51cca32 (2026-08-01)")
        self.assertEqual(update.describe({}), "unknown version")


class LatestCommitTest(HttpErrorMixin, unittest.TestCase):
    def latest(self, answer):
        with mock.patch("urllib.request.urlopen", side_effect=answer):
            return update.latest_commit("SalvadorCardona/whisper-desk", "main")

    def test_the_commit_and_its_date(self):
        result = self.latest(lambda *a, **k: FakeResponse(commit_payload()))
        self.assertEqual(result, {"commit": HEAD, "date": "2026-09-11T09:00:00Z"})

    def test_the_ref_is_the_one_asked_for(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **k: FakeResponse(commit_payload())) as urlopen:
            update.latest_commit("me/mine", "wip")
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://api.github.com/repos/me/mine/commits/wip",
        )

    def test_offline(self):
        with self.assertRaises(update.UpstreamUnreachable) as raised:
            self.latest(urllib.error.URLError("[Errno 111] Connection refused"))
        self.assertIn("offline", str(raised.exception))

    def test_a_private_repository(self):
        for code in (401, 403, 404):
            with self.subTest(code=code):
                with self.assertRaises(update.UpstreamUnreachable) as raised:
                    self.latest(self.http_error(code))
                self.assertIn("private repository", str(raised.exception))

    def test_a_nonexistent_ref(self):
        """GitHub answers 422 for a ref it has never heard of."""
        with self.assertRaises(update.UpstreamUnreachable) as raised:
            self.latest(self.http_error(422))
        self.assertIn("nonexistent branch", str(raised.exception))

    def test_an_answer_that_is_not_a_commit(self):
        with self.assertRaises(update.UpstreamUnreachable):
            self.latest(lambda *a, **k: FakeResponse(b"<html>nope</html>"))
        with self.assertRaises(update.UpstreamUnreachable):
            self.latest(lambda *a, **k: FakeResponse(b'{"message": "Not Found"}'))


class LocalSourceTest(unittest.TestCase):
    def clone(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        (path / "src/whisper_desk").mkdir(parents=True)
        (path / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        return path

    def test_a_github_installation_has_no_local_source(self):
        self.assertIsNone(update.local_source(FINGERPRINT))

    def test_a_clone_that_is_still_there(self):
        path = self.clone()
        self.assertEqual(
            update.local_source({"origin": "local", "src": str(path)}), path
        )

    def test_a_clone_that_has_gone(self):
        self.assertIsNone(
            update.local_source({"origin": "local", "src": "/nonexistent/clone"})
        )


class InstallEnvTest(unittest.TestCase):
    def test_the_repository_and_the_ref_are_replayed(self):
        env = update.install_env(FINGERPRINT, keep_hotkey=False)
        self.assertEqual(env["WD_REPO"], "SalvadorCardona/whisper-desk")
        self.assertEqual(env["WD_REF"], "main")
        self.assertNotIn("WD_SRC", env)
        self.assertNotIn("WD_NO_HOTKEY", env)

    def test_an_existing_shortcut_is_left_alone(self):
        """A binding the user has made their own must survive the update."""
        env = update.install_env(FINGERPRINT, keep_hotkey=True)
        self.assertEqual(env["WD_NO_HOTKEY"], "1")

    def test_a_local_installation_is_replayed_from_its_clone(self):
        with mock.patch.object(update, "local_source", return_value=Path("/clone")):
            env = update.install_env({"origin": "local", "src": "/clone"}, keep_hotkey=False)
        self.assertEqual(env["WD_SRC"], "/clone")


class FetchInstallScriptTest(HttpErrorMixin, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.destination = Path(directory.name)

    def test_it_is_copied_from_the_clone(self):
        clone = self.destination / "clone"
        (clone / "src/whisper_desk").mkdir(parents=True)
        (clone / "install.sh").write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
        script = update.fetch_install_script(
            {"origin": "local", "src": str(clone)}, self.destination
        )
        self.assertEqual(script.read_text(encoding="utf-8"), "#!/bin/sh\necho hello\n")

    def test_it_is_downloaded_otherwise(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **k: FakeResponse(b"#!/bin/sh\n")) as urlopen:
            script = update.fetch_install_script(FINGERPRINT, self.destination)
        self.assertEqual(script.read_bytes(), b"#!/bin/sh\n")
        self.assertIn("whisper-desk/main/install.sh", urlopen.call_args.args[0].full_url)

    def test_a_download_that_fails_says_so(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(404)):
            with self.assertRaises(update.UpstreamUnreachable) as raised:
                update.fetch_install_script(FINGERPRINT, self.destination)
        self.assertIn("private repository", str(raised.exception))


class CheckCommandTest(unittest.TestCase):
    """One line, an exit code, and not a single write."""

    def run_check(self, fingerprint, latest=None, error=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(update, "read_fingerprint", return_value=fingerprint), \
                mock.patch.object(
                    update, "latest_commit", side_effect=error,
                    return_value=latest or {"commit": HEAD, "date": "2026-09-11T09:00:00Z"},
                ):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["update", "--check"])
        return code, out.getvalue(), err.getvalue()

    def test_up_to_date(self):
        code, out, err = self.run_check({**FINGERPRINT, "commit": HEAD})
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("up to date", out)
        self.assertEqual(err, "")

    def test_something_new_upstream(self):
        code, out, _ = self.run_check(FINGERPRINT)
        self.assertEqual(code, 1)
        self.assertIn("51cca32", out)
        self.assertIn("60e53b1", out)

    def test_an_installation_from_before_the_fingerprint(self):
        code, out, err = self.run_check({})
        self.assertEqual(code, 1)
        self.assertIn("unknown version", out)
        self.assertIn("whisper-desk update", out)
        self.assertNotIn("Traceback", err)

    def test_offline(self):
        code, out, err = self.run_check(
            FINGERPRINT, error=update.UpstreamUnreachable("GitHub unreachable — offline?")
        )
        self.assertEqual(code, cli.CANNOT_TELL)
        self.assertEqual(out, "")
        self.assertIn("offline", err)
        self.assertNotIn("Traceback", err)

    def test_nothing_is_installed(self):
        with mock.patch.object(update, "read_fingerprint", return_value=FINGERPRINT), \
                mock.patch.object(update, "latest_commit",
                                  return_value={"commit": HEAD, "date": ""}), \
                mock.patch.object(update, "run_install") as run_install, \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main(["update", "--check"])
        run_install.assert_not_called()


class UpdateCommandTest(unittest.TestCase):
    def call(self, fingerprint, state="idle", installed=None, returncode=0):
        """Runs "whisper-desk update" with the daemon and install.sh replaced."""
        out, err = io.StringIO(), io.StringIO()
        answers = [fingerprint, installed if installed is not None else fingerprint]
        with mock.patch.object(update, "read_fingerprint", side_effect=answers), \
                mock.patch.object(update, "latest_commit",
                                  return_value={"commit": HEAD, "date": "2026-09-11T09:00:00Z"}), \
                mock.patch.object(update, "hotkey_installed", return_value=True), \
                mock.patch.object(update, "run_install", return_value=returncode) as run_install, \
                mock.patch("whisper_desk.client.send", return_value={"state": state}), \
                mock.patch("whisper_desk.service.restart", return_value=True) as restart:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["update"])
        return code, out.getvalue(), err.getvalue(), run_install, restart

    def test_a_dictation_under_way_is_not_cut_off(self):
        code, _, err, run_install, restart = self.call(FINGERPRINT, state="recording")
        self.assertEqual(code, 1)
        self.assertIn("dictation", err)
        run_install.assert_not_called()
        restart.assert_not_called()

    def test_an_up_to_date_machine_is_left_alone(self):
        code, out, _, run_install, restart = self.call({**FINGERPRINT, "commit": HEAD})
        self.assertEqual(code, 0)
        self.assertIn("already up to date", out)
        run_install.assert_not_called()
        restart.assert_not_called()

    def test_the_shortcut_is_preserved_and_the_service_restarted(self):
        code, out, _, run_install, restart = self.call(
            FINGERPRINT, installed={**FINGERPRINT, "commit": HEAD}
        )
        self.assertEqual(code, 0)
        self.assertEqual(run_install.call_args.args[1], True)   # keep_hotkey
        restart.assert_called_once_with()
        self.assertIn("untouched", out)
        self.assertIn("restarted", out)
        self.assertIn("60e53b1", out)

    def test_a_failed_installation_restarts_nothing(self):
        code, _, err, _, restart = self.call(FINGERPRINT, returncode=3)
        self.assertEqual(code, 1)
        self.assertIn("install.sh failed", err)
        restart.assert_not_called()


class InstallScriptTest(unittest.TestCase):
    """What install.sh promises, read in its text.

    The script cannot be run here: it downloads uv, builds a virtual
    environment and installs faster-whisper. What is checked is its logic —
    the three things the update leans on.
    """

    @classmethod
    def setUpClass(cls):
        cls.script = INSTALL_SH.read_text(encoding="utf-8")

    def test_an_existing_configuration_is_kept(self):
        section = self.script.split("# --- 5. configuration")[1].split("# --- 6.")[0]
        kept = re.search(r'if \[ -f "\$CONFIG" \]; then\n(.*?)\nelse', section, re.S)
        self.assertIsNotNone(kept, "the branch that keeps the configuration has moved")
        self.assertNotIn("cp ", kept.group(1))
        self.assertIn("existing configuration kept", kept.group(1))

    def test_the_fingerprint_is_written_after_the_sources(self):
        self.assertLess(
            self.script.index('rm -rf "$APP_DIR"'),
            self.script.index('} > "$VERSION_FILE"'),
        )

    def test_the_fingerprint_carries_what_update_compares(self):
        for key in ("commit=", "ref=", "date=", "repo=", "origin="):
            with self.subTest(key=key):
                self.assertIn(f"printf '{key}", self.script)


if __name__ == "__main__":
    unittest.main()
