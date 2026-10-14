"""The window: paste text, check it, fix it, copy it back."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QHelpEvent, QIcon, QKeySequence, QShortcut,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QStyleFactory, QTextEdit, QToolTip, QVBoxLayout, QWidget, QWidgetAction)

from . import issues as iss
from . import theme as th
from .latex import looks_like_latex
from .config import Config, load
from .engine import CheckResult, EngineError, LanguageTool
from .margin import Margin, shown

LANGUAGES = [("Auto", "auto"), ("Français", "fr"), ("English (US)", "en-US"), ("English (UK)", "en-GB")]
MAX_SUGGESTIONS = 7
SHEET_WIDTH = 860


class Bridge(QObject):
    """Carries results from the worker thread back to the window."""
    ready = Signal()
    failed = Signal(str)
    checked = Signal(str, object)
    check_failed = Signal(str)


class Editor(QPlainTextEdit):
    def __init__(self, window: Window):
        super().__init__()
        self.window_ = window
        self.issues: list[iss.Issue] = []
        self.setObjectName("sheet")
        self.setFont(th.serif(13))
        self.document().setDocumentMargin(26)
        self.setMaximumWidth(SHEET_WIDTH)
        self.document().contentsChange.connect(self._follow_edit)

    def set_issues(self, issues: list[iss.Issue]) -> None:
        self.issues = issues
        self.paint()

    def _follow_edit(self, pos: int, removed: int, added: int) -> None:
        if self.issues:
            self.issues = iss.shift(self.issues, pos, removed, added)
            self.paint()
            self.window_.issues_changed()

    def paint(self) -> None:
        kinds, tint = self.window_.theme.kinds, self.window_.theme.tint
        last = self.document().characterCount() - 1
        selections = []
        for issue in self.issues:
            if issue.end > last:
                continue
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            color = QColor(kinds[issue.kind])
            fmt.setUnderlineColor(color)
            color.setAlpha(tint)
            fmt.setBackground(color)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = self.span(issue)
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)

    def span(self, issue: iss.Issue) -> QTextCursor:
        cursor = QTextCursor(self.document())
        cursor.setPosition(issue.offset)
        cursor.setPosition(issue.end, QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def issue_at(self, point: QPoint) -> iss.Issue | None:
        pos = self.cursorForPosition(point).position()
        return next((i for i in self.issues if i.offset <= pos <= i.end and i.length), None)

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.ToolTip and isinstance(e, QHelpEvent):
            issue = self.issue_at(self.viewport().mapFromGlobal(e.globalPos()))
            if issue:
                QToolTip.showText(e.globalPos(), issue.message, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mouseReleaseEvent(self, e) -> None:
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton and not self.textCursor().hasSelection():
            issue = self.issue_at(e.position().toPoint())
            if issue:
                below = self.cursorRect(self.span(issue)).bottomLeft()
                self.window_.show_menu(issue, self.viewport().mapToGlobal(below))

    def contextMenuEvent(self, e) -> None:
        issue = self.issue_at(e.pos())
        if issue:
            self.window_.show_menu(issue, e.globalPos())
        else:
            super().contextMenuEvent(e)


class RulesDialog(QDialog):
    """The rules the user turned off, each with a button to turn it back on."""

    def __init__(self, window: Window):
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Rules turned off")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        intro = QLabel("Correcteur never flags these rules. Turn one back on to see its issues "
                       "at the next check.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(2)
        page = QWidget()
        page.setObjectName("marginInner")
        page.setLayout(self.rows)
        scroll = QScrollArea()
        scroll.setObjectName("margin")
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._fill()

    def _fill(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for rule, description in sorted(self.window_.disabled.items(), key=lambda r: r[1].lower()):
            row = QHBoxLayout()
            label = QLabel(f"{description or rule}<br><span style='color:{self.window_.theme.muted}'>{rule}</span>")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            button = QPushButton("Turn on")
            button.clicked.connect(lambda _=False, r=rule: (self.window_.turn_on(r), self._fill()))
            row.addWidget(label, 1)
            row.addWidget(button)
            holder = QWidget()
            holder.setLayout(row)
            self.rows.addWidget(holder)
        if not self.window_.disabled:
            empty = QLabel("No rule is turned off.")
            empty.setProperty("muted", True)
            self.rows.addWidget(empty)
        self.rows.addStretch()


class Window(QMainWindow):
    def __init__(self, config: Config, engine: LanguageTool | None = None):
        super().__init__()
        self.config = config
        self.engine = engine or LanguageTool(config)
        self.pool = ThreadPoolExecutor(max_workers=1)  # one worker: checks run in order, after start-up
        self.engine_state = "starting"  # starting, ready, failed
        self.language = ""
        self.note = ""
        self.dictionary = iss.load_dictionary(config.dictionary)
        self.ignored: set[tuple[str, str]] = set()
        self.disabled = iss.load_rules(config.disabled_rules)
        self.settings = QSettings("correcteur", "correcteur")
        self.theme = th.current()

        self.bridge = Bridge()
        self.bridge.ready.connect(self._engine_ready)
        self.bridge.failed.connect(self._engine_failed)
        self.bridge.checked.connect(self._checked)
        self.bridge.check_failed.connect(self._check_failed)

        self.margin_timer = QTimer(self, singleShot=True, interval=150)
        self.margin_timer.timeout.connect(self.refresh_margin)

        self._build()
        self.apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme(th.current()))
        self._start_engine()

    # ----- layout -------------------------------------------------------
    def _build(self) -> None:
        self.setWindowTitle("Correcteur")
        self.setWindowIcon(QIcon(str(th.ICON)))
        self.setMinimumSize(720, 460)
        self.resize(1180, 720)
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)

        self.editor = Editor(self)
        self.editor.setPlaceholderText("Paste your text here, then press Check.\n\n"
                                       "Underlined words have a suggestion: click one to fix it.")
        self.margin = Margin(self)

        self.lang_box = QComboBox()
        for label, code in LANGUAGES:
            self.lang_box.addItem(label, code)
        self.lang_box.setCurrentIndex(self.settings.value("language", 0, type=int))
        self.lang_box.setToolTip("Auto detects the language of each paragraph")
        self.picky_box = QCheckBox("Style suggestions")
        self.picky_box.setToolTip("Also flag wordiness, repetitions and other matters of style")
        self.picky_box.setChecked(self.settings.value("picky", "false") == "true")
        self.latex_box = QCheckBox("LaTeX")
        self.latex_box.setToolTip("Skip LaTeX commands, maths and comments; check only the prose.\n"
                                  "Ticked automatically when pasted text looks like LaTeX.")
        self.latex_box.setChecked(self.settings.value("latex", "false") == "true")

        self.paste_button = self._button("Paste && check", "Replace the text with the clipboard and check it",
                                         "Ctrl+Shift+V", self.paste_and_check)
        self.check_button = self._button("Check", "Check the text", "Ctrl+Return", self.check)
        self.check_button.setObjectName("primary")
        self.accept_button = self._button("Accept all", "Apply the first suggestion of every issue; "
                                          "Ctrl+Z undoes it", None, self.accept_all)
        self.copy_button = self._button("Copy text", "Copy the whole text to the clipboard",
                                        "Ctrl+Shift+C", self.copy)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        self.rules_button = QPushButton()
        self.rules_button.setObjectName("link")
        self.rules_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rules_button.setToolTip("See the rules you turned off, and turn them back on")
        self.rules_button.clicked.connect(lambda: RulesDialog(self).exec())

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.lang_box)
        top.addSpacing(6)
        top.addWidget(self.picky_box)
        top.addWidget(self.latex_box)
        top.addStretch()
        top.addWidget(self.paste_button)
        top.addWidget(self.check_button)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(self.editor, 1)
        body.addWidget(self.margin)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(self.status)
        bottom.addSpacing(10)
        bottom.addWidget(self.rules_button)
        bottom.addStretch(1)
        bottom.addWidget(self.accept_button)
        bottom.addWidget(self.copy_button)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)
        layout.addLayout(top)
        layout.addLayout(body, 1)
        layout.addLayout(bottom)
        desk = QWidget()
        desk.setObjectName("desk")
        desk.setLayout(layout)
        self.setCentralWidget(desk)

        QShortcut(QKeySequence("Ctrl+Enter"), self, self.check)  # keypad Enter
        QShortcut(QKeySequence("F8"), self, self.next_issue)
        QShortcut(QKeySequence("Shift+F8"), self, lambda: self.next_issue(backwards=True))
        self.editor.setFocus()
        self.update_status()

    def _button(self, label: str, tip: str, keys: str | None, slot) -> QPushButton:
        button = QPushButton(label)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if keys:
            QShortcut(QKeySequence(keys), self, slot)
            tip += f" ({QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText)})"
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def apply_theme(self, theme: th.Theme | None = None) -> None:
        self.theme = theme or self.theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setPalette(th.palette(self.theme))
            app.setStyleSheet(th.stylesheet(self.theme))
        self.editor.paint()
        self.refresh_margin()

    # ----- engine -------------------------------------------------------
    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:  # the window was closed while the worker was busy
            pass

    def _start_engine(self) -> None:
        try:
            self.engine.start()  # from the main thread, so the server lives as long as the app
        except EngineError as e:
            self._engine_failed(str(e))
            return
        self.pool.submit(self._wait_engine)

    def _wait_engine(self) -> None:
        try:
            self.engine.wait_ready()
            self.engine.warm_up()
        except Exception as e:
            self._emit(self.bridge.failed, str(e))
        else:
            self._emit(self.bridge.ready)

    def _engine_ready(self) -> None:
        if self.engine_state == "starting":
            self.engine_state = "ready"
        self.update_status(keep_note=self.note == "Starting LanguageTool, then checking…")

    def _engine_failed(self, message: str) -> None:
        self.engine_state = "failed"
        self.update_status()
        QMessageBox.critical(self, "LanguageTool did not start", message)

    # ----- checking -----------------------------------------------------
    def check(self) -> None:
        text = self.editor.toPlainText()
        if self.engine_state == "failed":
            self.note = "LanguageTool is not running. Close Correcteur and open it again."
        elif not text.strip():
            self.note = "Nothing to check yet: paste or type some text."
        else:
            self.note = "Checking…" if self.engine_state == "ready" else "Starting LanguageTool, then checking…"
            self.check_button.setEnabled(False)
            self.pool.submit(self._run_check, text, self.lang_box.currentData(), self.picky_box.isChecked(),
                             set(self.disabled), self.latex_box.isChecked())
        self.update_status(keep_note=True)

    def _run_check(self, text: str, language: str, picky: bool, disabled: set[str], tex: bool) -> None:
        try:
            result = self.engine.check(text, language, picky, disabled, tex)
        except Exception as e:
            self._emit(self.bridge.check_failed, str(e))
        else:
            self._emit(self.bridge.checked, text, result)

    def _checked(self, text: str, result: CheckResult) -> None:
        self.check_button.setEnabled(True)
        if self.editor.toPlainText() != text:
            self.note = "The text changed during the check. Press Check again."
            self.update_status(keep_note=True)
            return
        self.editor.set_issues(iss.drop_known(result.issues, text, self.dictionary, self.ignored, self.disabled))
        self.language = result.language
        self.note = "Some results are missing: the text may be too long." if result.incomplete else ""
        self.update_status(keep_note=bool(self.note))
        self.refresh_margin()

    def _check_failed(self, message: str) -> None:
        self.check_button.setEnabled(True)
        self.note = "The check failed."
        self.update_status(keep_note=True)
        QMessageBox.warning(self, "The check failed", message)

    # ----- fixing -------------------------------------------------------
    def show_menu(self, issue: iss.Issue, where: QPoint) -> None:
        menu = QMenu(self)
        header = QLabel(issue.message)
        header.setWordWrap(True)
        header.setMaximumWidth(420)
        header.setContentsMargins(10, 6, 10, 6)
        header.setStyleSheet(f"color: {self.theme.muted}; "
                             f"border-left: 3px solid {self.theme.kinds[issue.kind]};")
        action = QWidgetAction(menu)
        action.setDefaultWidget(header)
        menu.addAction(action)
        menu.addSeparator()
        bold = QFont(menu.font())
        bold.setBold(True)
        for replacement in issue.replacements[:MAX_SUGGESTIONS]:
            act = menu.addAction(shown(replacement))
            act.setFont(bold)
            act.triggered.connect(lambda _=False, r=replacement: self.apply(issue, r))
        if not issue.replacements:
            menu.addAction("No suggestion").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Ignore", lambda: self.ignore(issue))
        word = iss.u16_slice(self.editor.toPlainText(), issue.offset, issue.end)
        if issue.kind == "spelling" and word.strip():
            menu.addAction(f"Add “{word}” to dictionary", lambda: self.add_word(word))
        if issue.kind != "spelling":  # one rule covers all spelling: never offer to turn it off
            menu.addAction("Turn off this rule", lambda: self.turn_off(issue))
        menu.exec(where)

    def apply(self, issue: iss.Issue, replacement: str) -> None:
        self.editor.span(issue).insertText(replacement)

    def reveal(self, issue: iss.Issue) -> None:
        """Select the issue's text in the sheet and scroll to it."""
        self.editor.setTextCursor(self.editor.span(issue))
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def next_issue(self, backwards: bool = False) -> None:
        if not self.editor.issues:
            return
        here = self.editor.textCursor().selectionStart() if backwards else self.editor.textCursor().selectionEnd()
        ordered = sorted(self.editor.issues, key=lambda i: i.offset)
        if backwards:
            before = [i for i in ordered if i.offset < here]
            self.reveal(before[-1] if before else ordered[-1])
        else:
            after = [i for i in ordered if i.offset >= here]
            self.reveal(after[0] if after else ordered[0])

    def accept_all(self) -> None:
        chosen = iss.non_overlapping(self.editor.issues)
        if not chosen:
            self.note = "No suggestion to apply."
            self.update_status(keep_note=True)
            return
        cursor = QTextCursor(self.editor.document())
        cursor.beginEditBlock()
        for issue in chosen:  # last first, so earlier offsets stay valid
            span = self.editor.span(issue)
            cursor.setPosition(span.anchor())
            cursor.setPosition(span.position(), QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(issue.replacements[0])
        cursor.endEditBlock()
        self.note = f"Applied {len(chosen)} suggestion{'s' if len(chosen) > 1 else ''}. Ctrl+Z undoes them."
        self.update_status(keep_note=True)

    def ignore(self, issue: iss.Issue) -> None:
        word = iss.u16_slice(self.editor.toPlainText(), issue.offset, issue.end)
        self.ignored.add((issue.rule_id, word))
        self.editor.set_issues([i for i in self.editor.issues if i != issue])
        self.issues_changed()

    def add_word(self, word: str) -> None:
        iss.add_to_dictionary(self.config.dictionary, word)
        self.dictionary.add(word)
        text = self.editor.toPlainText()
        self.editor.set_issues(iss.drop_known(self.editor.issues, text, self.dictionary, set()))
        self.issues_changed()

    def turn_off(self, issue: iss.Issue) -> None:
        self.disabled[issue.rule_id] = issue.description or issue.message
        iss.save_rules(self.config.disabled_rules, self.disabled)
        self.editor.set_issues([i for i in self.editor.issues if i.rule_id != issue.rule_id])
        self.issues_changed()
        self.note = f"Turned off “{issue.description or issue.rule_id}”."
        self.update_status(keep_note=True)

    def turn_on(self, rule: str) -> None:
        self.disabled.pop(rule, None)
        iss.save_rules(self.config.disabled_rules, self.disabled)
        self.note = "Rule turned back on. Check again to see its issues."
        self.update_status(keep_note=True)

    def issues_changed(self) -> None:
        self.update_status()
        self.margin_timer.start()

    def refresh_margin(self) -> None:
        self.margin_timer.stop()
        if not self.language:
            self.margin.show_hint("Issues appear here after a check.")
        else:
            self.margin.show_issues(self.editor.issues, self.editor.toPlainText())

    # ----- clipboard ----------------------------------------------------
    def paste_and_check(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            self.note = "The clipboard is empty."
            self.update_status(keep_note=True)
            return
        self.editor.set_issues([])
        self.editor.setPlainText(text)
        detected = not self.latex_box.isChecked() and looks_like_latex(text)
        if detected:
            self.latex_box.setChecked(True)
        self.check()
        if detected:
            self.note = "LaTeX detected: commands and maths are skipped. Checking…"
            self.update_status(keep_note=True)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.editor.toPlainText())
        self.note = "Text copied."
        self.update_status(keep_note=True)

    # ----- status -------------------------------------------------------
    def update_status(self, keep_note: bool = False) -> None:
        if not keep_note:
            self.note = ""
        if self.note:
            text = self.note
        elif self.engine_state == "failed":
            text = "LanguageTool is not running."
        elif self.engine_state == "starting" and not self.language:
            text = "Starting LanguageTool…"
        elif not self.language:
            engines = getattr(self.engine, "engines", ["LanguageTool"])
            text = f"Ready to check with {' and '.join(engines)}."
        else:
            n = len(self.editor.issues)
            count = "No issues" if n == 0 else f"{n} issue{'s' if n > 1 else ''}"
            text = f"{count} in {self.language.replace(' + ', ' and ')}"
        self.status.setText(text)
        n = len(self.disabled)
        self.rules_button.setText(f"{n} rule{'s' if n > 1 else ''} off")
        self.rules_button.setVisible(n > 0)
        self.accept_button.setEnabled(any(i.replacements for i in self.editor.issues))

    def closeEvent(self, e) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("language", self.lang_box.currentIndex())
        self.settings.setValue("picky", "true" if self.picky_box.isChecked() else "false")
        self.settings.setValue("latex", "true" if self.latex_box.isChecked() else "false")
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.engine.stop()
        super().closeEvent(e)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Correcteur")
    app.setDesktopFileName("correcteur")
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setWindowIcon(QIcon(str(th.ICON)))
    try:
        config = load()
    except (ValueError, OSError) as e:
        QMessageBox.critical(None, "Configuration error", str(e))
        sys.exit(1)
    window = Window(config)
    window.show()
    sys.exit(app.exec())
