"""What the user taught Correcteur: dictionary words, ignored issues, rules turned off.

All of it is plain text, one entry per line, so it can be edited by hand and
kept under version control:

- ``dictionary.txt`` holds words for every language, ``dictionary-fr.txt`` and
  ``dictionary-en.txt`` words for one;
- ``ignored.txt`` holds ``RULE_ID<tab>text`` pairs, never flagged again;
- ``disabled-rules.txt`` holds ``RULE_ID  # description`` lines.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import Config
from .issues import Issue, in_dictionary, load_dictionary, load_rules, u16_slice

LANGUAGE_NAMES = {"": "all languages", "fr": "French", "en": "English"}
_ESCAPES = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNESCAPES = {v: k for k, v in _ESCAPES.items()}


def _escape(text: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in text)


def _unescape(text: str) -> str:
    return re.sub(r"\\[\\tnr]", lambda m: _UNESCAPES[m.group()], text)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def _write(path: Path, lines: list[str]) -> None:
    """Replace the file in one step, so that a crash never leaves it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def storable(word: str) -> bool:
    """A dictionary word is one line without spaces, not starting with "#"."""
    return bool(word) and not any(c.isspace() for c in word) and not word.startswith("#")


def language_of(code: str) -> str:
    """The dictionary a language code belongs to: "fr", "en" or "" (all)."""
    prefix = code.split("-")[0]
    return prefix if prefix in LANGUAGE_NAMES else ""


class UserData:
    def __init__(self, config: Config):
        self.dictionary_path = config.dictionary
        self.ignored_path = config.ignored
        self.rules_path = config.disabled_rules
        self.words = {lang: load_dictionary(self.dictionary_file(lang)) for lang in LANGUAGE_NAMES}
        self.ignored = self._load_ignored()
        self.rules = load_rules(self.rules_path)

    # ----- dictionary ---------------------------------------------------
    def dictionary_file(self, lang: str) -> Path:
        p = self.dictionary_path
        return p if not lang else p.with_name(f"{p.stem}-{lang}{p.suffix}")

    def knows(self, word: str, code: str = "") -> bool:
        lang = language_of(code)
        return in_dictionary(word, self.words[""]) or bool(lang and in_dictionary(word, self.words[lang]))

    # Each change edits the file line by line, re-reading it first: comments and
    # words added by hand, even while the app runs, are kept.
    def add_word(self, word: str, lang: str = "") -> bool:
        word = word.strip()
        if not storable(word):
            return False
        path = self.dictionary_file(lang)
        lines = _lines(path) or [f"# Correcteur dictionary ({LANGUAGE_NAMES[lang]}): one word per line."]
        if word not in (line.strip() for line in lines):
            lines.append(word)
            _write(path, lines)
        self.words[lang] = load_dictionary(path)
        return True

    def remove_word(self, word: str, lang: str = "") -> None:
        path = self.dictionary_file(lang)
        _write(path, [line for line in _lines(path) if line.strip() != word])
        self.words[lang] = load_dictionary(path)

    # ----- ignored issues -----------------------------------------------
    @staticmethod
    def _parse_ignored(line: str) -> tuple[tuple[str, str], str] | None:
        if not line.strip() or line.startswith("#"):
            return None
        rule, _, rest = line.partition("\t")
        text, _, description = rest.partition("\t")
        return (rule, _unescape(text)), description.removeprefix("# ")

    def _load_ignored(self) -> dict[tuple[str, str], str]:
        return dict(entry for line in _lines(self.ignored_path) if (entry := self._parse_ignored(line)))

    def ignore(self, rule: str, text: str, description: str = "") -> None:
        """Never flag ``text`` for ``rule`` again; tabs and line breaks in it are escaped."""
        lines = _lines(self.ignored_path) or [
            "# Issues Correcteur never flags again: RULE_ID<tab>text<tab># description.",
            "# In the text, \\t, \\n and \\\\ stand for a tab, a line break and a backslash."]
        if (rule, text) not in self._load_ignored():
            entry = f"{rule}\t{_escape(text)}"
            lines.append(f"{entry}\t# {description}" if description else entry)
            _write(self.ignored_path, lines)
        self.ignored = self._load_ignored()

    def unignore(self, rule: str, text: str) -> None:
        kept = [line for line in _lines(self.ignored_path)
                if not ((entry := self._parse_ignored(line)) and entry[0] == (rule, text))]
        _write(self.ignored_path, kept)
        self.ignored = self._load_ignored()

    # ----- rules --------------------------------------------------------
    def disable_rule(self, rule: str, description: str = "") -> None:
        lines = _lines(self.rules_path) or ["# Rules Correcteur never flags. Delete a line to turn its rule back on."]
        if rule not in load_rules(self.rules_path):
            lines.append(f"{rule}  # {description}" if description else rule)
            _write(self.rules_path, lines)
        self.rules = load_rules(self.rules_path)

    def enable_rule(self, rule: str) -> None:
        kept = [line for line in _lines(self.rules_path) if line.partition("#")[0].strip() != rule]
        _write(self.rules_path, kept)
        self.rules = load_rules(self.rules_path)

    # ----- filtering ----------------------------------------------------
    def keeps(self, issue: Issue, text: str) -> bool:
        if issue.rule_id in self.rules:
            return False
        word = u16_slice(text, issue.offset, issue.end)
        if issue.kind == "spelling" and self.knows(word, issue.language):
            return False
        return (issue.rule_id, word) not in self.ignored

    def filter(self, issues: list[Issue], text: str) -> list[Issue]:
        return [i for i in issues if self.keeps(i, text)]
