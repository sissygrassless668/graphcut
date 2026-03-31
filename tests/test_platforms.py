"""Tests for built-in platform and recipe definitions."""

from graphcut.platforms import get_platform_profile, get_workflow_recipe, list_platform_profiles


def test_platform_alias_lookup():
    """Instagram aliases should resolve to Reels."""
    profile = get_platform_profile("instagram")
    assert profile.key == "reels"
    assert profile.width == 1080
    assert profile.height == 1920


def test_recipe_defaults_are_available():
    """Recipes should expose creator-focused defaults."""
    recipe = get_workflow_recipe("podcast")
    assert recipe.default_platform == "shorts"
    assert recipe.remove_silence is True
    assert recipe.clips >= 1


def test_platform_listing_order_contains_common_surfaces():
    """Core publishing surfaces should be exposed in the built-in list."""
    keys = [profile.key for profile in list_platform_profiles()]
    assert "tiktok" in keys
    assert "shorts" in keys
    assert "youtube" in keys
