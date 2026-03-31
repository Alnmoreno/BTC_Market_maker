from datetime import datetime, timezone, timedelta

from src.market_selector import select_markets


def _make_market(
    question: str = "Test?",
    volume: float = 50000,
    active: bool = True,
    days_until_end: int = 30,
    yes_price: float = 0.45,
    no_price: float = 0.45,
) -> dict:
    end_date = datetime.now(timezone.utc) + timedelta(days=days_until_end)
    return {
        "question": question,
        "active": active,
        "volume_num_24hr": volume,
        "end_date_iso": end_date.isoformat(),
        "tokens": [
            {"token_id": "token_yes", "price": str(yes_price)},
            {"token_id": "token_no", "price": str(no_price)},
        ],
    }


DEFAULT_CONFIG = {
    "min_volume_24h": 10000,
    "min_spread": 0.02,
    "min_time_to_resolution_days": 7,
    "max_markets": 5,
}


class TestSelectMarkets:
    def test_selects_active_markets(self):
        markets = [_make_market(question="Good market", volume=50000)]
        result = select_markets(markets, DEFAULT_CONFIG)
        assert len(result) == 1

    def test_filters_inactive(self):
        markets = [_make_market(active=False)]
        result = select_markets(markets, DEFAULT_CONFIG)
        assert len(result) == 0

    def test_filters_low_volume(self):
        markets = [_make_market(volume=100)]
        result = select_markets(markets, DEFAULT_CONFIG)
        assert len(result) == 0

    def test_filters_near_resolution(self):
        markets = [_make_market(days_until_end=2)]
        result = select_markets(markets, DEFAULT_CONFIG)
        assert len(result) == 0

    def test_respects_max_markets(self):
        markets = [_make_market(question=f"Market {i}", volume=50000 - i * 1000) for i in range(10)]
        config = {**DEFAULT_CONFIG, "max_markets": 3}
        result = select_markets(markets, config)
        assert len(result) == 3

    def test_ranks_by_score(self):
        markets = [
            _make_market(question="Low vol", volume=15000),
            _make_market(question="High vol", volume=100000),
        ]
        result = select_markets(markets, DEFAULT_CONFIG)
        assert result[0]["question"] == "High vol"
