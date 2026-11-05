"""How the views show each net worth bucket: its title, its colour and its chart series.

Series colours belong to the entity: the three positive buckets own series 1..3 everywhere
(the Net worth tiles, groups and chart, the Settings section swatches); debt has no series
colour and shows in text-3.
"""

from __future__ import annotations

from dataclasses import dataclass

from ynab_unlinked.buckets import Bucket


@dataclass(frozen=True)
class BucketStyle:
    bucket: Bucket
    title: str
    """ "Cash": the Settings sections and pills, the Net worth tiles and series."""
    group_title: str
    """The title of the bucket's group in the Net worth accounts table."""
    slot: int | None
    """Index into `theme.SERIES` (`--series-{slot + 1}`), None for debt."""

    @property
    def series(self) -> str | None:
        """The CSS colour of the bucket's series, None for debt."""
        return None if self.slot is None else f"var(--series-{self.slot + 1})"

    @property
    def color(self) -> str:
        """The bucket's swatch and share bar colour: its series, text-3 for debt."""
        return self.series or "var(--text-3)"


STYLES: dict[Bucket, BucketStyle] = {
    Bucket.ASSETS: BucketStyle(Bucket.ASSETS, "Assets", "Assets", 0),
    Bucket.SAVINGS: BucketStyle(Bucket.SAVINGS, "Savings", "Savings", 1),
    Bucket.CASH: BucketStyle(Bucket.CASH, "Cash", "Cash · after debt", 2),
    Bucket.DEBT: BucketStyle(Bucket.DEBT, "Debt", "Debt", None),
}

NET_WORTH_ORDER = (Bucket.ASSETS, Bucket.SAVINGS, Bucket.CASH, Bucket.DEBT)
"""Net worth's tiles, groups and series, largest share first."""
SETTINGS_ORDER = (Bucket.CASH, Bucket.SAVINGS, Bucket.ASSETS, Bucket.DEBT)
"""Settings › Accounts: its sections and the bucket pills of every card."""
SERIES_BUCKETS = tuple(bucket for bucket in NET_WORTH_ORDER if STYLES[bucket].slot is not None)
"""The buckets with a series in the "by type" chart."""


__all__ = ["NET_WORTH_ORDER", "SERIES_BUCKETS", "SETTINGS_ORDER", "STYLES", "BucketStyle"]
