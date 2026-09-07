# Form fixtures

Real application-form HTML, saved to disk so the extractor (Stage 4) and the
filler (Stage 6) can be tested without hitting live job postings. Real markup,
zero network, zero flake, and no risk of spamming a real ATS.

| File | Source |
|---|---|
| `simple_form.html` | Hand-written minimal form — text, textarea, select, submit |
| `rippling_apply.html` | Rippling ATS, Edgehog Trading "Graduate Quantitative Trader" apply page, captured 2026-09-06 |

Captured with:

```python
from job_agent.browser import browser_context
with browser_context(headless=True) as ctx:
    page = ctx.new_page()
    page.goto(URL)
    page.wait_for_timeout(5000)
    Path("tests/fixtures/name.html").write_text(page.content())
```

No form was ever filled or submitted to capture these — they contain no
personal data.

## What Rippling taught us

Field `name` attributes are **random hashes** (`4Za8M3kpmM`, `n6i9CInKB6_`,
`QcXfRbBvt67`) and are regenerated per render. Selecting by `name` or `id` is
impossible on this ATS.

The only stable handle is the **accessibility label** — "First name", "Email",
"LinkedIn Link". This is direct evidence for the spec's decision to walk the
accessibility tree rather than build CSS selectors.

Rippling also does not set the HTML `required` attribute on any field; it
validates in JavaScript. So `FormField.required` cannot be read from the DOM
attribute alone.
