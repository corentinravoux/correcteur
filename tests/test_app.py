"""The window, driven with a fake engine on Qt's offscreen platform."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

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

    def check(self, text, language="auto", picky=False):
        self.calls.append((text, language, picky))
        found = []
        for word, rep, kind in (("Il ont", "Ils ont", "grammar"), ("des pomme", "des pommes", "grammar"),
                                ("Healpix", "Healpy", "spelling")):
            if word in text:
                found.append(Issue(text.index(word), len(word), f"fix {word}", [rep], f"R{len(found)}", kind))
        return CheckResult(found, "French")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    w = Window(Config(engine_dir=None, dictionary=tmp_path / "dictionary.txt"), engine=FakeEngine())
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
    assert window.status.text() == "3 issues (1 spelling, 2 grammar) · French"
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
    found = checked(app, window)
    window.add_word("Healpix")
    assert (tmp_path / "dictionary.txt").read_text() == "Healpix\n"
    assert len(window.editor.issues) == 2
    window.ignore(found[0])
    assert len(window.editor.issues) == 1
    # Both stay silent at the next check.
    assert [i.rule_id for i in checked(app, window)] == ["R1"]


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
