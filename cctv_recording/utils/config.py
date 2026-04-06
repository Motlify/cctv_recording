from json import loads, dump
import sys
import pathlib
import logging
import os
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, validator, ValidationError

CONFIG_FILE = pathlib.Path(os.path.dirname(__file__), "config.json")


# Logging
def configure_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s:[%(funcName)s] %(message)s"
    )
    logging.basicConfig(format="%(asctime)s %(levelname)-8s:[%(funcName)s] %(message)s")
    logging.getLogger("kafka").setLevel(logging.CRITICAL)


class Camera(BaseModel):
    name: str
    url: str
    audio: bool = False  # Default to False if not provided


class Kafka(BaseModel):
    api_url: str
    audio_topic: str
    images_topic: str


class FTPSorterConfig(BaseModel):
    """Configuration for FTP file sorting.

    This configuration allows sorting files from FTP directories
    into a date-based directory structure.

    Example filename pattern for Hikvision cameras:
        garage-01_00_20260323182654.mp4

    Pattern groups:
        - camera_name: Name of the camera (e.g., "garage-01")
        - spacing: Optional separator (e.g., "_00_")
        - year: 4-digit year (e.g., "2026")
        - month: 2-digit month (e.g., "03")
        - day: 2-digit day (e.g., "23")
        - hour: 2-digit hour (e.g., "18")
        - minute: 2-digit minute (e.g., "26")
        - second: 2-digit second (e.g., "54")
        - ext: File extension (e.g., "mp4", "jpg", "avi")
    """

    enabled: bool = False
    ftp_camera_dirs: List[str] = Field(default_factory=list)
    filename_pattern: str = (
        r"(?P<camera_name>.+?)_(?P<spacing>_00_)?(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
        r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.(?P<ext>mp4|avi|jpg|jpeg|mkv)"
    )
    supported_extensions: List[str] = Field(
        default_factory=lambda: [".mp4", ".avi", ".jpg", ".jpeg", ".mkv"]
    )
    retention_days: int = 30
    delete_source: bool = True


class Config(BaseModel):
    cameras: List[Camera]
    cameras_dir: str
    kafka: Optional[Kafka] = None
    audio_duration: Optional[int] = None
    still_images: Optional[str] = None
    still_image_interval: Optional[int] = None
    ftp_sorter: Optional[FTPSorterConfig] = None


def genconf() -> Optional[Config]:
    try:
        configuration = Config.parse_file(CONFIG_FILE)
        return configuration
    except ValidationError as e:
        logging.error(
            f"{CONFIG_FILE} is not a valid Config file, Errors: \n {e.json(indent=4)}"
        )
        sys.exit(1)
    except FileNotFoundError as e:
        logging.error(f"Config File: '{CONFIG_FILE}' could not be found")
        sys.exit(1)
