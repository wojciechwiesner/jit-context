"""Unit tests for v2_edits (run: python -m pytest test_v2_edits.py -q)."""
from v2_edits import Edit, apply_edit, new_flakes, parse_edits, resolve_path, syntax_error

SRC = '''import re


class Validator:
    regex = r"^[\\w.@+-]+$"

    def check(self, value):
        return bool(re.match(self.regex, value))
'''


def test_parse_plain_block():
    text = 'Fix:\n\npkg/v.py\n<<<<<<< SEARCH\n    regex = r"^[\\w.@+-]+$"\n=======\n    regex = r"\\A[\\w.@+-]+\\Z"\n>>>>>>> REPLACE\n'
    [e] = parse_edits(text)
    assert e.path == "pkg/v.py"
    assert e.replace == '    regex = r"\\A[\\w.@+-]+\\Z"'


def test_parse_fenced_and_backticked_path():
    text = "`pkg/v.py`\n```python\n<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n```"
    [e] = parse_edits(text)
    assert (e.path, e.search, e.replace) == ("pkg/v.py", "a = 1", "a = 2")


def test_backslashes_survive_verbatim():
    """The LFM failure: code inside JSON doubled the backslashes. Plain text must not."""
    e = Edit("v.py", '    regex = r"^[\\w.@+-]+$"', '    regex = r"\\A[\\w.@+-]+\\Z"')
    out, how = apply_edit(SRC, e)
    assert how == "exact"
    assert 'r"\\A[\\w.@+-]+\\Z"' in out
    assert "\\\\" not in out


def test_indent_shift_match():
    e = Edit("v.py", "def check(self, value):\n    return bool(re.match(self.regex, value))",
             "def check(self, value):\n    return bool(re.fullmatch(self.regex, value))")
    out, how = apply_edit(SRC, e)
    assert how == "indent-shift"
    assert "        return bool(re.fullmatch(self.regex, value))" in out


def test_not_found_gives_closest_region():
    e = Edit("v.py", "    def check(self, val):\n        return bool(re.match(self.regex, val))", "x")
    out, msg = apply_edit(SRC, e)
    assert out is None and "def check(self, value)" in msg and ("Closest match" in msg or "actually reads" in msg)


def test_ambiguous_rejected():
    out, msg = apply_edit("a = 1\nb = 2\na = 1\n", Edit("f.py", "a = 1", "a = 3"))
    assert out is None and "2 places" in msg


def test_syntax_and_new_flakes():
    assert syntax_error("def f(:\n  pass") is not None
    assert syntax_error(SRC) is None
    assert new_flakes("x = 1\n", "x = 1\ny = undefined_name\n") == ["undefined name 'undefined_name'"]


def test_line_numbers_from_read_file_are_stripped():
    """Observed with Qwen 7B: SEARCH copied with 'NNN: ' prefixes from read_file output."""
    text = ("a.py\n<<<<<<< SEARCH\n7:     def check(self, value):\n8:         return 1\n=======\n"
            "7:     def check(self, value):\n8:         return 2\n>>>>>>> REPLACE")
    [e] = parse_edits(text)
    assert e.search == "    def check(self, value):\n        return 1"
    assert e.replace.endswith("return 2")


def test_numbers_kept_when_not_every_line_prefixed():
    text = "a.py\n<<<<<<< SEARCH\nx = {\n1: 'a',\n}\n=======\nx = {}\n>>>>>>> REPLACE"
    [e] = parse_edits(text)
    assert "1: 'a'" in e.search


def test_anchor_hint_when_search_is_invented():
    """Observed with Qwen 7B: SEARCH invents a body; one real line anchors the hint."""
    src = "\n".join(["# pad"] * 20 + ["    def __new__(cls, name, bases, dct):", "        real_body = 1"] + ["# pad"] * 20)
    e = Edit("m.py", "    def __new__(cls, name, bases, dct):\n        for k, v in dct.items():\n"
                     "            dct[k] = cls._wrap_function(v)", "x")
    out, msg = apply_edit(src, e)
    assert out is None and "actually reads" in msg and "real_body = 1" in msg


def test_mid_line_substring_is_not_an_exact_match():
    """Observed on sphinx-7889: SEARCH with 3-space indent hit inside a 4-space line."""
    src = "class A:\n    def f(self, section: str) -> list:\n        return []\n"
    e = Edit("a.py", "   def f(self, section: str) -> list:",
             "   def f(self, section: str) -> list:\n       return [section]")
    out, how = apply_edit(src, e)
    assert how == "indent-shift"
    assert "\n    def f(self, section: str) -> list:\n        return [section]\n" in out
    assert syntax_error(out) is None


def test_anchor_prefers_named_def_over_body_line():
    """Observed on django-15863: hint pointed at another function sharing a body line."""
    other = ["def timesince_filter(value, arg=None):", "    try:", "        value = float(value)",
             "    except (ValueError, TypeError):", "        return ''"]
    target = ["def floatformat(text, arg=-1):", "    force_grouping = False", "    return text"]
    src = "\n".join(["# pad"] * 10 + other + ["# pad"] * 30 + target + ["# pad"] * 10)
    e = Edit("f.py", "def floatformat(value, arg=-1):\n    try:\n        value = float(value)\n"
                     "    except (ValueError, TypeError):\n        pass", "x")
    out, msg = apply_edit(src, e)
    assert out is None and "force_grouping = False" in msg


def test_resolve_path_placeholder_prefix_and_basename(tmp_path):
    (tmp_path / "astropy/utils").mkdir(parents=True)
    (tmp_path / "astropy/utils/misc.py").write_text("x = 1\n")
    tracked = ["astropy/utils/misc.py"]
    p, _ = resolve_path(tmp_path, "path/to/astropy/utils/misc.py", tracked)
    assert p == (tmp_path / "astropy/utils/misc.py").resolve()
    p, _ = resolve_path(tmp_path, "misc.py", tracked)
    assert p is not None and p.name == "misc.py"
    p, err = resolve_path(tmp_path, "astropy/utils/docval.py", tracked)
    assert p is None and "does not exist" in err
