from datetime import date

from app import pricing


def test_versioned_price_changes_on_effective_date():
    before = pricing.get_price("deepseek-chat", date(2026, 10, 31))
    after = pricing.get_price("deepseek-chat", date(2026, 11, 1))
    assert before["input_price_per_1k"] == 0.14
    assert after["input_price_per_1k"] == 0.16
    assert after["output_price_per_1k"] == 0.32


def test_cost_uses_input_and_output_prices():
    # 1K input + 1K output at 0.14 / 0.28
    cost = pricing.compute_cost("deepseek-chat", 1000, 1000, date(2026, 10, 31))
    assert cost == 0.42


def test_expensive_model_cost():
    cost = pricing.compute_cost("gpt-4o", 1000, 1000, date(2026, 10, 31))
    assert cost == 12.5


def test_zero_tokens_cost_zero():
    assert pricing.compute_cost("qwen-plus", 0, 0, date(2026, 10, 31)) == 0.0
