"""The margin beside the sheet: one proofreader's note per issue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import issues as iss
from .i18n import _
from .theme import serif
from .userdata import LANGUAGE_NAMES, language_of

if TYPE_CHECKING:
    from .app import Window

MAX_NOTES = 150      # beyond this the margin only counts the rest
MAX_CHIPS = 3
CHIP_CHARS = 22
WORD_CHARS = 40


def shown(text: str) -> str:
    """Make empty or blank text visible."""
    if text == "":
        return _("(delete)")
    return text.replace(" ", "·") if not text.strip() else text


def _elide(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def _muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setProperty("muted", True)
    label.setWordWrap(wrap)
    return label


class Note(QFrame):
    def __init__(self, issue: iss.Issue, word: str, window: Window):
        super().__init__()
        self.issue, self.window_ = issue, window
        self.color = QColor(window.theme.kinds[issue.kind])
        self.setObjectName("note")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Show in the text"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 8, 12)
        layout.setSpacing(5)

        flagged = QLabel(_elide(shown(word), WORD_CHARS))
        font = serif(12.5)
        font.setStrikeOut(issue.kind != "style")
        flagged.setFont(font)
        flagged.setStyleSheet(f"color: {self.color.name()};")
        flagged.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(flagged)

        text = issue.message if issue.source == "LanguageTool" else f"{issue.message} ({issue.source})"
        message = _muted(text)
        small = QFont(message.font())
        small.setPointSizeF(small.pointSizeF() * 0.92)
        message.setFont(small)
        layout.addWidget(message)

        if issue.replacements:
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for replacement in issue.replacements[:MAX_CHIPS]:
                chip = QPushButton(_elide(shown(replacement), CHIP_CHARS).replace("&", "&&"))
                chip.setObjectName("chip")
                chip.setToolTip(_("Replace with “{replacement}”", replacement=replacement))
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.clicked.connect(lambda _=False, r=replacement: window.apply(issue, r))
                chips.addWidget(chip)
            chips.addStretch()
            layout.addLayout(chips)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        for label, tip, slot in self._actions(word):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.setObjectName("link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

    def _actions(self, word: str):
        yield _("Ignore"), _("Never flag this again for this text"), lambda: self.window_.ignore(self.issue)
        if self.issue.kind == "spelling" and word.strip():
            lang = language_of(self.issue.language)
            yield (_("Add to dictionary"),
                   _("Add “{word}” to the {language} dictionary", word=word, language=_(LANGUAGE_NAMES[lang]))
                   if lang else _("Add “{word}” to the dictionary of all languages", word=word),
                   lambda: self.window_.add_word(word, lang))
        if self.issue.kind != "spelling":  # one rule covers all spelling: never offer to turn it off
            yield _("Turn off rule"), _("Never apply this rule again"), lambda: self.window_.turn_off(self.issue)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.window_.reveal(self.issue)
        super().mousePressEvent(e)

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        painter = QPainter(self)
        painter.fillRect(QRect(0, 10, 3, self.height() - 22), self.color)


class Margin(QScrollArea):
    def __init__(self, window: Window):
        super().__init__()
        self.window_ = window
        self.setObjectName("margin")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(290)
        self.setMaximumWidth(330)
        self.show_hint(_("Issues appear here after a check."))

    def _fresh(self) -> QVBoxLayout:
        """A new, empty page; :meth:`_attach` shows it once it is filled."""
        self._page = inner = QWidget()  # held until attached, or Python frees it
        inner.setObjectName("marginInner")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 2, 6, 0)
        layout.setSpacing(0)
        return layout

    def _attach(self, layout: QVBoxLayout) -> None:
        # Attach after filling: the scroll area sizes the page when it receives it.
        layout.addStretch()
        self.setWidget(self._page)

    def show_hint(self, text: str) -> None:
        layout = self._fresh()
        hint = _muted(text)
        hint.setContentsMargins(4, 6, 4, 0)
        layout.addWidget(hint)
        self._attach(layout)

    def set_current(self, issue: iss.Issue | None) -> None:
        """Highlight the note of ``issue`` and scroll to it."""
        for note in self.widget().findChildren(Note):
            current = note.issue == issue
            if note.property("current") != current:
                note.setProperty("current", current)
                note.style().unpolish(note)
                note.style().polish(note)
            if current:
                self.ensureWidgetVisible(note, 0, 40)

    def show_issues(self, issues: list[iss.Issue], text: str) -> None:
        if not issues:
            self.show_hint(_("No issues found."))
            return
        layout = self._fresh()
        title = QLabel(_("{n} to review", n=len(issues)))
        bold = QFont(title.font())
        bold.setPointSizeF(bold.pointSizeF() * 1.15)
        bold.setWeight(QFont.Weight.DemiBold)
        title.setFont(bold)
        title.setContentsMargins(4, 0, 4, 2)
        layout.addWidget(title)

        kinds = self.window_.theme.kinds
        counts = [(k, sum(i.kind == k for i in issues)) for k in iss.KINDS]
        legend = _muted("&nbsp;&nbsp;&nbsp;".join(
            f"<span style='color:{kinds[k]}'>●</span>&nbsp;{n}&nbsp;{_(k)}" for k, n in counts if n))
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setContentsMargins(4, 0, 4, 8)
        layout.addWidget(legend)

        for issue in issues[:MAX_NOTES]:
            layout.addWidget(Note(issue, iss.u16_slice(text, issue.offset, issue.end), self.window_))
        if len(issues) > MAX_NOTES:
            more = _muted(_("{n} more, shown in the text.", n=len(issues) - MAX_NOTES))
            more.setContentsMargins(4, 8, 4, 0)
            layout.addWidget(more)
        self._attach(layout)
