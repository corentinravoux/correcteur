"""Against the real LanguageTool server; skipped when it is not installed."""

import shutil

import pytest

from correcteur.config import load
from correcteur.engine import EngineError, LanguageTool

config = load()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(config.engine_dir is None or shutil.which(config.java) is None,
                       reason="LanguageTool or Java not installed"),
]


@pytest.fixture(scope="module")
def engine():
    with LanguageTool(config) as lt:
        yield lt


def test_french(engine):
    result = engine.check("Il ont mangé hier soir et je doit partir.", "auto")
    assert result.language.startswith("French")
    fixes = {i.rule_id: i.replacements[0] for i in result.issues}
    assert fixes.get("ACCORD_R_PERS_VERBE") in {"Ils ont", "dois"}


def test_english(engine):
    result = engine.check("This is a error in this sentense.", "en-US")
    assert {i.replacements[0] for i in result.issues} >= {"an", "sentence"}


def test_stop_ends_the_process():
    lt = LanguageTool(config)
    lt.start()
    lt.wait_ready()
    process = lt.process
    lt.stop()
    assert process.poll() is not None
    with pytest.raises(EngineError, match="not running"):
        lt.check("x")


def test_mixed_languages(engine):
    result = engine.check("Je doit partir.\n\nThis is a error.", "auto")
    assert result.language == "French + English (US)"
    assert {i.replacements[0] for i in result.issues} >= {"dois", "an"}
