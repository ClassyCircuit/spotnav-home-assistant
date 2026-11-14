"""The one judgement of which exchange rate a day document may be converted with, and its label (Stage 17.5).

A producer attaches the area's own ECB rate with the table's date (`fx_date`, `fx_src`): the day's own table,
or the newest earlier one no more than `MAX_RATE_AGE` before the day (`pricing/fx_rates.table_for`). This module
only *reads* what the document holds. It never fetches, estimates or substitutes a rate, and it never presents
an older table as the day's own:

* `own`      - the table is dated the day itself;
* `dated`    - an earlier table (age in days, within the rule), labelled as such;
* `undated`  - a usable rate that carries no date (an older relay document); used, but labelled undated;
* `missing`  - no rate, an unusable number, a table dated after the day or older than the rule: not usable.

A euro area needs no rate and has no label (`None`). Pure functions, no I/O.
"""

from __future__ import annotations

import math
from typing import Any, Final

from .fx_rates import MAX_RATE_AGE
from .relay_contract import PriceDocument

USABLE: Final = ("own", "dated", "undated")

_ORDER: Final = {"own": 0, "dated": 1, "undated": 2, "missing": 3}


def piece_rate(piece: PriceDocument, currency: str) -> dict[str, Any]:
    """The label of one stored file (never a composite): state, rate, table date, source, age in days."""
    rate = piece.fx_rate(currency)
    fx_date = piece.fx_date
    base: dict[str, Any] = {
        "day": piece.day.isoformat(),
        "rate": None, "date": None if fx_date is None else fx_date.isoformat(),
        "source": piece.fx_src, "age_days": None,
    }
    if rate is None or isinstance(rate, bool) or not isinstance(rate, (int, float)):
        return {**base, "state": "missing"}
    if not math.isfinite(rate) or rate <= 0:
        return {**base, "state": "missing"}
    base["rate"] = float(rate)
    if fx_date is None:
        return {**base, "state": "undated"}
    age = (piece.day - fx_date).days
    base["age_days"] = age
    if age < 0 or age > MAX_RATE_AGE.days:
        return {**base, "state": "missing", "rate": None}
    return {**base, "state": "own" if age == 0 else "dated"}


def rate_usable(document: PriceDocument, currency: str) -> bool:
    """Whether every file the day is made of has a rate it may be converted with (a euro area always does)."""
    if currency.upper() == "EUR":
        return True
    return all(piece_rate(piece, currency)["state"] in USABLE for piece in document.pieces())


def day_label(document: PriceDocument, currency: str) -> dict[str, Any] | None:
    """One day's label: its worst piece (a missing piece makes the day missing, an older table the day older)."""
    if currency.upper() == "EUR":
        return None
    labels = [piece_rate(piece, currency) for piece in document.pieces()]
    worst = max(labels, key=lambda item: (_ORDER[item["state"]], item["age_days"] or 0))
    return {**worst, "day": document.day.isoformat()}


def labels_for(documents: tuple[PriceDocument, ...], currency: str) -> list[dict[str, Any]] | None:
    """The labels of the days a plan was priced from, in the caller's order; `None` for a euro area."""
    if currency.upper() == "EUR":
        return None
    return [label for label in (day_label(document, currency) for document in documents) if label is not None]
