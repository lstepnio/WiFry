"""Tests for tc_manager service."""

import pytest

from app.models.impairment import (
    CorruptConfig,
    DelayConfig,
    DuplicateConfig,
    ImpairmentConfig,
    LossConfig,
    RateConfig,
    ReorderConfig,
)
from app.services.tc_manager import _build_netem_args, _parse_netem_options, _parse_qdiscs


class TestBuildNetemArgs:
    def test_empty_config(self):
        config = ImpairmentConfig()
        assert _build_netem_args(config) == []

    def test_delay_only(self):
        config = ImpairmentConfig(delay=DelayConfig(ms=50))
        args = _build_netem_args(config)
        assert args == ["delay", "50ms"]

    def test_delay_with_jitter(self):
        config = ImpairmentConfig(delay=DelayConfig(ms=50, jitter_ms=10))
        args = _build_netem_args(config)
        assert args == ["delay", "50ms", "10ms"]

    def test_delay_with_jitter_and_correlation(self):
        config = ImpairmentConfig(
            delay=DelayConfig(ms=50, jitter_ms=10, correlation_pct=25)
        )
        args = _build_netem_args(config)
        assert args == ["delay", "50ms", "10ms", "25%"]

    def test_loss_only(self):
        config = ImpairmentConfig(loss=LossConfig(pct=0.5))
        args = _build_netem_args(config)
        assert args == ["loss", "0.5%"]

    def test_loss_with_correlation(self):
        config = ImpairmentConfig(loss=LossConfig(pct=1.5, correlation_pct=25))
        args = _build_netem_args(config)
        assert args == ["loss", "1.5%", "25%"]

    def test_corrupt(self):
        config = ImpairmentConfig(corrupt=CorruptConfig(pct=0.1))
        args = _build_netem_args(config)
        assert args == ["corrupt", "0.1%"]

    def test_duplicate(self):
        config = ImpairmentConfig(duplicate=DuplicateConfig(pct=0.5))
        args = _build_netem_args(config)
        assert args == ["duplicate", "0.5%"]

    def test_reorder(self):
        config = ImpairmentConfig(reorder=ReorderConfig(pct=5, correlation_pct=50))
        args = _build_netem_args(config)
        assert args == ["reorder", "5%", "50%"]

    def test_combined(self):
        config = ImpairmentConfig(
            delay=DelayConfig(ms=100, jitter_ms=20, correlation_pct=25),
            loss=LossConfig(pct=2, correlation_pct=25),
            corrupt=CorruptConfig(pct=0.1),
        )
        args = _build_netem_args(config)
        assert "delay" in args
        assert "100ms" in args
        assert "loss" in args
        assert "2%" in args
        assert "corrupt" in args
        assert "0.1%" in args

    def test_zero_values_are_skipped(self):
        config = ImpairmentConfig(
            delay=DelayConfig(ms=0),
            loss=LossConfig(pct=0),
        )
        assert _build_netem_args(config) == []


class TestParseNetemOptions:
    def test_empty(self):
        config = _parse_netem_options({})
        assert config.delay is None
        assert config.loss is None

    def test_delay(self):
        # Real tc -j format: delay as nested dict with seconds
        opts = {"delay": {"delay": 0.05, "jitter": 0.01, "correlation": 0.25}}
        config = _parse_netem_options(opts)
        assert config.delay is not None
        assert config.delay.ms == 50.0
        assert config.delay.jitter_ms == 10.0
        assert config.delay.correlation_pct == 25.0

    def test_loss(self):
        # Real tc -j format: fractions (0.015 = 1.5%)
        opts = {"loss-random": {"loss": 0.015, "correlation": 0.25}}
        config = _parse_netem_options(opts)
        assert config.loss is not None
        assert config.loss.pct == 1.5
        assert config.loss.correlation_pct == 25.0


class TestParseQdiscs:
    def test_empty(self):
        state = _parse_qdiscs("wlan0", [])
        assert state.interface == "wlan0"
        assert not state.active

    def test_netem_qdisc(self):
        # Real tc -j format from RPi
        qdiscs = [
            {
                "kind": "netem",
                "options": {
                    "delay": {"delay": 0.03, "jitter": 0.005, "correlation": 0},
                    "loss-random": {"loss": 0.005, "correlation": 0},
                },
            }
        ]
        state = _parse_qdiscs("wlan0", qdiscs)
        assert state.active
        assert state.config.delay is not None
        assert state.config.delay.ms == 30.0
        assert state.config.loss is not None
        assert state.config.loss.pct == 0.5

    def test_netem_with_tbf(self):
        qdiscs = [
            {"kind": "netem", "options": {"delay": {"delay": 0.05}}},
            {"kind": "tbf", "options": {"rate": 1250000, "burst": 4000}},
        ]
        state = _parse_qdiscs("eth0", qdiscs)
        assert state.active
        assert state.config.rate is not None
        assert state.config.rate.kbit == 10000


class TestImpairmentConfig:
    def test_is_empty_when_all_none(self):
        config = ImpairmentConfig()
        assert config.is_empty()

    def test_is_not_empty_with_delay(self):
        config = ImpairmentConfig(delay=DelayConfig(ms=10))
        assert not config.is_empty()
