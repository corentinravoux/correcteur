"""User configuration: where the LanguageTool engine lives and how to run it.

Settings are read from ``~/.config/correcteur/config.toml`` (all keys optional)::

    engine_dir = "~/Software/languagetool"   # a LanguageTool-X.Y folder, or its parent
    ngrams_dir = "~/Software/languagetool/ngrams"
    java = "java"
    heap = "1g"
    english_variant = "en-US"
    dictionary = "~/.config/correcteur/dictionary.txt"

Without a config file, the engine is looked up in ``~/.local/share/correcteur``,
which is where ``correcteur --download`` puts it.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

SERVER_JAR = "languagetool-server.jar"
KEYS = {"engine_dir", "ngrams_dir", "java", "heap", "english_variant", "dictionary"}


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "correcteur"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "correcteur"


@dataclass
class Config:
    engine_dir: Path | None
    ngrams_dir: Path | None = None
    java: str = "java"
    heap: str = "1g"
    english_variant: str = "en-US"
    dictionary: Path = Path()

    def __post_init__(self):
        if self.dictionary == Path():
            self.dictionary = config_dir() / "dictionary.txt"


def _version(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path.name))


def find_engine(path: Path) -> Path | None:
    """Return the LanguageTool folder at ``path``, or the newest one inside it."""
    if (path / SERVER_JAR).is_file():
        return path
    if not path.is_dir():
        return None
    found = [d for d in path.glob("LanguageTool-*") if (d / SERVER_JAR).is_file()]
    return max(found, key=_version) if found else None


def _path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def load(path: Path | None = None) -> Config:
    path = path or config_dir() / "config.toml"
    raw: dict = {}
    if path.is_file():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        unknown = set(raw) - KEYS
        if unknown:
            raise ValueError(f"{path}: unknown setting(s) {', '.join(sorted(unknown))}; "
                             f"known: {', '.join(sorted(KEYS))}")

    engine_root = os.environ.get("CORRECTEUR_ENGINE_DIR") or raw.get("engine_dir")
    engine_root = _path(engine_root) if engine_root else data_dir()
    if "ngrams_dir" in raw:
        ngrams = _path(raw["ngrams_dir"])
    else:
        default = data_dir() / "ngrams"
        ngrams = default if default.is_dir() else None

    config = Config(
        engine_dir=find_engine(engine_root),
        ngrams_dir=ngrams,
        java=raw.get("java", "java"),
        heap=str(raw.get("heap", "1g")),
        english_variant=raw.get("english_variant", "en-US"),
    )
    if "dictionary" in raw:
        config.dictionary = _path(raw["dictionary"])
    return config
