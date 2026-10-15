"""The window, driven with a fake engine on Qt's offscreen platform."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from correcteur.app import Window
from correcteur.config import Config
from correcteur.engine import CheckResult
from correcteur.issues import Issue

TEXT = "Il ont mangé des pomme. Healpix est utile."


class FakeEngine:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def wait_ready(self):
        pass

    def warm_up(self):
        pass

    def stop(self):
        self.stopped = True

    def check(self, text, language="auto", picky=False, disabled=(), tex=False):
        self.calls.append((text, language, picky))
        self.tex = tex
        found = []
        for word, rep, kind in (("Il ont", "Ils ont", "grammar"), ("des pomme", "des pommes", "grammar"),
                                ("Healpix", "Healpy", "spelling")):
            if word in text:
                found.append(Issue(text.index(word), len(word), f"fix {word}", [rep], f"R{len(found)}", kind,
                                   description=f"Rule {len(found)}", language="fr"))
        return CheckResult(found, "French")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    config = Config(engine_dir=None, dictionary=tmp_path / "dictionary.txt",
                    disabled_rules=tmp_path / "disabled-rules.txt", ignored=tmp_path / "ignored.txt",
                    interface="en")
    w = Window(config, engine=FakeEngine())
    wait_for(app, lambda: w.engine_state == "ready")
    yield w
    w.close()


def wait_for(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        app.processEvents()
        time.sleep(0.01)


def checked(app, window, text=TEXT):
    window.language = ""  # set again when the result arrives
    window.editor.setPlainText(text)
    window.check()
    wait_for(app, lambda: window.language)
    return window.editor.issues


def test_check_shows_issues(app, window):
    found = checked(app, window)
    assert len(found) == 3
    assert len(window.editor.extraSelections()) == 3
    assert window.status.text() == "3 issues in French"
    assert window.engine.calls[-1] == (TEXT, "auto", False)


def test_apply_one_suggestion_moves_the_others(app, window):
    first, second, _ = checked(app, window)
    window.apply(first, first.replacements[0])
    assert window.editor.toPlainText().startswith("Ils ont mangé des pomme.")
    assert len(window.editor.issues) == 2
    moved = window.editor.issues[0]
    assert moved.offset == second.offset + 1
    assert window.editor.toPlainText()[moved.offset:moved.end] == "des pomme"


def test_accept_all_and_undo(app, window):
    checked(app, window)
    window.accept_all()
    assert window.editor.toPlainText() == "Ils ont mangé des pommes. Healpy est utile."
    assert window.editor.issues == []
    window.editor.undo()
    assert window.editor.toPlainText() == TEXT


def test_add_word_and_ignore(app, window, tmp_path):
    from correcteur.issues import load_dictionary

    found = checked(app, window)
    window.add_word("Healpix", "fr")
    assert load_dictionary(tmp_path / "dictionary-fr.txt") == {"Healpix"}
    assert len(window.editor.issues) == 2
    window.ignore(found[0])
    assert len(window.editor.issues) == 1
    assert "R0\tIl ont\t# Rule 0" in (tmp_path / "ignored.txt").read_text()
    # Both stay silent at the next check, and in a new window.
    assert [i.rule_id for i in checked(app, window)] == ["R1"]
    again = Window(window.config, engine=FakeEngine())
    assert again.user.knows("Healpix", "fr") and ("R0", "Il ont") in again.user.ignored
    again.close()


def test_text_changed_during_check_is_discarded(app, window):
    window.editor.setPlainText(TEXT)
    window.check()
    window.editor.insertPlainText("!")
    wait_for(app, lambda: "changed" in window.status.text())
    assert window.editor.issues == []


def test_copy_and_paste(app, window):
    clipboard = QApplication.clipboard()
    clipboard.setText("Il ont faim.")
    window.paste_and_check()
    wait_for(app, lambda: window.language)
    assert window.editor.toPlainText() == "Il ont faim."
    assert len(window.editor.issues) == 1
    window.editor.setPlainText("Corrigé.")
    window.copy()
    assert clipboard.text() == "Corrigé."


def test_margin_lists_notes_and_fixes(app, window):
    from correcteur.margin import Note
    from PySide6.QtWidgets import QPushButton

    checked(app, window)
    notes = window.margin.widget().findChildren(Note)
    assert [n.issue.rule_id for n in notes] == ["R0", "R1", "R2"]
    chip = next(b for b in notes[1].findChildren(QPushButton) if b.objectName() == "chip")
    chip.click()
    assert "des pommes" in window.editor.toPlainText()
    wait_for(app, lambda: len(window.margin.widget().findChildren(Note)) == 2)


def test_reveal_and_next_issue(app, window):
    found = checked(app, window)
    window.reveal(found[1])
    assert window.editor.textCursor().selectedText() == "des pomme"
    window.next_issue()
    assert window.editor.textCursor().selectedText() == "Healpix"
    window.next_issue()  # wraps around
    assert window.editor.textCursor().selectedText() == "Il ont"
    window.next_issue(backwards=True)
    assert window.editor.textCursor().selectedText() == "Healpix"


def test_theme_switch_repaints(app, window):
    from correcteur import theme

    checked(app, window)
    window.apply_theme(theme.DARK)
    colors = {s.format.underlineColor().name().upper() for s in window.editor.extraSelections()}
    assert colors <= {c.upper() for c in theme.DARK.kinds.values()}
    window.apply_theme(theme.LIGHT)


def test_turn_off_and_on_a_rule(app, window, tmp_path):
    from correcteur.dialogs import ExceptionsDialog
    from correcteur.issues import load_rules

    found = checked(app, window)
    assert window.exceptions_button.text() == "Exceptions"
    window.turn_off(found[0])
    assert load_rules(tmp_path / "disabled-rules.txt") == {"R0": "Rule 0"}
    assert [i.rule_id for i in window.editor.issues] == ["R1", "R2"]
    assert window.exceptions_button.text() == "Exceptions (1)"
    assert [i.rule_id for i in checked(app, window)] == ["R1", "R2"]  # stays off at the next check

    dialog = ExceptionsDialog(window)
    assert dialog.tabs.tabText(0) == "Rules turned off (1)"
    dialog.rules.tree.topLevelItem(0).setSelected(True)
    dialog.rules.button.click()
    assert load_rules(tmp_path / "disabled-rules.txt") == {}
    assert dialog.tabs.tabText(0) == "Rules turned off (0)"
    assert window.exceptions_button.text() == "Exceptions"
    assert len(checked(app, window)) == 3


def test_exceptions_dialog_dictionary(app, window, tmp_path):
    from correcteur.dialogs import ExceptionsDialog

    dialog = ExceptionsDialog(window)
    dialog.new_word.setText("HEALPix")
    dialog.new_lang.setCurrentIndex(dialog.new_lang.findData("en"))
    dialog._add_word()
    assert window.user.words["en"] == {"HEALPix"}
    assert dialog.tabs.tabText(2) == "Dictionary (1)"
    dialog.words.search.setText("zzz")
    assert dialog.words.tree.topLevelItem(0).isHidden()
    dialog.words.search.clear()
    dialog.words.tree.topLevelItem(0).setSelected(True)
    dialog.words.button.click()
    assert window.user.words["en"] == set()


def test_paste_latex_ticks_the_box(app, window):
    window.latex_box.setChecked(False)
    QApplication.clipboard().setText(r"Voir \cite{a} et \ref{b}: Il ont faim.")
    window.paste_and_check()
    assert window.latex_box.isChecked()
    wait_for(app, lambda: window.language)
    assert window.engine.tex is True
    QApplication.clipboard().setText("Plain text, Il ont faim.")
    window.paste_and_check()  # never unticked automatically
    assert window.latex_box.isChecked()


def test_spelling_notes_offer_no_turn_off(app, window):
    from correcteur.margin import Note

    checked(app, window)
    labels = {n.issue.kind: [b.text() for b in n.findChildren(QPushButton) if b.objectName() == "link"]
              for n in window.margin.widget().findChildren(Note)}
    assert labels["spelling"] == ["Ignore", "Add to dictionary"]
    assert labels["grammar"] == ["Ignore", "Turn off rule"]


def test_keyboard_review_loop(app, window, monkeypatch):
    def press_enter(menu, where):
        action = menu.activeAction()  # the first suggestion is preselected
        action.trigger()
        return action

    monkeypatch.setattr(window, "run_menu", press_enter)
    checked(app, window)
    window.editor.moveCursor(window.editor.textCursor().MoveOperation.Start)
    window.next_issue(menu=True)
    wait_for(app, lambda: window.status.text() == "No issue left.")
    assert window.editor.toPlainText() == "Ils ont mangé des pommes. Healpy est utile."


def test_current_note_follows_the_cursor(app, window):
    from correcteur.margin import Note

    found = checked(app, window)
    window.reveal(found[1])
    notes = window.margin.widget().findChildren(Note)
    assert [n.property("current") for n in notes] == [False, True, False]
    assert window.current_issue() == found[1]


def test_french_interface(app, tmp_path):
    from correcteur import i18n

    config = Config(engine_dir=None, dictionary=tmp_path / "d.txt", disabled_rules=tmp_path / "r.txt",
                    ignored=tmp_path / "i.txt", interface="fr")
    w = Window(config, engine=FakeEngine())
    try:
        assert w.check_button.text() == "Vérifier" and w.lang_box.itemText(2) == "Anglais (US)"
        checked(app, w)
        assert w.status.text() == "3 points à revoir en français"
        w.language = "French + English (US)"
        w.update_status()
        assert w.status.text() == "3 points à revoir en français et anglais (US)"
        assert w.margin.widget().findChildren(QLabel)[0].text() == "3 à revoir"
    finally:
        w.close()
        i18n.setup("en")


def test_margin_never_wider_than_its_panel(app, window):
    """Long suggestions, words and messages wrap or shorten instead of cutting the margin."""
    from correcteur.margin import Note

    text = ("Le modèle Chevallier-Polarski-Linder, mais je doit verifier les donnée. "
            "Voir https://example.org/a/very/long/path/that/never/breaks/anywhere/at/all ici.")
    long_message = ("Vérifiez l’accord entre le pronom « Il » et le verbe « ont ». Le verbe devrait être "
                    "à la 3ᵉ personne du singulier ou le pronom au pluriel.")
    issues = [
        Issue(text.index("Chevallier"), 26, "Faute de frappe possible trouvée.",
              ["Chevalier-Polarski-Linder", "Chevallier-Polarski-Lindner", "Chevaliers-Polarski"],
              "SPELL", "spelling", language="fr"),
        Issue(text.index("doit"), 4, long_message, ["dois"], "ACCORD", "grammar", language="fr"),
        Issue(text.index("https"), 66, "Lien très long : " + "x" * 80, ["https://example.org/" + "y" * 60],
              "URL", "typography", language="fr"),
    ]
    window.resize(1180, 700)
    window.show()
    window.editor.setPlainText(text)
    window._checked(text, CheckResult(issues, "French"))
    app.processEvents()
    page, viewport = window.margin.widget(), window.margin.viewport()
    assert page.width() <= viewport.width()
    for note in page.findChildren(Note):
        assert note.geometry().right() < viewport.width()
        for child in note.findChildren(QPushButton) + note.findChildren(QLabel):
            if child.isVisible():
                right = child.mapTo(page, child.rect().topRight()).x()
                assert right < viewport.width(), child.text()
                if isinstance(child, QLabel) and child.wordWrap():
                    assert child.height() >= child.heightForWidth(child.width()), child.text()


def test_undo_back_to_the_checked_text_restores_the_issues(app, window):
    checked(app, window)
    window.accept_all()
    assert window.editor.issues == []
    window.editor.undo()
    assert window.editor.toPlainText() == TEXT
    assert [i.rule_id for i in window.editor.issues] == ["R0", "R1", "R2"]
    assert window.status.text() == "3 issues in French"


def test_status_says_when_the_text_changed_since_the_check(app, window):
    found = checked(app, window)
    window.apply(found[0], "Ils ont")  # applying a suggestion is not a hand edit
    assert window.status.text() == "2 issues in French"
    window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
    window.editor.insertPlainText(" Fin.")
    assert window.status.text() == "2 issues in French (text edited since the check)"


def test_paste_clears_the_old_result_at_once(app, window):
    found = checked(app, window)
    QApplication.clipboard().setText("Court.")
    window.engine.check = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine down"))
    window._check_failed = lambda message: None   # no dialog in the test
    window.paste_and_check()
    assert window.margin.widget().findChildren(QLabel)[0].text() == "Issues appear here after a check."
    window.apply(found[2], "Healpy")    # an outdated issue, beyond the new text: nothing happens
    assert window.editor.toPlainText() == "Court."


def test_one_check_at_a_time(app, window):
    window.editor.setPlainText(TEXT)
    calls = len(window.engine.calls)
    window.check()
    window.check()  # Ctrl+Enter again while the first check runs
    wait_for(app, lambda: window.language)
    app.processEvents()
    assert len(window.engine.calls) == calls + 1
    assert window.check_button.isEnabled()


def test_refused_dictionary_word_is_explained(app, window):
    window.add_word("two words")
    assert window.status.text().startswith("Not added")
    assert window.user.words[""] == set()
