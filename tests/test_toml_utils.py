from __future__ import annotations

import tomllib

from freellmpool.toml_utils import toml_escape


def test_toml_escape_basic():
    assert toml_escape('a"b\\c') == 'a\\"b\\\\c'


def test_toml_escape_control_chars_keep_toml_parseable():
    # A value with a newline/CR must round-trip through a basic string, not break it.
    raw = 'x"\n\r\tinjected = "y'
    rendered = f'v = "{toml_escape(raw)}"'
    assert tomllib.loads(rendered)["v"] == raw  # tab stays literal; newline/CR escaped
