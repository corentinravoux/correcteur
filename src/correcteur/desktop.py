"""Add Correcteur to the desktop's application menu."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

ENTRY = """[Desktop Entry]
Type=Application
Name=Correcteur
GenericName=Grammar checker
Comment=Check French and English text locally with LanguageTool
Exec={exec}
Icon=tools-check-spelling
Terminal=false
Categories=Utility;TextTools;
Keywords=grammar;spelling;orthographe;grammaire;languagetool;
StartupWMClass=correcteur
"""


def install_desktop_entry() -> Path:
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    path = apps / "correcteur.desktop"
    path.write_text(ENTRY.format(exec=f"{shlex.quote(sys.executable)} -m correcteur"))
    return path
