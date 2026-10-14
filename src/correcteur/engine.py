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
from dataclasses import dataclass, replace
from pathlib import Path

from .config import SERVER_JAR, Config
from .issues import Issue, from_languagetool, u16_len


class EngineError(RuntimeError):
    pass


@dataclass
class CheckResult:
    issues: list[Issue]
    language: str
    incomplete: bool = False


def check_text(base_url: str, text: str, language: str = "auto", picky: bool = False,
               english_variant: str = "en-US", timeout: float = 120) -> CheckResult:
    """Send ``text`` to the LanguageTool server at ``base_url``."""
    params = {"text": text, "language": language}
    if language == "auto":
        params["preferredVariants"] = english_variant
    if picky:
        params["level"] = "picky"
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
    )


def paragraphs(text: str) -> list[tuple[int, str]]:
    """Split ``text`` at blank lines into (UTF-16 offset, paragraph) pairs, blank ones left out."""
    found, offset = [], 0
    for part in re.split(r"(\n[ \t]*\n)", text):
        if part.strip():
            found.append((offset, part))
        offset += u16_len(part)
    return found


def check_paragraphs(base_url: str, text: str, picky: bool = False,
                     english_variant: str = "en-US") -> CheckResult:
    """Check each paragraph with its own detected language, so French and English can be mixed."""
    issues, languages, incomplete = [], [], False
    for offset, part in paragraphs(text):
        result = check_text(base_url, part, "auto", picky, english_variant)
        issues += [replace(i, offset=i.offset + offset) for i in result.issues]
        if result.language and result.language not in languages:
            languages.append(result.language)
        incomplete |= result.incomplete
    return CheckResult(issues, " + ".join(languages), incomplete)


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

    def warm_up(self) -> None:
        """Load the French and English rules now, so the first real check is quick."""
        self.check("Ceci est un essai.", "fr")
        self.check("This is a test.", self.config.english_variant)

    def check(self, text: str, language: str = "auto", picky: bool = False) -> CheckResult:
        if self.process is None or self.process.poll() is not None:
            raise EngineError(f"LanguageTool is not running.\n{self.log_tail()}".rstrip())
        if language == "auto":
            return check_paragraphs(self.url, text, picky, self.config.english_variant)
        return check_text(self.url, text, language, picky, self.config.english_variant)

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
