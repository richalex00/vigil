from vigil_pipeline.ingest import Page, has_text, pages_to_dicts, render_for_prompt
from vigil_pipeline.quotes import find_quote, norm

PAGES = [
    Page(1, ["LG Chem", "Model INR18650 MJ1", "Nominal Capacity  3500 mAh", "Weight 49.0 g max"]),
    Page(2, ["Operating temperature −20 ℃ ~ 60 ℃", "AC impedance ≤ 35 mΩ", "manu-",
             "facturer: LG Energy Solution", "Charge voltage", "4.2 V"]),
]


def test_find_quote_exact_and_whitespace():
    assert find_quote("Nominal Capacity 3500 mAh", PAGES, 1) == (1, 3, 3)


def test_quote_matches_after_unicode_normalisation():
    assert find_quote("Operating temperature -20 °C ~ 60 °C", PAGES, 2) == (2, 1, 1)
    assert find_quote("ac impedance ≤ 35 mΩ", PAGES, 2) == (2, 2, 2)


def test_find_quote_falls_back_to_other_pages():
    assert find_quote("Weight 49.0 g max", PAGES, 7) == (1, 4, 4)
    assert find_quote("Weight 49.0 g max", PAGES, None) == (1, 4, 4)


def test_find_quote_spanning_two_lines():
    assert find_quote("Charge voltage 4.2 V", PAGES, 2) == (2, 5, 6)


def test_find_quote_across_hyphenated_line_break():
    assert find_quote("manufacturer: LG Energy Solution", PAGES, 2) == (2, 3, 4)


def test_find_quote_rejects_invented_and_short_quotes():
    assert find_quote("Nominal Capacity 3600 mAh", PAGES, 1) is None
    assert find_quote("4.2 V", PAGES, 2) is None


def test_norm_casefolds_and_collapses():
    assert norm("  Nominal\tCAPACITY  ") == "nominal capacity"


def test_has_text_and_render():
    assert not has_text([Page(1, ["x"])])
    assert has_text([Page(1, ["word " * 60])])
    assert render_for_prompt(PAGES).splitlines()[0] == "[p1 L1] LG Chem"
    assert pages_to_dicts(PAGES)[1]["number"] == 2
