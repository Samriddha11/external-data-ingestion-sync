"""Pass-through when file is already FOCUS-shaped."""

from __future__ import annotations

from typing import IO, TextIO


def transform(src: IO[str], dest: TextIO) -> None:
    dest.write(src.read())
