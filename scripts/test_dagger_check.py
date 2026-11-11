"""Failure and report contracts for the standard-library Dagger check runner."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dagger_check import CheckError, Session, run, select_checks


class FakeSession:
    def __init__(self, *, failures=(), broken_reports=()):
        self.failures = failures
        self.broken_reports = broken_reports
        self.checked = []
        self.exported = []

    def snapshot(self):
        return "filtered-workspace"

    def checks(self, workspace):
        assert workspace == "filtered-workspace"
        return ["dag://?check=application", "dag://?check=opengrep"]

    def check(self, workspace, uri):
        self.checked.append((workspace, uri))
        if uri in self.failures:
            raise CheckError("check failed")

    def export_report(self, workspace, name, path):
        self.exported.append((workspace, name, path))
        if name in self.broken_reports:
            raise CheckError("scanner crashed without a report")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.stderr = self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def test_failed_application_and_scan_still_export_both_reports(self):
        session = FakeSession(
            failures=("dag://?check=application", "dag://?check=opengrep")
        )
        self.assertEqual(run(session, reports=Path("reports")), 1)
        self.assertEqual(len(session.checked), 2)
        self.assertEqual(
            [call[1] for call in session.exported], ["datadog", "opengrep"]
        )
        self.assertTrue(
            all(call[0] == "filtered-workspace" for call in session.checked)
        )
        self.assertTrue(
            all(call[0] == "filtered-workspace" for call in session.exported)
        )

    def test_export_failure_is_fatal_and_does_not_skip_other_report(self):
        session = FakeSession(broken_reports=("datadog",))
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / "outputs"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(outputs)}):
                self.assertEqual(run(session, reports=Path("reports")), 1)
            contents = outputs.read_text()
        self.assertEqual(len(session.exported), 2)
        self.assertNotIn("datadog_exported=true", contents)
        self.assertIn("opengrep_exported=true", contents)

    def test_successful_check_does_not_hide_opengrep_export_failure(self):
        session = FakeSession(broken_reports=("opengrep",))
        self.assertEqual(run(session, reports=Path("reports")), 1)

    def test_success_and_optional_reports(self):
        session = FakeSession()
        self.assertEqual(run(session), 0)
        self.assertEqual(session.exported, [])
        self.assertEqual(run(FakeSession(), reports=Path("reports")), 0)

    def test_listing_does_not_execute_or_export(self):
        session = FakeSession()
        self.assertEqual(run(session, list_only=True, reports=Path("reports")), 0)
        self.assertEqual(session.checked, [])
        self.assertEqual(session.exported, [])

    def test_unknown_and_empty_selections_fail_closed(self):
        with self.assertRaises(CheckError):
            select_checks([], [])
        with self.assertRaises(CheckError):
            run(FakeSession(), names=["typo"])
        session = FakeSession()
        self.assertEqual(run(session, names=["opengrep"]), 0)
        self.assertEqual(
            session.checked, [("filtered-workspace", "dag://?check=opengrep")]
        )


class ApiTests(unittest.TestCase):
    def test_graphql_error_with_http_success_is_fatal(self):
        with patch.dict(
            os.environ,
            {"DAGGER_SESSION_PORT": "12345", "DAGGER_SESSION_TOKEN": "fixture"},
        ):
            session = Session()
        response = io.BytesIO(
            json.dumps({"errors": [{"message": "scan failed"}]}).encode()
        )
        response.status = 200
        with (
            patch("dagger_check.HTTPConnection") as connection,
            self.assertRaisesRegex(CheckError, "scan failed"),
        ):
            connection.return_value.getresponse.return_value = response
            session.query("{id}")

    def test_http_redirect_is_rejected(self):
        session = Session.__new__(Session)
        session.port = 12345
        session.headers = {}
        with (
            patch("dagger_check.HTTPConnection") as connection,
            self.assertRaisesRegex(CheckError, "HTTP 302"),
        ):
            connection.return_value.getresponse.return_value.status = 302
            session.query("{id}")

    def test_check_findings_and_missing_check_are_failures(self):
        session = Session.__new__(Session)
        for checks in (
            [],
            [{"sync": {"pass": False, "error": {"message": "active finding"}}}],
        ):
            session.query = Mock(
                return_value={
                    "node": {"artifacts": {"filterUri": {"asChecks": checks}}}
                }
            )
            with self.assertRaises(CheckError):
                session.check("workspace", "dag://?check=opengrep")

    def test_missing_or_empty_ignore_never_imports_workspace(self):
        session = Session.__new__(Session)
        session.query = Mock()
        for config in (b"", b"ignore = []", b"ignore = [1]"):
            with (
                patch("dagger_check.Path.open", return_value=io.BytesIO(config)),
                self.assertRaises(CheckError),
            ):
                session.snapshot()
        session.query.assert_not_called()

    def test_missing_session_has_actionable_error(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(CheckError, "dagger api with-session"),
        ):
            Session()


if __name__ == "__main__":
    unittest.main()
