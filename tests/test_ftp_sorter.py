#!/usr/bin/env python3
"""
Standalone Tests for the FTP File Sorter Module

This test file doesn't require pytest and can be run directly:
    python test_ftp_sorter_standalone.py

It creates a temporary directory structure with dummy files matching
the Hikvision FTP format and verifies the sorting logic works correctly.
"""

import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cctv_recording.ftp_sorter import (
    FileSorter,
    SortingConfig,
    ParsedFilename,
    run_sorter,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s: %(message)s"
)
logger = logging.getLogger(__name__)


class TestRunner:
    """Simple test runner that doesn't require pytest."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests_run = []

    def test(self, name):
        """Decorator for test functions."""

        def decorator(func):
            def wrapper(*args, **kwargs):
                try:
                    func(*args, **kwargs)
                    self.passed += 1
                    self.tests_run.append((name, True, None))
                    print(f"  ✓ {name}")
                except AssertionError as e:
                    self.failed += 1
                    self.tests_run.append((name, False, str(e)))
                    print(f"  ✗ {name}: {e}")
                except Exception as e:
                    self.failed += 1
                    self.tests_run.append((name, False, str(e)))
                    print(f"  ✗ {name}: {e}")

            return wrapper

        return decorator

    def report(self):
        """Print test summary."""
        print(f"\n{'=' * 60}")
        print(f"Tests Run: {self.passed + self.failed}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"{'=' * 60}")

        if self.failed > 0:
            print("\nFailed Tests:")
            for name, passed, error in self.tests_run:
                if not passed:
                    print(f"  - {name}: {error}")

        return self.failed == 0


def create_test_ftp_structure(base_dir: Path):
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
    ftp_dir1 = base_dir / "ftp_camera1"
    ftp_dir2 = base_dir / "ftp_camera2"
    ftp_dir1.mkdir()
    ftp_dir2.mkdir()

    # Define test files for ftp_camera1
    test_files1 = [
        ("garage-01_00_20260323182654.mp4", "garage-01", "2026", "03", "23"),
        ("garage-01_00_20260323184122.mp4", "garage-01", "2026", "03", "23"),
        ("garage-01_00_20260323190215.avi", "garage-01", "2026", "03", "23"),
        ("front-01_00_20260324083015.mp4", "front-01", "2026", "03", "24"),
        ("front-01_00_20260324084530.mp4", "front-01", "2026", "03", "24"),
        ("side-01_00_20260325071500.jpg", "side-01", "2026", "03", "25"),
    ]

    for filename, _, _, _, _ in test_files1:
        (ftp_dir1 / filename).touch()
        # Set modification time to match filename date
        date_str = filename.split("_")[-1].split(".")[0][:8]
        year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
        file_time = datetime(int(year), int(month), int(day), 12, 0, 0)
        os.utime(ftp_dir1 / filename, (file_time.timestamp(), file_time.timestamp()))

    # Create invalid/unprocessed files
    (ftp_dir1 / "invalid_file.txt").touch()
    (ftp_dir1 / "unsupported.xyz").touch()
    (ftp_dir1 / "malformed_no_date.mp4").touch()

    # Define test files for ftp_camera2
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

    return ftp_dir1, ftp_dir2


def main():
    """Run all tests."""
    runner = TestRunner()

    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp(prefix="cctv_test_"))
    logger.info(f"Created test directory: {temp_dir}")

    try:
        # Create test structure
        ftp_dir1, ftp_dir2 = create_test_ftp_structure(temp_dir)
        target_dir = temp_dir / "sorted"
        target_dir.mkdir()

        # =====================================================================
        # TEST 1: Filename Parsing - Hikvision Pattern
        # =====================================================================
        @runner.test("Test Hikvision pattern valid filenames")
        def test_hikvision_pattern():
            config = SortingConfig()
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
                # Additional camera name formats
                (
                    "front-cam_00_20260323182654.mp4",
                    "front-cam",
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
                ),
                (
                    "camera_001_00_20260323182654.mp4",
                    "camera_001",
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
                ),
                (
                    "backyard-cam_20260323182654.mp4",  # without _00_
                    "backyard-cam",
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
                ),
                # Edge cases with multiple _00_ in filename
                (
                    "garage-01_00__00_20260323182654.mp4",  # _00__00_ - should split by last
                    "garage-01_00_",  # keeps first _00_, removes last
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
                ),
                (
                    "cam_00_test_00_20260323182654.mp4",  # _00_ in middle and before date
                    "cam_00_test",  # removes last _00_ only
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
                ),
                (
                    "Driveway_East_00_20260323182654.mp4",
                    "Driveway_East",
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
                ),
                (
                    "entrance-north_00_20260323182654.mp4",
                    "entrance-north",
                    "2026",
                    "03",
                    "23",
                    "18",
                    "26",
                    "54",
                    "mp4",
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
                assert parsed.camera_name == expected_camera, (
                    f"Camera mismatch for {filename}"
                )
                assert parsed.year == year, f"Year mismatch for {filename}"
                assert parsed.month == month, f"Month mismatch for {filename}"
                assert parsed.day == day, f"Day mismatch for {filename}"
                assert parsed.hour == hour, f"Hour mismatch for {filename}"
                assert parsed.minute == minute, f"Minute mismatch for {filename}"
                assert parsed.second == second, f"Second mismatch for {filename}"
                assert parsed.extension == ext, f"Extension mismatch for {filename}"

        test_hikvision_pattern()

        # =====================================================================
        # TEST 2: Filename Parsing - Invalid Filenames
        # =====================================================================
        @runner.test("Test invalid filenames are rejected")
        def test_invalid_filenames():
            config = SortingConfig()
            sorter = FileSorter(config)

            invalid_filenames = [
                "malformed_no_date.mp4",
                "garage-01_no_numbers.mp4",
                "garage-01_00_20260323.mp4",  # Missing time
                "garage-01_00_20260323182654",  # No extension
                "20260323182654.mp4",  # No camera name
            ]

            for filename in invalid_filenames:
                parsed = sorter.parse_filename(filename, Path("/tmp") / filename)
                assert parsed is None, f"Should not parse: {filename}"

        test_invalid_filenames()

        # =====================================================================
        # TEST 3: Target Path Generation
        # =====================================================================
        @runner.test("Test target path generation")
        def test_target_path():
            config = SortingConfig()
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
                source_path=ftp_dir1 / "garage-01_00_20260323182654.mp4",
            )

            # New signature: get_target_path(parsed, target_base)
            target_base = target_dir / "garage-01"
            target = sorter.get_target_path(parsed, str(target_base))
            expected = (
                target_dir
                / "garage-01"
                / "2026"
                / "03"
                / "23"
                / "garage-01_00_20260323182654.mp4"
            )
            assert target == expected, f"Expected {expected}, got {target}"

        test_target_path()

        # =====================================================================
        # TEST 4: Directory Scanning
        # =====================================================================
        @runner.test("Test directory scanning for supported files")
        def test_scan_directory():
            config = SortingConfig(supported_extensions=[".mp4", ".avi", ".jpg"])
            sorter = FileSorter(config)

            files = sorter.scan_directory(str(ftp_dir1))
            filenames = [f[1] for f in files]

            assert "garage-01_00_20260323182654.mp4" in filenames, (
                "Should find MP4 files"
            )
            assert "garage-01_00_20260323190215.avi" in filenames, (
                "Should find AVI files"
            )
            assert "side-01_00_20260325071500.jpg" in filenames, "Should find JPG files"
            assert "invalid_file.txt" not in filenames, "Should not find TXT files"
            assert "unsupported.xyz" not in filenames, "Should not find XYZ files"

        test_scan_directory()

        # =====================================================================
        # TEST 5: File Extension Support Check
        # =====================================================================
        @runner.test("Test file extension support")
        def test_extension_support():
            config = SortingConfig(supported_extensions=[".mp4", ".avi"])
            sorter = FileSorter(config)

            assert sorter.is_supported_file("video.mp4") is True, "Should support .mp4"
            assert sorter.is_supported_file("video.MP4") is True, (
                "Should support .MP4 (case insensitive)"
            )
            assert sorter.is_supported_file("video.avi") is True, "Should support .avi"
            assert sorter.is_supported_file("video.jpg") is False, (
                "Should not support .jpg"
            )
            assert sorter.is_supported_file("video.txt") is False, (
                "Should not support .txt"
            )

        test_extension_support()

        # =====================================================================
        # TEST 6: Full Sorting Workflow
        # =====================================================================
        @runner.test("Test full sorting workflow")
        def test_full_workflow():
            config = SortingConfig(
                ftp_camera_dirs=[str(ftp_dir1), str(ftp_dir2)],
                target_dir=str(target_dir),
                supported_extensions=[".mp4", ".avi", ".jpg"],
                retention_days=30,
                delete_source=True,
            )

            sorter = FileSorter(config)
            stats = sorter.sort_files()

            # Verify statistics
            assert stats["processed"] == 9, (
                f"Expected 9 processed, got {stats['processed']}"
            )
            assert stats["skipped"] == 1, f"Expected 1 skipped, got {stats['skipped']}"

            # In legacy mode, files go to target_dir/year/month/day/ (no camera subdir)
            # Verify files are in correct locations
            assert (
                target_dir / "2026" / "03" / "23" / "garage-01_00_20260323182654.mp4"
            ).exists()
            assert (
                target_dir / "2026" / "03" / "23" / "garage-01_00_20260323190215.avi"
            ).exists()
            assert (
                target_dir / "2026" / "03" / "24" / "front-01_00_20260324083015.mp4"
            ).exists()
            assert (
                target_dir / "2026" / "03" / "25" / "side-01_00_20260325071500.jpg"
            ).exists()
            assert (
                target_dir / "2026" / "04" / "01" / "back-01_00_20260401120000.mp4"
            ).exists()
            assert (
                target_dir / "2026" / "04" / "02" / "doorbell_00_20260402080000.mp4"
            ).exists()

            # Verify source files are deleted
            assert not (ftp_dir1 / "garage-01_00_20260323182654.mp4").exists()
            assert not (ftp_dir1 / "garage-01_00_20260323184122.mp4").exists()

            # Unsupported files should remain
            assert (ftp_dir1 / "invalid_file.txt").exists()
            assert (ftp_dir1 / "unsupported.xyz").exists()

        test_full_workflow()

        # =====================================================================
        # TEST 7: Retention Policy
        # =====================================================================
        @runner.test("Test retention policy - old files deleted")
        def test_retention():
            # Create old file
            old_dir = target_dir / "garage-01" / "2025" / "01" / "01"
            old_dir.mkdir(parents=True)
            old_file = old_dir / "garage-01_00_20250101120000.mp4"
            old_file.touch()
            old_date = datetime.now() - timedelta(days=60)
            os.utime(old_file, (old_date.timestamp(), old_date.timestamp()))

            # Create recent file
            recent_dir = target_dir / "garage-01" / "2026" / "04" / "01"
            recent_dir.mkdir(parents=True, exist_ok=True)
            recent_file = recent_dir / "garage-01_00_20260401120000.mp4"
            recent_file.touch()
            recent_date = datetime.now() - timedelta(days=5)
            os.utime(recent_file, (recent_date.timestamp(), recent_date.timestamp()))

            config = SortingConfig(target_dir=str(target_dir), retention_days=30)
            sorter = FileSorter(config)

            deleted_count = sorter.delete_old_files_in_dir(str(target_dir))

            assert deleted_count == 1, f"Expected 1 deleted, got {deleted_count}"
            assert not old_file.exists(), "Old file should be deleted"
            assert recent_file.exists(), "Recent file should remain"

        test_retention()

        # =====================================================================
        # TEST 8: Single-camera mode (your setup)
        # =====================================================================
        @runner.test("Test cameras_root_dir single-camera mode")
        def test_single_camera_mode():
            # Create structure like your setup:
            # /tmp/cameras/garage-01/ftp/
            cameras_root = temp_dir / "cameras_root"
            camera_dir = cameras_root / "garage-01"
            ftp_dir = camera_dir / "ftp"
            ftp_dir.mkdir(parents=True)

            # Create test files in FTP directory
            (ftp_dir / "garage-01_00_20260323182654.mp4").touch()
            (ftp_dir / "garage-01_00_20260323184122.mp4").touch()

            config = SortingConfig(
                cameras_root_dir=str(cameras_root),
                ftp_subdirectory="ftp",
                retention_days=30,
                delete_source=True,
            )

            sorter = FileSorter(config)
            stats = sorter.sort_files()

            assert stats["processed"] == 2, (
                f"Expected 2 processed, got {stats['processed']}"
            )
            # Files should be in /tmp/cameras_root/garage-01/2026/03/23/
            assert (
                camera_dir / "2026" / "03" / "23" / "garage-01_00_20260323182654.mp4"
            ).exists()
            assert (
                camera_dir / "2026" / "03" / "23" / "garage-01_00_20260323184122.mp4"
            ).exists()
            # Source files should be deleted
            assert not (ftp_dir / "garage-01_00_20260323182654.mp4").exists()

        test_single_camera_mode()

        # =====================================================================
        # TEST 8b: No FTP subdirectory - files in camera root
        # =====================================================================
        @runner.test("Test no FTP subdirectory - files in camera root")
        def test_no_ftp_subdirectory():
            """Test that files are picked up from camera directory when FTP subdir doesn't exist."""
            # Create structure without FTP subdirectory:
            # /tmp/cameras2/garage-01/          <- files here directly
            cameras_root = temp_dir / "cameras_root_no_ftp"
            camera_dir = cameras_root / "garage-01"
            camera_dir.mkdir(parents=True)

            # Create test files directly in camera directory (no ftp/ subdir)
            (camera_dir / "garage-01_00_20260323182654.mp4").touch()
            (camera_dir / "garage-01_00_20260323184122.mp4").touch()

            config = SortingConfig(
                cameras_root_dir=str(cameras_root),
                ftp_subdirectory="ftp",  # This subdir doesn't exist
                retention_days=30,
                delete_source=True,
            )

            sorter = FileSorter(config)
            stats = sorter.sort_files()

            assert stats["processed"] == 2, (
                f"Expected 2 processed, got {stats['processed']}"
            )
            # Files should be moved from /tmp/cameras2/garage-01/
            # to /tmp/cameras2/garage-01/2026/03/23/
            assert (
                camera_dir / "2026" / "03" / "23" / "garage-01_00_20260323182654.mp4"
            ).exists()
            assert (
                camera_dir / "2026" / "03" / "23" / "garage-01_00_20260323184122.mp4"
            ).exists()
            # Source files should be deleted from camera root
            assert not (camera_dir / "garage-01_00_20260323182654.mp4").exists()
            assert not (camera_dir / "garage-01_00_20260323184122.mp4").exists()

        test_no_ftp_subdirectory()

        # =====================================================================
        # TEST 8c: Various camera names end-to-end
        # =====================================================================
        @runner.test("Test various camera names end-to-end")
        def test_various_camera_names():
            """Test that different camera name formats work in the full workflow."""
            cameras_root = temp_dir / "cameras_various"

            # Create multiple cameras with different name formats
            camera_configs = [
                ("garage-01", "garage-01_00_20260323182654.mp4"),
                ("front-cam", "front-cam_00_20260323182654.mp4"),
                ("camera_001", "camera_001_00_20260323182654.mp4"),
                ("backyard-cam", "backyard-cam_20260323182654.mp4"),  # no _00_
                ("Driveway_East", "Driveway_East_00_20260323182654.mp4"),
                ("entrance-north", "entrance-north_00_20260323182654.mp4"),
            ]

            for camera_name, filename in camera_configs:
                camera_dir = cameras_root / camera_name
                camera_dir.mkdir(parents=True)
                (camera_dir / filename).touch()

            config = SortingConfig(
                cameras_root_dir=str(cameras_root),
                ftp_subdirectory="ftp",  # Doesn't exist, so uses camera root
                retention_days=30,
                delete_source=True,
            )

            sorter = FileSorter(config)
            stats = sorter.sort_files()

            # Should process all 6 cameras
            assert stats["processed"] == 6, (
                f"Expected 6 processed, got {stats['processed']}"
            )

            # Verify all files are in correct date directories
            for camera_name, filename in camera_configs:
                camera_dir = cameras_root / camera_name
                assert (camera_dir / "2026" / "03" / "23" / filename).exists(), (
                    f"File for {camera_name} should be sorted"
                )
                # Source file should be deleted
                assert not (camera_dir / filename).exists()

        test_various_camera_names()

        # =====================================================================
        # TEST 9: Date Path Property
        # =====================================================================
        @runner.test("Test ParsedFilename date_path property")
        def test_date_path():
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

            assert parsed.date_path == "2026/03/23", (
                f"Expected '2026/03/23', got '{parsed.date_path}'"
            )

        test_date_path()

        # =====================================================================
        # TEST 10: Timestamp Property
        # =====================================================================
        @runner.test("Test ParsedFilename timestamp property")
        def test_timestamp():
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
            assert ts.year == 2026, "Year should be 2026"
            assert ts.month == 3, "Month should be 3"
            assert ts.day == 23, "Day should be 23"
            assert ts.hour == 18, "Hour should be 18"
            assert ts.minute == 26, "Minute should be 26"
            assert ts.second == 54, "Second should be 54"

        test_timestamp()

        # =====================================================================
        # TEST 11: Dash Date Format Support
        # =====================================================================
        @runner.test("Test dash date format parsing")
        def test_dash_date():
            """Test that dash date format works with the parsing logic."""
            # The current parser looks for 14 consecutive digits (YYYYMMDDHHMMSS)
            # Standard format: camera_front_20260323182654.mp4 (no dashes)
            # The parser finds the first 14 digits it sees
            config = SortingConfig()
            sorter = FileSorter(config)

            # Standard format without dashes
            filename = "camera_front_20260323182654.mp4"
            parsed = sorter.parse_filename(filename, Path("/tmp") / filename)

            assert parsed is not None, f"Should parse filename: {filename}"
            assert parsed.camera_name == "camera_front", (
                f"Camera should be 'camera_front', got '{parsed.camera_name}'"
            )
            assert parsed.year == "2026", "Year should be 2026"
            assert parsed.month == "03", "Month should be 03"
            assert parsed.day == "23", "Day should be 23"
            assert parsed.hour == "18", "Hour should be 18"
            assert parsed.minute == "26", "Minute should be 26"
            assert parsed.second == "54", "Second should be 54"

        test_dash_date()

        # =====================================================================
        # TEST 12: Pattern without _00_ spacing
        # =====================================================================
        @runner.test("Test pattern without _00_ spacing")
        def test_no_spacing():
            config = SortingConfig()
            sorter = FileSorter(config)

            # Pattern should also work without _00_
            filename = "garage-01_20260323182654.mp4"
            parsed = sorter.parse_filename(filename, Path("/tmp") / filename)
            assert parsed is not None, "Should parse without spacing"
            assert parsed.camera_name == "garage-01", (
                f"Camera should be 'garage-01', got '{parsed.camera_name}'"
            )

        test_no_spacing()

        # =====================================================================
        # TEST 13: File Move Operation
        # =====================================================================
        @runner.test("Test file move operation")
        def test_file_move():
            move_test_dir = temp_dir / "move_test"
            move_test_dir.mkdir()

            source = move_test_dir / "source.mp4"
            target = (
                move_test_dir
                / "target"
                / "camera"
                / "2026"
                / "03"
                / "23"
                / "source.mp4"
            )

            source.touch()

            config = SortingConfig()
            sorter = FileSorter(config)

            result = sorter.move_file(source, target)

            assert result is True, "Move should succeed"
            assert target.exists() is True, "Target should exist"
            assert source.exists() is False, "Source should not exist"

        test_file_move()

        # =====================================================================
        # TEST 14: Camera Names Without _00_ Spacing
        # =====================================================================
        @runner.test("Test pattern without _00_ spacing")
        def test_no_spacing():
            config = SortingConfig()
            sorter = FileSorter(config)

            # Pattern should work without _00_
            filename = "garage-01_20260323182654.mp4"
            parsed = sorter.parse_filename(filename, Path("/tmp") / filename)
            assert parsed is not None, "Should parse without spacing"
            assert parsed.camera_name == "garage-01", (
                f"Camera should be 'garage-01', got '{parsed.camera_name}'"
            )

        test_no_spacing()

    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"Cleaned up test directory: {temp_dir}")

    # Print final report
    success = runner.report()

    if success:
        print("\n✅ All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
