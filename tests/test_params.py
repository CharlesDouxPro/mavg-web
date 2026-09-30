"""La grammaire ${nom}, la substitution en une passe, et le typage des valeurs."""

import pytest

from app.params import coerce, render, scan


def test_scan_finds_names_and_malformed_fragments():
    assert scan("A ${source_url} et ${angle}.") == (["source_url", "angle"], [])
    assert scan("Prix : $5, $nom, 100$") == ([], [])
    names, bad = scan("${Source} ${a-b} ${} ${ok}")
    assert names == ["ok"] and bad == ["${Source}", "${a-b}", "${}"]
    assert scan("fin ${ouvert")[1] == ["${ouvert"]


def test_render_is_single_pass():
    # Une valeur n'est jamais relue : ${b} qu'elle contient reste tel quel.
    assert render("${a}", {"a": "${b}", "b": "BOOM"}) == "${b}"
    assert render(r"${a}", {"a": r"\1 \g<0>"}) == r"\1 \g<0>"


def test_render_missing_values():
    assert render("Hello ${who}", {}) == "Hello "
    assert render("Hello ${who}", {}, keep_missing=True) == "Hello ${who}"


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("number", "1,5", 1.5),
        ("number", "45", 45),
        ("number", 3.0, 3),
        ("boolean", "oui", True),
        ("boolean", "false", False),
        ("boolean", True, True),
        ("url", " https://lequipe.fr/a?b=1 ", "https://lequipe.fr/a?b=1"),
        ("string", "  un angle  ", "un angle"),
        ("text", "l1\r\nl2", "l1\nl2"),
    ],
)
def test_coerce_accepts(kind, raw, expected):
    assert coerce(kind, raw) == expected


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("number", "beaucoup"),
        ("number", "inf"),
        ("number", True),
        ("boolean", "peut-être"),
        ("url", "lequipe.fr"),
        ("url", "javascript:alert(1)"),
        ("string", "deux\nlignes"),
        ("string", "x" * 501),
    ],
)
def test_coerce_refuses(kind, raw):
    with pytest.raises(ValueError):
        coerce(kind, raw)
