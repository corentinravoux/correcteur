import pytest

from correcteur import i18n


@pytest.fixture(autouse=True)
def back_to_english():
    yield
    i18n.setup("en")


def test_setup(monkeypatch):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.setup("auto") == "fr"
    monkeypatch.setenv("LANG", "C.UTF-8")
    assert i18n.setup("auto") == "en"
    assert i18n.setup("fr") == "fr" and i18n.setup("de") == "en"


def test_translate_and_plurals():
    i18n.setup("fr")
    assert i18n._("Check") == "Vérifier"
    assert i18n._("Not in the table") == "Not in the table"
    assert i18n.ngettext("{n} issue in {language}", "{n} issues in {language}", 1, language="x") == \
        "1 point à revoir en x"
    assert i18n.language_name("English (US)") == "anglais (US)"
    i18n.setup("en")
    assert i18n.ngettext("{n} issue in {language}", "{n} issues in {language}", 2, language="French") == \
        "2 issues in French"


def test_every_placeholder_survives():
    import re
    for english, french in i18n.FR.items():
        assert set(re.findall(r"{\w+}", english)) == set(re.findall(r"{\w+}", french)), english
