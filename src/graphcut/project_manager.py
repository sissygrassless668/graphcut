"""Project manager for handling GraphCut project lifecycle."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from graphcut.media_prober import probe_file
from graphcut.models import ClipRef, ProjectManifest

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages the creation, loading, and modification of GraphCut projects."""

    @staticmethod
    def create_project(name: str, directory: Path) -> ProjectManifest:
        """Create a new project directory with manifest and build folder.

        Args:
            name: Project name.
            directory: Directory where the project folder (named `name`) will be created.

        Returns:
            The initialized ProjectManifest.

        Raises:
            ValueError: If the project directory already exists.
        """
        project_dir = directory / name
        if project_dir.exists():
            raise ValueError(f"Project directory already exists: {project_dir}")

        logger.info("Creating new project '%s' at %s", name, project_dir)
        project_dir.mkdir(parents=True)
        (project_dir / "build").mkdir()

        now = datetime.now(timezone.utc)
        manifest = ProjectManifest(
            name=name,
            created_at=now,
            updated_at=now,
        )

        manifest_path = project_dir / "project.yaml"
        manifest.save_yaml(manifest_path)
        return manifest

    @staticmethod
    def load_project(project_dir: Path) -> ProjectManifest:
        """Load a project manifest from a directory.

        Args:
            project_dir: Path to the project directory.

        Returns:
            The parsed ProjectManifest.

        Raises:
            ValueError: If the directory or project.yaml does not exist.
        """
        manifest_path = project_dir / "project.yaml"
        if not manifest_path.exists():
            raise ValueError(f"No project.yaml found in {project_dir}")

        logger.debug("Loading project from %s", manifest_path)
        return ProjectManifest.load_yaml(manifest_path)

    @staticmethod
    def save_project(manifest: ProjectManifest, project_dir: Path) -> None:
        """Save a project manifest to disk, updating the updated_at timestamp.

        Args:
            manifest: The ProjectManifest to save.
            project_dir: Path to the project directory.
        """
        manifest.updated_at = datetime.now(timezone.utc)
        manifest_path = project_dir / "project.yaml"
        logger.debug("Saving project to %s", manifest_path)
        manifest.save_yaml(manifest_path)

    @staticmethod
    def add_source(
        manifest: ProjectManifest, file_path: Path, source_id: str | None = None
    ) -> str:
        """Probe and add a source media file to the manifest.

        Args:
            manifest: The manifest to update.
            file_path: Path to the media file.
            source_id: Optional custom source ID (defaults to file stem).

        Returns:
            The assigned source_id.

        Raises:
            ValueError: If the file does not exist or probing fails.
        """
        file_path = file_path.resolve()
        if not file_path.exists():
            raise ValueError(f"Source file not found: {file_path}")

        source_id = source_id or file_path.stem
        if source_id in manifest.sources:
            suffix = 1
            original_id = source_id
            while f"{original_id}_{suffix}" in manifest.sources:
                suffix += 1
            source_id = f"{original_id}_{suffix}"

        logger.info("Adding source %s: %s", source_id, file_path)
        try:
            media_info = probe_file(file_path)
        except Exception as e:
            raise ValueError(f"Failed to probe media file {file_path}: {e}") from e

        manifest.sources[source_id] = media_info
        return source_id

    @staticmethod
    def remove_source(
        manifest: ProjectManifest,
        source_id: str,
        delete_file: bool = False,
        project_dir: Path | None = None,
    ) -> bool:
        """Remove a source from the manifest and all its clip references.

        Args:
            manifest: The manifest to update.
            source_id: The ID of the source to remove.
            delete_file: If True, also delete the underlying media file.
            project_dir: Required when delete_file=True to scope safe deletion.

        Raises:
            ValueError: If the source_id doesn't exist.

        Returns:
            True if a source file was deleted from disk, False otherwise.
        """
        if source_id not in manifest.sources:
            raise ValueError(f"Source '{source_id}' not found in project sources")
        if delete_file and project_dir is None:
            raise ValueError("project_dir must be provided when delete_file=True")

        source_info = manifest.sources[source_id]
        source_path = source_info.file_path.resolve()
        file_deleted = False

        logger.info("Removing source %s", source_id)
        del manifest.sources[source_id]
        
        # Remove any clip references
        manifest.clip_order = [
            clip for clip in manifest.clip_order if clip.source_id != source_id
        ]
        
        # Clear specific references
        if manifest.narration == source_id:
            manifest.narration = None
        if manifest.music == source_id:
            manifest.music = None
        if manifest.webcam and manifest.webcam.source_id == source_id:
            manifest.webcam = None

        if delete_file:
            project_root = project_dir.resolve()
            if not source_path.exists() or not source_path.is_file():
                return False

            if not source_path.is_relative_to(project_root):
                logger.warning(
                    "Skipped deleting file outside project directory: %s",
                    source_path,
                )
                return False

            still_referenced = any(
                info.file_path.resolve() == source_path
                for info in manifest.sources.values()
            )
            if still_referenced:
                logger.info("Skipped deleting shared file still referenced: %s", source_path)
                return False

            source_path.unlink(missing_ok=True)
            file_deleted = True
            logger.info("Deleted source file: %s", source_path)

        return file_deleted

    @staticmethod
    def add_to_clip_order(
        manifest: ProjectManifest, source_id: str, position: int | None = None
    ) -> None:
        """Add a source to the central clip sequence.

        Args:
            manifest: The manifest to update.
            source_id: The ID of the source to add.
            position: Optional insertion index (defaults to append).

        Raises:
            ValueError: If the source_id doesn't exist.
        """
        if source_id not in manifest.sources:
            raise ValueError(f"Source '{source_id}' not found setup before adding to clip order")

        logger.debug("Adding %s to clip sequence", source_id)
        clip = ClipRef(source_id=source_id)
        
        if position is not None and 0 <= position < len(manifest.clip_order):
            manifest.clip_order.insert(position, clip)
        else:
            manifest.clip_order.append(clip)

    @staticmethod
    def reorder_clips(manifest: ProjectManifest, new_order: list[int]) -> None:
        """Reorder the entire clip sequence by index list.

        Args:
            manifest: The manifest to update.
            new_order: List of indices mapping old positions to new.

        Raises:
            ValueError: If the index list is invalid.
        """
        if len(new_order) != len(manifest.clip_order):
            raise ValueError("Reorder list length must match current clip order length")
        
        try:
            reordered = [manifest.clip_order[i] for i in new_order]
        except IndexError as e:
            raise ValueError("Invalid index in reorder list") from e
            
        manifest.clip_order = reordered
