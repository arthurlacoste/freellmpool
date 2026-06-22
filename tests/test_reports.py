from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from freellmpool.artifacts import (
    RUN_RECORD_KINDS,
    RUN_RECORD_SCHEMA_VERSION,
    RunRecord,
    RunRecordStore,
)
from freellmpool.models import Model, Provider
from freellmpool.quota import QuotaStore
from freellmpool.reports import (
    render_cost_report,
    render_html_report,
    render_markdown_report,
    write_report,
)


def _clock():
    return datetime(2026, 6, 19, 12, 34, 56, tzinfo=UTC)


def _store(tmp_path: Path) -> RunRecordStore:
    return RunRecordStore(
        tmp_path / "data" / "run_records.jsonl",
        reports_dir=tmp_path / "data" / "reports",
        clock=_clock,
    )


def test_run_record_schema_supports_all_reportable_kinds():
    for kind in sorted(RUN_RECORD_KINDS):
        record = RunRecord.from_dict(
            {
                "schema_version": RUN_RECORD_SCHEMA_VERSION,
                "run_id": f"20260619T123456Z-{kind.replace('-', '_')}",
                "kind": kind,
                "created_at": "2026-06-19T12:34:56Z",
                "title": f"{kind} report",
                "prompt": "input",
                "output": "output",
            }
        )

        assert record.kind == kind
        assert record.to_dict()["schema_version"] == "1.0.0"


def test_store_is_append_only_and_last_uses_append_order(tmp_path):
    store = _store(tmp_path)
    first = store.append_new(kind="ask", title="first", prompt="one", output="old")
    # A malformed line should not become "last" and should not require a pointer file.
    store.path.write_text(
        store.path.read_text(encoding="utf-8") + "{not json}\n",
        encoding="utf-8",
    )
    second = store.append_new(kind="battle", title="second", prompt="two", output="new")

    assert first.run_id == "20260619T123456Z-0001"
    assert second.run_id == "20260619T123456Z-0003"
    assert store.last() == second
    assert store.report_path(second.run_id, "md") == tmp_path / "data" / "reports" / (
        second.run_id + ".md"
    )
    assert store.report_path(second.run_id, "html") == tmp_path / "data" / "reports" / (
        second.run_id + ".html"
    )


def test_markdown_preserves_prose_but_redacts_obvious_secrets():
    secret_shapes = (
        "sk-abcdefghijklmnopqrstuvwxyz",
        "sk-or-abcdefghijklmnopqrstuvwxyz",
        "gsk_abcdefghijklmnopqrstuvwxyz",
        "csk-abcdefghijklmnopqrstuvwxyz",
        "nvapi-abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "AIzaabcdefghijklmnopqrstuvwxyz",
    )
    record = RunRecord(
        run_id="run-1",
        kind="ask",
        created_at="2026-06-19T12:34:56Z",
        title="Ask report",
        prompt="line one\nline two\nAuthorization: Bearer abcdefghijklmnop",
        output="\n".join(
            [
                "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz",
                *secret_shapes,
                "keep *markdown* prose",
            ]
        ),
    )

    markdown = render_markdown_report(record)

    assert "line one\nline two" in markdown
    assert "keep *markdown* prose" in markdown
    assert "Bearer <redacted>" in markdown
    for secret in secret_shapes:
        assert secret not in markdown
    assert "OPENAI_API_KEY=<redacted>" in markdown
    assert markdown.count("<redacted-api-key>") >= len(secret_shapes)


def test_html_escapes_untrusted_text_and_has_no_external_asset_references():
    record = RunRecord(
        run_id="run-2",
        kind="battle",
        created_at="2026-06-19T12:34:56Z",
        title='Battle "report" <unsafe>',
        prompt='<script src="https://cdn.example/x.js">alert("x")</script>',
        output='quote: "hello" and API_KEY=supersecretvalue',
        items=(
            {
                "label": 'alpha/<b>"model"</b>',
                "provider_id": "alpha",
                "model": 'model"<tag>',
                "text": "visit http://example.test or set script-src none",
                "error": 'bad <img src="https://cdn.example/y.png">',
            },
        ),
    )

    rendered = render_html_report(record)
    lower = rendered.lower()

    assert "&lt;unsafe&gt;" in rendered
    assert "&quot;report&quot;" in rendered
    assert "&lt;script" in rendered
    assert "<script" not in lower
    assert "<img" not in lower
    assert "https://" not in lower
    assert "http://" not in lower
    assert "//cdn" not in lower
    assert "script-src" not in lower
    assert "supersecretvalue" not in rendered
    assert "API_KEY=&lt;redacted&gt;" in rendered


def test_report_cli_list_last_and_open_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FREELLMPOOL_DATA_DIR", str(tmp_path / "data"))
    store = RunRecordStore(clock=_clock)
    first = store.append_new(kind="ask", title="first", output="old")
    second = store.append_new(kind="recipe", title="recipe run", output="new", recipe="pr-review")
    assert first.run_id != second.run_id

    from freellmpool.cli import main

    assert main(["report", "list"]) == 0
    listed = capsys.readouterr().out
    assert first.run_id in listed
    assert second.run_id in listed
    assert "recipe run" in listed

    assert main(["report", "last", "--markdown"]) == 0
    assert "# recipe run" in capsys.readouterr().out

    assert main(["report", "last", "--html", "--path"]) == 0
    html_path = Path(capsys.readouterr().out.strip())
    assert html_path == tmp_path / "data" / "reports" / f"{second.run_id}.html"
    assert html_path.exists()

    monkeypatch.setattr("freellmpool.reports.webbrowser.open", lambda _url: False)
    assert main(["report", "open", second.run_id]) == 0
    opened = Path(capsys.readouterr().out.strip())
    assert opened == html_path


def test_report_last_html_open_falls_back_to_printing_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FREELLMPOOL_DATA_DIR", str(tmp_path / "data"))
    record = RunRecordStore(clock=_clock).append_new(kind="ask", title="latest", output="ok")
    monkeypatch.setattr("freellmpool.reports.webbrowser.open", lambda _url: False)

    from freellmpool.cli import main

    assert main(["report", "last", "--html", "--open"]) == 0

    path = Path(capsys.readouterr().out.strip())
    assert path == tmp_path / "data" / "reports" / f"{record.run_id}.html"
    assert path.exists()


def test_cost_show_uses_recorded_usage_and_local_quota_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FREELLMPOOL_DATA_DIR", str(tmp_path / "data"))
    quota_path = tmp_path / "quota.json"
    monkeypatch.setenv("FREELLMPOOL_QUOTA_PATH", str(quota_path))
    # ``cost show`` reports today's local quota counters via the default
    # QuotaStore clock, so record quota on that same day instead of pinning this
    # setup to the run-record fixture date.
    QuotaStore(path=quota_path).record("alpha", "alpha-small")
    record = RunRecordStore(clock=_clock).append_new(
        kind="ask",
        title="ask",
        provider_id="alpha",
        model="alpha-small",
        role="coder",
        profile="metaswarm",
        usage={"prompt_tokens": 100, "completion_tokens": 20},
    )
    monkeypatch.setattr(
        "freellmpool.cli.Pool.from_default_config",
        classmethod(lambda cls: (_ for _ in ()).throw(AssertionError("must not call providers"))),
    )

    from freellmpool.cli import main

    assert main(["cost", "show", record.run_id]) == 0
    out = capsys.readouterr().out
    assert "role:     coder" in out
    assert "profile:  metaswarm" in out
    assert "tokens:   100 in / 20 out" in out
    assert "alpha/alpha-small: used 1/" in out
    assert "estimated not spent" in out

    assert main(["cost", "show", "missing-run"]) == 3
    assert "report list" in capsys.readouterr().err


def test_cost_renderer_uses_local_catalog_quota_and_item_usage(tmp_path):
    quota = QuotaStore(path=tmp_path / "quota.json", clock=_clock)
    quota.record("alpha", "alpha-small")
    catalog = [
        Provider(
            id="alpha",
            label="Alpha",
            adapter="openai",
            base_url="https://alpha.test/v1",
            auth="none",
            models=(Model("alpha-small", rpd=2),),
        )
    ]
    record = RunRecord(
        run_id="run-3",
        kind="second-opinion",
        created_at="2026-06-19T12:34:56Z",
        title="panel",
        usage={"prompt_tokens": 1, "completion_tokens": 2},
        items=(
            {
                "provider_id": "alpha",
                "model": "alpha-small",
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        ),
    )

    out = render_cost_report(record, quota=quota, catalog=catalog)

    assert "tokens:   4 in / 6 out" in out
    assert "alpha/alpha-small: used 1/2 today" in out


def test_report_files_are_written_to_deterministic_paths(tmp_path):
    store = _store(tmp_path)
    record = store.append_new(kind="job", title="job report", output="done")

    md_path = write_report(record, "md", store=store)
    html_path = write_report(record, "html", store=store)

    assert md_path == tmp_path / "data" / "reports" / f"{record.run_id}.md"
    assert html_path == tmp_path / "data" / "reports" / f"{record.run_id}.html"
    assert md_path.read_text(encoding="utf-8").startswith("# job report")
    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")
