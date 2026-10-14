import io

from correcteur import download


def test_fetch_sends_a_user_agent(tmp_path, monkeypatch):
    # languagetool.org answers 403 to Python's default User-Agent.
    seen = {}

    class Reply(io.BytesIO):
        headers = {"Content-Length": "5"}

    def fake_urlopen(request):
        seen["agent"] = request.get_header("User-agent")
        return Reply(b"hello")

    monkeypatch.setattr(download.urllib.request, "urlopen", fake_urlopen)
    download._fetch("https://example.org/x.zip", tmp_path / "x.zip")
    assert seen["agent"].startswith("correcteur/")
    assert (tmp_path / "x.zip").read_bytes() == b"hello"
