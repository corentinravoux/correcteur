"""Issues found in a text, and the bookkeeping that keeps them aligned with it.

Offsets and lengths are counted in UTF-16 code units, as both LanguageTool (Java)
and Qt count them. They differ from Python string indices only for characters
outside the Basic Multilingual Plane, such as the mathematical letters 𝑥 or 𝛼 that
come with text pasted from a PDF.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

KINDS = ("spelling", "grammar", "style", "typography")

_STYLE = {"style", "register", "locale-violation", "inconsistency", "characters"}
_TYPOGRAPHY = {"typographical", "whitespace"}


@dataclass(frozen=True)
class Issue:
    offset: int
    length: int
    message: str
    replacements: list[str] = field(default_factory=list, compare=False)
    rule_id: str = ""
    kind: str = "grammar"
    description: str = field(default="", compare=False)  # the rule's name, e.g. "Possible typo"
    source: str = field(default="LanguageTool", compare=False)
    language: str = field(default="", compare=False)      # code of the paragraph's language, e.g. "fr"

    @property
    def end(self) -> int:
        return self.offset + self.length


def kind_of(issue_type: str, category: str) -> str:
    if issue_type == "misspelling" and category == "TYPOS":
        return "spelling"
    if issue_type in _STYLE or category in {"STYLE", "REDUNDANCY", "PLAIN_ENGLISH", "REPETITIONS_STYLE"}:
        return "style"
    if issue_type in _TYPOGRAPHY or category in {"TYPOGRAPHY", "PUNCTUATION"}:
        return "typography"
    return "grammar"


def from_languagetool(matches: list[dict]) -> list[Issue]:
    issues = []
    for m in matches:
        rule = m.get("rule", {})
        issues.append(Issue(
            offset=m["offset"],
            length=m["length"],
            message=m.get("message", ""),
            replacements=[r["value"] for r in m.get("replacements", [])],
            rule_id=rule.get("id", ""),
            kind=kind_of(rule.get("issueType", ""), rule.get("category", {}).get("id", "")),
            description=rule.get("description", ""),
        ))
    return issues


def u16_slice(text: str, start: int, end: int) -> str:
    data = text.encode("utf-16-le")
    return data[2 * start:2 * end].decode("utf-16-le", errors="replace")


def u16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def shift(issues: list[Issue], pos: int, removed: int, added: int) -> list[Issue]:
    """Follow an edit of the text: ``removed`` units at ``pos`` replaced by ``added``.

    Issues before the edit stay, issues after it move, and issues it touches are
    dropped because their text is no longer the one that was checked.
    """
    delta = added - removed
    kept = []
    for issue in issues:
        if issue.end <= pos:
            kept.append(issue)
        elif issue.offset >= pos + removed:
            kept.append(replace(issue, offset=issue.offset + delta) if delta else issue)
    return kept


def non_overlapping(issues: list[Issue]) -> list[Issue]:
    """Issues that have a suggestion, last first, skipping any that overlap a later one."""
    chosen, limit = [], None
    for issue in sorted(issues, key=lambda i: (i.offset, i.end), reverse=True):
        if not issue.replacements or (limit is not None and issue.end > limit):
            continue
        chosen.append(issue)
        limit = issue.offset
    return chosen


def apply_all(text: str, issues: list[Issue]) -> str:
    """Apply the first suggestion of every issue that has one."""
    data = text.encode("utf-16-le")
    for issue in non_overlapping(issues):
        data = data[:2 * issue.offset] + issue.replacements[0].encode("utf-16-le") + data[2 * issue.end:]
    return data.decode("utf-16-le")


def in_dictionary(word: str, dictionary: set[str]) -> bool:
    # A word at the start of a sentence is capitalised: accept "Healpy" for "healpy".
    return word in dictionary or (word[:1].isupper() and word[:1].lower() + word[1:] in dictionary)


def load_dictionary(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {w.strip() for w in lines if w.strip() and not w.lstrip().startswith("#")}


def load_rules(path: Path) -> dict[str, str]:
    """Turned-off rules, one per line: ``RULE_ID  # description``."""
    if not path.is_file():
        return {}
    rules = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        rule, _, description = line.partition("#")
        if rule.strip():
            rules[rule.strip()] = description.strip()
    return rules


def save_rules(path: Path, rules: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Rules Correcteur never flags. Delete a line to turn its rule back on."]
    lines += [f"{rule}  # {description}" if description else rule for rule, description in sorted(rules.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge(primary: list[Issue], second: list[Issue], text: str) -> list[Issue]:
    """Add a second engine's issues to the first's.

    An issue inside one of the first engine's spans becomes a suggestion for it,
    put first: two engines agreeing on a fix is the best signal there is. An
    issue elsewhere is kept as it is. One that partly overlaps is dropped.
    """
    merged = list(primary)
    for extra in second:
        hits = [k for k, p in enumerate(merged) if p.offset < extra.end and extra.offset < p.end]
        if not hits:
            merged.append(extra)
            continue
        k = hits[0]
        host = merged[k]
        if len(hits) > 1 or not (host.offset <= extra.offset and extra.end <= host.end) or not extra.replacements:
            continue
        before = u16_slice(text, host.offset, extra.offset)
        after = u16_slice(text, extra.end, host.end)
        fix = before + extra.replacements[0] + after
        merged[k] = replace(host, replacements=[fix] + [r for r in host.replacements if r != fix])
    return sorted(merged, key=lambda i: (i.offset, i.end))
