"""Render the LaunchAgent plist template.

Deliberately not `sed`. The values substituted in are a home directory, an API URL and a
credentials path — all of which can contain characters that `sed` reads as syntax:

- `&` in a `sed` replacement means "the text that matched", so an API URL carrying a
  query string (`...?a=1&b=2`) writes the `__API_URL__` placeholder back into the plist
  instead of the URL.
- `|` ends the expression early when it is also the delimiter, and a backslash starts
  an escape.

The result is a plist that `launchctl bootstrap` rejects with a message that points
nowhere near the cause. `str.replace` has no metacharacters at all.

The values also land inside XML, where `&` and `<` have to be entities — the same `&`
that breaks `sed` would produce a malformed document even if the substitution worked.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

# Placeholder in the template -> environment variable holding its value. launchd never
# expands `~` and never reads a shell profile, so every one of these has to be absolute
# by the time the plist is written.
PLACEHOLDERS = {
    "__HOME__": "AGENT_HOME",
    "__API_URL__": "AGENT_API_URL",
    "__CREDENTIALS__": "AGENT_CREDENTIALS",
}


def render(template: str, values: dict[str, str]) -> str:
    """Substitute placeholders, escaping each value for XML."""
    for placeholder, value in values.items():
        template = template.replace(placeholder, escape(value))
    return template


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: python -m safari_history.launch_agent <template.plist>\n"
            f"  reads {', '.join(PLACEHOLDERS.values())} from the environment,\n"
            "  writes the rendered plist to stdout",
            file=sys.stderr,
        )
        return 2

    values = {}
    for placeholder, variable in PLACEHOLDERS.items():
        value = os.environ.get(variable)
        if value is None:
            print(f"error: {variable} is not set", file=sys.stderr)
            return 2
        values[placeholder] = value

    try:
        template = Path(args[0]).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {args[0]}: {exc}", file=sys.stderr)
        return 2

    sys.stdout.write(render(template, values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
