"""The Exceptions window: rules turned off, ignored issues, dictionary words."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTabWidget, QToolTip, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .i18n import _

NOT_A_WORD = "Not added: a dictionary entry is one word, without spaces, not starting with #."
from .userdata import LANGUAGE_NAMES

if TYPE_CHECKING:
    from .app import Window


class _Page(QWidget):
    """A filterable list with a button acting on the selected rows."""

    def __init__(self, intro: str, columns: list[str], action: str, on_action):
        super().__init__()
        self.on_action = on_action
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        hint = QLabel(intro)
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Filter"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(columns)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.itemSelectionChanged.connect(self._selection)
        layout.addWidget(self.tree, 1)
        self.extra = QHBoxLayout()
        layout.addLayout(self.extra)
        self.button = QPushButton(action)
        self.button.setEnabled(False)
        self.button.clicked.connect(lambda: self.on_action([i.data(0, Qt.ItemDataRole.UserRole)
                                                            for i in self.tree.selectedItems()]))
        self.extra.addStretch()
        self.extra.addWidget(self.button)

    def fill(self, rows: list[tuple[list[str], object]]) -> None:
        self.tree.clear()
        for columns, key in rows:
            item = QTreeWidgetItem(columns)
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.tree.addTopLevelItem(item)
        self.tree.sortItems(0, Qt.SortOrder.AscendingOrder)
        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        needle = text.casefold()
        for k in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(k)
            shown = any(needle in item.text(c).casefold() for c in range(self.tree.columnCount()))
            item.setHidden(not shown)

    def _selection(self) -> None:
        self.button.setEnabled(bool(self.tree.selectedItems()))


class ExceptionsDialog(QDialog):
    def __init__(self, window: Window):
        super().__init__(window)
        self.window_ = window
        self.user = window.user
        self.setWindowTitle(_("Exceptions"))
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.rules = _Page(_("These rules are never applied. Turn one back on to see its issues at the next check."),
                           [_("Rule"), _("Identifier")], _("Turn back on"), self._enable)
        self.ignored = _Page(_("These issues were ignored and are never flagged again for the same text."),
                             [_("Text"), _("Rule"), _("Identifier")], _("Flag again"), self._unignore)
        self.words = _Page(_("Words that are never flagged as misspelt, for every language or for one."),
                           [_("Word"), _("Language")], _("Remove"), self._remove_words)
        self.new_word = QLineEdit()
        self.new_word.setPlaceholderText(_("New word"))
        self.new_word.returnPressed.connect(self._add_word)
        self.new_lang = QComboBox()
        for lang, name in LANGUAGE_NAMES.items():
            self.new_lang.addItem(_(name).capitalize(), lang)
        add = QPushButton(_("Add"))
        add.clicked.connect(self._add_word)
        for k, widget in enumerate((self.new_word, self.new_lang, add)):
            self.words.extra.insertWidget(k, widget)

        for page in (self.rules, self.ignored, self.words):
            self.tabs.addTab(page, "")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.rules.fill([([desc or rule, rule], rule) for rule, desc in self.user.rules.items()])
        self.ignored.fill([([text, desc or rule, rule], (rule, text))
                           for (rule, text), desc in self.user.ignored.items()])
        self.words.fill([([word, _(LANGUAGE_NAMES[lang]).capitalize()], (word, lang))
                         for lang, words in self.user.words.items() for word in words])
        for k, (label, n) in enumerate((("Rules turned off ({n})", len(self.user.rules)),
                                        ("Ignored ({n})", len(self.user.ignored)),
                                        ("Dictionary ({n})", sum(map(len, self.user.words.values()))))):
            self.tabs.setTabText(k, _(label, n=n))
        self.window_.exceptions_changed()

    def _enable(self, rules: list[str]) -> None:
        for rule in rules:
            self.user.enable_rule(rule)
        self.refresh()

    def _unignore(self, pairs: list[tuple[str, str]]) -> None:
        for rule, text in pairs:
            self.user.unignore(rule, text)
        self.refresh()

    def _remove_words(self, entries: list[tuple[str, str]]) -> None:
        for word, lang in entries:
            self.user.remove_word(word, lang)
        self.refresh()

    def _add_word(self) -> None:
        word = self.new_word.text().strip()
        if not word:
            return
        if self.user.add_word(word, self.new_lang.currentData()):
            self.new_word.clear()
            self.refresh()
        else:
            QToolTip.showText(self.new_word.mapToGlobal(self.new_word.rect().bottomLeft()),
                              _(NOT_A_WORD), self.new_word)
            self.new_word.selectAll()
