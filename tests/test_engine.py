import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from correcteur.config import Config
from correcteur.engine import EngineError, LanguageTool, check_latex, check_paragraphs, check_text, paragraphs
from correcteur.issues import u16_len, u16_slice

from test_issues import LT_MATCHES


class FakeLanguageTool(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        params = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        if "data" in params:
            segments = json.loads(params.pop("data"))["annotation"]
            params["text"] = "".join(s.get("text", s.get("markup")) for s in segments)
            params["annotated"] = "yes"
        FakeLanguageTool.requests.append(params)
        if params["language"] == "xx":
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error: 'xx' is not a language code")
            return
        name, code = ("Catalan", "ca") if "Catalan" in params["text"] and params["language"] == "auto" \
            else ("French", "fr")
        reply = {"language": {"name": name, "code": code}, "matches": LT_MATCHES,
                 "warnings": {"incompleteResults": params["text"] == "long"}}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    FakeLanguageTool.requests = []
    httpd = HTTPServer(("127.0.0.1", 0), FakeLanguageTool)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_check_text(server):
    result = check_text(server, "Il ont mangé des pomme.", "auto", picky=True, english_variant="en-GB")
    assert result.language == "French" and not result.incomplete
    assert [i.rule_id for i in result.issues] == ["ACCORD_R_PERS_VERBE", "FR_SPELLING_RULE"]
    sent = FakeLanguageTool.requests[-1]
    assert sent == {"text": "Il ont mangé des pomme.", "language": "auto",
                    "preferredVariants": "en-GB", "level": "picky"}


def test_check_text_fixed_language_sends_no_variant(server):
    check_text(server, "Bonjour", "fr")
    assert FakeLanguageTool.requests[-1] == {"text": "Bonjour", "language": "fr"}


def test_check_text_sends_disabled_rules(server):
    check_text(server, "Bonjour", "fr", disabled={"B_RULE", "A_RULE"})
    assert FakeLanguageTool.requests[-1]["disabledRules"] == "A_RULE,B_RULE"


def test_check_text_reports_incomplete_and_errors(server):
    assert check_text(server, "long").incomplete
    with pytest.raises(EngineError, match="not a language code"):
        check_text(server, "x", "xx")
    with pytest.raises(EngineError, match="not reachable"):
        check_text("http://127.0.0.1:9", "x")


def test_start_without_engine():
    with pytest.raises(EngineError, match="correcteur --download"):
        LanguageTool(Config(engine_dir=None)).start()


def test_start_without_java(tmp_path):
    with pytest.raises(EngineError, match="Java was not found"):
        LanguageTool(Config(engine_dir=tmp_path, java="no-such-java")).start()


def test_command_uses_ngrams(tmp_path):
    lt = LanguageTool(Config(engine_dir=tmp_path, ngrams_dir=Path("/data/ngrams"), heap="2g"))
    lt.port, lt._workdir = 8123, tmp_path
    cmd = lt.command()
    java = cmd[cmd.index("java"):]
    assert java[:5] == ["java", "-Xmx2g", "-cp", "languagetool-server.jar", "org.languagetool.server.HTTPServer"]
    assert java[java.index("--port") + 1] == "8123"
    props = Path(java[java.index("--config") + 1])
    assert props.read_text() == "languageModel=/data/ngrams\n"


def test_paragraphs_offsets_are_utf16():
    text = "Premier 𝑥.\n\n  \nSecond.\nSame paragraph.\n \t\nThird"
    found = paragraphs(text)
    assert [p for _, p in found] == ["Premier 𝑥.", "  \nSecond.\nSame paragraph.", "Third"]
    for offset, part in found:
        assert u16_slice(text, offset, offset + u16_len(part)) == part


def test_check_paragraphs_merges_results(server):
    text = "Il ont mangé des pomme.\n\nIl ont mangé des pomme."
    result = check_paragraphs(server, text)
    assert [r["text"] for r in FakeLanguageTool.requests] == ["Il ont mangé des pomme."] * 2
    assert [i.offset for i in result.issues] == [0, 13, 25, 38]
    assert result.language == "French"


def test_check_latex_sends_annotation_and_protects_markup(server):
    # The fake server always reports "Il ont" at 0..6 and a typo at 13..22.
    text = "Il ont mangé \\emph{des} pomme."
    result = check_latex(server, text, "fr")
    sent = FakeLanguageTool.requests[-1]
    assert sent["annotated"] == "yes" and sent["text"] == text
    assert [i.replacements for i in result.issues] == [["Ils ont", "Il a"]]  # the typo over \emph{ is dropped


def test_auto_rechecks_other_languages(server):
    long = "Il ont mangé des pomme hier soir avec les amis."
    text = f"{long}\n\nCatalan words in a long paragraph here\n\n{long}"
    result = check_paragraphs(server, text)
    assert [r["language"] for r in FakeLanguageTool.requests] == ["auto", "auto", "auto", "fr"]
    assert result.language == "French"


def test_auto_short_paragraphs_follow_the_text(server):
    long = "Il ont mangé des pomme hier soir avec les amis."
    check_paragraphs(server, f"Catalan title\n\n{long}")
    # The title is short: checked again in French, the language of the long paragraph.
    assert [r["language"] for r in FakeLanguageTool.requests] == ["auto", "auto", "fr"]


def test_macros_follow_the_preamble_file(tmp_path):
    preamble = tmp_path / "macros.sty"
    preamble.write_text("\\newcommand\\desi{DESI}\n")
    lt = LanguageTool(Config(engine_dir=None, latex_preamble=[preamble, tmp_path / "missing.sty"]))
    assert lt.macros() == {"desi": "DESI"}
    preamble.write_text("\\newcommand\\desi{DESI}\n\\newcommand\\ztf{ZTF}\n")
    import os
    os.utime(preamble, (1, 1))  # a different modification time
    assert lt.macros() == {"desi": "DESI", "ztf": "ZTF"}


def test_failed_launch_cleans_up(tmp_path, monkeypatch):
    import subprocess
    (tmp_path / "languagetool-server.jar").write_text("")
    lt = LanguageTool(Config(engine_dir=tmp_path, java="python3"))

    def broken(*args, **kwargs):
        raise PermissionError("not executable")

    monkeypatch.setattr(subprocess, "Popen", broken)
    with pytest.raises(EngineError, match="could not be started"):
        lt.start()
    assert lt._workdir is None and lt.process is None
