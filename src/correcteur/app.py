"""The window: paste text, check it, fix it, copy it back."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QLibraryInfo, QObject, QPoint, QSettings, Qt, QTimer, QTranslator, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QHelpEvent, QIcon, QKeySequence, QShortcut,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QStyleFactory, QTextEdit, QToolTip,
                               QVBoxLayout, QWidget, QWidgetAction)

from . import issues as iss
from . import theme as th
from . import i18n
from .i18n import _, language_name, ngettext
from .latex import looks_like_latex
from .config import Config, load
from .dialogs import ExceptionsDialog
from .engine import CheckResult, EngineError, LanguageTool
from .margin import Margin, shown
from .userdata import LANGUAGE_NAMES, UserData, language_of

LANGUAGES = [("Auto", "auto"), ("Français", "fr"), ("English (US)", "en-US"), ("English (UK)", "en-GB")]
MAX_SUGGESTIONS = 7
NOT_A_WORD = "Not added: a dictionary entry is one word, without spaces, not starting with #."
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
        self.window_.text_edited()

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
        if e.reason() == e.Reason.Keyboard:  # the Menu key or Shift+F10: the issue at the cursor
            issue = self.window_.current_issue()
            if issue:
                self.window_.show_menu(issue, self.window_.below(issue), keyboard=True)
                return
        issue = self.issue_at(e.pos())
        if issue:
            self.window_.show_menu(issue, e.globalPos())
        else:
            super().contextMenuEvent(e)


def _install_qt_french() -> None:
    """Translate Qt's own words, such as "Close" in dialogs, once per application."""
    app = QApplication.instance()
    if app is None or app.property("correcteur_fr"):
        return
    translator = QTranslator(app)
    if translator.load("qtbase_fr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        app.setProperty("correcteur_fr", True)


class Window(QMainWindow):
    def __init__(self, config: Config, engine: LanguageTool | None = None):
        super().__init__()
        if i18n.setup(config.interface) == "fr":
            _install_qt_french()
        self.config = config
        self.engine = engine or LanguageTool(config)
        self.pool = ThreadPoolExecutor(max_workers=1)  # one worker: checks run in order, after start-up
        self.engine_state = "starting"  # starting, ready, failed
        self.language = ""
        self.note = ""
        self.checked_text, self.checked_issues = "", []  # the last check, to come back to after an undo
        self.stale = False      # edited by hand since the last check
        self.checking = False   # a check is queued or running
        self._closing = False
        self._own_edit = False  # an edit made by applying a suggestion
        self.user = UserData(config)
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
        self.editor.setPlaceholderText(_("Paste your text here, then press Check.\n\n"
                                         "Underlined words have a suggestion: click one to fix it."))
        self.margin = Margin(self)

        self.lang_box = QComboBox()
        for label, code in LANGUAGES:
            self.lang_box.addItem(_(label), code)
        self.lang_box.setCurrentIndex(self.settings.value("language", 0, type=int))
        self.lang_box.setToolTip(_("Auto detects the language of each paragraph"))
        self.picky_box = QCheckBox(_("Style suggestions"))
        self.picky_box.setToolTip(_("Also flag wordiness, repetitions and other matters of style"))
        self.picky_box.setChecked(self.settings.value("picky", "false") == "true")
        self.latex_box = QCheckBox("LaTeX")
        self.latex_box.setToolTip(_("Skip LaTeX commands, maths and comments; check only the prose.\n"
                                    "Ticked automatically when pasted text looks like LaTeX."))
        self.latex_box.setChecked(self.settings.value("latex", "false") == "true")

        self.paste_button = self._button(_("Paste && check"), _("Replace the text with the clipboard and check it"),
                                         "Ctrl+Shift+V", self.paste_and_check)
        self.check_button = self._button(_("Check"), _("Check the text"), "Ctrl+Return", self.check)
        self.check_button.setObjectName("primary")
        self.accept_button = self._button(_("Accept all"), _("Apply the first suggestion of every issue; "
                                                             "Ctrl+Z undoes it"), None, self.accept_all)
        self.copy_button = self._button(_("Copy text"), _("Copy the whole text to the clipboard"),
                                        "Ctrl+Shift+C", self.copy)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        self.exceptions_button = QPushButton()
        self.exceptions_button.setObjectName("link")
        self.exceptions_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exceptions_button.setToolTip(_("Rules turned off, ignored issues and dictionary words"))
        self.exceptions_button.clicked.connect(lambda: ExceptionsDialog(self).exec())

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
        bottom.addWidget(self.exceptions_button)
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
        QShortcut(QKeySequence("F8"), self, lambda: self.next_issue(menu=True))
        QShortcut(QKeySequence("Shift+F8"), self, lambda: self.next_issue(backwards=True, menu=True))
        self.editor.cursorPositionChanged.connect(lambda: self.margin.set_current(self.current_issue()))
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
        self.update_status(keep_note=self.note == _("Starting LanguageTool, then checking…"))

    def _engine_failed(self, message: str) -> None:
        if self._closing:
            return
        self.engine_state = "failed"
        self.update_status()
        QMessageBox.critical(self, _("LanguageTool did not start"), message)

    # ----- checking -----------------------------------------------------
    def check(self) -> None:
        text = self.editor.toPlainText()
        if self.engine_state == "failed":
            self.note = _("LanguageTool is not running. Close Correcteur and open it again.")
        elif not text.strip():
            self.note = _("Nothing to check yet: paste or type some text.")
        elif self.checking:  # one at a time; a text changed meanwhile is caught when the result arrives
            return
        else:
            self.note = _("Checking…") if self.engine_state == "ready" else _("Starting LanguageTool, then checking…")
            self.checking = True
            self.check_button.setEnabled(False)
            self.pool.submit(self._run_check, text, self.lang_box.currentData(), self.picky_box.isChecked(),
                             set(self.user.rules), self.latex_box.isChecked())
        self.update_status(keep_note=True)

    def _run_check(self, text: str, language: str, picky: bool, disabled: set[str], tex: bool) -> None:
        try:
            result = self.engine.check(text, language, picky, disabled, tex)
        except Exception as e:
            self._emit(self.bridge.check_failed, str(e))
        else:
            self._emit(self.bridge.checked, text, result)

    def _checked(self, text: str, result: CheckResult) -> None:
        self.checking = False
        self.check_button.setEnabled(True)
        if self.editor.toPlainText() != text:
            self.note = _("The text changed during the check. Press Check again.")
            self.update_status(keep_note=True)
            return
        self.checked_text, self.checked_issues, self.stale = text, result.issues, False
        self.editor.set_issues(self.user.filter(result.issues, text))
        self.language = result.language
        self.note = _("Some results are missing: the text may be too long.") if result.incomplete else ""
        self.update_status(keep_note=bool(self.note))
        self.refresh_margin()

    def _check_failed(self, message: str) -> None:
        self.checking = False
        self.check_button.setEnabled(True)
        if self._closing:  # the engine was stopped under a running check
            return
        self.note = _("The check failed.")
        self.update_status(keep_note=True)
        QMessageBox.warning(self, _("The check failed"), message)

    # ----- fixing -------------------------------------------------------
    def show_menu(self, issue: iss.Issue, where: QPoint, keyboard: bool = False) -> None:
        """The issue's menu. From the keyboard, Enter applies the first suggestion and
        the next issue's menu opens; Esc stops."""
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
        first = None
        for replacement in issue.replacements[:MAX_SUGGESTIONS]:
            act = menu.addAction(shown(replacement).replace("&", "&&"))
            act.setFont(bold)
            act.triggered.connect(lambda _=False, r=replacement: self.apply(issue, r))
            first = first or act
        if not issue.replacements:
            menu.addAction(_("No suggestion")).setEnabled(False)
        menu.addSeparator()
        if keyboard:
            menu.addAction(_("&Skip"), lambda: None)
        menu.addAction(_("&Ignore"), lambda: self.ignore(issue))
        word = iss.u16_slice(self.editor.toPlainText(), issue.offset, issue.end)
        quoted = word.replace("&", "&&")
        if issue.kind == "spelling" and word.strip():
            lang = language_of(issue.language)
            if lang:
                menu.addAction(_("&Add “{word}” to the {language} dictionary", word=quoted,
                                 language=_(LANGUAGE_NAMES[lang])), lambda: self.add_word(word, lang))
            menu.addAction(_("Add “{word}” to the dictionary of all &languages", word=quoted),
                           lambda: self.add_word(word, ""))
        if issue.kind != "spelling":  # one rule covers all spelling: never offer to turn it off
            menu.addAction(_("&Turn off this rule"), lambda: self.turn_off(issue))
        if keyboard and first:
            menu.setActiveAction(first)
        chosen = self.run_menu(menu, where)
        if keyboard and chosen is not None:
            QTimer.singleShot(0, lambda: self.next_issue(menu=True))

    def run_menu(self, menu: QMenu, where: QPoint):
        """Show ``menu`` and return the chosen action (a seam for the tests)."""
        return menu.exec(where)

    def apply(self, issue: iss.Issue, replacement: str) -> None:
        if issue.end > self.editor.document().characterCount() - 1:  # outdated: beyond the text
            return
        self._own_edit = True
        try:
            self.editor.span(issue).insertText(replacement)
        finally:
            self._own_edit = False

    def reveal(self, issue: iss.Issue) -> None:
        """Select the issue's text in the sheet and scroll to it."""
        self.editor.setTextCursor(self.editor.span(issue))
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def next_issue(self, backwards: bool = False, menu: bool = False) -> None:
        """Select the next (or previous) issue, wrapping around; with ``menu``, open its menu."""
        if not self.editor.issues:
            if menu:
                self.note = _("No issue left.")
                self.update_status(keep_note=True)
            return
        cursor = self.editor.textCursor()
        ordered = sorted(self.editor.issues, key=lambda i: i.offset)
        if backwards:
            before = [i for i in ordered if i.offset < cursor.selectionStart()]
            target = before[-1] if before else ordered[-1]
        else:
            after = [i for i in ordered if i.offset >= cursor.selectionEnd()]
            target = after[0] if after else ordered[0]
        self.reveal(target)
        if menu:
            self.note = _("Enter applies the suggestion, the arrows choose another, Esc stops.")
            self.update_status(keep_note=True)
            QTimer.singleShot(0, lambda: self.show_menu(target, self.below(target), keyboard=True))

    def current_issue(self) -> iss.Issue | None:
        """The issue under the cursor or selection."""
        cursor = self.editor.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        return next((i for i in self.editor.issues if i.offset <= start and end <= i.end), None)

    def below(self, issue: iss.Issue) -> QPoint:
        return self.editor.viewport().mapToGlobal(self.editor.cursorRect(self.editor.span(issue)).bottomLeft())

    def accept_all(self) -> None:
        chosen = iss.non_overlapping(self.editor.issues)
        if not chosen:
            self.note = _("No suggestion to apply.")
            self.update_status(keep_note=True)
            return
        cursor = QTextCursor(self.editor.document())
        self._own_edit = True
        cursor.beginEditBlock()
        for issue in chosen:  # last first, so earlier offsets stay valid
            span = self.editor.span(issue)
            cursor.setPosition(span.anchor())
            cursor.setPosition(span.position(), QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(issue.replacements[0])
        cursor.endEditBlock()
        self._own_edit = False
        self.note = ngettext("Applied {n} suggestion. Ctrl+Z undoes it.",
                             "Applied {n} suggestions. Ctrl+Z undoes them.", len(chosen))
        self.update_status(keep_note=True)

    def ignore(self, issue: iss.Issue) -> None:
        word = iss.u16_slice(self.editor.toPlainText(), issue.offset, issue.end)
        self.user.ignore(issue.rule_id, word, issue.description or issue.message)
        self.refilter()

    def add_word(self, word: str, lang: str = "") -> None:
        """Add ``word`` to the dictionary of ``lang``, or of all languages."""
        if not self.user.add_word(word, lang):
            self.note = _(NOT_A_WORD)
            self.update_status(keep_note=True)
            return
        self.refilter()

    def turn_off(self, issue: iss.Issue) -> None:
        self.user.disable_rule(issue.rule_id, issue.description or issue.message)
        self.refilter()
        self.note = _("Turned off “{rule}”.", rule=issue.description or issue.rule_id)
        self.update_status(keep_note=True)

    def refilter(self) -> None:
        """Hide the issues the user's exceptions now cover."""
        self.editor.set_issues(self.user.filter(self.editor.issues, self.editor.toPlainText()))
        self.issues_changed()

    def exceptions_changed(self) -> None:
        self.refilter()

    def text_edited(self) -> None:
        """Follow any edit: back at the checked text (an undo), the checked issues return."""
        if self.language and self.editor.toPlainText() == self.checked_text:
            self.stale = False
            restored = self.user.filter(self.checked_issues, self.checked_text)
            if restored != self.editor.issues:
                self.editor.set_issues(restored)
        elif self.language and not self._own_edit:
            self.stale = True
        self.issues_changed()

    def issues_changed(self) -> None:
        self.update_status()
        self.margin_timer.start()

    def refresh_margin(self) -> None:
        self.margin_timer.stop()
        if not self.language:
            self.margin.show_hint(_("Issues appear here after a check."))
        else:
            self.margin.show_issues(self.editor.issues, self.editor.toPlainText())
            self.margin.set_current(self.current_issue())

    # ----- clipboard ----------------------------------------------------
    def paste_and_check(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            self.note = _("The clipboard is empty.")
            self.update_status(keep_note=True)
            return
        self.editor.set_issues([])
        self.language = ""  # the old result no longer applies
        self.editor.setPlainText(text)
        self.refresh_margin()
        detected = not self.latex_box.isChecked() and looks_like_latex(text)
        if detected:
            self.latex_box.setChecked(True)
        self.check()
        if detected:
            self.note = _("LaTeX detected: commands and maths are skipped. Checking…")
            self.update_status(keep_note=True)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.editor.toPlainText())
        self.note = _("Text copied.")
        self.update_status(keep_note=True)

    # ----- status -------------------------------------------------------
    def update_status(self, keep_note: bool = False) -> None:
        if not keep_note:
            self.note = ""
        if self.note:
            text = self.note
        elif self.engine_state == "failed":
            text = _("LanguageTool is not running.")
        elif self.engine_state == "starting" and not self.language:
            text = _("Starting LanguageTool…")
        elif not self.language:
            engines = getattr(self.engine, "engines", ["LanguageTool"])
            text = _("Ready to check with {engines}.", engines=_(" and ").join(engines))
        else:
            n = len(self.editor.issues)
            language = _(" and ").join(language_name(x) for x in self.language.split(" + "))
            text = (_("No issues in {language}", language=language) if n == 0 else
                    ngettext("{n} issue in {language}", "{n} issues in {language}", n, language=language))
            if self.stale:
                text += _(" (text edited since the check)")
        self.status.setText(text)
        n = len(self.user.rules) + len(self.user.ignored)
        self.exceptions_button.setText(_("Exceptions ({n})", n=n) if n else _("Exceptions"))
        self.accept_button.setEnabled(any(i.replacements for i in self.editor.issues))

    def closeEvent(self, e) -> None:
        self._closing = True
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
        QMessageBox.critical(None, _("Configuration error"), str(e))
        sys.exit(1)
    window = Window(config)
    window.show()
    sys.exit(app.exec())
