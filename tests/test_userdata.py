from correcteur.config import Config
from correcteur.issues import Issue
from correcteur.userdata import UserData, language_of


def make(tmp_path):
    return UserData(Config(engine_dir=None, dictionary=tmp_path / "dictionary.txt",
                           disabled_rules=tmp_path / "rules.txt", ignored=tmp_path / "ignored.txt"))


def test_language_of():
    assert [language_of(c) for c in ("fr", "en-US", "en-GB", "ca", "")] == ["fr", "en", "en", "", ""]


def test_dictionaries_per_language(tmp_path):
    user = make(tmp_path)
    user.add_word("redshift", "")
    user.add_word("fσ8", "fr")
    user.add_word("lensing", "en")
    assert (tmp_path / "dictionary-fr.txt").read_text().splitlines()[1:] == ["fσ8"]
    assert user.knows("redshift", "fr") and user.knows("Redshift", "en-US")  # capitalised at sentence start
    assert user.knows("fσ8", "fr") and not user.knows("fσ8", "en-US")
    assert user.knows("lensing", "en-GB") and not user.knows("lensing", "fr")
    again = make(tmp_path)
    assert again.words == {"": {"redshift"}, "fr": {"fσ8"}, "en": {"lensing"}}
    again.remove_word("lensing", "en")
    assert make(tmp_path).words["en"] == set()


def test_ignored_round_trip(tmp_path):
    user = make(tmp_path)
    user.ignore("RULE_A", "les donnée", "Accord")
    user.ignore("RULE_B", "deux  espaces")
    assert make(tmp_path).ignored == {("RULE_A", "les donnée"): "Accord", ("RULE_B", "deux  espaces"): ""}
    user.unignore("RULE_A", "les donnée")
    assert list(make(tmp_path).ignored) == [("RULE_B", "deux  espaces")]


def test_rules_round_trip(tmp_path):
    user = make(tmp_path)
    user.disable_rule("WHITESPACE_RULE", "Whitespace repetition")
    assert make(tmp_path).rules == {"WHITESPACE_RULE": "Whitespace repetition"}
    user.enable_rule("WHITESPACE_RULE")
    assert make(tmp_path).rules == {}


def test_filter(tmp_path):
    user = make(tmp_path)
    text = "Healpix est utile, teh fin, les donnée."
    found = [Issue(0, 7, "", kind="spelling", language="fr"),
             Issue(19, 3, "", ["the"], "TYPO", "spelling", language="fr"),
             Issue(28, 10, "", rule_id="ACCORD", language="fr"),
             Issue(28, 10, "", rule_id="OFF", language="fr")]
    user.add_word("healpix", "fr")
    user.ignore("ACCORD", "les donnée")
    user.disable_rule("OFF")
    assert user.filter(found, text) == [found[1]]
    user.add_word("teh", "en")  # another language's dictionary does not count
    assert user.filter(found, text) == [found[1]]
    grammar = Issue(0, 7, "", kind="grammar", language="fr")  # dictionaries only silence spelling
    assert user.filter([grammar], text) == [grammar]


def test_ignored_text_with_tabs_and_newlines(tmp_path):
    user = make(tmp_path)
    user.ignore("DUPLICATE", "the\nthe", "Repeated word")
    user.ignore("TAB", "a\tb")
    assert make(tmp_path).ignored == {("DUPLICATE", "the\nthe"): "Repeated word", ("TAB", "a\tb"): ""}
    user.unignore("DUPLICATE", "the\nthe")
    assert list(make(tmp_path).ignored) == [("TAB", "a\tb")]


def test_dictionary_refuses_words_it_cannot_store(tmp_path):
    user = make(tmp_path)
    assert not user.add_word("two\nlines") and not user.add_word("#tag") and not user.add_word(" ")
    assert user.add_word("HEALPix")
    assert make(tmp_path).words[""] == {"HEALPix"}


def test_saving_keeps_hand_edits_and_comments(tmp_path):
    path = tmp_path / "dictionary-fr.txt"
    path.write_text("# my cosmology words\nredshift\n", encoding="utf-8")
    user = make(tmp_path)
    with open(path, "a", encoding="utf-8") as f:   # edited by hand while the app runs
        f.write("lensing\n")
    user.add_word("fσ8", "fr")
    user.remove_word("redshift", "fr")
    assert path.read_text(encoding="utf-8").splitlines() == ["# my cosmology words", "lensing", "fσ8"]
    rules = tmp_path / "rules.txt"
    rules.write_text("# turned off on purpose\nA_RULE  # first\n", encoding="utf-8")
    user = make(tmp_path)
    user.disable_rule("B_RULE", "second")
    user.enable_rule("A_RULE")
    assert rules.read_text(encoding="utf-8").splitlines() == ["# turned off on purpose", "B_RULE  # second"]
    assert not list(tmp_path.glob("*.tmp"))
