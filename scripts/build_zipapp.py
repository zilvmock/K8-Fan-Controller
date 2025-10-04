#!/usr/bin/env python3
"""Build the k8-fan-controller zipapp with the expected package layout."""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable

DEFAULT_INTERPRETER = "/usr/bin/env python3"
PACKAGE_NAME = "k8_fan_controller"


def copytree(src: pathlib.Path, dst: pathlib.Path, *, ignore_patterns: Iterable[str]) -> None:
    """Copy directory tree while skipping unwanted patterns."""
    if dst.exists():
        raise FileExistsError(f"Destination already exists: {dst}")

    ignore = shutil.ignore_patterns(*ignore_patterns)
    shutil.copytree(src, dst, ignore=ignore)


def build_zipapp(output: pathlib.Path, *, interpreter: str = DEFAULT_INTERPRETER) -> None:
    """Create a zipapp that keeps PACKAGE_NAME as a real package."""
    project_root = pathlib.Path(__file__).resolve().parents[1]
    package_src = project_root / PACKAGE_NAME
    if not package_src.is_dir():
        raise SystemExit(f"Missing package directory: {package_src}")

    output_parent = output.parent
    if output_parent and not output_parent.exists():
        output_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="k8-fan-controller-zipapp-") as tmpdir:
        staging = pathlib.Path(tmpdir)
        # Copy package sources without caches/pycs.
        copytree(package_src, staging / PACKAGE_NAME, ignore_patterns=("__pycache__", "*.pyc", "*.pyo"))

        # Provide explicit __main__ that delegates to the package entrypoint.
        main_path = staging / "__main__.py"
        main_path.write_text(
            "from k8_fan_controller.__main__ import main\n\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n",
            encoding="utf-8",
        )

        cmd = [
            sys.executable,
            "-m",
            "zipapp",
            str(staging),
            "-p",
            interpreter,
            "-o",
            str(output),
        ]
        subprocess.run(cmd, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        type=pathlib.Path,
        help="Path to the zipapp file that should be produced",
    )
    parser.add_argument(
        "--interpreter",
        default=DEFAULT_INTERPRETER,
        help=f"Shebang interpreter to embed (default: {DEFAULT_INTERPRETER})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    build_zipapp(args.output, interpreter=args.interpreter)


if __name__ == "__main__":
    main()
