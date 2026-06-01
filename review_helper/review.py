"""Check PR/MR review status using Lightpanda headless browser."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import lightpanda

from review_helper.pr_urls import PullRequestRef

LOGIN_HINTS = (
    "sign in to github",
    "sign in to gitlab",
    "you must be logged in",
)


@dataclass(frozen=True, slots=True)
class ReviewStatus:
    reviewed: bool
    source: str = "lightpanda"
    detail: str = ""


def _name_matches_review(text: str, names: list[str]) -> bool:
    lower = text.lower()
    for name in names:
        nl = name.lower()
        if nl not in lower:
            continue
        idx = lower.find(nl)
        snippet = lower[idx : idx + 140]
        if "awaiting requested review" in snippet or "awaiting review" in snippet:
            continue
        if any(
            marker in snippet
            for marker in (
                "approved these changes",
                "requested changes",
                "left review comments",
                "approved this merge request",
                "approved by",
                "reviewed",
            )
        ):
            return True
    return False


def _looks_like_login_page(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in LOGIN_HINTS)


def _text_from_html(page_html: str) -> str:
    without_scripts = re.sub(
        r"<script[^>]*>.*?</script>",
        " ",
        page_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    without_styles = re.sub(
        r"<style[^>]*>.*?</style>",
        " ",
        without_scripts,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = html.unescape(re.sub(r"<[^>]+>", " ", without_styles))
    return re.sub(r"\s+", " ", text)


def check_review(pr: PullRequestRef, reviewer_names: list[str]) -> ReviewStatus:
    try:
        response = lightpanda.fetch(pr.canonical_url, wait_ms=3000)
        page_html = response.text
    except Exception as exc:
        return ReviewStatus(False, detail=str(exc))

    text = _text_from_html(page_html)
    if _looks_like_login_page(text):
        return ReviewStatus(False, detail="login-required")

    reviewed = _name_matches_review(text, reviewer_names)
    return ReviewStatus(reviewed)
