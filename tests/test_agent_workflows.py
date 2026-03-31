"""Tests for agent-first creator workflow helpers."""

from pathlib import Path

from click.testing import CliRunner

from graphcut.agent_workflows import (
    build_publish_bundle,
    build_storyboard,
    bundle_to_markdown,
    resolve_script_text,
)
from graphcut.cli import cli


def test_build_storyboard_creates_hook_shot():
    """Storyboard plans should generate hook-oriented first shots."""
    storyboard = build_storyboard(
        "First explain the problem. Then show the solution.",
        platform_name="tiktok",
        provider="generic",
    )

    assert len(storyboard.shots) >= 2
    assert storyboard.shots[0].camera_move == "fast punch-in"
    assert storyboard.shots[0].on_screen_text


def test_build_publish_bundle_includes_titles_and_hashtags():
    """Publish bundles should include reusable metadata for each asset."""
    bundle = build_publish_bundle(
        platform_name="shorts",
        source_name="growth-hacks.mp4",
        script_text="Growth hacks for creators who want more reach and better retention.",
    )

    assert bundle.assets
    assert len(bundle.assets[0].title_options) == 3
    assert bundle.assets[0].hashtags


def test_resolve_script_text_prefers_inline_text(tmp_path: Path):
    """Inline text should win over file inputs."""
    script_path = tmp_path / "script.txt"
    script_path.write_text("from file", encoding="utf-8")

    resolved = resolve_script_text(script_file=script_path, text="inline text")

    assert resolved == "inline text"


def test_bundle_to_markdown_mentions_asset_filename():
    """Markdown output should be creator-readable."""
    bundle = build_publish_bundle(platform_name="tiktok", source_name="demo.mp4", script_text="Demo script")
    markdown = bundle_to_markdown(bundle)

    assert "# Tiktok Package" in markdown
    assert bundle.assets[0].filename in markdown


def test_cli_storyboard_json_outputs_shots():
    """The storyboard CLI should expose a machine-readable shot plan."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["storyboard", "--text", "Lead with the hook. Then explain the win.", "--json"],
    )

    assert result.exit_code == 0
    assert '"shots"' in result.output


def test_cli_package_markdown_writes_bundle(tmp_path: Path):
    """The package CLI should be able to write markdown output."""
    runner = CliRunner()
    output_path = tmp_path / "bundle.md"

    result = runner.invoke(
        cli,
        [
            "package",
            "demo.mp4",
            "--text",
            "A creator workflow for faster posting.",
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    assert "Title Options:" in output_path.read_text(encoding="utf-8")
