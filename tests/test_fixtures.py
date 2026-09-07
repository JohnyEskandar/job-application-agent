from pathlib import Path

from job_agent.fixtures import strip_scripts


def test_script_tags_are_removed():
    html = "<html><body><input id='a'><script>x=1</script></body></html>"
    out = strip_scripts(html)
    assert "<script" not in out
    assert "<input id='a'>" in out


def test_multiline_and_attributed_scripts_are_removed():
    html = """<div><script type="application/json" id="__NEXT_DATA__">
    {"props": {"a": 1}}
    </script><input></div>"""
    out = strip_scripts(html)
    assert "__NEXT_DATA__" not in out
    assert "<input>" in out


def test_the_committed_rippling_fixture_has_no_scripts():
    html = Path("tests/fixtures/rippling_apply.html").read_text()
    assert "<script" not in html.lower(), (
        "fixture will re-hydrate and wipe itself when loaded from file://"
    )
