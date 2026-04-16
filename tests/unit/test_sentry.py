"""Unit tests for src.api.sentry_utils.

Imports directly from src.api.sentry_utils — NOT from src.api.main — so
that the DATABASE_URL check in src.api.database is never triggered.
No DATABASE_URL env var is required to run this test file.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from src.api.sentry_utils import _init_sentry, _traces_sampler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_DSN = "https://abc123@o0.ingest.sentry.io/1"
HEALTH_CONTEXT = {"asgi_scope": {"path": "/health"}}
API_ITEMS_CONTEXT = {"asgi_scope": {"path": "/api/items"}}
EMPTY_CONTEXT: dict = {}


# ---------------------------------------------------------------------------
# _init_sentry
# ---------------------------------------------------------------------------


class TestInitSentry:
    """Tests for the _init_sentry helper."""

    def test_init_sentry_calls_sdk_when_dsn_set(self) -> None:
        """sentry_sdk.init is called once with the correct dsn and environment."""
        with patch("src.api.sentry_utils.sentry_sdk.init") as mock_init:
            _init_sentry(
                dsn=VALID_DSN,
                environment="test",
                traces_sampler=lambda x: 1.0,
            )

        mock_init.assert_called_once()
        _, kwargs = mock_init.call_args
        assert kwargs["dsn"] == VALID_DSN
        assert kwargs["environment"] == "test"

    def test_init_sentry_passes_traces_sampler_to_sdk(self) -> None:
        """The traces_sampler argument is forwarded to sentry_sdk.init."""
        sampler = MagicMock(return_value=0.5)
        with patch("src.api.sentry_utils.sentry_sdk.init") as mock_init:
            _init_sentry(dsn=VALID_DSN, environment="test", traces_sampler=sampler)

        _, kwargs = mock_init.call_args
        assert kwargs["traces_sampler"] is sampler

    def test_init_sentry_passes_send_default_pii_false(self) -> None:
        """send_default_pii is always False to protect user privacy."""
        with patch("src.api.sentry_utils.sentry_sdk.init") as mock_init:
            _init_sentry(dsn=VALID_DSN, environment="production")

        _, kwargs = mock_init.call_args
        assert kwargs["send_default_pii"] is False

    def test_init_sentry_skips_sdk_when_dsn_empty(self) -> None:
        """sentry_sdk.init is NOT called when dsn is an empty string."""
        with patch("src.api.sentry_utils.sentry_sdk.init") as mock_init:
            _init_sentry(dsn="", environment="test")

        mock_init.assert_not_called()

    def test_init_sentry_skips_sdk_when_dsn_none(self) -> None:
        """sentry_sdk.init is NOT called when dsn is None."""
        with patch("src.api.sentry_utils.sentry_sdk.init") as mock_init:
            _init_sentry(dsn=None, environment="test")

        mock_init.assert_not_called()

    def test_init_sentry_returns_none_when_dsn_set(self) -> None:
        """_init_sentry returns None (not the return value of sentry_sdk.init)."""
        with patch("src.api.sentry_utils.sentry_sdk.init", return_value="unexpected"):
            result = _init_sentry(dsn=VALID_DSN, environment="test")

        assert result is None

    def test_init_sentry_returns_none_when_dsn_empty(self) -> None:
        """_init_sentry returns None even in the no-op early-return path."""
        result = _init_sentry(dsn="", environment="test")
        assert result is None


# ---------------------------------------------------------------------------
# _traces_sampler — /health filtering
# ---------------------------------------------------------------------------


class TestTracesSamplerHealthFilter:
    """Tests that /health requests always return 0.0 regardless of env vars."""

    def test_traces_sampler_returns_zero_for_health(self) -> None:
        """Return 0.0 for /health so health-check polling never creates transactions."""
        result = _traces_sampler(HEALTH_CONTEXT)
        assert result == 0.0

    def test_traces_sampler_health_bypasses_env_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with SENTRY_TRACES_SAMPLE_RATE=1.0, /health still returns 0.0."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")
        assert _traces_sampler(HEALTH_CONTEXT) == 0.0

    def test_traces_sampler_health_bypasses_invalid_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The /health early return happens before the float() parse, so an
        invalid SENTRY_TRACES_SAMPLE_RATE does not affect the /health result."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "not-a-number")
        assert _traces_sampler(HEALTH_CONTEXT) == 0.0


# ---------------------------------------------------------------------------
# _traces_sampler — non-health paths
# ---------------------------------------------------------------------------


class TestTracesSamplerNonHealthPaths:
    """Tests for paths other than /health."""

    def test_traces_sampler_returns_nonzero_for_api_items(self) -> None:
        """A non-health path should yield a positive sample rate by default."""
        result = _traces_sampler(API_ITEMS_CONTEXT)
        assert result > 0

    def test_traces_sampler_default_rate_is_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SENTRY_TRACES_SAMPLE_RATE is not set, the rate defaults to 1.0."""
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
        assert _traces_sampler(API_ITEMS_CONTEXT) == 1.0

    def test_traces_sampler_uses_env_var_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SENTRY_TRACES_SAMPLE_RATE=0.5 is respected for non-health paths."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")
        assert _traces_sampler(API_ITEMS_CONTEXT) == 0.5

    def test_traces_sampler_empty_context_uses_default_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A context with no asgi_scope key is treated as a non-health path."""
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
        assert _traces_sampler(EMPTY_CONTEXT) == 1.0

    def test_traces_sampler_missing_path_key_uses_default_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A context with asgi_scope but no 'path' key is treated as non-health."""
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
        assert _traces_sampler({"asgi_scope": {}}) == 1.0

    @pytest.mark.parametrize(
        "path",
        ["/api/items", "/api/items/some-id", "/docs", "/openapi.json", "/"],
    )
    def test_traces_sampler_non_health_paths_are_sampled(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Several common non-health paths all produce a positive sample rate."""
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
        result = _traces_sampler({"asgi_scope": {"path": path}})
        assert result > 0.0


# ---------------------------------------------------------------------------
# _traces_sampler — invalid / out-of-range env var
# ---------------------------------------------------------------------------


class TestTracesSamplerRateValidation:
    """Tests for SENTRY_TRACES_SAMPLE_RATE parsing and clamping."""

    def test_traces_sampler_invalid_rate_falls_back_to_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-numeric rate value triggers a warning and falls back to 1.0."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "not-a-number")
        result = _traces_sampler(API_ITEMS_CONTEXT)
        assert result == 1.0

    def test_traces_sampler_invalid_rate_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-numeric rate value emits a WARNING-level log."""
        import logging

        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "not-a-number")
        with caplog.at_level(logging.WARNING, logger="src.api.sentry_utils"):
            _traces_sampler(API_ITEMS_CONTEXT)

        assert any("not a valid float" in record.message for record in caplog.records)

    def test_traces_sampler_clamps_above_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rate > 1.0 is clamped down to 1.0."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "2.0")
        assert _traces_sampler(API_ITEMS_CONTEXT) == 1.0

    def test_traces_sampler_clamps_below_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rate < 0.0 is clamped up to 0.0."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "-0.5")
        assert _traces_sampler(API_ITEMS_CONTEXT) == 0.0

    def test_traces_sampler_clamps_exactly_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rate of exactly 0.0 passes through without clamping."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")
        assert _traces_sampler(API_ITEMS_CONTEXT) == 0.0

    def test_traces_sampler_clamps_exactly_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rate of exactly 1.0 passes through without clamping."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")
        assert _traces_sampler(API_ITEMS_CONTEXT) == 1.0

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0.0", 0.0),
            ("0.1", 0.1),
            ("0.5", 0.5),
            ("1.0", 1.0),
            ("2.0", 1.0),   # clamped
            ("-0.5", 0.0),  # clamped
        ],
    )
    def test_traces_sampler_rate_range_parametrized(
        self,
        raw: str,
        expected: float,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Parametrized coverage of rate parsing and clamping."""
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", raw)
        assert _traces_sampler(API_ITEMS_CONTEXT) == expected
