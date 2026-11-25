from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_hidden_attribute_wins_over_label_display():
    """Login: Einrichtungscode/Name sind per hidden ausgeblendet; label{display:grid} darf das nicht überstimmen."""
    html = (STATIC / "login.html").read_text(encoding="utf-8")
    assert "label{display:grid" in html
    assert "[hidden]{display:none!important}" in html


def _i18n_keys() -> dict:
    import json

    src = (STATIC / "i18n.js").read_text(encoding="utf-8")
    return json.loads(src.split("=", 1)[1].rsplit(";", 1)[0])


def _ui_strings(name: str) -> set[str]:
    import re

    html = (STATIC / name).read_text(encoding="utf-8")
    keys = {
        m.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8") for m in re.findall(r"\bt\('((?:[^'\\]|\\.)+)'", html)
    }
    keys |= set(re.findall(r"label:'([^']+)'", html))
    if "const SRC=" in html:
        keys |= set(re.findall(r":'([^']+)'", html.split("const SRC=")[1].split("};")[0]))
        keys |= set(re.findall(r"\['\w+','([^']+)'\]", html.split("const TABS=")[1].split(";")[0]))
    return keys


def test_every_ui_text_has_an_english_translation():
    en = _i18n_keys()
    missing = sorted((_ui_strings("index.html") | _ui_strings("login.html")) - en.keys())
    assert not missing, f"Ohne Übersetzung in static/i18n.js: {missing}"


def test_english_keeps_placeholders():
    import re

    for de, en in _i18n_keys().items():
        assert sorted(re.findall(r"\{\w+\}", de)) == sorted(re.findall(r"\{\w+\}", en)), de


def test_server_messages_have_english_and_same_placeholders():
    import re

    from app import i18n

    for de, en in i18n.EN.items():
        assert sorted(re.findall(r"\{\w+\}", de)) == sorted(re.findall(r"\{\w+\}", en)), de
