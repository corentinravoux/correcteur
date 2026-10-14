# Correcteur

[![tests](https://github.com/corentinravoux/correcteur/actions/workflows/tests.yml/badge.svg)](https://github.com/corentinravoux/correcteur/actions/workflows/tests.yml)

A small desktop grammar checker for French and English. Paste text, press
**Check**, fix what is underlined, copy the result back.

Checking is done by [LanguageTool](https://github.com/languagetool-org/languagetool),
running as a private server on your machine: no account, no subscription, and
the text never leaves your computer. The server starts when the window opens and
stops when it closes, so nothing stays in memory between uses.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshot-dark.png">
  <img alt="Correcteur: a French and an English paragraph with underlined issues, and the list of issues in the margin" src="docs/screenshot.png">
</picture>

## Install

Requirements: Linux, Python ≥ 3.11, and a Java runtime ≥ 17. On X11, Qt also
needs `libxcb-cursor0` (Debian/Ubuntu: `sudo apt install libxcb-cursor0`).

```bash
pip install correcteur
correcteur --download --grammalecte --ngrams fr,en   # engines into ~/.local/share/correcteur
correcteur --install-desktop                         # adds "Correcteur" to the application menu
```

`--download` alone fetches LanguageTool (250 MB). The extras are optional:

- `--grammalecte` adds [Grammalecte](https://grammalecte.net) (25 MB), a French
  grammar checker used as a second opinion on French text. When both engines
  flag the same words, Grammalecte's fix is offered first.
- `--ngrams fr,en` improves the detection of confused words (*their/there*,
  *a/à*, *sa/ça*). It is large: French 1.8 GB, English 9 GB to download, 18 GB
  unpacked for both.

`--into DIR` installs somewhere else; point `engine_dir`, `ngrams_dir` and
`grammalecte_dir` at it in the configuration.

## Use

Start **Correcteur** from the menu, or run `correcteur`.

| Action | How |
|---|---|
| Check | **Check** button or `Ctrl+Enter` |
| Paste the clipboard and check it | **Paste & check** or `Ctrl+Shift+V` |
| Fix one issue | click a suggestion in the margin, or click the underlined text |
| See the explanation | read the margin note, or hover the underlined text |
| Go to the next / previous issue | `F8` / `Shift+F8`, or click a margin note |
| Apply every first suggestion | **Accept all** (`Ctrl+Z` undoes it) |
| Copy the text | **Copy text** or `Ctrl+Shift+C` |

Every issue gets a note in the margin: the flagged words struck through, the
explanation, and one button per suggestion. Colours: red spelling, blue
grammar, green style, amber typography. The window follows the desktop's light
or dark setting.

**Style suggestions** enables LanguageTool's "picky" rules (wordiness,
repetitions…). In **Auto** mode each paragraph is checked in its own language,
so French and English can be mixed in one text.

**LaTeX** checks only the prose of LaTeX source: commands, maths, citations,
references and comments are skipped, while section titles, emphasis, captions
and footnotes are checked. It is ticked automatically when pasted text looks
like LaTeX. An issue that overlaps a command has no suggestion, so that fixing
it cannot break the command.

**Turn off rule**, in a margin note or the menu of an underline, stops a rule
for good. The rules turned off are listed behind the "rules off" link at the
bottom, where each can be turned back on. Spelling has no such action: add the
word to the dictionary instead.

**Accept all** takes the first suggestion each time, which is not always the
right one (*des pomme* → *de la pomme* rather than *des pommes*); look over
the result.

A menu entry *Add to dictionary* teaches it your own words; they are stored one
per line in `~/.config/correcteur/dictionary.txt`.

Without the window:

```bash
correcteur --check notes.txt            # prints line:column, issue and suggestion
correcteur --check chapter.tex          # .tex files are read as LaTeX (or force --latex / --no-latex)
echo "Il ont faim." | correcteur --check - --language fr
```

## Configure

Optional, in `~/.config/correcteur/config.toml`:

```toml
engine_dir = "~/Software/languagetool"        # a LanguageTool-X.Y folder, or its parent
ngrams_dir = "~/Software/languagetool/ngrams"  # folder holding en/ and fr/
java = "java"
heap = "1g"                                     # Java memory limit
english_variant = "en-US"                       # used by Auto: en-US or en-GB
dictionary = "~/.config/correcteur/dictionary.txt"
disabled_rules = "~/.config/correcteur/disabled-rules.txt"
grammalecte = true                              # use Grammalecte when installed
grammalecte_dir = "~/.local/share/correcteur/grammalecte"
```

## Develop

```bash
pip install -e ".[dev]"
pytest          # the integration tests run only when LanguageTool is installed
```

### Release

Once, on PyPI: add a trusted publisher for the project `correcteur` with owner
`corentinravoux`, repository `correcteur`, workflow `release.yml` and
environment `pypi`; and create the `pypi` environment in the GitHub repository
settings. Then, for each release:

1. set `__version__` in `src/correcteur/__init__.py` and date the entry in `CHANGELOG.md`;
2. commit, then `git tag v0.1.0 && git push origin main v0.1.0`.

The `release` workflow checks that the tag matches the version, builds,
publishes to PyPI and creates the GitHub release.

## Licence

MIT. LanguageTool (LGPL-2.1) and Grammalecte (GPL-3.0) are downloaded
separately, not bundled.
