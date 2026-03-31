from src.circuit_breaker import CircuitBreaker, PriceHistory


class TestPriceHistory:
    def test_moving_average(self):
        h = PriceHistory()
        h.add(0.50, ts=100)
        h.add(0.52, ts=101)
        h.add(0.54, ts=102)
        ma = h.moving_average(window_seconds=10)
        assert abs(ma - 0.52) < 0.001

    def test_price_change_pct(self):
        h = PriceHistory()
        h.add(0.50, ts=100)
        h.add(0.55, ts=110)
        change = h.price_change_pct(window_seconds=20)
        assert abs(change - 10.0) < 0.1  # 10% change

    def test_volatility(self):
        h = PriceHistory()
        # Stable prices → low volatility
        for i in range(10):
            h.add(0.50, ts=100 + i)
        vol = h.volatility(window_seconds=20)
        assert vol == 0.0

    def test_volatile_prices(self):
        h = PriceHistory()
        prices = [0.50, 0.55, 0.45, 0.60, 0.40]
        for i, p in enumerate(prices):
            h.add(p, ts=100 + i)
        vol = h.volatility(window_seconds=20)
        assert vol > 0.05


class TestCircuitBreaker:
    def _make_cb(self, max_change=10.0, check_window=60, recovery_threshold=0.005):
        return CircuitBreaker({
            "max_change_pct": max_change,
            "check_window_seconds": check_window,
            "ma_window_seconds": 300,
            "recovery_volatility_threshold": recovery_threshold,
            "recovery_window_seconds": 120,
        })

    def test_normal_prices_ok(self):
        cb = self._make_cb()
        # Small price changes → no trip
        for i in range(10):
            cb.record_price("token1", 0.50 + i * 0.001)
        assert cb.check("token1") is True
        assert cb.is_tripped("token1") is False

    def test_trips_on_large_move(self):
        cb = self._make_cb(max_change=5.0, check_window=100)
        # Record base price
        cb.record_price("token1", 0.50)
        # Record 12% jump within same window
        cb.histories["token1"].add(0.56, ts=cb.histories["token1"].timestamps[-1] + 10)
        assert cb.check("token1") is False
        assert cb.is_tripped("token1") is True

    def test_recovers_when_stable(self):
        cb = self._make_cb(max_change=5.0, check_window=100, recovery_threshold=0.01)

        # Trip it
        cb.record_price("token1", 0.50)
        cb.histories["token1"].add(0.56, ts=cb.histories["token1"].timestamps[-1] + 10)
        cb.check("token1")
        assert cb.is_tripped("token1") is True

        # Add stable prices well after the spike (outside recovery_window=120s)
        base_ts = cb.histories["token1"].timestamps[-1] + 200
        for i in range(20):
            cb.histories["token1"].add(0.56, ts=base_ts + i)

        # Should recover since volatility is 0 in the recovery window
        result = cb.check("token1")
        assert result is True
        assert cb.is_tripped("token1") is False

    def test_no_data_is_safe(self):
        cb = self._make_cb()
        assert cb.check("unknown_token") is True
