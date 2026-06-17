from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "integrations" / "metaswarm" / "freellmpool-review-adapter.sh"
README = ROOT / "integrations" / "metaswarm" / "README.md"


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
    env["XDG_CACHE_HOME"] = str(tmp_path / "xdg-cache")
    env["FREELLMPOOL_CONFIG_FILE"] = str(tmp_path / "empty-config.toml")
    env["FREELLMPOOL_KEYS_PATH"] = str(tmp_path / "empty-keys.json")
    env["METASWARM_LOG_DIR"] = str(tmp_path / "logs")
    for name in ("MISTRAL_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY"):
        env.pop(name, None)
    (tmp_path / "home").mkdir()
    (tmp_path / "xdg-config").mkdir()
    (tmp_path / "xdg-data").mkdir()
    (tmp_path / "xdg-cache").mkdir()
    (tmp_path / "empty-config.toml").write_text("# empty test config\n", encoding="utf-8")
    (tmp_path / "empty-keys.json").write_text("{}\n", encoding="utf-8")
    return env


def test_metaswarm_adapter_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(ADAPTER)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_metaswarm_adapter_no_key_review_fails_closed(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "example.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "example.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    (repo / "example.txt").write_text("after\n", encoding="utf-8")

    spec = tmp_path / "spec.md"
    rubric = tmp_path / "rubric.md"
    spec.write_text("Return PASS when the diff has no secret.\n", encoding="utf-8")
    rubric.write_text("Check for secrets only. Blocking issues require FAIL.\n", encoding="utf-8")

    result = subprocess.run(
        [
            str(ADAPTER),
            "review",
            "--worktree",
            str(repo),
            "--rubric-file",
            str(rubric),
            "--spec-file",
            str(spec),
            "--timeout",
            "20",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["tool"] == "freellmpool"
    assert payload["command"] == "review"
    assert payload["exit_code"] == 2
    assert payload["error_type"] == "auth_missing"
    assert "MISTRAL_API_KEY" in payload["raw_log"]
    assert "NVIDIA_API_KEY" in payload["raw_log"]
    assert "OPENROUTER_API_KEY" in payload["raw_log"]
    assert "secret" not in payload["raw_log"].lower()


def test_metaswarm_adapter_implement_is_unsupported(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(ADAPTER), "implement", "--attempt", "2"],
        text=True,
        capture_output=True,
        env=_base_env(tmp_path),
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["tool"] == "freellmpool"
    assert payload["command"] == "implement"
    assert payload["attempt"] == 2
    assert payload["exit_code"] == 2
    assert payload["error_type"] == "unsupported_role"
    assert "review-only" in payload["raw_log"]


def test_metaswarm_docs_are_linked() -> None:
    integrations = (ROOT / "docs" / "INTEGRATIONS.md").read_text(encoding="utf-8")
    agents = (ROOT / "docs" / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    llms = (ROOT / "docs" / "llms.txt").read_text(encoding="utf-8")
    adapter_text = ADAPTER.read_text(encoding="utf-8")
    integration_readme = README.read_text(encoding="utf-8")

    assert "integrations/metaswarm" in integrations
    assert "metaswarm" in agents.lower()
    assert "metaswarm" in readme.lower()
    assert "metaswarm" in llms.lower()
    assert "auth_missing" in adapter_text
    assert "review-only" in integration_readme
    assert ".metaswarm/external-tools.yaml" in integration_readme
