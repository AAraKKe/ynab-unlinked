"""The wizard's steps and what it offers to pick. Pure: no NiceGUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

STEPS = ("Token", "Budget", "Banks", "Done")
TOKEN, BUDGET, LOADERS, DONE = range(len(STEPS))

CopyState = Literal["running", "done", "failed"]


@dataclass(frozen=True)
class AccountOption:
    id: str
    name: str
