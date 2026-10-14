"""Grammalecte, a French grammar checker, as a second opinion on French text.

Grammalecte (https://grammalecte.net, GPL-3.0) is optional and downloaded
separately, not bundled: ``correcteur --download --grammalecte``. Only its grammar
checks are used; LanguageTool already handles spelling.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .issues import Issue, u16_len

URL = "https://grammalecte.net/zip/Grammalecte-fr-v2.3.0.zip"

# Typography rules that disagree with plain text pasted from an email or a LaTeX
# file: typographic apostrophes, non-breaking spaces, runs of spaces.
OFF = {"apos": False, "nbsp": False, "esp": False}
PICKY = {"redon1": True, "redon2": True}  # repetitions within a paragraph, and across

STYLE = {"redon1", "redon2", "pleo", "bs", "neg", "mc", "eepi"}
TYPOGRAPHY = {"typo", "apos", "esp", "nbsp", "tab", "num", "unit", "liga", "mapos", "chim", "maj", "virg",
              "poncfin", "nf", "tu", "minis", "html", "latex", "md", "ocr"}


def available(path: Path | None) -> bool:
    return path is not None and (path / "grammalecte" / "__init__.py").is_file()


def kind_of(option: str) -> str:
    if option in STYLE:
        return "style"
    if option in TYPOGRAPHY:
        return "typography"
    return "grammar"


class Grammalecte:
    def __init__(self, path: Path):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        import grammalecte  # noqa: PLC0415  (optional, found at run time)

        self.engine = grammalecte.GrammarChecker("fr").getGCEngine()
        self.labels = self.engine.getOptionsLabels("fr")

    def check(self, text: str, picky: bool = False, disabled=()) -> list[Issue]:
        """Grammar issues in ``text``, with UTF-16 offsets like LanguageTool's."""
        options = {**self.engine.getDefaultOptions(), **OFF, **(PICKY if picky else {})}
        issues, offset = [], 0
        for line in text.split("\n"):
            if line.strip():
                for error in self.engine.parse(line, "FR", dOptions=options):
                    issue = self._issue(error, line, offset)
                    if issue.rule_id not in disabled:
                        issues.append(issue)
            offset += u16_len(line) + 1
        return issues

    def _issue(self, error: dict, line: str, offset: int) -> Issue:
        start = offset + u16_len(line[:error["nStart"]])
        option = error.get("sType", "")
        return Issue(
            offset=start,
            length=u16_len(line[error["nStart"]:error["nEnd"]]),
            message=error.get("sMessage", ""),
            replacements=list(error.get("aSuggestions", [])),
            rule_id=error.get("sRuleId", ""),
            kind=kind_of(option),
            description=self.labels.get(option, [option])[0],
            source="Grammalecte",
            language="fr",
        )
