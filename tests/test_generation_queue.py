"""Tests for provider-agnostic generation queue workflows."""

from pathlib import Path

from click.testing import CliRunner

from graphcut.cli import cli
from graphcut.generation_queue import fetch_job, get_job, list_jobs, submit_job, wait_for_job


def _sample_storyboard() -> dict:
    return {
        "platform": "tiktok",
        "provider": "mock",
        "hook_style": "curiosity",
        "total_duration_seconds": 8.0,
        "shots": [
            {
                "shot_id": "shot_01",
                "beat": "Hook beat",
                "duration_seconds": 4.0,
                "voiceover": "Hook beat",
                "visual_prompt": "A strong opening visual.",
                "on_screen_text": "Wait for it...",
                "camera_move": "fast punch-in",
                "asset_type": "generated-video",
                "aspect_ratio": "9:16",
            },
            {
                "shot_id": "shot_02",
                "beat": "Follow-up beat",
                "duration_seconds": 4.0,
                "voiceover": "Follow-up beat",
                "visual_prompt": "A supporting visual.",
                "on_screen_text": "The key move",
                "camera_move": "slow push-in",
                "asset_type": "generated-video",
                "aspect_ratio": "9:16",
            },
        ],
    }


def test_generation_queue_mock_lifecycle(tmp_path: Path):
    """Mock jobs should submit, complete, and fetch local assets."""
    queue_dir = tmp_path / "queue"
    output_dir = tmp_path / "generated"

    job = submit_job(_sample_storyboard(), queue_dir=queue_dir, output_dir=output_dir)
    assert job["status"] == "queued"

    waited = wait_for_job(job["job_id"], queue_dir=queue_dir, timeout_seconds=1.0, poll_seconds=0.01)
    assert waited["status"] == "succeeded"

    fetched = fetch_job(job["job_id"], queue_dir=queue_dir, output_dir=output_dir)
    assert len(fetched["local_assets"]) == 2
    assert Path(fetched["local_assets"][0]["path"]).exists()


def test_generation_queue_list_and_get(tmp_path: Path):
    """Jobs should be discoverable after submission."""
    queue_dir = tmp_path / "queue"
    submit_job(_sample_storyboard(), queue_dir=queue_dir)

    jobs = list_jobs(queue_dir=queue_dir)
    assert len(jobs) == 1

    loaded = get_job(jobs[0]["job_id"], queue_dir=queue_dir)
    assert loaded["job_id"] == jobs[0]["job_id"]


def test_cli_generate_with_fetch_outputs_job_json(tmp_path: Path):
    """The generate CLI should submit and fetch mock assets."""
    runner = CliRunner()
    queue_dir = tmp_path / "queue"
    output_dir = tmp_path / "generated"

    result = runner.invoke(
        cli,
        [
            "generate",
            "--text",
            "Lead with the hook. Then show the payoff.",
            "--provider",
            "mock",
            "--queue-dir",
            str(queue_dir),
            "--output-dir",
            str(output_dir),
            "--fetch",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"status": "succeeded"' in result.output
    assert '"local_assets"' in result.output


def test_cli_queue_submit_and_fetch(tmp_path: Path):
    """Queue CLI commands should work with a storyboard file."""
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(__import__("json").dumps(_sample_storyboard()), encoding="utf-8")
    queue_dir = tmp_path / "queue"
    output_dir = tmp_path / "generated"
    runner = CliRunner()

    submit = runner.invoke(
        cli,
        [
            "queue",
            "submit",
            str(storyboard_path),
            "--queue-dir",
            str(queue_dir),
            "--output-dir",
            str(output_dir),
            "--json",
        ],
    )
    assert submit.exit_code == 0

    job_id = __import__("json").loads(submit.output)["job_id"]
    fetched = runner.invoke(
        cli,
        [
            "queue",
            "fetch",
            job_id,
            "--queue-dir",
            str(queue_dir),
            "--output-dir",
            str(output_dir),
            "--json",
        ],
    )
    assert fetched.exit_code == 0
    assert '"local_assets"' in fetched.output
