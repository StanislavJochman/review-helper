"""Progress reporting for CLI operations."""

from __future__ import annotations

import sys
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def _use_progress() -> bool:
    return sys.stderr.isatty()


def iterate_with_progress(
    items: Iterable[T],
    *,
    desc: str,
    unit: str = "it",
    label: Callable[[T], str] | None = None,
) -> Iterable[T]:
    if not _use_progress():
        yield from items
        return

    from tqdm import tqdm

    bar = tqdm(items, desc=desc, unit=unit, file=sys.stderr, dynamic_ncols=True)
    for item in bar:
        if label is not None:
            bar.set_postfix_str(label(item), refresh=False)
        yield item


def status(message: str) -> None:
    if _use_progress():
        from tqdm import tqdm

        tqdm.write(message, file=sys.stderr)
    else:
        print(message, file=sys.stderr)
