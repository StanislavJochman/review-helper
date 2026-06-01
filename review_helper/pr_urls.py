"""Parse and normalize GitHub/GitLab PR and MR URLs (including self-hosted)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# github.com, github.example.com, etc.
GITHUB_PULL_RE = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)",
    re.IGNORECASE,
)

# gitlab.com, gitlab.cee.redhat.com, etc.
GITLAB_MR_RE = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<project>.+?)/-/merge_requests/(?P<number>\d+)",
    re.IGNORECASE,
)

TABLINK_RE = re.compile(
    r"^\[(?P<window>\d+):(?P<tab>\d+)\]\s+title:\s*(?P<title>.*?),\s+url:\s*(?P<url>\S+)\s*$"
)


@dataclass(frozen=True, slots=True)
class PullRequestRef:
    platform: str  # "github" or "gitlab"
    host: str
    project: str  # "owner/repo" or nested GitLab path
    number: int
    url: str
    tab_id: str
    window_id: str
    title: str

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.platform, self.host.lower(), self.project.lower(), self.number)

    @property
    def canonical_url(self) -> str:
        if self.platform == "github":
            owner, repo = self.project.split("/", 1)
            return f"https://{self.host}/{owner}/{repo}/pull/{self.number}"
        return f"https://{self.host}/{self.project}/-/merge_requests/{self.number}"


@dataclass(frozen=True, slots=True)
class ChromeTab:
    window_id: str
    tab_id: str
    title: str
    url: str


def parse_tablink(line: str) -> ChromeTab | None:
    match = TABLINK_RE.match(line.strip())
    if not match:
        return None
    return ChromeTab(
        window_id=match.group("window"),
        tab_id=match.group("tab"),
        title=match.group("title"),
        url=match.group("url"),
    )


def parse_pr_url(url: str, tab: ChromeTab) -> PullRequestRef | None:
    github = GITHUB_PULL_RE.match(url)
    if github:
        owner = github.group("owner")
        repo = github.group("repo")
        return PullRequestRef(
            platform="github",
            host=github.group("host"),
            project=f"{owner}/{repo}",
            number=int(github.group("number")),
            url=url,
            tab_id=tab.tab_id,
            window_id=tab.window_id,
            title=tab.title,
        )

    gitlab = GITLAB_MR_RE.match(url)
    if gitlab:
        return PullRequestRef(
            platform="gitlab",
            host=gitlab.group("host"),
            project=gitlab.group("project"),
            number=int(gitlab.group("number")),
            url=url,
            tab_id=tab.tab_id,
            window_id=tab.window_id,
            title=tab.title,
        )
    return None


def tab_keep_score(url: str) -> int:
    """Higher score = prefer keeping this tab when deduplicating."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    score = 0

    if not parsed.fragment:
        score += 50

    suffix_penalties = (
        "/changes",
        "/files",
        "/commits",
        "/diffs",
        "/pipelines",
        "/discussions",
    )
    if not any(path.endswith(s) or f"{s}/" in path for s in suffix_penalties):
        score += 40

    if re.search(r"/pull/\d+$", path, re.I) or re.search(
        r"/-/merge_requests/\d+$", path, re.I
    ):
        score += 100

    return score
