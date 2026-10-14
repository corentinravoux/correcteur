"""Command line: open the window, or set things up, or check a file without a window."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .issues import u16_slice


def _position(text: str, offset: int) -> tuple[int, int]:
    before = u16_slice(text, 0, offset)
    return before.count("\n") + 1, len(before) - before.rfind("\n")


def check_file(path: str, language: str, picky: bool, tex: bool | None = None) -> int:
    from .config import load
    from .engine import LanguageTool
    from .latex import looks_like_latex
    from .userdata import UserData

    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    if tex is None:
        tex = path.endswith(".tex") or looks_like_latex(text)
    config = load()
    user = UserData(config)
    with LanguageTool(config) as engine:
        result = engine.check(text, language, picky, set(user.rules), tex)
    result.issues = user.filter(result.issues, text)
    for issue in result.issues:
        line, col = _position(text, issue.offset)
        word = u16_slice(text, issue.offset, issue.end)
        hint = f"  → {issue.replacements[0]!r}" if issue.replacements else ""
        print(f"{line}:{col}  [{issue.kind}] {word!r}: {issue.message}{hint}")
    print(f"{len(result.issues)} issue(s), {result.language}", file=sys.stderr)
    return 1 if result.issues else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="correcteur", description=(
        "Grammar checker for French and English, running LanguageTool on this machine. "
        "Without options, opens the window."))
    parser.add_argument("--download", action="store_true",
                        help="download LanguageTool into ~/.local/share/correcteur")
    parser.add_argument("--ngrams", default="", metavar="LANGS",
                        help="with --download, also fetch n-gram data, e.g. 'fr,en' "
                             "(better confusion-word detection; fr 1.8 GB, en 9 GB)")
    parser.add_argument("--grammalecte", action="store_true",
                        help="with --download, also fetch Grammalecte (French grammar, GPL-3.0, 25 MB)")
    parser.add_argument("--into", metavar="DIR", type=Path,
                        help="with --download, install there instead of ~/.local/share/correcteur")
    parser.add_argument("--install-desktop", action="store_true",
                        help="add Correcteur to the application menu")
    parser.add_argument("--check", metavar="FILE",
                        help="check a text file ('-' for standard input) and print the issues")
    parser.add_argument("--language", default="auto", help="with --check: auto, fr, en-US, en-GB…")
    parser.add_argument("--picky", action="store_true", help="with --check: include style suggestions")
    parser.add_argument("--latex", action=argparse.BooleanOptionalAction, default=None,
                        help="with --check: read the file as LaTeX (default: for .tex files and "
                             "text that looks like LaTeX)")
    args = parser.parse_args(argv)

    if args.download or args.install_desktop:
        if args.download:
            from .download import download
            engine = download(args.into, [x.strip() for x in args.ngrams.split(",") if x.strip()],
                              args.grammalecte)
            print(f"LanguageTool ready: {engine}")
        if args.install_desktop:
            from .desktop import install_desktop_entry
            print(f"Menu entry written: {install_desktop_entry()}")
        return
    if args.check:
        sys.exit(check_file(args.check, args.language, args.picky, args.latex))

    from .app import main as run_app
    run_app()
