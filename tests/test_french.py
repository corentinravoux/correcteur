"""Grammalecte wrapper and merging; the real Grammalecte is used only when installed."""

import pytest

from correcteur import french
from correcteur.config import load
from correcteur.issues import Issue, merge


class FakeEngine:
    def __init__(self):
        self.options = []

    def getDefaultOptions(self):
        return {"apos": True, "nbsp": True, "esp": True, "conj": True, "redon1": False}

    def parse(self, line, country, dOptions=None):
        self.options.append(dOptions)
        if "𝑥 Il ont" in line:  # a character outside the BMP before the error
            start = line.index("Il")
            return [{"nStart": start, "nEnd": start + 2, "sRuleId": "g2_conj", "sType": "conj",
                     "aSuggestions": ["Ils"], "sMessage": "Accord avec « ont »."}]
        return []


@pytest.fixture
def checker():
    g = french.Grammalecte.__new__(french.Grammalecte)
    g.engine, g.labels = FakeEngine(), {"conj": ["Conjugaisons", ""]}
    return g


def test_check_offsets_and_options(checker):
    text = "Première ligne.\nUn 𝑥 Il ont faim."
    [issue] = checker.check(text)
    assert (issue.offset, issue.length) == (16 + 6, 2)  # "Un 𝑥 ": 𝑥 counts two UTF-16 units
    assert (issue.kind, issue.description, issue.source) == ("grammar", "Conjugaisons", "Grammalecte")
    assert checker.engine.options[-1] == {"apos": False, "nbsp": False, "esp": False, "conj": True,
                                          "redon1": False}
    checker.check(text, picky=True)
    assert checker.engine.options[-1]["redon1"] is True
    assert checker.check(text, disabled={"g2_conj"}) == []


def test_kind_of():
    assert french.kind_of("conj") == "grammar"
    assert french.kind_of("redon1") == "style"
    assert french.kind_of("typo") == "typography"


def test_available(tmp_path):
    assert not french.available(None) and not french.available(tmp_path)
    (tmp_path / "grammalecte").mkdir()
    (tmp_path / "grammalecte" / "__init__.py").write_text("")
    assert french.available(tmp_path)


def test_merge():
    text = "Il ont mangé les donnée hier."
    lt = [Issue(0, 6, "accord", ["Ils ont", "Il a"], "A"), Issue(13, 10, "déterminant", ["la donnée"], "B")]
    gl = [Issue(0, 2, "", ["Ils"], "g1", source="Grammalecte"),        # agrees with LanguageTool
          Issue(17, 6, "", ["données"], "g2", source="Grammalecte"),   # a better fix inside B
          Issue(24, 4, "", ["hier"], "g3", source="Grammalecte"),      # elsewhere: kept
          Issue(5, 10, "", ["x"], "g4", source="Grammalecte")]          # straddles A and B: dropped
    merged = merge(lt, gl, text)
    assert [(i.rule_id, i.replacements) for i in merged] == [
        ("A", ["Ils ont", "Il a"]), ("B", ["les données", "la donnée"]), ("g3", ["hier"])]


config = load()


@pytest.mark.integration
@pytest.mark.skipif(not french.available(config.grammalecte_dir), reason="Grammalecte not installed")
def test_real_grammalecte():
    g = french.Grammalecte(config.grammalecte_dir)
    issues = g.check("Il faut qu'on part avant que nous partons.\nJe doit l'an dernier.")
    assert {"partions", "dois"} <= {i.replacements[0] for i in issues}
    assert all(i.rule_id != "apostrophe_typographique" for i in issues)
