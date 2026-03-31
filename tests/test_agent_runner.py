"""Tests for declarative agent specs and creator briefs."""

import json
from pathlib import Path

from click.testing import CliRunner

from graphcut.agent_runner import agent_template, run_agent_job
from graphcut.cli import cli
from graphcut.models import MediaInfo


def test_agent_template_contains_workflow():
    """Templates should provide a valid workflow scaffold."""
    payload = agent_template("viralize")
    assert payload["workflow"] == "viralize"
    assert "params" in payload


def test_run_agent_job_storyboard_returns_result():
    """Storyboard specs should execute without needing a file."""
    result = run_agent_job(
        {
            "workflow": "storyboard",
            "params": {
                "text": "Hook first. Then explain the payoff.",
                "platform_name": "tiktok",
                "provider": "mock",
            },
        }
    )

    assert result["workflow"] == "storyboard"
    assert "shots" in result["result"]


def test_run_agent_job_creator_brief(monkeypatch, tmp_path: Path):
    """Creator brief specs should return a recommendation bundle."""
    source = tmp_path / "podcast.mp4"
    source.write_bytes(b"fake")

    monkeypatch.setattr(
        "graphcut.agent_runner.probe_file",
        lambda path: MediaInfo(
            file_path=path,
            duration_seconds=600.0,
            width=1920,
            height=1080,
            media_type="video",
        ),
    )

    result = run_agent_job(
        {
            "workflow": "creator-brief",
            "params": {"source_file": str(source)},
        }
    )

    assert result["result"]["recommended_workflow"] == "viralize"


def test_cli_agent_run_spec_file(monkeypatch, tmp_path: Path):
    """The agent runner CLI should execute a JSON job spec."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "workflow": "storyboard",
                "params": {
                    "text": "Open with the pain point. Then show the solution.",
                    "platform_name": "tiktok",
                    "provider": "mock",
                },
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "run", str(spec_path), "--json"])

    assert result.exit_code == 0
    assert '"workflow": "storyboard"' in result.output


def test_cli_creator_brief_json(monkeypatch, tmp_path: Path):
    """The creator brief CLI should emit a machine-readable recommendation."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake")

    monkeypatch.setattr(
        "graphcut.agent_runner.probe_file",
        lambda path: MediaInfo(
            file_path=path,
            duration_seconds=30.0,
            width=1080,
            height=1920,
            media_type="video",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["creator", "brief", str(source), "--json"])

    assert result.exit_code == 0
    assert '"recommended_workflow": "make"' in result.output
