"""Run Lightpanda review checks."""

from __future__ import annotations

from review_helper.pr_urls import PullRequestRef
from review_helper.progress import iterate_with_progress
from review_helper.review import ReviewStatus, check_review


def _pr_label(pr: PullRequestRef) -> str:
    return f"{pr.project}#{pr.number}"


def check_reviews(
    prs: dict[tuple, PullRequestRef], reviewer_names: list[str]
) -> dict[tuple, ReviewStatus]:
    results: dict[tuple, ReviewStatus] = {}
    items = list(prs.items())
    for key, pr in iterate_with_progress(
        items,
        desc="Checking reviews",
        unit="pr",
        label=lambda item: _pr_label(item[1]),
    ):
        results[key] = check_review(pr, reviewer_names)
    return results
