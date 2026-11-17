import dataclasses

import pytest

from goldsilver.parsers import parse_gold, parse_silver
from goldsilver.report import (Block, ReportError, build_blocks, pack_messages, render_text)
from goldsilver.validation import validate_gold, validate_pair, validate_silver

from .conftest import GOLD_URL, SILVER_URL


def test_valid_pair_passes(gold_html, silver_html_today, frozen_now):
    g, s = parse_gold(gold_html, GOLD_URL), parse_silver(silver_html_today, SILVER_URL)
    result = validate_pair(g, s, frozen_now, max_age_days=1)
    assert result.ok, result.errors


def test_stale_page_is_rejected(gold_html, silver_html, frozen_now):
    s = parse_silver(silver_html, SILVER_URL)           # dated 27 Oct
    result = validate_silver(s, frozen_now, max_age_days=1)
    assert not result.ok and "old" in result.errors[0]
    assert validate_silver(s, frozen_now, max_age_days=60).ok


def test_price_ordering_and_headline_mismatch_are_rejected(gold_html, frozen_now):
    g = parse_gold(gold_html, GOLD_URL)
    g.current_rates[1] = dataclasses.replace(g.current_rates[1], price=99999.0)   # 22K > 24K
    assert any("24K price is not higher" in e for e in validate_gold(g, frozen_now, 1).errors)
    g2 = parse_gold(gold_html, GOLD_URL)
    g2.headline_rates[0] = dataclasses.replace(g2.headline_rates[0], price=1.0)
    assert any("headline price" in e for e in validate_gold(g2, frozen_now, 1).errors)


def test_report_contents_and_na(gold_html, silver_html_today, frozen_now):
    g, s = parse_gold(gold_html, GOLD_URL), parse_silver(silver_html_today, SILVER_URL)
    text = render_text(build_blocks(g, s, frozen_now))
    assert "Report date: Tuesday, 17 November 2026" in text
    assert "14:35 IST" in text
    assert "24K | Price: ₹13,604 | Change: 🔴 -76" in text
    assert "1 kg | Price: ₹2,20,000 | Previous: ₹2,20,000 | Change: 0" in text
    assert "Purity:" not in text
    gold_weight_block = text.split("GOLD - PRICE BY WEIGHT", 1)[1].split("SILVER (INR)", 1)[0]
    assert "8 g:" in gold_weight_block and "10 g:" in gold_weight_block
    assert "1 g:" not in gold_weight_block and "100 g:" not in gold_weight_block
    silver_weight_block = text.split("SILVER - PRICE BY WEIGHT", 1)[1]
    assert "8 g:" in silver_weight_block and "10 g:" in silver_weight_block
    assert "1 g:" not in silver_weight_block and "100 g:" not in silver_weight_block
    assert GOLD_URL in text and SILVER_URL in text
    g.current_rates[0] = dataclasses.replace(g.current_rates[0], change_text=None)
    assert "24K | Price: ₹13,604 | Change: N/A" in render_text(build_blocks(g, s, frozen_now))


def test_pack_single_message_has_no_label():
    msgs = pack_messages([Block(["A", "a1"]), Block(["B", "b1"])], limit=1000)
    assert msgs == ["A\na1\n\nB\nb1"]


def test_pack_splits_between_blocks_and_labels_parts():
    blocks = [Block(["H%d" % i] + ["x" * 30] * 5) for i in range(6)]
    msgs = pack_messages(blocks, limit=400)
    assert len(msgs) > 1
    assert all(len(m) <= 400 for m in msgs)
    assert msgs[0].startswith(f"[Part 1/{len(msgs)}]")
    # no block is split when it fits
    assert sum(m.count("H") for m in msgs) == 6


def test_pack_splits_oversized_block_by_lines_with_continued_heading():
    block = Block(["HISTORY"] + [f"line {i:03d} " + "y" * 40 for i in range(40)])
    msgs = pack_messages([block], limit=500)
    assert len(msgs) > 1 and all(len(m) <= 500 for m in msgs)
    body = "\n".join(msgs)
    for i in range(40):
        assert body.count(f"line {i:03d} ") == 1          # each record exactly once, never cut
    assert "HISTORY (continued)" in msgs[1]


def test_pack_rejects_unsplittable_line():
    with pytest.raises(ReportError):
        pack_messages([Block(["H", "z" * 2000])], limit=500)


def test_full_report_fits_in_real_limit(gold_html, silver_html_today, frozen_now):
    g, s = parse_gold(gold_html, GOLD_URL), parse_silver(silver_html_today, SILVER_URL)
    msgs = pack_messages(build_blocks(g, s, frozen_now))
    assert all(len(m) <= 4096 for m in msgs)
