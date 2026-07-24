"""Tests for the HTML -> text extractor (core/html_text.py)."""
from core.html_text import html_to_text


def test_strips_tags_and_scripts():
    html = """
    <html><head><title>T</title><style>.a{color:red}</style></head>
    <body><script>var x=1;</script><p>Hello <b>world</b></p></body></html>
    """
    out = html_to_text(html)
    assert "Hello world" in out
    assert "var x" not in out
    assert "color:red" not in out


def test_block_tags_create_newlines():
    out = html_to_text("<p>one</p><p>two</p>")
    assert "one" in out and "two" in out
    assert out.index("one") < out.index("two")
    # they should be on separate lines
    assert "one two" not in out


def test_entities_decoded():
    assert "A&B" in html_to_text("<p>A&amp;B</p>")


def test_whitespace_collapsed():
    out = html_to_text("<p>a     b\t\tc</p>")
    assert "a b c" in out


def test_empty_or_sparse_page():
    # a JS-only shell yields little/no text -> that's fine (and measurable via byte_size)
    out = html_to_text("<html><body></body></html>")
    assert out.strip() == ""


def test_drops_nav_footer():
    html = "<nav>menu links</nav><p>real content</p><footer>copyright</footer>"
    out = html_to_text(html)
    assert "real content" in out
    assert "menu links" not in out
    assert "copyright" not in out
