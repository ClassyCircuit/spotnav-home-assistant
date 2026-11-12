"""Fast actual-module provenance checks without a running HA or network."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.spotnav.api import dashboard
from custom_components.spotnav.pricing import price_repository as repo
from custom_components.spotnav.pricing.providers import choose_provider


def test_held_provider_survives_router_change_and_failed_refresh():
    day = date(2026, 10, 25)
    fetched = datetime(2026, 10, 24, tzinfo=timezone.utc)
    cache = repo._Cached({}, fetched, SimpleNamespace(covers_whole_day=lambda: True), provider="entsoe")
    fake = SimpleNamespace(_held_file=lambda *_: cache, _attempt=lambda *_: (fetched, "http_status"), _inflight={})
    result = repo.PriceRepository._day_snapshot(fake, "A", day, authority="unknown")
    assert result.provenance == ((day, "entsoe", fetched, "stale"),)
    assert choose_provider(nordpool_serves=True, nordpool_loaded=True, entsoe_serves=True, entsoe_key_usable=True) == "nordpool"


def test_composed_display_day_keeps_each_file_provenance(monkeypatch):
    day = date(2026, 10, 25)
    fetched = datetime(2026, 10, 24, tzinfo=timezone.utc)
    def snap(d, provider, state):
        return repo.DaySnapshot("A", d, state, object(), "memory", fetched, None, None, "listed", False, complete=True,
                                provenance=((d, provider, fetched, state),))
    snapshots = {day: snap(day, "nordpool", "ready"), day + timedelta(days=1): snap(day + timedelta(days=1), "entsoe", "stale")}
    fake = SimpleNamespace(file_snapshot=lambda _area, d: snapshots[d])
    monkeypatch.setattr(repo, "principal_market_day", lambda *_: day)
    monkeypatch.setattr(repo, "market_days_for", lambda *_: tuple(snapshots))
    monkeypatch.setattr(repo, "compose_display_day", lambda *_: object())
    result = repo.PriceRepository._display_snapshot(fake, "A", day, "Europe/London", "Europe/Paris")
    assert [fact[1] for fact in result.provenance] == ["nordpool", "entsoe"]
    assert result.provenance[1][3] == "stale"


def test_dashboard_serializes_held_provenance_not_current_route(monkeypatch):
    day = date(2026, 10, 25)
    fetched = datetime(2026, 10, 24, tzinfo=timezone.utc)
    snapshot = repo.DaySnapshot("A", day, "stale", object(), "memory", fetched, fetched, None, "listed", False,
                                provenance=((day, "entsoe", fetched, "stale"),))
    capture = SimpleNamespace(area=None, days=(snapshot,), snapshot=None, intervals=None, area_entry=None,
                              source_status=SimpleNamespace(as_dict=lambda: {"key": "nordpool"}))
    monkeypatch.setattr(dashboard, "serialize_intervals", lambda _: [])
    monkeypatch.setattr(dashboard, "_held_resolutions", lambda _: [])
    monkeypatch.setattr(dashboard, "_resolution_of", lambda _: None)
    answer = dashboard.serialize_prices(capture)
    assert answer["provider"]["key"] == "nordpool"
    assert answer["today_provenance"] == [{"market_day": "2026-10-25", "provider": "entsoe", "fetched_at": fetched.isoformat(), "state": "stale"}]
    assert answer["tomorrow_provenance"] is None
