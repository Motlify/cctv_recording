#!/usr/bin/env python3
"""
Tests for the FTP File Sorter Module

These tests create a temporary directory structure with dummy files
matching the Hikvision FTP format and verify the sorting logic works
correctly without requiring external configuration.

Run with: pytest test_ftp_sorter.py -v
"""

import os
import pytest
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Generator

from ftp_sorter import (
    FileSorter,
    SortingConfig,
    ParsedFilename,
    FilenamePatterns,
    run_sorter,
    create_hikvision_sorter,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for testing."""
    temp_path = Path(tempfile.mkdtemp(prefix="cctv_test_"))
    yield temp_path
    # Cleanup after test
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def ftp_structure(temp_dir: Path) -> Path:
    """Create a realistic FTP directory structure with dummy files.

    Structure:
    /tmp/cctv_test_xxx/
        ftp_camera1/
            garage-01_00_20260323182654.mp4
            garage-01_00_20260323184122.mp4
            garage-01_00_20260323190215.avi
            front-01_00_20260324083015.mp4
            front-01_00_20260324084530.mp4
            side-01_00_20260325071500.jpg
            invalid_file.txt
            unsupported.xyz
            malformed_no_date.mp4
        ftp_camera2/
            back-01_00_20260401120000.mp4
            back-01_00_20260401121530.mp4
            doorbell_00_20260402080000.mp4
    """
    # Create FTP directories
    ftp_dir1 = temp_dir / "ftp_camera1"
    ftp_dir2 = temp_dir / "ftp_camera2"
    ftp_dir1.mkdir()
    ftp_dir2.mkdir()

    # Define test files with their expected parsed values
    test_files = [
        # (filename, expected_camera, expected_year, expected_month, expected_day)
        ("garage-01_00_20260323182654.mp4", "garage-01", "2026", "03", "23"),
        ("garage-01_00_20260323184122.mp4", "garage-01", "2026", "03", "23"),
        ("garage-01_00_20260323190215.avi", "garage-01", "2026", "03", "23"),
        ("front-01_00_20260324083015.mp4", "front-01", "2026", "03", "24"),
        ("front-01_00_20260324084530.mp4", "front-01", "2026", "03", "24"),
        ("side-01_00_20260325071500.jpg", "side-01", "2026", "03", "25"),
    ]

    # Create files in ftp_camera1
    for filename, _, _, _, _ in test_files:
        (ftp_dir1 / filename).touch()
        # Set modification time to match filename date
        # Extract date from filename: 20260323182654 -> 2026-03-23
        date_str = filename.split("_")[-1].split(".")[0][:8]
        year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
        file_time = datetime(int(year), int(month), int(day), 12, 0, 0)
        os.utime(ftp_dir1 / filename, (file_time.timestamp(), file_time.timestamp()))

    # Create files in ftp_camera2
    test_files2 = [
        ("back-01_00_20260401120000.mp4", "back-01", "2026", "04", "01"),
        ("back-01_00_20260401121530.mp4", "back-01", "2026", "04", "01"),
        ("doorbell_00_20260402080000.mp4", "doorbell", "2026", "04", "02"),
    ]

    for filename, _, _, _, _ in test_files2:
        (ftp_dir2 / filename).touch()
        date_str = filename.split("_")[-1].split(".")[0][:8]
        year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
        file_time = datetime(int(year), int(month), int(day), 12, 0, 0)
        os.utime(ftp_dir2 / filename, (file_time.timestamp(), file_time.timestamp()))

    # Create invalid/unprocessed files
    (ftp_dir1 / "invalid_file.txt").touch()
    (ftp_dir1 / "unsupported.xyz").touch()
    (ftp_dir1 / "malformed_no_date.mp4").touch()

    return temp_dir


@pytest.fixture
def old_files_structure(temp_dir: Path) -> Path:
    """Create directory structure with old files for retention testing."""
    # Create camera directory structure with old files
    old_date = datetime.now() - timedelta(days=60)

    camera_dir = (
        temp_dir
        / "sorted"
        / "garage-01"
        / str(old_date.year)
        / f"{old_date.month:02d}"
        / f"{old_date.day:02d}"
    )
    camera_dir.mkdir(parents=True)

    # Create old file
    old_file = camera_dir / "garage-01_00_20250101120000.mp4"
    old_file.touch()
    os.utime(old_file, (old_date.timestamp(), old_date.timestamp()))

    # Create recent file (should not be deleted)
    recent_date = datetime.now() - timedelta(days=5)
    recent_file = camera_dir / "garage-01_00_20260401120000.mp4"
    recent_file.touch()
    os.utime(recent_file, (recent_date.timestamp(), recent_date.timestamp()))

    return temp_dir


# =============================================================================
# Test Cases
# =============================================================================


class TestFilenameParsing:
    """Test filename parsing with various patterns."""

    def test_hikvision_pattern_valid(self):
        """Test parsing valid Hikvision FTP filenames."""
        config = SortingConfig(filename_pattern=FilenamePatterns.HIKVISION_FTP)
        sorter = FileSorter(config)

        test_cases = [
            (
                "garage-01_00_20260323182654.mp4",
                "garage-01",
                "2026",
                "03",
                "23",
                "18",
                "26",
                "54",
                "mp4",
            ),
            (
                "front_00_20260324083015.avi",
                "front",
                "2026",
                "03",
                "24",
                "08",
                "30",
                "15",
                "avi",
            ),
            (
                "back-01_00_20260401120000.mkv",
                "back-01",
                "2026",
                "04",
                "01",
                "12",
                "00",
                "00",
                "mkv",
            ),
            (
                "side-01_00_20260325071500.jpg",
                "side-01",
                "2026",
                "03",
                "25",
                "07",
                "15",
                "00",
                "jpg",
            ),
        ]

        for (
            filename,
            expected_camera,
            year,
            month,
            day,
            hour,
            minute,
            second,
            ext,
        ) in test_cases:
            parsed = sorter.parse_filename(filename, Path("/tmp") / filename)
            assert parsed is not None, f"Failed to parse: {filename}"
            assert parsed.camera_name == expected_camera
            assert parsed.year == year
            assert parsed.month == month
            assert parsed.day == day
            assert parsed.hour == hour
            assert parsed.minute == minute
            assert parsed.second == second
            assert parsed.extension == ext

    def test_hikvision_pattern_without_spacing(self):
        """Test parsing filenames without the _00_ spacing."""
        config = SortingConfig(filename_pattern=FilenamePatterns.HIKVISION_FTP)
        sorter = FileSorter(config)

        # Pattern should also work without _00_
        filename = "garage-01_20260323182654.mp4"
        parsed = sorter.parse_filename(filename, Path("/tmp") / filename)
        assert parsed is not None
        assert parsed.camera_name == "garage-01"

    def test_invalid_filenames(self):
        """Test that invalid filenames return None."""
        config = SortingConfig(filename_pattern=FilenamePatterns.HIKVISION_FTP)
        sorter = FileSorter(config)

        invalid_filenames = [
            "malformed_no_date.mp4",
            "no_camera_name_20260323182654.mp4",
            "garage-01_no_numbers.mp4",
            "garage-01_00_20260323.mp4",  # Missing time
            "garage-01_00_ABCD0323182654.mp4",  # Non-numeric date
            "garage-01_00_20260323182654",  # No extension
        ]

        for filename in invalid_filenames:
            parsed = sorter.parse_filename(filename, Path("/tmp") / filename)
            assert parsed is None, f"Should not parse: {filename}"

    def test_dash_date_pattern(self):
        """Test parsing dash-separated date format."""
        config = SortingConfig(filename_pattern=FilenamePatterns.DASH_DATE)
        sorter = FileSorter(config)

        filename = "camera_front_2026-03-23_18-26-54.mp4"
        parsed = sorter.parse_filename(filename, Path("/tmp") / filename)

        assert parsed is not None
        assert parsed.camera_name == "camera_front"
        assert parsed.year == "2026"
        assert parsed.month == "03"
        assert parsed.day == "23"
        assert parsed.hour == "18"
        assert parsed.minute == "26"
        assert parsed.second == "54"


class TestFileOperations:
    """Test file moving and sorting operations."""

    def test_get_target_path(self):
        """Test target path generation."""
        config = SortingConfig(
            target_dir="/mnt/cctv", filename_pattern=FilenamePatterns.HIKVISION_FTP
        )
        sorter = FileSorter(config)

        parsed = ParsedFilename(
            camera_name="garage-01",
            year="2026",
            month="03",
            day="23",
            hour="18",
            minute="26",
            second="54",
            extension="mp4",
            original_filename="garage-01_00_20260323182654.mp4",
            source_path=Path("/ftp/garage-01_00_20260323182654.mp4"),
        )

        target = sorter.get_target_path(parsed)
        expected = Path(
            "/mnt/cctv/garage-01/2026/03/23/garage-01_00_20260323182654.mp4"
        )
        assert target == expected

    def test_scan_directory(self, ftp_structure: Path):
        """Test directory scanning for supported files."""
        ftp_dir1 = ftp_structure / "ftp_camera1"

        config = SortingConfig(
            ftp_camera_dirs=[str(ftp_dir1)],
            supported_extensions=[".mp4", ".avi", ".jpg"],
        )
        sorter = FileSorter(config)

        files = sorter.scan_directory(str(ftp_dir1))
        filenames = [f[1] for f in files]

        # Should find all supported files
        assert "garage-01_00_20260323182654.mp4" in filenames
        assert "garage-01_00_20260323190215.avi" in filenames
        assert "side-01_00_20260325071500.jpg" in filenames

        # Should not find unsupported files
        assert "invalid_file.txt" not in filenames
        assert "unsupported.xyz" not in filenames

    def test_is_supported_file(self):
        """Test file extension support check."""
        config = SortingConfig(supported_extensions=[".mp4", ".avi"])
        sorter = FileSorter(config)

        assert sorter.is_supported_file("video.mp4") is True
        assert sorter.is_supported_file("video.MP4") is True
        assert sorter.is_supported_file("video.avi") is True
        assert sorter.is_supported_file("video.jpg") is False
        assert sorter.is_supported_file("video.txt") is False

    def test_move_file(self, temp_dir: Path):
        """Test file moving operation."""
        source = temp_dir / "source.mp4"
        target = temp_dir / "target" / "camera" / "2026" / "03" / "23" / "source.mp4"

        source.touch()

        config = SortingConfig()
        sorter = FileSorter(config)

        result = sorter.move_file(source, target)

        assert result is True
        assert target.exists() is True
        assert source.exists() is False


class TestRetentionPolicy:
    """Test file retention and deletion logic."""

    def test_should_delete_old_file(self, temp_dir: Path):
        """Test detection of old files for deletion."""
        # Create old file
        old_date = datetime.now() - timedelta(days=60)
        old_file = temp_dir / "old.mp4"
        old_file.touch()
        os.utime(old_file, (old_date.timestamp(), old_date.timestamp()))

        config = SortingConfig(retention_days=30)
        sorter = FileSorter(config)

        assert sorter.should_delete_file(old_file) is True

    def test_should_not_delete_recent_file(self, temp_dir: Path):
        """Test that recent files are not deleted."""
        # Create recent file
        recent_date = datetime.now() - timedelta(days=5)
        recent_file = temp_dir / "recent.mp4"
        recent_file.touch()
        os.utime(recent_file, (recent_date.timestamp(), recent_date.timestamp()))

        config = SortingConfig(retention_days=30)
        sorter = FileSorter(config)

        assert sorter.should_delete_file(recent_file) is False

    def test_delete_old_files(self, old_files_structure: Path):
        """Test old file deletion process."""
        config = SortingConfig(
            target_dir=str(old_files_structure / "sorted"), retention_days=30
        )
        sorter = FileSorter(config)

        deleted_count = sorter.delete_old_files()

        # Should delete the old file
        assert deleted_count == 1

        # Old file should be gone
        old_file = (
            old_files_structure
            / "sorted"
            / "garage-01"
            / "2025"
            / "01"
            / "01"
            / "garage-01_00_20250101120000.mp4"
        )
        assert old_file.exists() is False

        # Recent file should remain
        recent_file = (
            old_files_structure
            / "sorted"
            / "garage-01"
            / "2026"
            / "04"
            / "01"
            / "garage-01_00_20260401120000.mp4"
        )
        assert recent_file.exists() is True


class TestIntegration:
    """Integration tests with full sorting workflow."""

    def test_full_sort_workflow(self, ftp_structure: Path):
        """Test complete file sorting workflow."""
        ftp_dir1 = ftp_structure / "ftp_camera1"
        ftp_dir2 = ftp_structure / "ftp_camera2"
        target_dir = ftp_structure / "sorted"

        config = SortingConfig(
            ftp_camera_dirs=[str(ftp_dir1), str(ftp_dir2)],
            target_dir=str(target_dir),
            filename_pattern=FilenamePatterns.HIKVISION_FTP,
            supported_extensions=[".mp4", ".avi", ".jpg"],
            retention_days=30,
            delete_source=True,
        )

        sorter = FileSorter(config)
        stats = sorter.sort_files()

        # Verify statistics
        assert stats["processed"] == 9  # All valid files from both dirs
        assert stats["skipped"] == 1  # malformed_no_date.mp4

        # Verify files are in correct locations
        # garage-01 files
        assert (
            target_dir
            / "garage-01"
            / "2026"
            / "03"
            / "23"
            / "garage-01_00_20260323182654.mp4"
        ).exists()
        assert (
            target_dir
            / "garage-01"
            / "2026"
            / "03"
            / "23"
            / "garage-01_00_20260323190215.avi"
        ).exists()

        # front-01 files
        assert (
            target_dir
            / "front-01"
            / "2026"
            / "03"
            / "24"
            / "front-01_00_20260324083015.mp4"
        ).exists()

        # side-01 files
        assert (
            target_dir
            / "side-01"
            / "2026"
            / "03"
            / "25"
            / "side-01_00_20260325071500.jpg"
        ).exists()

        # back-01 files
        assert (
            target_dir
            / "back-01"
            / "2026"
            / "04"
            / "01"
            / "back-01_00_20260401120000.mp4"
        ).exists()

        # doorbell files
        assert (
            target_dir
            / "doorbell"
            / "2026"
            / "04"
            / "02"
            / "doorbell_00_20260402080000.mp4"
        ).exists()

        # Verify source files are deleted
        assert not (ftp_dir1 / "garage-01_00_20260323182654.mp4").exists()
        assert not (ftp_dir1 / "garage-01_00_20260323184122.mp4").exists()

        # Unsupported files should remain
        assert (ftp_dir1 / "invalid_file.txt").exists()
        assert (ftp_dir1 / "unsupported.xyz").exists()

    def test_run_sorter_convenience_function(self, ftp_structure: Path):
        """Test the run_sorter convenience function."""
        ftp_dir = ftp_structure / "ftp_camera1"
        target_dir = ftp_structure / "output"

        config = SortingConfig(
            ftp_camera_dirs=[str(ftp_dir)],
            target_dir=str(target_dir),
            filename_pattern=FilenamePatterns.HIKVISION_FTP,
            delete_source=False,  # Keep source for verification
        )

        stats = run_sorter(config)

        assert stats["processed"] == 6
        assert (
            target_dir
            / "garage-01"
            / "2026"
            / "03"
            / "23"
            / "garage-01_00_20260323182654.mp4"
        ).exists()

        # Source should still exist
        assert (ftp_dir / "garage-01_00_20260323182654.mp4").exists()

    def test_create_hikvision_sorter(self, ftp_structure: Path):
        """Test the create_hikvision_sorter factory function."""
        ftp_dir = ftp_structure / "ftp_camera1"
        target_dir = ftp_structure / "hik_output"

        sorter = create_hikvision_sorter(
            ftp_dirs=[str(ftp_dir)], target_dir=str(target_dir), retention_days=30
        )

        stats = sorter.sort_files()

        assert stats["processed"] == 6
        assert isinstance(sorter, FileSorter)


class TestParsedFilename:
    """Test ParsedFilename named tuple functionality."""

    def test_date_path_property(self):
        """Test the date_path property."""
        parsed = ParsedFilename(
            camera_name="garage-01",
            year="2026",
            month="03",
            day="23",
            hour="18",
            minute="26",
            second="54",
            extension="mp4",
            original_filename="test.mp4",
            source_path=Path("/tmp/test.mp4"),
        )

        assert parsed.date_path == "2026/03/23"

    def test_timestamp_property(self):
        """Test the timestamp property."""
        parsed = ParsedFilename(
            camera_name="garage-01",
            year="2026",
            month="03",
            day="23",
            hour="18",
            minute="26",
            second="54",
            extension="mp4",
            original_filename="test.mp4",
            source_path=Path("/tmp/test.mp4"),
        )

        ts = parsed.timestamp
        assert ts.year == 2026
        assert ts.month == 3
        assert ts.day == 23
        assert ts.hour == 18
        assert ts.minute == 26
        assert ts.second == 54


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_scan_nonexistent_directory(self, temp_dir: Path):
        """Test scanning a non-existent directory."""
        config = SortingConfig()
        sorter = FileSorter(config)

        files = sorter.scan_directory("/nonexistent/path")
        assert files == []

    def test_move_nonexistent_file(self, temp_dir: Path):
        """Test moving a non-existent file."""
        source = temp_dir / "does_not_exist.mp4"
        target = temp_dir / "target.mp4"

        config = SortingConfig()
        sorter = FileSorter(config)

        result = sorter.move_file(source, target)
        assert result is False

    def test_custom_pattern(self, temp_dir: Path):
        """Test using a custom regex pattern."""
        # Custom pattern: CAM_YYYYMMDD_HHMMSS.ext
        custom_pattern = r"(?P<camera_name>[A-Z]+)_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.(?P<ext>mp4)"

        config = SortingConfig(filename_pattern=custom_pattern)
        sorter = FileSorter(config)

        filename = "GARAGE_20260323_182654.mp4"
        parsed = sorter.parse_filename(filename, temp_dir / filename)

        assert parsed is not None
        assert parsed.camera_name == "GARAGE"
        assert parsed.year == "2026"
        assert parsed.month == "03"
        assert parsed.day == "23"


# =============================================================================
# Example Usage Test
# =============================================================================


def test_example_usage():
    """Test the example usage from the module docstring."""
    # Create temporary directories
    with tempfile.TemporaryDirectory() as tmpdir:
        ftp_dir = Path(tmpdir) / "ftp"
        target_dir = Path(tmpdir) / "sorted"
        ftp_dir.mkdir()
        target_dir.mkdir()

        # Create some test files
        (ftp_dir / "garage-01_00_20260323182654.mp4").touch()
        (ftp_dir / "front-01_00_20260324083015.mp4").touch()

        # Use the module as documented
        config = SortingConfig(
            ftp_camera_dirs=[str(ftp_dir)],
            target_dir=str(target_dir),
            filename_pattern=FilenamePatterns.HIKVISION_FTP,
            retention_days=30,
            delete_source=True,
        )

        stats = run_sorter(config)

        assert stats["processed"] == 2
        assert (
            target_dir
            / "garage-01"
            / "2026"
            / "03"
            / "23"
            / "garage-01_00_20260323182654.mp4"
        ).exists()
        assert (
            target_dir
            / "front-01"
            / "2026"
            / "03"
            / "24"
            / "front-01_00_20260324083015.mp4"
        ).exists()


if __name__ == "__main__":
    # Run pytest if available, otherwise run basic tests
    pytest.main([__file__, "-v"])
