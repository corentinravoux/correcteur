"""Run a private LanguageTool server for the lifetime of the app, and query it.

The server listens on a free port of 127.0.0.1 only. It is stopped when the app
closes and, through ``setpriv --pdeathsig``, also when the app crashes, so no Java
process is left behind holding memory.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import french, latex
from .config import SERVER_JAR, Config
from .issues import Issue, from_languagetool, merge, u16_len, u16_slice


class EngineError(RuntimeError):
    pass


LANGUAGES = ("fr", "en")  # Auto picks between these


@dataclass
class CheckResult:
    issues: list[Issue]
    language: str
    incomplete: bool = False
    code: str = ""
    parts: list[tuple[int, int, str]] = field(default_factory=list)  # (start, end, language code)


def check_text(base_url: str, text: str | list[dict], language: str = "auto", picky: bool = False,
               english_variant: str = "en-US", disabled=(), timeout: float = 120) -> CheckResult:
    """Send ``text`` to the LanguageTool server at ``base_url``.

    ``text`` is a string, or annotated text: a list of ``{"text": ...}`` and
    ``{"markup": ..., "interpretAs": ...}`` segments (see :mod:`correcteur.latex`).
    """
    if isinstance(text, str):
        params = {"text": text, "language": language}
    else:
        params = {"data": json.dumps({"annotation": text}), "language": language}
    if language == "auto":
        params["preferredVariants"] = english_variant
    if picky:
        params["level"] = "picky"
    if disabled:
        params["disabledRules"] = ",".join(sorted(disabled))
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(f"{base_url}/v2/check", data=data, timeout=timeout) as reply:
            result = json.load(reply)
    except urllib.error.HTTPError as e:
        raise EngineError(f"LanguageTool refused the request: {e.read().decode(errors='replace')}") from e
    except OSError as e:
        raise EngineError(f"LanguageTool is not reachable: {e}") from e
    return CheckResult(
        issues=from_languagetool(result.get("matches", [])),
        language=result.get("language", {}).get("name", ""),
        incomplete=bool(result.get("warnings", {}).get("incompleteResults")),
        code=result.get("language", {}).get("code", ""),
    )


def paragraphs(text: str) -> list[tuple[int, str]]:
    """Split ``text`` at blank lines into (UTF-16 offset, paragraph) pairs, blank ones left out."""
    found, offset = [], 0
    for part in re.split(r"(\n[ \t]*\n)", text):
        if part.strip():
            found.append((offset, part))
        offset += u16_len(part)
    return found


def check_chunks(base_url: str, chunks, language: str = "auto", picky: bool = False,
                 english_variant: str = "en-US", disabled=()) -> CheckResult:
    """Check (offset, text) pieces one by one; with "auto", each gets its own language.

    Detection is unreliable on short pieces such as headings. A piece detected as
    neither French nor English is checked again in the language most other pieces
    have, or in English when there is none.
    """
    chunks = list(chunks)
    results = [check_text(base_url, part, language, picky, english_variant, disabled) for _, part in chunks]
    if language == "auto":
        known = [r.code for r in results if r.code.split("-")[0] in LANGUAGES]
        fallback = max(set(known), key=known.count) if known else english_variant
        results = [r if r.code.split("-")[0] in LANGUAGES
                   else check_text(base_url, part, fallback, picky, english_variant, disabled)
                   for r, (_, part) in zip(results, chunks)]
    issues, languages, incomplete, parts = [], [], False, []
    for (offset, part), result in zip(chunks, results):
        issues += [replace(i, offset=i.offset + offset) for i in result.issues]
        parts.append((offset, offset + u16_len(part if isinstance(part, str) else latex.source(part)), result.code))
        if result.language and result.language not in languages:
            languages.append(result.language)
        incomplete |= result.incomplete
    return CheckResult(issues, " + ".join(languages), incomplete, parts=parts)


def check_paragraphs(base_url: str, text: str, picky: bool = False,
                     english_variant: str = "en-US", disabled=()) -> CheckResult:
    """Check each paragraph with its own detected language, so French and English can be mixed."""
    return check_chunks(base_url, paragraphs(text), "auto", picky, english_variant, disabled)


def check_latex(base_url: str, text: str, language: str = "auto", picky: bool = False,
                english_variant: str = "en-US", disabled=(), segments: list[dict] | None = None) -> CheckResult:
    """Check the prose of LaTeX source, paragraph by paragraph.

    An issue that overlaps a command keeps its message but loses its suggestions:
    applying one would delete part of the command. A spelling issue there is
    dropped: it comes from reading markup and prose as one word.
    """
    segments = segments if segments is not None else latex.annotate(text)
    result = check_chunks(base_url, latex.paragraphs(segments), language, picky, english_variant, disabled)
    spans = latex.markup_spans(segments)
    result.issues = [replace(i, replacements=[]) if overlaps(i, spans) else i for i in result.issues
                     if not (i.kind == "spelling" and overlaps(i, spans))]
    return result


def overlaps(issue: Issue, spans: list[tuple[int, int]]) -> bool:
    return any(a < issue.end and issue.offset < b for a, b in spans)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LanguageTool:
    """A LanguageTool server owned by this process."""

    def __init__(self, config: Config):
        self.config = config
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.french: french.Grammalecte | None = None
        self.french_error = ""
        self._french_tried = False
        self._workdir: Path | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def command(self) -> list[str]:
        cmd = [self.config.java, f"-Xmx{self.config.heap}", "-cp", SERVER_JAR,
               "org.languagetool.server.HTTPServer", "--port", str(self.port)]
        if self.config.ngrams_dir and self._workdir:
            props = self._workdir / "server.properties"
            props.write_text(f"languageModel={self.config.ngrams_dir}\n")
            cmd += ["--config", str(props)]
        setpriv = shutil.which("setpriv")
        return [setpriv, "--pdeathsig", "TERM", *cmd] if setpriv else cmd

    def start(self) -> None:
        """Launch the server; returns at once, see :meth:`wait_ready`."""
        engine = self.config.engine_dir
        if engine is None:
            raise EngineError("LanguageTool was not found. Run `correcteur --download`, or set "
                              "engine_dir in ~/.config/correcteur/config.toml.")
        if not shutil.which(self.config.java):
            raise EngineError(f"Java was not found ({self.config.java!r}). "
                              "Install a Java runtime, version 17 or later.")
        if self.config.ngrams_dir and not self.config.ngrams_dir.is_dir():
            raise EngineError(f"ngrams_dir does not exist: {self.config.ngrams_dir}")
        self._workdir = Path(tempfile.mkdtemp(prefix="correcteur-"))
        self.port = _free_port()
        log = open(self._workdir / "server.log", "wb")
        self.process = subprocess.Popen(self.command(), cwd=engine, stdout=log,
                                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        log.close()

    def log_tail(self, lines: int = 15) -> str:
        if not self._workdir or not (self._workdir / "server.log").is_file():
            return ""
        text = (self._workdir / "server.log").read_text(errors="replace")
        return "\n".join(text.splitlines()[-lines:])

    def wait_ready(self, timeout: float = 90) -> None:
        if self.process is None:
            raise EngineError("LanguageTool is not running.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise EngineError(f"LanguageTool stopped while starting:\n{self.log_tail()}")
            try:
                with urllib.request.urlopen(f"{self.url}/v2/languages", timeout=2):
                    return
            except OSError:
                time.sleep(0.25)
        raise EngineError(f"LanguageTool did not start within {timeout:.0f} s:\n{self.log_tail()}")

    @property
    def engines(self) -> list[str]:
        return ["LanguageTool"] + (["Grammalecte"] if self.french else [])

    def load_french(self) -> None:
        """Load Grammalecte if it is installed and wanted; a failure only disables it."""
        if self._french_tried:
            return
        self._french_tried = True
        if not (self.config.grammalecte and french.available(self.config.grammalecte_dir)):
            return
        try:
            self.french = french.Grammalecte(self.config.grammalecte_dir)
        except Exception as e:  # a broken or incompatible copy must not stop the app
            self.french_error = f"Grammalecte could not be loaded: {e}"

    def warm_up(self) -> None:
        """Load the French and English rules now, so the first real check is quick."""
        self.check("Ceci est un essai.", "fr")
        self.check("This is a test.", self.config.english_variant)

    def check(self, text: str, language: str = "auto", picky: bool = False, disabled=(),
              tex: bool = False) -> CheckResult:
        if self.process is None or self.process.poll() is not None:
            raise EngineError(f"LanguageTool is not running.\n{self.log_tail()}".rstrip())
        self.load_french()
        variant = self.config.english_variant
        if tex:
            segments = latex.annotate(text)
            result = check_latex(self.url, text, language, picky, variant, disabled, segments)
            base, spans = latex.mask(segments), latex.markup_spans(segments)
        else:
            chunks = paragraphs(text) if language == "auto" else [(0, text)]
            result = check_chunks(self.url, chunks, language, picky, variant, disabled)
            base, spans = text, []
        if self.french:
            result.issues = merge(result.issues, self._second_opinion(result, base, spans, picky, disabled), text)
        return result

    def _second_opinion(self, result: CheckResult, base: str, spans, picky: bool, disabled) -> list[Issue]:
        """Grammalecte's issues in the French parts; ``base`` has any markup blanked out."""
        found = []
        for start, end, code in result.parts:
            if code.startswith("fr"):
                found += [replace(i, offset=i.offset + start)
                          for i in self.french.check(u16_slice(base, start, end), picky, disabled)]
        return [i for i in found if not overlaps(i, spans)]

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    def __enter__(self) -> LanguageTool:
        self.start()
        self.wait_ready()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
