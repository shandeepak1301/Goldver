from goldsilver.parsers import parse_gold, parse_price_cell, parse_silver, to_number

from .conftest import GOLD_URL, SILVER_URL


def test_to_number_handles_indian_grouping_and_signs():
    assert to_number("₹1,24,700") == 124700
    assert to_number("-5,000") == -5000
    assert to_number("\u221276") == -76
    assert to_number("N/A") is None


def test_parse_price_cell():
    assert parse_price_cell("₹13,604 (-76)") == ("₹13,604", 13604.0, "-76", -76.0)
    assert parse_price_cell("₹2,20,000    (0)") == ("₹2,20,000", 220000.0, "0", 0.0)
    assert parse_price_cell("₹14,411 (+55)")[2:] == ("+55", 55.0)
    assert parse_price_cell("—") == (None, None, None, None)


def test_parse_gold(gold_html):
    g = parse_gold(gold_html, GOLD_URL)
    assert g.city == "Chennai"
    assert g.page_date == "2026-11-17"
    assert g.page_meta_timestamp_ist.startswith("2026-11-17T00:00:00+05:30")
    cur = {r.label: r for r in g.current_rates}
    assert [r.label for r in g.current_rates] == ["24K", "22K", "18K"]
    assert cur["24K"].price == 13604 and cur["24K"].change == -76 and cur["24K"].purity == "99.9%"
    assert cur["22K"].price_text == "₹12,470" and cur["22K"].purity == "91.6%"
    assert cur["18K"].purity == "75%"
    assert len(g.rates_by_weight) == 12            # 4 weights x 3 carats
    assert g.notes and "indicative" in g.notes[0] and not g.notes[0].startswith("*")


def test_parse_silver(silver_html):
    s = parse_silver(silver_html, SILVER_URL)
    assert s.city == "Chennai"
    assert s.page_date == "2026-10-27"
    gram, kilo = s.current_rates
    assert (gram.price, gram.previous_price, gram.change_text) == (220, 220, "0")
    assert (kilo.price, kilo.weight_grams, kilo.unit) == (220000, 1000, "kg")
    assert len(s.rates_by_weight) == 5


def test_missing_data_is_none_not_invented():
    html = ("<html><head><title>Gold Rate on 17 November 2026</title></head><body><h1>Gold Rate in Chennai</h1>"
            "<table><tr><th>Gram</th><th>24K</th><th>22K</th></tr><tr><td>1</td><td>₹13,604</td><td>₹12,470</td></tr></table>"
            "</body></html>")
    g = parse_gold(html, GOLD_URL)
    r = g.current_rates[0]
    assert r.change is None and r.change_text is None and r.purity is None
    assert g.notes == []


def test_parse_error_when_no_prices():
    import pytest
    from goldsilver.parsers import ParseError
    with pytest.raises(ParseError):
        parse_gold("<html><body><h1>Please enable JavaScript</h1></body></html>", GOLD_URL)
