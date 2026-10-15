import pytest

from correcteur import latex
from correcteur.issues import u16_slice

SAMPLES = [
    r"Comme montré par \citet{smith20}, les donnée $x$ sont \emph{bonne}.",
    "\\section{Introduction}\\label{sec:intro}\nLe texte % un commentaire\ncontinue ici.",
    r"On a \[ E = mc^2 \] et \begin{equation} a=b \label{eq:1} \end{equation} donc voilà.",
    r"Voir la figure~\ref{fig:a} et l'équation \eqref{eq:1}, à 10\,km de \SI{3}{\metre}.",
    "Caf\\'e, na\\\"ive, \\c{c}a, \\oe uvre et 50\\% de \\LaTeX{}.",
    "\\begin{figure}[t]\n\\includegraphics[width=\\linewidth]{a.pdf}\n\\caption{Une figure.}\n\\end{figure}",
    "\\begin{verbatim}\nnot prose $\n\\end{verbatim}\nAfter.",
    r"Unclosed $math and \textbf{bold",
    "``quoted'' text \\\\ new line \\\\[2pt] and \\href{http://x.org}{a link}.",
    "Prix 5\\$ et \\textcolor{red}{rouge}; \\footnote{Une note.} fin.",
    "",
]


@pytest.mark.parametrize("src", SAMPLES)
def test_segments_give_back_the_source(src):
    segments = latex.annotate(src)
    assert latex.source(segments) == src
    assert all(("text" in s) != ("markup" in s) for s in segments)


def read(src):
    return latex.interpreted(latex.annotate(src))


def test_interpretation():
    assert read(SAMPLES[0]) == "Comme montré par [1], les donnée X sont bonne."
    assert read(SAMPLES[1]) == "Introduction\nLe texte \ncontinue ici."
    assert read(SAMPLES[2]) == "On a X et X donc voilà."
    assert read(SAMPLES[3]) == "Voir la figure 1 et l'équation 1, à 10 km de 1."
    assert read(SAMPLES[4]) == "Café, naïve, ça, œuvre et 50% de LaTeX."
    assert read(SAMPLES[5]) == "\n\nUne figure.\n"
    assert read(SAMPLES[6]) == "\nAfter."
    assert read(SAMPLES[8]) == '"quoted" text   new line   and a link.'
    assert read(SAMPLES[9]) == "Prix 5$ et rouge; Une note. fin."
    assert read(r"Le modèle \lcdm~reste, \lcdm, et \noindent Ho\v rava.") == "Le modèle X reste, X, et  Hořava."


def test_markup_spans_and_mask():
    src = "Un 𝑥 \\emph{mot} ici."
    segments = latex.annotate(src)
    spans = latex.markup_spans(segments)
    assert [u16_slice(src, a, b) for a, b in spans] == ["\\emph{", "}"]
    masked = latex.mask(segments)
    assert masked == "Un 𝑥       mot  ici." and len(masked) == len(src)
    assert latex.mask(latex.annotate("a %c\nb")) == "a   \nb"


def test_paragraphs():
    src = "\\section{Titre}\nPremier paragraphe.\n\n% seul commentaire\n\n\\begin{equation}\na\n\n b\n\\end{equation}\nSecond 𝑥.\n\nTrois."
    chunks = latex.paragraphs(latex.annotate(src))
    texts = [latex.interpreted(c).strip() for _, c in chunks]
    assert texts == ["Titre\nPremier paragraphe.", "X\nSecond 𝑥.", "Trois."]
    for offset, chunk in chunks:
        part = latex.source(chunk)
        assert u16_slice(src, offset, offset + len(part.encode("utf-16-le")) // 2) == part


def test_looks_like_latex():
    assert latex.looks_like_latex(SAMPLES[0] + " \\section{A}")
    assert latex.looks_like_latex("On pose $a$ et $b$.")
    assert not latex.looks_like_latex("Il coûte 5 $ et c'est tout.")
    assert not latex.looks_like_latex("Plain text with a back\\slash.")


PREAMBLE = r"""
\newcommand\mnras{MNRAS}             % Monthly Notices
\newcommand{\lcdm}{$\Lambda\mathrm{CDM}$}
\newcommand{\lcdmnu}{\ensuremath{\Lambda\mathrm{CDM}\nu}}
\newcommand{\lcdmtitle}{\texorpdfstring{$\Lambda$}{Λ}CDM}
\renewcommand*{\desi}{DESI}
\providecommand{\aap}{A\&A}
\def\ie{i.e.}
\newcommand{\com}[1]{\textcolor{blue}{#1}}
\newcommand{\both}{\desi{} et \mnras}
% \newcommand{\commented}{Nope}
"""


def test_parse_macros():
    macros = latex.parse_macros(PREAMBLE)
    assert macros == {"mnras": "MNRAS", "lcdm": "X", "lcdmnu": "X", "lcdmtitle": "X", "desi": "DESI",
                      "aap": "A&A", "ie": "i.e.", "both": "DESI et MNRAS"}


def test_macros_in_text():
    macros = latex.parse_macros(PREAMBLE)
    src = r"Le modèle \lcdm{} et \lcdm, dans \mnras. \com{Une note.}"
    assert read_with(src, macros) == "Le modèle X et X, dans MNRAS. Une note."
    defined_here = "\\newcommand\\survey{DESI}\n\\def\\eg{e.g.}\nLe relevé \\survey, \\eg ici."
    assert read_with(defined_here, {}) == "\n\nLe relevé DESI, e.g. ici."
    assert latex.source(latex.annotate(defined_here)) == defined_here


def read_with(src, macros):
    return latex.interpreted(latex.annotate(src, macros))


def test_mask_keeps_utf16_positions():
    # 𝑥 and 𝛼 are two UTF-16 units each; the masked copy must keep every position.
    src = "% 𝑥 commentaire\nLes donnée $𝛼$ sont ici."
    from correcteur.issues import u16_len
    assert u16_len(latex.mask(latex.annotate(src))) == u16_len(src)


def test_annotate_is_linear_in_length():
    import time
    big = "Le modèle $x$ et \\ldots puis \\oe uvre. " * 10000   # about 400 000 characters
    start = time.monotonic()
    latex.annotate(big)
    assert time.monotonic() - start < 0.5
