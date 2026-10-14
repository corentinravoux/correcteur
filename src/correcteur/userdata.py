"""What the user taught Correcteur: dictionary words, ignored issues, rules turned off.

All of it is plain text, one entry per line, so it can be edited by hand and
kept under version control:

- ``dictionary.txt`` holds words for every language, ``dictionary-fr.txt`` and
  ``dictionary-en.txt`` words for one;
- ``ignored.txt`` holds ``RULE_ID<tab>text`` pairs, never flagged again;
- ``disabled-rules.txt`` holds ``RULE_ID  # description`` lines.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .issues import Issue, in_dictionary, load_dictionary, load_rules, save_rules, u16_slice

LANGUAGE_NAMES = {"": "all languages", "fr": "French", "en": "English"}


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

    def add_word(self, word: str, lang: str = "") -> None:
        self.words[lang].add(word)
        self._save_words(lang)

    def remove_word(self, word: str, lang: str = "") -> None:
        self.words[lang].discard(word)
        self._save_words(lang)

    def _save_words(self, lang: str) -> None:
        path = self.dictionary_file(lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        name = LANGUAGE_NAMES[lang]
        lines = [f"# Correcteur dictionary ({name}): one word per line."] + sorted(self.words[lang], key=str.lower)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ----- ignored issues -----------------------------------------------
    def _load_ignored(self) -> dict[tuple[str, str], str]:
        if not self.ignored_path.is_file():
            return {}
        ignored = {}
        for line in self.ignored_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            rule, _, rest = line.partition("\t")
            text, _, description = rest.partition("\t")
            ignored[(rule, text)] = description.removeprefix("# ")
        return ignored

    def ignore(self, rule: str, text: str, description: str = "") -> None:
        self.ignored[(rule, text)] = description
        self._save_ignored()

    def unignore(self, rule: str, text: str) -> None:
        self.ignored.pop((rule, text), None)
        self._save_ignored()

    def _save_ignored(self) -> None:
        self.ignored_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Issues Correcteur never flags again: RULE_ID<tab>text<tab># description."]
        for (rule, text), description in sorted(self.ignored.items()):
            lines.append(f"{rule}\t{text}\t# {description}" if description else f"{rule}\t{text}")
        self.ignored_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ----- rules --------------------------------------------------------
    def disable_rule(self, rule: str, description: str = "") -> None:
        self.rules[rule] = description
        save_rules(self.rules_path, self.rules)

    def enable_rule(self, rule: str) -> None:
        self.rules.pop(rule, None)
        save_rules(self.rules_path, self.rules)

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
