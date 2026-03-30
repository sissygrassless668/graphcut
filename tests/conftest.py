"""Shared fixtures for QuickCut tests."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for project tests."""
    return tmp_path
