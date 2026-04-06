#!/usr/bin/env python3
"""FTP File Sorter Module

Sorts files from FTP directories based on date patterns in filenames and organizes them
into structured date-based directories (year/month/day) within each camera's folder.

Designed for setups where each camera has its own directory with an FTP subdirectory:
    /mnt/cctv/
      garage-01/
        ftp/                    <- FTP server outputs files here
          garage-01_00_20260323182654.mp4
          garage-01_00_20260323184122.mp4
        2026/03/23/             <- Sorted files end up here
          garage-01_00_20260323182654.mp4

Filename pattern supported:
    garage-01_00_20260323182654.mp4

    Components:
    - Camera name: garage-01 (extracted from before the timestamp)
    - Date/time: 20260323182654 (YYYYMMDDHMMSS)
    - Extension: mp4

Usage (for your setup):
    from ftp_sorter import FileSorter, SortingConfig

    config = SortingConfig(
        cameras_root_dir="/mnt/cctv",
        ftp_subdirectory="ftp",
        retention_days=30
    )

    sorter = FileSorter(config)
    sorter.sort_files()
"""

import re
import os
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, NamedTuple
from datetime import datetime, timedelta


class ParsedFilename(NamedTuple):
    """Represents a parsed filename with extracted components."""

    camera_name: str
    year: str
    month: str
    day: str
    hour: str
    minute: str
    second: str
    extension: str
    original_filename: str
    source_path: Path

    @property
    def date_path(self) -> str:
        """Returns the date-based path (year/month/day)."""
        return f"{self.year}/{self.month}/{self.day}"

    @property
    def timestamp(self) -> datetime:
        """Returns the full timestamp as datetime object."""
        return datetime(
            int(self.year),
            int(self.month),
            int(self.day),
            int(self.hour),
            int(self.minute),
            int(self.second),
        )


@dataclass
class SortingConfig:
    """Configuration for the file sorter.

    Supports two modes:

    1. Single-camera FTP mode (recommended for your setup):
       - cameras_root_dir: Root directory containing camera subdirectories
       - ftp_subdirectory: Name of subdirectory within each camera that contains FTP files
       - Files are sorted from {cameras_root_dir}/{camera}/{ftp_subdirectory}
         to {cameras_root_dir}/{camera}/{year}/{month}/{day}/

       Example:
           cameras_root_dir: "/mnt/cctv"
           ftp_subdirectory: "ftp"
           Structure:
               /mnt/cctv/garage-01/ftp/     <- FTP files here
               /mnt/cctv/garage-01/2026/03/23/  <- Sorted files here

    2. Multi-directory FTP mode:
       - ftp_camera_dirs: List of specific FTP directories to scan
       - target_dir: Root where sorted files will be placed
       - Files are sorted from ftp_camera_dirs to target_dir/{camera}/{year}/{month}/{day}/

    Attributes:
        cameras_root_dir: Root directory containing camera subdirectories (e.g., /mnt/cctv)
        ftp_subdirectory: Name of FTP subdirectory within each camera (e.g., "ftp")
        ftp_camera_dirs: List of specific FTP directories to monitor (legacy mode)
        target_dir: Root directory where sorted files will be placed (legacy mode)
        supported_extensions: List of file extensions to process
        retention_days: Number of days to keep files before deletion
        delete_source: Whether to delete source files after sorting
    """

    # New single-camera mode
    cameras_root_dir: Optional[str] = None
    ftp_subdirectory: str = "ftp"

    # Legacy multi-directory mode
    ftp_camera_dirs: List[str] = field(default_factory=list)
    target_dir: str = "/mnt/cctv"

    # Other settings
    supported_extensions: List[str] = field(
        default_factory=lambda: [".mp4", ".avi", ".jpg", ".jpeg", ".mkv"]
    )
    retention_days: int = 30
    delete_source: bool = True
    create_dummy_structure: bool = False

    def __post_init__(self):
        # Convert extensions to lowercase for comparison
        self.supported_extensions = [
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in self.supported_extensions
        ]

    def get_camera_directories(self) -> List[Tuple[Optional[str], str, str]]:
        """Get list of camera directories to process.

        Returns:
            List of tuples (camera_name, source_dir, target_dir)

        Example for single-camera mode:
            Input: cameras_root_dir="/mnt/cctv", ftp_subdirectory="ftp"
            Returns: [("garage-01", "/mnt/cctv/garage-01/ftp", "/mnt/cctv/garage-01"), ...]
        """
        cameras = []
        logger = logging.getLogger(__name__)

        # Single-camera mode: scan cameras_root_dir for camera subdirectories
        if self.cameras_root_dir:
            root_path = Path(self.cameras_root_dir)
            if root_path.exists():
                for camera_dir in root_path.iterdir():
                    if camera_dir.is_dir():
                        camera_name = camera_dir.name
                        ftp_dir = camera_dir / self.ftp_subdirectory
                        if ftp_dir.exists():
                            # Use FTP subdirectory as source
                            cameras.append((camera_name, str(ftp_dir), str(camera_dir)))
                        else:
                            # FTP subdirectory doesn't exist, use camera directory itself as source
                            # Files will be picked up from /mnt/cctv/garage-01/ directly
                            # and moved to /mnt/cctv/garage-01/2026/03/23/
                            cameras.append(
                                (camera_name, str(camera_dir), str(camera_dir))
                            )
            else:
                logger.warning(
                    f"Cameras root directory does not exist: {self.cameras_root_dir}"
                )

        # Legacy mode: use ftp_camera_dirs
        for ftp_dir in self.ftp_camera_dirs:
            # For legacy mode, try to extract camera name from the path
            # or use the target_dir as specified
            cameras.append((None, ftp_dir, self.target_dir))

        return cameras


class FileSorter:
    """Sorts files from FTP directories to date-based structure."""

    def __init__(self, config: SortingConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)

    def parse_filename(
        self, filename: str, source_path: Path
    ) -> Optional[ParsedFilename]:
        """Parse a filename to extract camera name and date components.

        This method uses a two-step approach:
        1. Find the date pattern (14 digits: YYYYMMDDHHMMSS)
        2. Extract camera name from everything before the date
        3. Check for optional _00_ separator

        Example:
            garage-01_00_20260323182654.mp4 -> camera_name="garage-01", year=2026, month=03, etc.
            garage-01_20260323182654.mp4 -> camera_name="garage-01", year=2026, month=03, etc.

        Args:
            filename: The filename to parse
            source_path: Full path to the source file

        Returns:
            ParsedFilename object if successful, None if parsing fails
        """
        # Step 1: Find the date pattern (YYYYMMDDhhmmss) - 14 digits
        date_pattern = r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
        date_match = re.search(date_pattern, filename)

        if not date_match:
            self.logger.debug(f"No date pattern found in filename: {filename}")
            return None

        date_start = date_match.start()
        year, month, day, hour, minute, second = date_match.groups()

        # Step 2: Check for valid extension
        ext_match = re.search(
            r"\.({})$".format(
                "|".join(ext.lstrip(".") for ext in self.config.supported_extensions)
            ),
            filename,
            re.IGNORECASE,
        )
        if not ext_match:
            self.logger.debug(f"No valid extension found in filename: {filename}")
            return None

        extension = ext_match.group(1).lower()

        # Step 3: Extract camera name from prefix (everything before date)
        prefix = filename[:date_start]

        # Step 4: Handle _00_ or _00 separator
        if prefix.endswith("_00_"):
            camera_name = prefix[:-4]  # Remove trailing _00_
        elif prefix.endswith("_00"):
            camera_name = prefix[:-3]  # Remove trailing _00
        elif prefix.endswith("_"):
            camera_name = prefix[:-1]  # Remove trailing underscore
        else:
            camera_name = prefix

        # Validate camera name
        if not camera_name:
            self.logger.debug(f"No camera name found in filename: {filename}")
            return None

        return ParsedFilename(
            camera_name=camera_name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=second,
            extension=extension,
            original_filename=filename,
            source_path=source_path,
        )

    def get_target_path(self, parsed: ParsedFilename, target_base: str) -> Path:
        """Generate the target path for a parsed filename.

        Args:
            parsed: ParsedFilename object
            target_base: Base directory for this camera (e.g., /mnt/cctv/garage-01)

        Returns:
            Path object representing the target location
        """
        return Path(
            target_base,
            parsed.year,
            parsed.month,
            parsed.day,
            parsed.original_filename,
        )

    def should_delete_file(self, file_path: Path) -> bool:
        """Determine if a file should be deleted based on retention policy.

        Args:
            file_path: Path to the file

        Returns:
            True if file should be deleted, False otherwise
        """
        if not file_path.exists():
            return False

        file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
        cutoff_date = datetime.now() - timedelta(days=self.config.retention_days)

        return file_time < cutoff_date

    def is_supported_file(self, filename: str) -> bool:
        """Check if file has supported extension.

        Args:
            filename: Filename to check

        Returns:
            True if extension is supported
        """
        ext = Path(filename).suffix.lower()
        return ext in self.config.supported_extensions

    def scan_directory(self, directory: str) -> List[Tuple[Path, str]]:
        """Scan a directory for files to process.

        Args:
            directory: Directory to scan

        Returns:
            List of tuples (full_path, filename)
        """
        files = []
        dir_path = Path(directory)

        if not dir_path.exists():
            self.logger.warning(f"Directory does not exist: {directory}")
            return files

        try:
            for file_path in dir_path.iterdir():
                if file_path.is_file() and self.is_supported_file(file_path.name):
                    files.append((file_path, file_path.name))
        except Exception as e:
            self.logger.error(f"Error scanning directory {directory}: {e}")

        return files

    def move_file(self, source: Path, target: Path) -> bool:
        """Move a file from source to target.

        Args:
            source: Source file path
            target: Target file path

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create target directory if it doesn't exist
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o1777)

            # Move the file
            shutil.move(str(source), str(target))
            self.logger.info(f"Moved: {source} -> {target}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to move {source} to {target}: {e}")
            return False

    def delete_old_files_in_dir(self, directory: str) -> int:
        """Delete files older than retention_days in a specific directory.

        Args:
            directory: Directory to clean up

        Returns:
            Number of files deleted
        """
        deleted_count = 0
        target_path = Path(directory)

        if not target_path.exists():
            return deleted_count

        for root, dirs, files in os.walk(target_path):
            for filename in files:
                file_path = Path(root, filename)

                # Check if file should be deleted
                if self.should_delete_file(file_path):
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        self.logger.info(f"Deleted old file: {file_path}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete {file_path}: {e}")

        # Clean up empty directories
        self._cleanup_empty_dirs(target_path)

        return deleted_count

    def _cleanup_empty_dirs(self, directory: Path) -> None:
        """Remove empty directories recursively."""
        for root, dirs, files in os.walk(str(directory), topdown=False):
            for dir_name in dirs:
                dir_path = Path(root, dir_name)
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        self.logger.debug(f"Removed empty directory: {dir_path}")
                except Exception as e:
                    self.logger.debug(f"Could not remove directory {dir_path}: {e}")

    def sort_files(self) -> Dict[str, int]:
        """Main sorting operation.

        Processes all configured camera FTP directories, parsing filenames and
        moving files to appropriate date-based directories within each camera's folder.

        Returns:
            Dictionary with statistics:
            - 'processed': Number of files successfully processed
            - 'failed': Number of files that failed to process
            - 'skipped': Number of files skipped (unsupported or unparsable)
            - 'deleted': Number of old files deleted
        """
        stats = {"processed": 0, "failed": 0, "skipped": 0, "deleted": 0}

        # Get all camera directories to process
        camera_dirs = self.config.get_camera_directories()

        if not camera_dirs:
            self.logger.warning("No camera directories found to process")
            return stats

        # Process each camera
        for camera_name, ftp_dir, target_dir in camera_dirs:
            self.logger.info(
                f"Processing camera: {camera_name or 'unknown'} from {ftp_dir}"
            )

            # First, delete old files in this camera's target directory
            deleted = self.delete_old_files_in_dir(target_dir)
            stats["deleted"] += deleted

            files = self.scan_directory(ftp_dir)
            self.logger.info(f"Found {len(files)} files to process")

            for file_path, filename in files:
                # Parse filename
                parsed = self.parse_filename(filename, file_path)

                if not parsed:
                    self.logger.debug(f"Skipping unparsable file: {filename}")
                    stats["skipped"] += 1
                    continue

                # Determine target path (within the same camera directory)
                target_path = self.get_target_path(parsed, target_dir)

                # Move the file
                if self.move_file(file_path, target_path):
                    stats["processed"] += 1
                else:
                    stats["failed"] += 1

        return stats


# Convenience functions for common use cases
def run_sorter(config: SortingConfig) -> Dict[str, int]:
    """Run the file sorter with the given configuration.

    Args:
        config: Sorting configuration

    Returns:
        Statistics dictionary
    """
    sorter = FileSorter(config)
    return sorter.sort_files()


if __name__ == "__main__":
    # Example standalone usage for your specific setup
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s: %(message)s"
    )

    # Configuration for your setup:
    # /mnt/cctv/
    #   garage-01/
    #     ftp/              <- FTP files here
    #     2026/03/23/       <- Sorted files here
    config = SortingConfig(
        cameras_root_dir="/mnt/cctv",
        ftp_subdirectory="ftp",  # Name of the FTP subdirectory in each camera folder
        supported_extensions=[".mp4", ".avi", ".jpg", ".mkv"],
        retention_days=30,
        delete_source=True,
    )

    # Run sorter
    stats = run_sorter(config)
    print(f"\nSorting complete!")
    print(f"  Processed: {stats['processed']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Deleted: {stats['deleted']}")
