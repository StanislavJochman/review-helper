"""Run Lightpanda PR/MR status checks."""

from __future__ import annotations

from collections import defaultdict

from review_helper.pr_urls import PullRequestRef
from review_helper.progress import map_with_progress, status as log_status
from review_helper.review import (
    FETCH_RECHECK_WAIT_MS,
    PrStatus,
    check_pr_tabs,
    needs_recheck,
)

RECHECK_WAIT_TIMES = (FETCH_RECHECK_WAIT_MS, 20000)


def _pr_label(tabs: list[PullRequestRef]) -> str:
    pr = tabs[0]
    return f"{pr.project}#{pr.number}"


def _group_by_key(prs: list[PullRequestRef]) -> dict[tuple, list[PullRequestRef]]:
    grouped: dict[tuple, list[PullRequestRef]] = defaultdict(list)
    for pr in prs:
        grouped[pr.key].append(pr)
    return grouped


def check_pr_statuses(
    prs: list[PullRequestRef],
    reviewer_names: list[str],
    *,
    parallel: bool = True,
) -> dict[tuple, PrStatus]:
    grouped = _group_by_key(prs)
    items = list(grouped.items())

    def worker(item: tuple[tuple, list[PullRequestRef]]) -> tuple[tuple, PrStatus]:
        key, tabs = item
        return key, check_pr_tabs(tabs, reviewer_names)

    checked = map_with_progress(
        worker,
        items,
        desc="Checking PR status",
        unit="pr",
        label=lambda item: _pr_label(item[1]),
        parallel=parallel,
    )
    result = dict(checked)

    inconclusive = [
        (key, tabs)
        for key, tabs in items
        if needs_recheck(result.get(key, PrStatus()))
    ]
    if inconclusive:
        log_status(f"Rechecking {len(inconclusive)} failed fetch(es)...")
        def recheck_worker(
            item: tuple[tuple, list[PullRequestRef]],
        ) -> tuple[tuple, PrStatus]:
            key, tabs = item
            return key, check_pr_tabs(
                tabs,
                reviewer_names,
                wait_times=RECHECK_WAIT_TIMES,
            )

        rechecked = map_with_progress(
            recheck_worker,
            inconclusive,
            desc="Rechecking PR status",
            unit="pr",
            label=lambda item: _pr_label(item[1]),
            parallel=parallel,
        )
        result.update(dict(rechecked))

    return result
