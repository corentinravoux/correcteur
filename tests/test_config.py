import pytest

from correcteur import config


def make_engine(path):
    path.mkdir(parents=True)
    (path / config.SERVER_JAR).write_text("")
    return path


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("CORRECTEUR_ENGINE_DIR", raising=False)


def test_find_engine_picks_newest(tmp_path):
    make_engine(tmp_path / "LanguageTool-6.10")
    newest = make_engine(tmp_path / "LanguageTool-6.12")
    make_engine(tmp_path / "LanguageTool-6.9")
    assert config.find_engine(tmp_path) == newest
    assert config.find_engine(newest) == newest
    assert config.find_engine(tmp_path / "missing") is None


def test_defaults_use_data_dir(tmp_path):
    cfg = config.load()
    assert cfg.engine_dir is None and cfg.ngrams_dir is None
    engine = make_engine(tmp_path / "data" / "correcteur" / "LanguageTool-6.6")
    (tmp_path / "data" / "correcteur" / "ngrams").mkdir()
    cfg = config.load()
    assert cfg.engine_dir == engine
    assert cfg.ngrams_dir == tmp_path / "data" / "correcteur" / "ngrams"
    assert cfg.dictionary == tmp_path / "config" / "correcteur" / "dictionary.txt"
    assert (cfg.java, cfg.heap, cfg.english_variant) == ("java", "1g", "en-US")


def test_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    engine = make_engine(tmp_path / "lt" / "LanguageTool-6.6")
    path = tmp_path / "config" / "correcteur" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('engine_dir = "~/lt"\nngrams_dir = "~/ng"\nheap = "2g"\n'
                    'english_variant = "en-GB"\ndictionary = "~/words.txt"\n'
                    'latex_preamble = "~/macros.sty"\n')
    cfg = config.load()
    assert cfg.engine_dir == engine
    assert cfg.ngrams_dir == tmp_path / "ng"
    assert (cfg.heap, cfg.english_variant) == ("2g", "en-GB")
    assert cfg.dictionary == tmp_path / "words.txt"
    assert cfg.latex_preamble == [tmp_path / "macros.sty"]


def test_unknown_key_is_an_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('engin_dir = "x"\n')
    with pytest.raises(ValueError, match="engin_dir"):
        config.load(path)


def test_environment_overrides_engine(tmp_path, monkeypatch):
    engine = make_engine(tmp_path / "elsewhere" / "LanguageTool-7.0")
    monkeypatch.setenv("CORRECTEUR_ENGINE_DIR", str(tmp_path / "elsewhere"))
    assert config.load().engine_dir == engine
