from src.pricing_engine import calculate_quotes, calculate_mid_price


class TestCalculateMidPrice:
    def test_normal_orderbook(self):
        book = {
            "bids": [{"price": "0.48"}],
            "asks": [{"price": "0.52"}],
        }
        assert calculate_mid_price(book) == 0.50

    def test_empty_orderbook(self):
        assert calculate_mid_price({"bids": [], "asks": []}) is None

    def test_missing_sides(self):
        assert calculate_mid_price({"bids": [{"price": "0.5"}], "asks": []}) is None


class TestCalculateQuotes:
    def test_basic_quotes(self):
        quotes = calculate_quotes(
            mid_price=0.50,
            inventory=0,
            spread=0.04,
            order_size=50,
            num_levels=1,
            skew_factor=0.5,
            max_position=500,
        )
        assert len(quotes) == 1
        assert quotes[0].bid_price == 0.48
        assert quotes[0].ask_price == 0.52

    def test_inventory_skew_long(self):
        """When long, bid should drop and ask should drop (encourage selling)."""
        quotes = calculate_quotes(
            mid_price=0.50,
            inventory=250,  # 50% of max
            spread=0.04,
            order_size=50,
            num_levels=1,
            skew_factor=0.5,
            max_position=500,
        )
        assert len(quotes) == 1
        # Skew = 0.5 * (250/500) * 0.02 = 0.005
        assert quotes[0].bid_price < 0.48
        assert quotes[0].ask_price < 0.52

    def test_inventory_skew_short(self):
        """When short, bid should rise and ask should rise (encourage buying)."""
        quotes = calculate_quotes(
            mid_price=0.50,
            inventory=-250,
            spread=0.04,
            order_size=50,
            num_levels=1,
            skew_factor=0.5,
            max_position=500,
        )
        assert len(quotes) == 1
        assert quotes[0].bid_price > 0.48
        assert quotes[0].ask_price > 0.52

    def test_multiple_levels(self):
        quotes = calculate_quotes(
            mid_price=0.50,
            inventory=0,
            spread=0.04,
            order_size=50,
            num_levels=3,
            skew_factor=0.5,
            max_position=500,
        )
        assert len(quotes) == 3
        # Deeper levels should have wider spread
        assert quotes[1].bid_price < quotes[0].bid_price
        assert quotes[1].ask_price > quotes[0].ask_price
        # Deeper levels should have smaller size
        assert quotes[1].bid_size < quotes[0].bid_size

    def test_price_clamping(self):
        """Prices should stay within [0.01, 0.99]."""
        quotes = calculate_quotes(
            mid_price=0.02,
            inventory=0,
            spread=0.04,
            order_size=50,
            num_levels=1,
            skew_factor=0.5,
            max_position=500,
        )
        for q in quotes:
            assert q.bid_price >= 0.01
            assert q.ask_price <= 0.99

    def test_extreme_price_high(self):
        quotes = calculate_quotes(
            mid_price=0.98,
            inventory=0,
            spread=0.04,
            order_size=50,
            num_levels=1,
            skew_factor=0.5,
            max_position=500,
        )
        for q in quotes:
            assert q.bid_price >= 0.01
            assert q.ask_price <= 0.99

    def test_zero_inventory(self):
        quotes = calculate_quotes(
            mid_price=0.50,
            inventory=0,
            spread=0.04,
            order_size=50,
            num_levels=1,
            skew_factor=0.5,
            max_position=500,
        )
        # Symmetric around mid
        assert abs((quotes[0].bid_price + quotes[0].ask_price) / 2 - 0.50) < 0.001
