"""Render the ERDs from the design document; requires Mermaid CLI."""

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("application-payment", "matching-gathering", "feedback-operations", "gathering-physical")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer", default=shutil.which("mmdc"))
    parser.add_argument("--puppeteer-config", type=Path)
    args = parser.parse_args()
    if not args.renderer:
        parser.error("Mermaid CLI (mmdc) is required; pass --renderer /path/to/mmdc")
    source = ROOT / "docs/design/core-data-model.md"
    blocks = re.findall(r"```mermaid\s*\n(erDiagram\b.*?)\n```", source.read_text(), re.S)
    if len(blocks) != len(NAMES):
        parser.error(f"Expected exactly {len(NAMES)} erDiagram blocks in core-data-model.md")
    destination = ROOT / "docs/design/erd"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="serentable-erd-") as temporary:
        for name, block in zip(NAMES, blocks):
            diagram = Path(temporary) / (name + ".mmd")
            diagram.write_text(block + "\n")
            for extension in ("svg", "png"):
                command = [
                    args.renderer,
                    "-i",
                    str(diagram),
                    "-o",
                    str(destination / (name + "." + extension)),
                    "-b",
                    "white",
                    "-t",
                    "neutral",
                    "-w",
                    "1800",
                ]
                if args.puppeteer_config:
                    command.extend(["-p", str(args.puppeteer_config)])
                subprocess.run(command, check=True)
    print(f"Rendered {len(NAMES)} SVG and {len(NAMES)} PNG files in docs/design/erd")


if __name__ == "__main__":
    main()
