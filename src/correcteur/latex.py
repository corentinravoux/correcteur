r"""Read LaTeX source as prose plus markup, so that only the prose is checked.

The result is LanguageTool's *annotated text*: a list of segments, each either
``{"text": ...}`` (checked) or ``{"markup": ..., "interpretAs": ...}`` (skipped,
read as the given replacement). Joined together, the segments give back the
source exactly, so the positions LanguageTool reports are positions in the source.

Maths becomes "X", citations "[1]", references "1". Section titles, emphasis,
footnotes and captions stay prose. Comments, labels, package and file commands,
and verbatim-like environments are skipped.

Macros without arguments, defined in the text or in a preamble passed in with
:func:`parse_macros`, read as what they stand for: ``\newcommand\mnras{MNRAS}``
makes ``\mnras`` read "MNRAS". A macro that stands for maths or symbols reads "X".
"""

from __future__ import annotations

import re
import unicodedata

from .issues import u16_len

MATH = "X"
MATH_ENVS = {name + star for name in ("equation", "align", "alignat", "gather", "multline", "eqnarray",
                                      "flalign", "displaymath", "math", "dmath") for star in ("", "*")}
SKIP_ENVS = {"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment", "tikzpicture",
             "filecontents", "filecontents*", "thebibliography"}
DROP = {"label", "usepackage", "RequirePackage", "documentclass", "bibliographystyle", "bibliography",
        "addbibresource", "input", "include", "includegraphics", "includeonly", "url",
        "newenvironment", "renewenvironment", "DeclareMathOperator", "let", "setlength", "addtolength", "setcounter", "addtocounter", "vspace", "hspace",
        "pagestyle", "thispagestyle", "definecolor", "hypersetup", "graphicspath", "newacronym",
        "acrodef", "newtheorem", "linespread", "geometry", "affiliation", "email", "orcid",
        "rule", "raisebox", "phantom", "hphantom", "vphantom", "bibitem", "selectlanguage", "pagenumbering"}
REFS = {"ref", "eqref", "autoref", "cref", "Cref", "pageref", "vref", "nameref", "crefrange"}
UNITS = {"SI", "si", "num", "qty", "unit", "SIrange", "numrange", "qtyrange", "ang"}
LAYOUT = {"item", "noindent", "indent", "centering", "raggedright", "raggedleft", "maketitle",
          "tableofcontents", "listoffigures", "listoftables", "newpage", "clearpage", "cleardoublepage",
          "par", "smallskip", "medskip", "bigskip", "hline", "toprule", "midrule", "bottomrule", "cline",
          "small", "footnotesize", "scriptsize", "tiny", "normalsize", "large", "Large", "LARGE", "huge",
          "Huge", "bfseries", "itshape", "rmfamily", "sffamily", "ttfamily", "mdseries", "upshape",
          "scshape", "em", "appendix", "frontmatter", "mainmatter", "backmatter", "linebreak", "pagebreak",
          "nolinebreak", "nopagebreak", "newline", "protect", "relax", "xspace", "hfill", "vfill", "null",
          "quad", "qquad", "printbibliography", "selectlanguage", "and", "sloppy", "fussy", "onecolumn",
          "twocolumn", "minitoc", "chapter", "section", "subsection", "subsubsection", "paragraph",
          "subparagraph", "part", "caption", "footnote", "emph", "textbf", "textit", "textsc", "textrm",
          "textsf", "texttt", "underline", "mbox", "text", "title", "author", "date", "abstract"}
FIRST_ARG_MARKUP = {"textcolor", "colorbox", "href", "foreignlanguage", "hyperref", "fcolorbox", "texorpdfstring"}
DEFINERS = {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand", "def", "gdef", "edef", "xdef"}
SYMBOLS = {"ldots": "…", "dots": "…", "textellipsis": "…", "LaTeX": "LaTeX", "TeX": "TeX",
           "textendash": "–", "textemdash": "—", "textquoteright": "’", "textquoteleft": "‘",
           "oe": "œ", "OE": "Œ", "ae": "æ", "AE": "Æ", "ss": "ß", "o": "ø", "O": "Ø", "aa": "å",
           "AA": "Å", "l": "ł", "L": "Ł", "i": "ı", "j": "ȷ", "S": "§", "P": "¶", "copyright": "©",
           "textdegree": "°", "degree": "°", "euro": "€", "og": "«", "fg": "»"}
ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
           ".": "\u0307", "c": "\u0327", "u": "\u0306", "v": "\u030c", "H": "\u030b", "k": "\u0328"}
SPACES = {",": " ", ";": " ", ":": " ", " ": " ", "!": "", "@": "", "/": ""}

_SPECIAL = re.compile(r"[%$\\{}~&]|``|''")
_NAME = re.compile(r"[A-Za-z]+\*?")
_LOOKS = re.compile(r"\\(?:begin|end|section|subsection|cite\w*|ref|eqref|label|emph|textbf|textit|"
                    r"footnote|item|frac|usepackage|documentclass)\b|\$[^$\n]+\$")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_SPACED_LETTER = re.compile(r"[ \t]+(?=[A-Za-z])")
_NEWCOMMAND = re.compile(r"\\(?:(?:re)?newcommand|providecommand|DeclareRobustCommand)\*?\s*"
                         r"(?:\{\s*\\([A-Za-z]+)\s*\}|\\([A-Za-z]+))\s*(?:\[(\d)\])?\s*(?:\[[^\]]*\])?\s*(?=\{)")
_DEF = re.compile(r"\\[gex]?def\s*\\([A-Za-z]+)([^{]*)(?=\{)")
_COMMENT = re.compile(r"(?<!\\)%.*")
_PLAIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ0-9 .,;:'’&/–-]+")


def looks_like_latex(text: str) -> bool:
    return len(_LOOKS.findall(text)) >= 2


class _Segments:
    def __init__(self):
        self.items: list[dict] = []

    def text(self, s: str) -> None:
        if not s:
            return
        if self.items and "text" in self.items[-1]:
            self.items[-1]["text"] += s
        else:
            self.items.append({"text": s})

    def markup(self, s: str, means: str = "") -> None:
        if not s:
            return
        if self.items and "markup" in self.items[-1]:
            self.items[-1]["markup"] += s
            self.items[-1]["interpretAs"] += means
        else:
            self.items.append({"markup": s, "interpretAs": means})


def _group_end(src: str, i: int) -> int:
    """End (exclusive) of the ``{...}`` or ``[...]`` group opening at ``i``; braces nest."""
    close = "}" if src[i] == "{" else "]"
    depth, j = 0, i + 1
    while j < len(src):
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0 and close == "}":
                return j + 1
            depth -= 1
        elif c == "]" and close == "]" and depth == 0:
            return j + 1
        j += 1
    return len(src)


def _groups_end(src: str, i: int, brackets_only: bool = False, limit: int | None = None) -> int:
    """Skip the argument groups that follow a command at ``i``."""
    count = 0
    while i < len(src) and src[i] in ("[" if brackets_only else "[{") and (limit is None or count < limit):
        i = _group_end(src, i)
        count += 1
    return i


def _unescaped(src: str, needle: str, start: int) -> int:
    j = start
    while (j := src.find(needle, j)) >= 0:
        backslashes = len(src[:j]) - len(src[:j].rstrip("\\"))
        if backslashes % 2 == 0:
            return j
        j += 1
    return -1


def _until(src: str, needle: str, start: int) -> int:
    j = src.find(needle, start)
    return len(src) if j < 0 else j + len(needle)


def parse_macros(src: str, known: dict[str, str] | None = None) -> dict[str, str]:
    """Macros without arguments defined in ``src``, each with what it reads as.

    ``known`` holds macros defined earlier (a preamble), usable in these
    definitions. A macro with arguments is left out: its arguments are prose.
    """
    macros = dict(known or {})
    clean = _COMMENT.sub("", src)
    found = []
    for m in _NEWCOMMAND.finditer(clean):
        found.append((m.start(), m[1] or m[2], m[3] not in (None, "0"), m.end()))
    for m in _DEF.finditer(clean):
        found.append((m.start(), m[1], "#" in m[2], m.end()))
    for _, name, has_args, body_start in sorted(found):
        if has_args:
            macros.pop(name, None)
            continue
        body = clean[body_start + 1:_group_end(clean, body_start) - 1]
        macros[name] = _reading(body, macros)
    return macros


def _reading(body: str, macros: dict[str, str]) -> str:
    text = " ".join(interpreted(annotate(body, macros, parse=False)).split())
    return text if not text or _PLAIN.fullmatch(text) else MATH


def annotate(src: str, macros: dict[str, str] | None = None, parse: bool = True) -> list[dict]:
    """Split ``src`` into prose and markup; ``macros`` maps macro names to their reading."""
    macros = parse_macros(src, macros) if parse else (macros or {})
    out = _Segments()
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "%":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.markup(src[i:j])
        elif c == "$":
            if src.startswith("$$", i):
                j = _until(src, "$$", i + 2)
            else:
                j = _unescaped(src, "$", i + 1)
                j = n if j < 0 else j + 1
            out.markup(src[i:j], MATH)
        elif c == "\\":
            j = _command(src, i, out, macros)
        elif c in "{}":
            j = i + 1
            out.markup(c)
        elif c == "~":
            j = i + 1
            out.markup(c, " ")
        elif c == "&":
            j = i + 1
            out.markup(c, " ")
        elif src.startswith(("``", "''"), i):
            j = i + 2
            out.markup(src[i:j], '"')
        else:
            m = _SPECIAL.search(src, i + 1)
            j = m.start() if m else n
            out.text(src[i:j])
        i = j
    return out.items


def _command(src: str, i: int, out: _Segments, macros: dict[str, str]) -> int:
    n = len(src)
    if i + 1 >= n:
        out.markup(src[i:])
        return n
    nxt = src[i + 1]
    if nxt == "\\":                                   # line break, \\* and \\[2pt]
        j = i + 2 + (src.startswith("*", i + 2))
        j = _groups_end(src, j, brackets_only=True)
        out.markup(src[i:j], " ")
        return j
    if nxt in "%&$#_{}":
        out.markup(src[i:i + 2], nxt)
        return i + 2
    if nxt in SPACES:
        out.markup(src[i:i + 2], SPACES[nxt])
        return i + 2
    if nxt == "(":
        j = _until(src, "\\)", i + 2)
        out.markup(src[i:j], MATH)
        return j
    if nxt == "[":
        j = _until(src, "\\]", i + 2)
        out.markup(src[i:j], MATH)
        return j
    if nxt in ACCENTS and not nxt.isalpha():
        return _accent(src, i, i + 2, nxt, out)

    m = _NAME.match(src, i + 1)
    if not m:
        out.markup(src[i:i + 2])
        return i + 2
    name, j = m.group(), m.end()
    if name in ACCENTS and j < n and src[j] == "{":   # \c{c}, \v{s}
        return _accent(src, i, j, name, out)
    if name in ACCENTS and (m := _SPACED_LETTER.match(src, j)):   # \v r
        return _accent(src, i, m.end(), name, out)
    if name in ("begin", "end") and j < n and src[j] == "{":
        k = _group_end(src, j)
        env = src[j + 1:k - 1]
        if name == "begin" and (env in MATH_ENVS or env in SKIP_ENVS):
            end = _until(src, "\\end{" + env + "}", k)
            out.markup(src[i:end], MATH if env in MATH_ENVS else "")
            return end
        k = _groups_end(src, k) if name == "begin" else k
        out.markup(src[i:k])
        return k
    base = name.rstrip("*")
    if base in DEFINERS:
        m = (_DEF if base.endswith("def") else _NEWCOMMAND).match(src, i)
        k = _group_end(src, m.end()) if m else _groups_end(src, j)
        out.markup(src[i:k])
        return k
    if name in macros:
        k = j + 2 if src.startswith("{}", j) else j
        out.markup(src[i:k], macros[name])
        return k
    if base.startswith(("cite", "Cite")) or base in ("parencite", "textcite", "autocite", "footcite"):
        k = _groups_end(src, j)
        out.markup(src[i:k], "[1]")
        return k
    if base == "ensuremath":
        k = _groups_end(src, j)
        out.markup(src[i:k], MATH)
        return k
    if base in REFS or base in UNITS:
        k = _groups_end(src, j)
        out.markup(src[i:k], "1")
        return k
    if base in DROP:
        k = _groups_end(src, j)
        out.markup(src[i:k])
        return k
    if name in SYMBOLS:
        # TeX swallows the spaces after a control word: "\oe uvre" reads "œuvre".
        k = j + 2 if src.startswith("{}", j) else j + len(src[j:]) - len(src[j:].lstrip(" \t"))
        out.markup(src[i:k], SYMBOLS[name])
        return k
    if base in FIRST_ARG_MARKUP:
        k = _groups_end(src, j, brackets_only=True)
        k = _groups_end(src, k, limit=1)
        out.markup(src[i:k])
        return k
    # Any other command: drop its name and options; a braced argument stays prose.
    k = _groups_end(src, j, brackets_only=True)
    if base not in LAYOUT and k == j and not src.startswith("{", j):
        # A bare macro such as \lcdm stands for a word: read it as one.
        out.markup(src[i:k], MATH)
        return k
    out.markup(src[i:k])
    return k


def _accent(src: str, i: int, j: int, accent: str, out: _Segments) -> int:
    if j < len(src) and src[j] == "{":
        k = _group_end(src, j)
        letter = src[j + 1:k - 1]
    else:
        k = min(j + 1, len(src))
        letter = src[j:k]
    letter = {"\\i": "i", "\\j": "j"}.get(letter, letter)
    out.markup(src[i:k], unicodedata.normalize("NFC", letter + ACCENTS[accent]) if letter else "")
    return k


def source(segments: list[dict]) -> str:
    return "".join(s.get("text", s.get("markup", "")) for s in segments)


def interpreted(segments: list[dict]) -> str:
    """The text as LanguageTool reads it."""
    return "".join(s["text"] if "text" in s else s["interpretAs"] for s in segments)


def markup_spans(segments: list[dict]) -> list[tuple[int, int]]:
    """UTF-16 (start, end) of every markup segment."""
    spans, offset = [], 0
    for s in segments:
        length = u16_len(s.get("text", s.get("markup", "")))
        if "markup" in s:
            spans.append((offset, offset + length))
        offset += length
    return spans


def mask(segments: list[dict]) -> str:
    """The source with markup blanked out, keeping every position and line break."""
    return "".join(s["text"] if "text" in s else re.sub(r"[^\n]", " ", s["markup"]) for s in segments)


def paragraphs(segments: list[dict]) -> list[tuple[int, list[dict]]]:
    """Split at blank lines in the prose: (UTF-16 offset, segments) for paragraphs that hold prose."""
    chunks: list[tuple[int, list[dict]]] = []
    current: list[dict] = []
    start = offset = 0

    def close(at: int) -> None:
        nonlocal current, start
        if any("text" in s and s["text"].strip() for s in current):
            chunks.append((start, current))
        current, start = [], at

    for s in segments:
        if "markup" in s:
            current.append(s)
            offset += u16_len(s["markup"])
            continue
        pos = 0
        for m in _BLANK_LINE.finditer(s["text"]):
            if m.start() > pos:
                current.append({"text": s["text"][pos:m.start()]})
            offset += u16_len(s["text"][pos:m.end()])
            close(offset)
            pos = m.end()
        if pos < len(s["text"]):
            current.append({"text": s["text"][pos:]})
            offset += u16_len(s["text"][pos:])
    close(offset)
    return chunks
