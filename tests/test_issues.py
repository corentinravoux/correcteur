from correcteur import issues as iss
from correcteur.issues import Issue

# Two matches as LanguageTool 6.6 returns them for "Il ont mangé des pomme hier soir."
LT_MATCHES = [
    {"message": "Vérifiez l’accord entre le pronom « Il » et le verbe « ont ».", "offset": 0, "length": 6,
     "replacements": [{"value": "Ils ont"}, {"value": "Il a"}],
     "rule": {"id": "ACCORD_R_PERS_VERBE", "description": "je + token + verbe", "issueType": "uncategorized",
              "category": {"id": "GRAMMAR"}}},
    {"message": "Faute de frappe possible trouvée.", "offset": 13, "length": 9,
     "replacements": [{"value": "des pommes"}],
     "rule": {"id": "FR_SPELLING_RULE", "issueType": "misspelling", "category": {"id": "TYPOS"}}},
]


def test_from_languagetool():
    found = iss.from_languagetool(LT_MATCHES)
    assert [(i.offset, i.length, i.kind) for i in found] == [(0, 6, "grammar"), (13, 9, "spelling")]
    assert found[0].replacements == ["Ils ont", "Il a"]
    assert found[0].rule_id == "ACCORD_R_PERS_VERBE"
    assert found[0].description == "je + token + verbe" and found[0].source == "LanguageTool"


def test_kind_of():
    assert iss.kind_of("misspelling", "TYPOS") == "spelling"
    assert iss.kind_of("misspelling", "CONFUSED_WORDS") == "grammar"
    assert iss.kind_of("style", "MISC") == "style"
    assert iss.kind_of("uncategorized", "REDUNDANCY") == "style"
    assert iss.kind_of("whitespace", "MISC") == "typography"
    assert iss.kind_of("uncategorized", "PUNCTUATION") == "typography"
    assert iss.kind_of("grammar", "GRAMMAR") == "grammar"


def test_shift_keeps_moves_and_drops():
    a, b, c = Issue(0, 3, "a"), Issue(10, 4, "b"), Issue(20, 2, "c")
    # Insert 5 units at 15: a and b stay, c moves.
    assert iss.shift([a, b, c], 15, 0, 5) == [a, b, Issue(25, 2, "c")]
    # Delete units 11..12: b is touched and dropped, c moves back.
    assert iss.shift([a, b, c], 11, 2, 0) == [a, Issue(18, 2, "c")]
    # Typing right before or right after an issue keeps it.
    assert iss.shift([b], 10, 0, 1) == [Issue(11, 4, "b")]
    assert iss.shift([b], 14, 0, 1) == [b]
    # Replacing the issue's own text drops it.
    assert iss.shift([b], 10, 4, 6) == []


def test_apply_all_skips_overlaps_and_empty():
    text = "Il ont mangé des pomme."
    found = [Issue(0, 6, "", ["Ils ont"]), Issue(13, 9, "", ["des pommes"]),
             Issue(17, 5, "", ["pommes"]),  # overlaps the previous one
             Issue(7, 5, "", [])]           # no suggestion
    assert iss.apply_all(text, found) == "Ils ont mangé des pommes."


def test_utf16_offsets_outside_bmp():
    # 𝑥 is one Python character but two UTF-16 units, as LanguageTool and Qt count.
    text = "Let 𝑥 be teh value."
    assert iss.u16_len("𝑥") == 2
    assert iss.u16_slice(text, 10, 13) == "teh"
    assert iss.apply_all(text, [Issue(10, 3, "", ["the"])]) == "Let 𝑥 be the value."


def test_rules_file(tmp_path):
    path = tmp_path / "rules.txt"
    assert iss.load_rules(path) == {}
    iss.save_rules(path, {"WHITESPACE_RULE": "Whitespace repetition", "NO_DESC": ""})
    assert path.read_text().splitlines()[1:] == ["NO_DESC", "WHITESPACE_RULE  # Whitespace repetition"]
    assert iss.load_rules(path) == {"WHITESPACE_RULE": "Whitespace repetition", "NO_DESC": ""}
