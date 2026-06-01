"""CLI entry point for review-helper."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict

from review_helper import __version__
from review_helper.chrome import ChromeCliError, close_tab, list_tabs
from review_helper.pr_urls import PullRequestRef, parse_pr_url, tab_keep_score
from review_helper.progress import iterate_with_progress, status as log_status
from review_helper.review_batch import check_reviews

PR_AUTHOR_RE = re.compile(r" by ([^·]+?) · Pull Request ", re.IGNORECASE)


def _split_name(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [part.lower() for part in re.split(r"[\s._-]+", spaced) if part]


def _identity_tokens(git_name: str | None, git_email: str | None) -> set[str]:
    tokens: set[str] = set()
    if git_name:
        tokens.update(_split_name(git_name))
        tokens.add(git_name.lower())
    if git_email and "@" in git_email:
        local = git_email.split("@", 1)[0].lower()
        tokens.add(local)
        tokens.update(_split_name(local))
    return {t for t in tokens if len(t) >= 4}


def _git_config(key: str) -> str | None:
    result = subprocess.run(
        ["git", "config", key],
        capture_output=True,
        text=True,
        check=False,
    )
    value = (result.stdout or "").strip()
    return value or None


def _author_names_from_tabs(prs: list[PullRequestRef]) -> list[str]:
    authors: list[str] = []
    for pr in prs:
        match = PR_AUTHOR_RE.search(pr.title)
        if match:
            authors.append(match.group(1).strip())
    return authors


def _related_names(prs: list[PullRequestRef], tokens: set[str]) -> list[str]:
    if not tokens:
        return []
    related: list[str] = []
    seen: set[str] = set()
    for author in _author_names_from_tabs(prs):
        author_lower = author.lower()
        if any(token in author_lower for token in tokens):
            key = author_lower
            if key not in seen:
                seen.add(key)
                related.append(author)
    return related


def _reviewer_names(args: argparse.Namespace, prs: list[PullRequestRef]) -> list[str]:
    names: list[str] = []
    git_name = _git_config("user.name")
    git_email = _git_config("user.email")

    if args.reviewer:
        names.extend(args.reviewer)
    else:
        if git_name:
            names.append(git_name)
        if git_email and "@" in git_email:
            names.append(git_email.split("@", 1)[0])
        github_user = _git_config("github.user")
        if github_user:
            names.append(github_user)
        names.extend(_related_names(prs, _identity_tokens(git_name, git_email)))

    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(name)
    return unique


def _collect_pr_tabs() -> list[PullRequestRef]:
    tabs = list_tabs()
    prs: list[PullRequestRef] = []
    for tab in tabs:
        pr = parse_pr_url(tab.url, tab)
        if pr:
            prs.append(pr)
    return prs


def _dedupe_tabs(prs: list[PullRequestRef]) -> tuple[list[str], dict[tuple, PullRequestRef]]:
    groups: dict[tuple, list[PullRequestRef]] = defaultdict(list)
    for pr in prs:
        groups[pr.key].append(pr)

    to_close: list[str] = []
    kept: dict[tuple, PullRequestRef] = {}

    for key, group in groups.items():
        group.sort(key=lambda p: tab_keep_score(p.url), reverse=True)
        kept[key] = group[0]
        for duplicate in group[1:]:
            to_close.append(duplicate.tab_id)

    return to_close, kept


def _format_pr(pr: PullRequestRef) -> str:
    return f"{pr.host} {pr.project}#{pr.number}"


def _group_tabs_by_pr(
    prs: list[PullRequestRef], tab_ids: set[str]
) -> list[tuple[PullRequestRef, list[PullRequestRef]]]:
    by_key: dict[tuple, list[PullRequestRef]] = defaultdict(list)
    for pr in prs:
        if pr.tab_id in tab_ids:
            by_key[pr.key].append(pr)

    grouped: list[tuple[PullRequestRef, list[PullRequestRef]]] = []
    for key in sorted(by_key, key=lambda k: (k[1], k[2], k[3])):
        tabs = by_key[key]
        tabs.sort(key=lambda p: int(p.tab_id))
        grouped.append((tabs[0], tabs))
    return grouped


def _print_section(
    heading: str,
    grouped: list[tuple[PullRequestRef, list[PullRequestRef]]],
) -> list[str]:
    tab_ids: list[str] = []
    if not grouped:
        return tab_ids
    print(f"{heading} ({sum(len(tabs) for _, tabs in grouped)} tab(s)):")
    for representative, tabs in grouped:
        print(f"  {_format_pr(representative)}")
        for tab in tabs:
            print(f"    {tab.url}")
            tab_ids.append(tab.tab_id)
    return tab_ids


def _close_tabs(tab_ids: list[str]) -> None:
    for tab_id in iterate_with_progress(
        sorted(tab_ids, key=int),
        desc="Closing tabs",
        unit="tab",
    ):
        try:
            close_tab(tab_id)
        except ChromeCliError as exc:
            log_status(f"Failed to close tab {tab_id}: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review-helper",
        description=(
            "Find GitHub/GitLab PR tabs in Chrome, close duplicates, "
            "and close PRs you have already reviewed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without closing tabs",
    )
    parser.add_argument(
        "--reviewer",
        action="append",
        metavar="NAME",
        help=(
            "Reviewer name or username to match (default: git config user.name "
            "and email local-part)"
        ),
    )
    parser.add_argument(
        "--dedupe-only",
        action="store_true",
        help="Only close duplicate PR tabs; skip review-status checks",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        log_status("Scanning Chrome tabs...")
        prs = _collect_pr_tabs()
    except ChromeCliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not prs:
        log_status("No GitHub/GitLab PR or MR tabs found.")
        return 0

    reviewer_names = _reviewer_names(args, prs)
    if not reviewer_names:
        print(
            "No reviewer name found. Set git config user.name or pass --reviewer.",
            file=sys.stderr,
        )
        return 1

    duplicate_tab_ids, kept_by_key = _dedupe_tabs(prs)
    log_status(f"Found {len(prs)} PR/MR tab(s), {len(kept_by_key)} unique")
    duplicate_ids = set(duplicate_tab_ids)
    reviewed_ids: set[str] = set()

    if not args.dedupe_only:
        try:
            review_status = check_reviews(kept_by_key, reviewer_names)
        except Exception as exc:
            print(f"Lightpanda error: {exc}", file=sys.stderr)
            review_status = {}

        reviewed_keys: set[tuple] = set()
        for key, status in review_status.items():
            if status.reviewed:
                reviewed_keys.add(key)

        for pr in prs:
            if pr.key in reviewed_keys:
                reviewed_ids.add(pr.tab_id)
                duplicate_ids.discard(pr.tab_id)

    if not duplicate_ids and not reviewed_ids:
        log_status("Nothing to close.")
        return 0

    tabs_to_close: list[str] = []
    tabs_to_close.extend(
        _print_section("Duplicates", _group_tabs_by_pr(prs, duplicate_ids))
    )
    if duplicate_ids and reviewed_ids:
        print()
    tabs_to_close.extend(
        _print_section(
            "Already reviewed",
            _group_tabs_by_pr(prs, reviewed_ids),
        )
    )

    if not args.dry_run and tabs_to_close:
        _close_tabs(tabs_to_close)

    return 0
