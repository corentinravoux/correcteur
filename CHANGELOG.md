# Changelog

## 0.1.0 (unreleased)

First release.

- Desktop window: paste text, check it, fix issues from the margin notes or the
  underlines, copy it back. Light and dark themes follow the desktop.
- LanguageTool runs as a private server that lives as long as the window.
- French and English; in Auto mode each paragraph is checked in its own language.
- LaTeX mode: commands, maths, citations and comments are skipped, prose in
  titles, emphasis, captions and footnotes is checked. Ticked automatically
  when pasted text looks like LaTeX.
- Grammalecte as a second opinion on French grammar, when installed.
- Personal dictionary, and rules that can be turned off and back on.
- `correcteur --check FILE` prints the issues without opening the window.
- `correcteur --download` fetches LanguageTool, its n-gram data and Grammalecte.
