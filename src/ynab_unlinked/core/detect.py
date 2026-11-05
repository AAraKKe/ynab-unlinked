"""Find which loader reads each statement file.

Every loader that accepts the file suffix sniffs the file; the ones that recognise it parse
it for real with their `auto` options resolved and the options saved for the bank (Settings ›
Banks) on top of them. Nothing here prints or prompts: frontends show the `Detection` and
decide what to do with ambiguity.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec, loaders
from ynab_unlinked.exceptions import ParsingError

if TYPE_CHECKING:
    from pathlib import Path

    from ynab_unlinked.config import LatestConfig, LoaderConfig
    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.entities import Match
    from ynab_unlinked.models import Transaction

MIN_CONFIDENCE = 0.5
"""Sniff confidence a loader needs to be tried at all."""
CLEAR_LEAD = 0.25
"""Confidence the top candidate needs over the runner up to be chosen without asking."""

# A sniff reports what it inferred from the file as `key=value` in its reason
_HINT = re.compile(r"\b(\w+)=(\w+)")


@dataclass(frozen=True)
class Candidate:
    loader: LoaderSpec
    confidence: float
    reason: str
    options: Mapping[str, str]
    """Resolved options, `auto` values filled in. Pass them to `loader.build`."""
    transactions: tuple[Transaction, ...] | None
    """None when the trial parse failed."""
    error: str | None


@dataclass(frozen=True)
class Detection:
    input_file: Path
    candidates: tuple[Candidate, ...]
    """Best first."""

    @property
    def _parsed(self) -> list[Candidate]:
        return [c for c in self.candidates if c.transactions is not None]

    @property
    def best(self) -> Candidate | None:
        """The only candidate that parsed the file, or the top one when it is clearly ahead."""
        match self._parsed:
            case [only]:
                return only
            case [top, runner_up, *_] if _is_clear_lead(top.confidence - runner_up.confidence):
                return top
            case _:
                return None

    @property
    def ambiguous(self) -> bool:
        """Several loaders parsed the file and none is clearly ahead."""
        return self.best is None and len(self._parsed) > 1


def detect_loaders(files: Sequence[Path], context: YnabUnlinkedContext[Any]) -> list[Detection]:
    """One `Detection` per file, in the order given. Unsupported files get no candidates."""
    specs = loaders()
    return [_detect(input_file, specs, context) for input_file in files]


def _detect(
    input_file: Path, specs: Sequence[LoaderSpec], context: YnabUnlinkedContext[Any]
) -> Detection:
    candidates: list[Candidate] = []
    for spec in specs:
        if not spec.accepts(input_file):
            continue

        match = _sniff(spec, input_file)
        if match.confidence < MIN_CONFIDENCE:
            continue

        candidates.append(_trial(spec, match, input_file, context))

    candidates.sort(
        key=lambda c: (c.transactions is not None, c.confidence, len(c.transactions or ())),
        reverse=True,
    )
    return Detection(input_file=input_file, candidates=tuple(candidates))


def _sniff(spec: LoaderSpec, input_file: Path) -> Match:
    from ynab_unlinked.entities import Match

    # Sniffing does not depend on the options, any concrete value builds a valid sniffer
    try:
        return spec.build(resolve_options(spec)).sniff(input_file)
    except Exception as error:
        return Match(0.0, f"Could not sniff the file: {_describe(error)}")


def _trial(
    spec: LoaderSpec, match: Match, input_file: Path, context: YnabUnlinkedContext[Any]
) -> Candidate:
    options: dict[str, str] = {}
    try:
        options = preferred_options(
            resolve_options(spec, match.reason), context.config.entity(spec.name)
        )
        entity = spec.build(options)
        trial_context = dataclasses.replace(context, extras=spec.context_extras(options))
        transactions = tuple(entity.parse(input_file, trial_context))
    except Exception as error:
        return Candidate(spec, match.confidence, match.reason, options, None, _describe(error))

    return Candidate(spec, match.confidence, match.reason, options, transactions, None)


def preferred_options(options: Mapping[str, str], saved: LoaderConfig | None) -> dict[str, str]:
    """`options` with the bank's saved non `auto` values (Settings › Banks) on top of them."""
    preferred = dict(options)
    for key, value in (saved.options if saved else {}).items():
        if key in preferred and value != AUTO:
            preferred[key] = value
    return preferred


def saved_options(spec: LoaderSpec, config: LatestConfig) -> dict[str, str]:
    """The options saved for the bank of `spec` with a value other than `auto`."""
    unset = dict.fromkeys((option.key for option in spec.options), AUTO)
    preferred = preferred_options(unset, config.entity(spec.name))
    return {key: value for key, value in preferred.items() if value != AUTO}


def resolve_options(spec: LoaderSpec, reason: str = "") -> dict[str, str]:
    """Concrete values for every option of `spec`, inferring `auto` from the sniff reason."""
    hints = dict(_HINT.findall(reason))
    return {
        option.key: _resolve_auto(option, hints) if option.default == AUTO else option.default
        for option in spec.options
    }


def _resolve_auto(option: LoaderOption, hints: Mapping[str, str]) -> str:
    choices = [choice for choice in option.choices or () if choice != AUTO]

    if (hint := hints.get(option.key)) is not None and (not choices or hint in choices):
        return hint

    if option.key == "year":
        # A statement without year is dated in the current one. The Sabadell parser moves
        # back every row this would put after today: a December statement read in January.
        return str(dt.date.today().year)

    if choices:
        return choices[0]

    raise ValueError(f"The {option.key!r} option cannot be inferred, pass a value")


def _is_clear_lead(difference: float) -> bool:
    # Rounded so that 0.85 - 0.6 counts as the 0.25 it is meant to be
    return round(difference, 6) >= CLEAR_LEAD


def _describe(error: Exception) -> str:
    if isinstance(error, ParsingError):
        return error.message
    return str(error) or type(error).__name__
