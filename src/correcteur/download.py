"""Download the LanguageTool engine and, optionally, its n-gram data."""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from .config import data_dir, find_engine
from .french import URL as GRAMMALECTE_URL
from .french import available as grammalecte_available

ENGINE_URL = "https://languagetool.org/download/LanguageTool-stable.zip"
NGRAM_URLS = {
    "en": "https://languagetool.org/download/ngram-data/ngrams-en-20150817.zip",  # 9.0 GB
    "fr": "https://languagetool.org/download/ngram-data/ngrams-fr-20150913.zip",  # 1.8 GB
}


def _fetch(url: str, dest: Path) -> None:
    partial = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as reply, open(partial, "wb") as out:
        total = int(reply.headers.get("Content-Length", 0))
        done = 0
        while chunk := reply.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {dest.name}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", file=sys.stderr)
    print(file=sys.stderr)
    partial.rename(dest)


def _unpack(url: str, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    archive = into / url.rsplit("/", 1)[1]
    print(f"Downloading {url}", file=sys.stderr)
    _fetch(url, archive)
    print(f"Unpacking into {into}", file=sys.stderr)
    with zipfile.ZipFile(archive) as z:
        z.extractall(into)
    archive.unlink()


def download_grammalecte(dest: Path) -> Path:
    """Fetch Grammalecte and keep only its Python package, in ``dest/grammalecte``."""
    target = dest / "grammalecte"
    if grammalecte_available(target):
        print(f"Grammalecte already present: {target}", file=sys.stderr)
        return target
    target.mkdir(parents=True, exist_ok=True)
    archive = target / GRAMMALECTE_URL.rsplit("/", 1)[1]
    print(f"Downloading {GRAMMALECTE_URL}", file=sys.stderr)
    _fetch(GRAMMALECTE_URL, archive)
    with zipfile.ZipFile(archive) as z:
        z.extractall(target, [m for m in z.namelist() if m.startswith("grammalecte/")])
        z.extract("LICENSE.txt", target)
    archive.unlink()
    return target


def download(dest: Path | None = None, ngrams: tuple[str, ...] | list[str] = (),
             grammalecte: bool = False) -> Path:
    dest = dest or data_dir()
    unknown = set(ngrams) - set(NGRAM_URLS)
    if unknown:
        raise ValueError(f"no n-gram data for {', '.join(sorted(unknown))}; available: {', '.join(NGRAM_URLS)}")
    engine = find_engine(dest)
    if engine is None:
        _unpack(ENGINE_URL, dest)
        engine = find_engine(dest)
    else:
        print(f"LanguageTool already present: {engine}", file=sys.stderr)
    if engine is None:
        raise RuntimeError(f"the download did not contain {ENGINE_URL.rsplit('/', 1)[1]} as expected")
    for lang in ngrams:
        if (dest / "ngrams" / lang).is_dir():
            print(f"n-grams for {lang} already present", file=sys.stderr)
            continue
        _unpack(NGRAM_URLS[lang], dest / "ngrams")
    if grammalecte:
        download_grammalecte(dest)
    if shutil.which("java") is None:
        print("Warning: Java was not found; install a Java runtime, version 17 or later.", file=sys.stderr)
    return engine
