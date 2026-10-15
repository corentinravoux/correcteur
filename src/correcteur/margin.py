"""The margin beside the sheet: one proofreader's note per issue."""

from __future__ import annotations

from typing import TYPE_CHECKING

import re

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QFrame, QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import issues as iss
from .i18n import _
from .theme import serif
from .userdata import LANGUAGE_NAMES, language_of

if TYPE_CHECKING:
    from .app import Window

MAX_NOTES = 150      # beyond this the margin only counts the rest
MAX_CHIPS = 3
PANEL_MIN, PANEL_MAX = 290, 330
# Widths that fit the narrowest panel: a note's content is the panel minus the
# scroll bar, the page margin and the note's own margins.
WORD_PX = PANEL_MIN - 50     # the flagged words
CHIP_PX = PANEL_MIN - 75     # the text of one suggestion button
_LONG_TOKEN = re.compile(r"\S{24,}")


def shown(text: str) -> str:
    """Make empty or blank text visible."""
    if text == "":
        return _("(delete)")
    return text.replace(" ", "·") if not text.strip() else text


def _elide(widget: QWidget, text: str, pixels: int, mode=Qt.TextElideMode.ElideRight) -> str:
    """``text`` shortened with "…" to fit ``pixels`` in the widget's font."""
    return QFontMetrics(widget.font()).elidedText(text, mode, pixels)


def breakable(text: str) -> str:
    """Let very long words (URLs, file paths) wrap, by allowing breaks inside them."""
    return _LONG_TOKEN.sub(lambda m: "\u200b".join(m.group()[k:k + 12] for k in range(0, len(m.group()), 12)), text)


def _muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setProperty("muted", True)
    label.setWordWrap(wrap)
    if wrap:  # wraps to the width it gets, never asks for more
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class FlowLayout(QLayout):
    """Lays its widgets out left to right, starting a new line when the width runs out."""

    def __init__(self, spacing: int = 6, line_spacing: int = 4):
        super().__init__()
        self._items = []
        self._spacing, self._line_spacing = spacing, line_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint().boundedTo(QSize(rect.width(), 10 ** 6))
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self._line_spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


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

        flagged = QLabel()
        font = serif(12.5)
        font.setStrikeOut(issue.kind != "style")
        flagged.setFont(font)
        flagged.setText(_elide(flagged, shown(word), WORD_PX, Qt.TextElideMode.ElideMiddle))
        if flagged.text() != shown(word):
            flagged.setToolTip(word)
        flagged.setStyleSheet(f"color: {self.color.name()};")
        flagged.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(flagged)

        text = issue.message if issue.source == "LanguageTool" else f"{issue.message} ({issue.source})"
        message = _muted(breakable(text))
        small = QFont(message.font())
        small.setPointSizeF(small.pointSizeF() * 0.92)
        message.setFont(small)
        layout.addWidget(message)

        if issue.replacements:
            chips = FlowLayout()
            for replacement in issue.replacements[:MAX_CHIPS]:
                chip = QPushButton()
                chip.setObjectName("chip")
                chip.setText(_elide(chip, shown(replacement), CHIP_PX).replace("&", "&&"))
                chip.setToolTip(_("Replace with “{replacement}”", replacement=replacement))
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.clicked.connect(lambda _=False, r=replacement: window.apply(issue, r))
                chips.addWidget(chip)
            layout.addLayout(chips)

        actions = FlowLayout(spacing=12, line_spacing=0)
        for label, tip, slot in self._actions(word):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.setObjectName("link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            actions.addWidget(button)
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
        self.setMinimumWidth(PANEL_MIN)
        self.setMaximumWidth(PANEL_MAX)
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
        legend = _muted("&nbsp; ".join(  # may wrap between items, never inside one
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
