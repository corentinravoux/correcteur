"""The window: paste text, check it, fix it, copy it back."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QHelpEvent, QIcon, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QTextEdit, QToolTip, QVBoxLayout,
                               QWidget, QWidgetAction)

from . import issues as iss
from .config import Config, load
from .engine import CheckResult, EngineError, LanguageTool

COLORS = {"spelling": "#d93025", "grammar": "#1a73e8", "style": "#188038", "typography": "#e37400"}
LANGUAGES = [("Auto", "auto"), ("Français", "fr"), ("English (US)", "en-US"), ("English (UK)", "en-GB")]
MAX_SUGGESTIONS = 7


def _shown(replacement: str) -> str:
    if replacement == "":
        return "(delete)"
    return replacement.replace(" ", "·") if not replacement.strip() else replacement


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
        self.document().contentsChange.connect(self._follow_edit)

    def set_issues(self, issues: list[iss.Issue]) -> None:
        self.issues = issues
        self._paint()

    def _follow_edit(self, pos: int, removed: int, added: int) -> None:
        if self.issues:
            self.issues = iss.shift(self.issues, pos, removed, added)
            self._paint()
            self.window_.update_status()

    def _paint(self) -> None:
        last = self.document().characterCount() - 1
        selections = []
        for issue in self.issues:
            if issue.end > last:
                continue
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            color = QColor(COLORS[issue.kind])
            fmt.setUnderlineColor(color)
            color.setAlpha(28)
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
        self.settings = QSettings("correcteur", "correcteur")

        self.bridge = Bridge()
        self.bridge.ready.connect(self._engine_ready)
        self.bridge.failed.connect(self._engine_failed)
        self.bridge.checked.connect(self._checked)
        self.bridge.check_failed.connect(self._check_failed)

        self._build()
        self._start_engine()

    # ----- layout -------------------------------------------------------
    def _build(self) -> None:
        self.setWindowTitle("Correcteur")
        self.setWindowIcon(QIcon.fromTheme("tools-check-spelling"))
        self.resize(820, 560)
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)

        self.editor = Editor(self)
        self.editor.setPlaceholderText("Paste your text here, then press Check (Ctrl+Enter).\n"
                                       "Click an underlined word to fix it.")
        font = QFont(self.editor.font())
        font.setPointSize(12)
        self.editor.setFont(font)

        self.lang_box = QComboBox()
        for label, code in LANGUAGES:
            self.lang_box.addItem(label, code)
        self.lang_box.setCurrentIndex(self.settings.value("language", 0, type=int))
        self.picky_box = QCheckBox("Style suggestions")
        self.picky_box.setToolTip("Also flag wordiness, repetitions and other style issues")
        self.picky_box.setChecked(self.settings.value("picky", "false") == "true")
        legend = QLabel("  ".join(f"<span style='color:{c}'>●</span> {k}" for k, c in COLORS.items()))

        top = QHBoxLayout()
        top.addWidget(QLabel("Language:"))
        top.addWidget(self.lang_box)
        top.addSpacing(12)
        top.addWidget(self.picky_box)
        top.addStretch()
        top.addWidget(legend)

        self.status = QLabel()
        self.paste_button = QPushButton("Paste && check")
        self.check_button = QPushButton("Check")
        self.accept_button = QPushButton("Accept all")
        self.copy_button = QPushButton("Copy")
        self.check_button.setDefault(True)
        self.paste_button.setToolTip("Replace the text with the clipboard and check it (Ctrl+Shift+V)")
        self.check_button.setToolTip("Check the text (Ctrl+Enter)")
        self.accept_button.setToolTip("Apply the first suggestion of every issue (Ctrl+Z undoes it)")
        self.copy_button.setToolTip("Copy the whole text to the clipboard (Ctrl+Shift+C)")
        self.paste_button.clicked.connect(self.paste_and_check)
        self.check_button.clicked.connect(self.check)
        self.accept_button.clicked.connect(self.accept_all)
        self.copy_button.clicked.connect(self.copy)

        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        for button in (self.paste_button, self.check_button, self.accept_button, self.copy_button):
            bottom.addWidget(button)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.editor, 1)
        layout.addLayout(bottom)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        for keys, slot in (("Ctrl+Return", self.check), ("Ctrl+Enter", self.check),
                           ("Ctrl+Shift+V", self.paste_and_check), ("Ctrl+Shift+C", self.copy)):
            QShortcut(QKeySequence(keys), self, slot)
        self.update_status()

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
        self.update_status()

    def _engine_failed(self, message: str) -> None:
        self.engine_state = "failed"
        self.update_status()
        QMessageBox.critical(self, "Correcteur: LanguageTool did not start", message)

    # ----- checking -----------------------------------------------------
    def check(self) -> None:
        text = self.editor.toPlainText()
        if self.engine_state == "failed":
            self.note = "LanguageTool is not running; restart Correcteur."
        elif not text.strip():
            self.note = "Nothing to check."
        else:
            self.note = "Checking…" if self.engine_state == "ready" else "Starting LanguageTool, then checking…"
            self.pool.submit(self._run_check, text, self.lang_box.currentData(), self.picky_box.isChecked())
        self.update_status(keep_note=True)

    def _run_check(self, text: str, language: str, picky: bool) -> None:
        try:
            result = self.engine.check(text, language, picky)
        except Exception as e:
            self._emit(self.bridge.check_failed, str(e))
        else:
            self._emit(self.bridge.checked, text, result)

    def _checked(self, text: str, result: CheckResult) -> None:
        if self.editor.toPlainText() != text:
            self.note = "The text changed during the check: press Check again."
            self.update_status(keep_note=True)
            return
        self.editor.set_issues(iss.drop_known(result.issues, text, self.dictionary, self.ignored))
        self.language = result.language
        self.note = "Results are incomplete: the text may be too long." if result.incomplete else ""
        self.update_status(keep_note=bool(self.note))

    def _check_failed(self, message: str) -> None:
        self.note = "The check failed."
        self.update_status(keep_note=True)
        QMessageBox.warning(self, "Correcteur", message)

    # ----- fixing -------------------------------------------------------
    def show_menu(self, issue: iss.Issue, where: QPoint) -> None:
        menu = QMenu(self)
        header = QLabel(issue.message)
        header.setWordWrap(True)
        header.setMaximumWidth(420)
        header.setContentsMargins(10, 6, 10, 6)
        header.setStyleSheet(f"color: palette(placeholder-text); border-left: 3px solid {COLORS[issue.kind]};")
        action = QWidgetAction(menu)
        action.setDefaultWidget(header)
        menu.addAction(action)
        menu.addSeparator()
        bold = QFont(menu.font())
        bold.setBold(True)
        for replacement in issue.replacements[:MAX_SUGGESTIONS]:
            act = menu.addAction(_shown(replacement))
            act.setFont(bold)
            act.triggered.connect(lambda _=False, r=replacement: self.apply(issue, r))
        if not issue.replacements:
            menu.addAction("No suggestion").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Ignore", lambda: self.ignore(issue))
        word = iss.u16_slice(self.editor.toPlainText(), issue.offset, issue.end)
        if issue.kind == "spelling" and word.strip():
            menu.addAction(f"Add “{word}” to dictionary", lambda: self.add_word(word))
        menu.exec(where)

    def apply(self, issue: iss.Issue, replacement: str) -> None:
        self.editor.span(issue).insertText(replacement)

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
        self.note = f"Applied {len(chosen)} fix{'es' if len(chosen) > 1 else ''} (Ctrl+Z to undo)."
        self.update_status(keep_note=True)

    def ignore(self, issue: iss.Issue) -> None:
        word = iss.u16_slice(self.editor.toPlainText(), issue.offset, issue.end)
        self.ignored.add((issue.rule_id, word))
        self.editor.set_issues([i for i in self.editor.issues if i != issue])
        self.update_status()

    def add_word(self, word: str) -> None:
        iss.add_to_dictionary(self.config.dictionary, word)
        self.dictionary.add(word)
        text = self.editor.toPlainText()
        self.editor.set_issues(iss.drop_known(self.editor.issues, text, self.dictionary, set()))
        self.update_status()

    # ----- clipboard ----------------------------------------------------
    def paste_and_check(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            self.note = "The clipboard is empty."
            self.update_status(keep_note=True)
            return
        self.editor.set_issues([])
        self.editor.setPlainText(text)
        self.check()

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.editor.toPlainText())
        self.note = "Copied to the clipboard."
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
            text = "Ready."
        else:
            counts = {k: sum(i.kind == k for i in self.editor.issues) for k in iss.KINDS}
            total = sum(counts.values())
            if total == 0:
                text = f"No issues · {self.language}"
            else:
                detail = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
                text = f"{total} issue{'s' if total > 1 else ''} ({detail}) · {self.language}"
        self.status.setText(text)
        self.accept_button.setEnabled(any(i.replacements for i in self.editor.issues))

    def closeEvent(self, e) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("language", self.lang_box.currentIndex())
        self.settings.setValue("picky", "true" if self.picky_box.isChecked() else "false")
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.engine.stop()
        super().closeEvent(e)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Correcteur")
    app.setDesktopFileName("correcteur")
    try:
        config = load()
    except (ValueError, OSError) as e:
        QMessageBox.critical(None, "Correcteur: configuration error", str(e))
        sys.exit(1)
    window = Window(config)
    window.show()
    sys.exit(app.exec())
