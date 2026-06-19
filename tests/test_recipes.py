from __future__ import annotations

import json
import tomllib
from pathlib import Path

from freellmpool.models import Reply
from freellmpool.panel import PanelAnswer, PanelResult
from freellmpool.recipes import (
    RECIPE_SCHEMA_VERSION,
    MissingRecipeVariableError,
    get_recipe,
    list_recipes_json,
    render_prompt,
    run_recipe,
)

ROOT = Path(__file__).resolve().parents[1]


def test_recipe_list_json_has_stable_versioned_schema():
    payload = list_recipes_json()

    assert payload["schema_version"] == RECIPE_SCHEMA_VERSION
    names = {recipe["name"] for recipe in payload["recipes"]}
    assert {
        "second-opinion",
        "pr-review",
        "repo-summary",
        "launch-copy-critic",
        "metaswarm-worker-review",
    } <= names
    for recipe in payload["recipes"]:
        assert {
            "name",
            "version",
            "description",
            "role",
            "input_mode",
            "output_mode",
            "example",
        } <= set(recipe)


def test_recipe_json_files_include_required_schema_fields():
    for path in (ROOT / "src" / "freellmpool" / "recipes").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == RECIPE_SCHEMA_VERSION
        assert data["version"]
        assert data["example"].startswith("freellmpool recipe run ")
        assert isinstance(data["variables"], list)


def test_recipe_show_and_list_cli(capsys):
    from freellmpool.cli import main

    assert main(["recipe", "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == RECIPE_SCHEMA_VERSION

    assert main(["recipe", "show", "pr-review"]) == 0
    out = capsys.readouterr().out
    assert "pr-review" in out
    assert "example:" in out


def test_recipe_run_text_file_uses_pool_ask(monkeypatch, tmp_path, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    patch = tmp_path / "patch.diff"
    patch.write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return Reply(text="revise: missing test", provider_id="fake", model="critic", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["recipe", "run", "pr-review", "--input", str(patch)]) == 0

    assert "diff --git" in captured["prompt"]
    assert captured["kwargs"]["routing"] == "quality"
    assert captured["kwargs"]["max_tokens"] == 1024
    assert "critical reviewer" in captured["kwargs"]["system"].lower()
    assert "revise: missing test" in capsys.readouterr().out


def test_recipe_run_second_opinion_uses_panel_helper(monkeypatch):
    import freellmpool.recipes as recipes

    calls = {}

    def fake_run_panel(pool, *, prompt, **kwargs):
        calls["pool"] = pool
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        return PanelResult(
            prompt=prompt,
            requested_count=2,
            selected_count=1,
            max_tokens=512,
            answers=(
                PanelAnswer(
                    provider_id="alpha",
                    model="a",
                    label="alpha/a",
                    family="alpha",
                    text="ok",
                    latency_ms=1,
                ),
            ),
        )

    monkeypatch.setattr(recipes, "run_panel", fake_run_panel)

    recipe = get_recipe("second-opinion")
    result = run_recipe(object(), recipe, input_text="is this design solid?", opinions=2)

    assert calls["kwargs"]["n"] == 2
    assert calls["kwargs"]["routing"] == "quality"
    assert "independent answer" in calls["kwargs"]["system"].lower()
    assert "is this design solid?" in calls["prompt"]
    assert "freellmpool panel" in result.output


def test_recipe_run_can_read_stdin(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured["prompt"] = prompt
            return Reply(text="copy critique", provider_id="fake", model="critic", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "launch copy from stdin")

    assert main(["recipe", "run", "launch-copy-critic"]) == 0

    assert "launch copy from stdin" in captured["prompt"]
    assert "copy critique" in capsys.readouterr().out


def test_recipe_run_repo_summary_path_glob(monkeypatch, tmp_path, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    source = tmp_path / "module.py"
    source.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return Reply(text="repo summary", provider_id="fake", model="summarizer", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["recipe", "run", "repo-summary", "--path", str(tmp_path / "*.py")]) == 0

    assert str(source) in captured["prompt"]
    assert "def hello" in captured["prompt"]
    assert captured["kwargs"]["routing"] == "spread"
    assert "repo summary" in capsys.readouterr().out


def test_recipe_run_metaswarm_requires_validation_output(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    class FailPool:
        def ask(self, *args, **kwargs):
            raise AssertionError("provider should not be called when variables are missing")

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FailPool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["recipe", "run", "metaswarm-worker-review", "worker summary"]) == 3

    assert "missing recipe variable(s): validation_output" in capsys.readouterr().err


def test_recipe_missing_variables_lists_all_names():
    recipe = get_recipe("metaswarm-worker-review")

    try:
        render_prompt(recipe, {"input": "", "validation_output": ""})
    except MissingRecipeVariableError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing variables")

    assert "input" in message
    assert "validation_output" in message


def test_recipe_run_provider_exhaustion_is_cli_error(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.errors import NoProvidersConfigured
    from freellmpool.router import Pool

    class EmptyPool:
        def ask(self, *args, **kwargs):
            raise NoProvidersConfigured("no provider has an API key set")

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: EmptyPool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["recipe", "run", "pr-review", "patch"]) == 3

    assert "no provider has an API key set" in capsys.readouterr().err


def test_recipe_run_metaswarm_accepts_validation_output(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return Reply(text="approve", provider_id="fake", model="critic", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert (
        main(
            [
                "recipe",
                "run",
                "metaswarm-worker-review",
                "worker summary",
                "--validation-output",
                "pytest passed",
            ]
        )
        == 0
    )

    assert "worker summary" in captured["prompt"]
    assert "pytest passed" in captured["prompt"]
    assert "approve" in capsys.readouterr().out


def test_recipe_bad_name_and_missing_input_are_distinct(monkeypatch, capsys):
    from freellmpool.cli import main

    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["recipe", "run", "nope", "input"]) == 3
    assert "unknown recipe 'nope'" in capsys.readouterr().err

    assert main(["recipe", "run", "pr-review"]) == 3
    assert "requires prompt text, stdin, --input <file>, or --path <glob>" in capsys.readouterr().err


def test_recipe_package_data_is_in_build_config():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel_force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    sdist_force_include = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"][
        "force-include"
    ]

    for name in (
        "second-opinion",
        "pr-review",
        "repo-summary",
        "launch-copy-critic",
        "metaswarm-worker-review",
    ):
        source = f"src/freellmpool/recipes/{name}.json"
        assert source in wheel_force_include
        assert source in sdist_force_include
