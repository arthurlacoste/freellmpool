"""Small TOML writing helpers for simple generated config files."""

from __future__ import annotations


def toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def toml_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{toml_escape(str(value))}"'


def dump_simple_toml(data: dict[str, dict]) -> str:
    chunks = []
    for table, values in data.items():
        lines = [f"[{table}]"]
        for key, value in values.items():
            lines.append(f"{key} = {toml_value(value)}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + ("\n" if chunks else "")
