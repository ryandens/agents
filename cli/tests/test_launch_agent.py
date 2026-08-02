"""Rendering the LaunchAgent plist.

The whole reason this is Python and not `sed` is that the values substituted in can
contain `&`, which `sed` reads as "the text that matched" and XML reads as the start of
an entity. An API URL with a query string is the realistic case, and the failure is
nasty: `launchctl bootstrap` rejects the plist with a message that says nothing about
why. These pin both halves — correct substitution, and well-formed XML afterwards.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from xml.etree import ElementTree

import pytest

from safari_history.launch_agent import PLACEHOLDERS, main, render

TEMPLATE = (
    Path(__file__).parent.parent
    / "launchd"
    / "com.ryandens.safari-history-export.plist"
)


def values(
    home: str = "/Users/someone",
    api_url: str = "https://agents.example.com/api/browser-history",
    credentials: str = "/Users/someone/.config/sa.json",
) -> dict[str, str]:
    return {
        "__HOME__": home,
        "__API_URL__": api_url,
        "__CREDENTIALS__": credentials,
    }


def test_the_shipped_template_renders_to_a_valid_plist() -> None:
    rendered = render(TEMPLATE.read_text(encoding="utf-8"), values())
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == "com.ryandens.safari-history-export"


def test_no_placeholder_survives_rendering() -> None:
    rendered = render(TEMPLATE.read_text(encoding="utf-8"), values())
    for placeholder in PLACEHOLDERS:
        assert placeholder not in rendered


def test_an_ampersand_in_the_url_does_not_reinsert_the_placeholder() -> None:
    """The exact sed failure: `&` in a replacement means "what matched"."""
    url = "https://agents.example.com/api/browser-history?a=1&b=2"
    rendered = render(TEMPLATE.read_text(encoding="utf-8"), values(api_url=url))

    assert "__API_URL__" not in rendered
    # Round-trips through a real plist parser, so the escaping has to be right too.
    assert (
        plistlib.loads(rendered.encode("utf-8"))["EnvironmentVariables"][
            "SAFARI_HISTORY_API_URL"
        ]
        == url
    )


@pytest.mark.parametrize(
    "hostile",
    [
        "https://x.example/api?a=1&b=2",  # sed: & is the matched text
        "https://x.example/api|pipe",  # sed: | ends the expression
        "https://x.example/api\\back",  # sed: backslash starts an escape
        "https://x.example/api?q=<tag>",  # xml: < opens an element
        'https://x.example/api?q="quoted"',  # xml: quotes inside an attribute
        "https://x.example/api?q=a&amp;b",  # already-escaped text must not double-escape
    ],
)
def test_metacharacters_survive_the_round_trip(hostile: str) -> None:
    rendered = render(TEMPLATE.read_text(encoding="utf-8"), values(api_url=hostile))

    # Well-formed XML, and the value that comes back out is the one that went in.
    ElementTree.fromstring(rendered)
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["EnvironmentVariables"]["SAFARI_HISTORY_API_URL"] == hostile


def test_main_writes_the_rendered_plist(tmp_path, monkeypatch, capsys) -> None:
    for placeholder, variable in PLACEHOLDERS.items():
        monkeypatch.setenv(variable, values()[placeholder])

    assert main([str(TEMPLATE)]) == 0
    assert plistlib.loads(capsys.readouterr().out.encode("utf-8"))["Label"]


def test_main_refuses_when_a_value_is_missing(monkeypatch, capsys) -> None:
    """Better than rendering a plist with an empty path launchd would silently accept."""
    for variable in PLACEHOLDERS.values():
        monkeypatch.delenv(variable, raising=False)

    assert main([str(TEMPLATE)]) == 2
    assert "is not set" in capsys.readouterr().err
