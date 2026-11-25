from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_hidden_attribute_wins_over_label_display():
    """Login: Einrichtungscode/Name sind per hidden ausgeblendet; label{display:grid} darf das nicht überstimmen."""
    html = (STATIC / "login.html").read_text(encoding="utf-8")
    assert "label{display:grid" in html
    assert "[hidden]{display:none!important}" in html
