"""Fail-closed filesystem checks for private local runtime data."""

from __future__ import annotations

import os
import stat
from pathlib import Path

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class PrivatePathError(ValueError):
    """A local runtime path is unsafe to read from or write to."""


def ensure_private_directory(path: Path) -> None:
    """Create a private directory or validate an existing user-supplied one."""

    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        path.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE)
        path_stat = path.lstat()

    if stat.S_ISLNK(path_stat.st_mode):
        raise PrivatePathError("directory must not be a symbolic link")
    if not stat.S_ISDIR(path_stat.st_mode):
        raise PrivatePathError("path must be a directory")
    if stat.S_IMODE(path_stat.st_mode) & 0o077:
        raise PrivatePathError("directory permissions must not allow group or other access")


def create_or_validate_private_file(path: Path) -> None:
    """Create a private regular file or validate an existing application file."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        os.close(descriptor)

    path_stat = path.lstat()
    if stat.S_ISLNK(path_stat.st_mode):
        raise PrivatePathError("file must not be a symbolic link")
    if not stat.S_ISREG(path_stat.st_mode):
        raise PrivatePathError("path must be a regular file")
    if stat.S_IMODE(path_stat.st_mode) & 0o077:
        raise PrivatePathError("file permissions must not allow group or other access")
