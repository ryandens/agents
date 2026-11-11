"""Run discovered checks on a filtered workspace in one Dagger API session.

Invoke with: dagger api with-session python scripts/dagger_check.py
Uses only the Python standard library; the CLI owns the authenticated session.
"""

import argparse
import base64
import concurrent.futures
import contextlib
import json
import os
import sys
import tomllib
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class CheckError(RuntimeError):
    pass


QUERY_ERRORS = (CheckError, HTTPException, OSError, ValueError, KeyError, TypeError)


class Session:
    def __init__(self):
        try:
            self.port = int(os.environ["DAGGER_SESSION_PORT"])
            token = os.environ["DAGGER_SESSION_TOKEN"]
        except (KeyError, ValueError) as error:
            raise CheckError("Run under 'dagger api with-session'.") from error
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": "Basic " + base64.b64encode(f"{token}:".encode()).decode(),
        }

    def query(self, document, **variables):
        with contextlib.closing(
            HTTPConnection("127.0.0.1", self.port, timeout=3600)
        ) as connection:
            connection.request(
                "POST",
                "/query",
                body=json.dumps({"query": document, "variables": variables}).encode(),
                headers=self.headers,
            )
            response = connection.getresponse()
            if response.status != 200:
                raise CheckError(f"Dagger API returned HTTP {response.status}.")
            result = json.load(response)
        if result.get("errors"):
            raise CheckError("\n".join(error["message"] for error in result["errors"]))
        if not isinstance(result.get("data"), dict):
            raise CheckError("Dagger returned no query data.")
        return result["data"]

    def snapshot(self):
        with Path("dagger.toml").open("rb") as config:
            exclude = tomllib.load(config).get("ignore")
        if (
            not isinstance(exclude, list)
            or not exclude
            or not all(isinstance(pattern, str) and pattern for pattern in exclude)
        ):
            raise CheckError("dagger.toml must declare source exclusions in 'ignore'.")
        result = self.query(
            """query($exclude: [String!]) {
              currentWorkspace {
                directory(path: "/", exclude: $exclude, gitignore: true) {
                  asWorkspace { id }
                }
              }
            }""",
            exclude=exclude,
        )
        return result["currentWorkspace"]["directory"]["asWorkspace"]["id"]

    def checks(self, workspace):
        result = self.query(
            """query($workspace: ID!) {
              node(id: $workspace) { ... on Workspace {
                artifacts { filterTypes(types: ["Check"]) { items { uri } } }
              } }
            }""",
            workspace=workspace,
        )
        return [
            item["uri"] for item in result["node"]["artifacts"]["filterTypes"]["items"]
        ]

    def check(self, workspace, uri):
        result = self.query(
            """query($workspace: ID!, $uri: String!) {
              node(id: $workspace) { ... on Workspace {
                artifacts { filterUri(uri: $uri) {
                  asChecks { sync { pass error { message } } }
                } }
              } }
            }""",
            workspace=workspace,
            uri=uri,
        )["node"]["artifacts"]["filterUri"]["asChecks"]
        if len(result) != 1:
            raise CheckError(f"Expected exactly one check for {uri}.")
        check = result[0]["sync"]
        if not check["pass"]:
            raise CheckError((check.get("error") or {}).get("message", "Check failed."))

    def export_report(self, workspace, name, path):
        result = self.query(
            """query($workspace: ID!, $uri: String!, $path: String!) {
              node(id: $workspace) { ... on Workspace {
                artifacts { filterUri(uri: $uri) { one { value {
                  ... on Directory { export(path: $path, wipe: true) }
                } } } }
              } }
            }""",
            workspace=workspace,
            uri=f"dag://?directory={name}-report",
            path=str(path.resolve()),
        )
        value = result["node"]["artifacts"]["filterUri"]["one"]["value"]
        if not value or not value.get("export"):
            raise CheckError(f"{name} did not export a report directory.")


def select_checks(uris, names):
    if not uris:
        raise CheckError("Dagger discovered no checks.")
    if not names:
        return uris
    by_name = {parse_qs(urlsplit(uri).query).get("check", [""])[0]: uri for uri in uris}
    missing = set(names) - by_name.keys()
    if missing:
        raise CheckError(f"Unknown checks: {', '.join(sorted(missing))}")
    selected = {by_name[name] for name in names}
    return [uri for uri in uris if uri in selected]


def run_checks(session, workspace, uris, jobs):
    passed = True
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {pool.submit(session.check, workspace, uri): uri for uri in uris}
        for future in concurrent.futures.as_completed(pending):
            uri = pending[future]
            try:
                future.result()
                print(f"PASS {uri}", flush=True)
            except QUERY_ERRORS as error:
                passed = False
                print(f"FAIL {uri}\n{error}", file=sys.stderr, flush=True)
    return passed


def output(name, exported):
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a") as outputs:
            outputs.write(f"{name}_exported={str(exported).lower()}\n")


def run(session, *, jobs=2, names=(), reports=None, list_only=False):
    workspace = session.snapshot()
    uris = select_checks(session.checks(workspace), names)
    if list_only:
        print("\n".join(uris))
        return 0
    passed = run_checks(session, workspace, uris, jobs)
    if reports is not None:
        # Each export is attempted even after failed checks or another failed export.
        # Reuse the exact workspace and session so OpenGrep's session cache applies.
        for name in ("datadog", "opengrep"):
            try:
                output(name, False)
                session.export_report(workspace, name, reports / name)
                output(name, True)
                print(f"EXPORTED {name}", flush=True)
            except QUERY_ERRORS as error:
                passed = False
                print(f"FAIL {name} report\n{error}", file=sys.stderr, flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="append", default=[], help="Exact check name")
    parser.add_argument("-j", "--jobs", type=int, default=2)
    parser.add_argument(
        "--reports", type=Path, help="Export Datadog and OpenGrep reports"
    )
    parser.add_argument(
        "--list", action="store_true", help="List checks without running"
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    try:
        return run(
            Session(),
            jobs=args.jobs,
            names=args.check,
            reports=args.reports,
            list_only=args.list,
        )
    except QUERY_ERRORS as error:
        print(f"FAIL check runner\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
