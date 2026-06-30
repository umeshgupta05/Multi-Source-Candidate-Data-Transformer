"""GitHubExtractor — extracts candidate data from GitHub REST API.

Calls:
- ``GET /users/{username}`` → name, bio, location, email, blog
- ``GET /users/{username}/repos`` → languages (→ skills)

Edge-case handling:
- 404 user → return empty list, log warning.
- Rate-limited (429) → return empty list, log warning.
- Network error → return empty list, log warning.
- Never crashes the pipeline.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path

import requests

from candidate_transformer.models.raw import RawFieldValue

from . import _qwen_client as qwen_client
from .base import BaseExtractor
from ._location_parser import parse_location_text
from .resume_extractor import ResumeExtractor

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_BASE_CONFIDENCE = 0.90
_README_REGEX_CONFIDENCE = 0.72
_README_LLM_CONFIDENCE = 0.58
_TIMEOUT = 10  # seconds
_README_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_README_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-._~%]+/?", re.I)
_README_URL_RE = re.compile(
    r"https?://[^\s)\],;]+|"
    r"(?:www\.)?[a-zA-Z0-9][a-zA-Z0-9\-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9\-]*)*\.[a-zA-Z]{2,}(?:/[^\s)\],;]*)?",
    re.I,
)
_README_SKILL_TERMS = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Redux", "Next.js",
    "Node.js", "Express", "Spring Boot", "REST APIs", "GraphQL", "Docker",
    "Kubernetes", "AWS", "GCP", "Azure", "MySQL", "PostgreSQL", "MongoDB",
    "Redis", "Git", "GitHub", "Machine Learning", "Deep Learning", "PyTorch",
    "TensorFlow", "Pandas", "NumPy", "FastAPI", "Django", "Flask",
]


class GitHubExtractor(BaseExtractor):
    """Extract candidate data from GitHub profiles via REST API."""

    source_name = "github_api"

    def __init__(self, readme_llm_enabled: bool | None = None) -> None:
        if readme_llm_enabled is None:
            readme_llm_enabled = os.getenv("QWEN_GITHUB_README_LLM", "false").lower() in {"1", "true", "yes"}
        self.readme_llm_enabled = readme_llm_enabled

    def extract(self, source_path: str | Path) -> list[RawFieldValue]:
        """*source_path* is a text file with one GitHub username per line."""
        path = Path(source_path)
        if not self._check_file(path):
            return []

        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
        except OSError as exc:
            logger.warning("[%s] Cannot read %s: %s", self.source_name, path, exc)
            return []

        results: list[RawFieldValue] = []
        for line in lines:
            username = self._normalize_username(line)
            if not username or username.startswith("#"):
                continue
            try:
                rfvs = self._extract_user(username)
                results.extend(rfvs)
            except Exception:
                logger.exception(
                    "[%s] Unexpected error for username '%s' — skipping.",
                    self.source_name,
                    username,
                )

        logger.info(
            "[%s] Extracted %d field values from %s",
            self.source_name,
            len(results),
            path,
        )
        return results

    def _extract_user(self, username: str) -> list[RawFieldValue]:
        """Extract RFVs for a single GitHub user."""
        # Fetch user profile.
        user_data = self._api_get(f"/users/{username}")
        if user_data is None:
            return []

        rfvs: list[RawFieldValue] = []

        # Candidate key: prefer email, fall back to login.
        email = (user_data.get("email") or "").strip().lower()
        name = (user_data.get("name") or "").strip()
        candidate_key = email or name.lower() or username.lower()

        # Name.
        if name:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="full_name",
                value=name,
                source=self.source_name,
                method="api_field",
                confidence=_BASE_CONFIDENCE,
            ))

        # Email.
        if email:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="emails",
                value=email,
                source=self.source_name,
                method="api_field",
                confidence=_BASE_CONFIDENCE,
            ))

        # Bio → headline.
        bio = (user_data.get("bio") or "").strip()
        if bio:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="headline",
                value=bio,
                source=self.source_name,
                method="api_field",
                confidence=_BASE_CONFIDENCE,
            ))

        # Location.
        location = (user_data.get("location") or "").strip()
        if location:
            parsed_location = parse_location_text(location)
            if parsed_location:
                rfvs.extend(self._location_rfvs(
                    candidate_key,
                    parsed_location,
                    username,
                    source=self.source_name,
                    method="api_location_parse",
                    confidence=0.78,
                ))
            else:
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="location.city",
                    value=location,
                    source=self.source_name,
                    method="api_field",
                    confidence=0.7,  # Location is free-text, less structured.
                ))

        # Blog → portfolio link.
        blog = (user_data.get("blog") or "").strip()
        if blog:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="links.portfolio",
                value=blog,
                source=self.source_name,
                method="api_field",
                confidence=_BASE_CONFIDENCE,
            ))

        # GitHub profile URL.
        html_url = user_data.get("html_url", f"https://github.com/{username}")
        rfvs.append(self._make_rfv(
            candidate_key=candidate_key,
            field="links.github",
            value=html_url,
            source=self.source_name,
            method="api_field",
            confidence=_BASE_CONFIDENCE,
        ))

        # Company.
        company = (user_data.get("company") or "").strip().lstrip("@")
        if company:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="current_company",
                value=company,
                source=self.source_name,
                method="api_field",
                confidence=0.7,
            ))

        # --- Repos → languages (skills) ---
        repos = self._api_get(f"/users/{username}/repos?per_page=100&sort=pushed")
        if repos and isinstance(repos, list):
            languages: set[str] = set()
            for repo in repos:
                if isinstance(repo, dict) and not repo.get("fork", False):
                    lang = repo.get("language")
                    if lang:
                        languages.add(lang)

            for lang in sorted(languages):
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="skills",
                    value=lang,
                    source=self.source_name,
                    method="repo_language_analysis",
                    confidence=_BASE_CONFIDENCE,
                ))

        readme_text = self._fetch_profile_readme(username)
        if readme_text:
            rfvs.extend(self._extract_readme_regex(readme_text, candidate_key, username))
            rfvs.extend(self._extract_readme_llm(readme_text, candidate_key, username))

        return rfvs

    @staticmethod
    def _normalize_username(raw: str) -> str:
        value = raw.strip().lstrip("\ufeff")
        if not value or value.startswith("#"):
            return ""
        value = re.sub(r"^https?://", "", value, flags=re.I)
        value = re.sub(r"^www\.", "", value, flags=re.I)
        if value.lower().startswith("github.com/"):
            value = value.split("/", 1)[1]
        value = value.strip().strip("/").split("/")[0]
        return re.split(r"[?#]", value, maxsplit=1)[0]

    def _api_get(self, endpoint: str) -> dict | list | None:
        """Make a GET request to the GitHub API. Returns None on failure."""
        url = f"{_API_BASE}{endpoint}"
        try:
            resp = requests.get(url, timeout=_TIMEOUT, headers={"Accept": "application/vnd.github.v3+json"})

            if resp.status_code == 404:
                logger.warning("[%s] 404 Not Found: %s", self.source_name, url)
                return None
            if resp.status_code == 403 or resp.status_code == 429:
                logger.warning("[%s] Rate limited (%d): %s", self.source_name, resp.status_code, url)
                return None
            if resp.status_code != 200:
                logger.warning("[%s] HTTP %d: %s", self.source_name, resp.status_code, url)
                return None

            return resp.json()

        except requests.RequestException as exc:
            logger.warning("[%s] Network error for %s: %s", self.source_name, url, exc)
            return None

    def _fetch_profile_readme(self, username: str) -> str | None:
        """Fetch README text from the special GitHub profile repository."""
        payload = self._api_get(f"/repos/{username}/{username}/readme")
        if not isinstance(payload, dict):
            return None

        content = payload.get("content")
        encoding = payload.get("encoding")
        if isinstance(content, str) and encoding == "base64":
            try:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            except ValueError as exc:
                logger.warning("[%s] Could not decode README for %s: %s", self.source_name, username, exc)
                return None

        download_url = payload.get("download_url")
        if isinstance(download_url, str) and download_url:
            try:
                response = requests.get(download_url, timeout=_TIMEOUT)
                if response.ok:
                    return response.text
            except requests.RequestException as exc:
                logger.warning("[%s] README download failed for %s: %s", self.source_name, username, exc)
        return None

    def _extract_readme_regex(
        self,
        text: str,
        candidate_key: str,
        username: str,
    ) -> list[RawFieldValue]:
        """Extract candidate hints from profile README markdown without an LLM."""
        cleaned = ResumeExtractor._normalize_text(_strip_markdown(text))
        rfvs: list[RawFieldValue] = []
        rfvs.append(self._readme_rfv(
            candidate_key,
            "links.github",
            f"https://github.com/{username}",
            username,
            "readme_identity",
        ))

        for email in dict.fromkeys(_README_EMAIL_RE.findall(cleaned)):
            rfvs.append(self._readme_rfv(candidate_key, "emails", email.lower(), username, "github_readme_regex"))

        for url in dict.fromkeys(_README_LINKEDIN_RE.findall(cleaned)):
            rfvs.append(self._readme_rfv(candidate_key, "links.linkedin", url, username, "github_readme_regex"))

        for url in self._portfolio_urls_from_readme(cleaned):
            rfvs.append(self._readme_rfv(candidate_key, "links.portfolio", url, username, "github_readme_regex"))

        headline = self._headline_from_readme(cleaned, username)
        if headline:
            rfvs.append(self._readme_rfv(candidate_key, "headline", headline, username, "github_readme_regex"))

        location = self._location_from_readme(cleaned)
        if location:
            rfvs.extend(self._location_rfvs(
                candidate_key,
                location,
                username,
                source="github_readme_regex",
                method="readme_location_parse",
                confidence=_README_REGEX_CONFIDENCE,
            ))

        for skill in self._skills_from_readme(cleaned):
            rfvs.append(self._readme_rfv(candidate_key, "skills", skill, username, "github_readme_regex"))

        return rfvs

    def _extract_readme_llm(
        self,
        text: str,
        candidate_key: str,
        username: str,
    ) -> list[RawFieldValue]:
        """Extract structured fields from profile README text using Qwen."""
        if not self.readme_llm_enabled:
            return []

        try:
            raw = qwen_client.call_qwen_text(qwen_client.make_resume_prompt(text), source_name="github_readme_llm")
            data = qwen_client.parse_qwen_json(raw)
            rfvs = qwen_client.qwen_json_to_rfvs(
                data,
                f"github://{username}/README.md",
                source="github_readme_llm",
                method="github_readme_llm",
                confidence=_README_LLM_CONFIDENCE,
                candidate_key_override=candidate_key,
                metadata={"username": username},
            )
            if not any(r.field == "links.github" for r in rfvs):
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="links.github",
                    value=f"https://github.com/{username}",
                    source="github_readme_llm",
                    method="readme_identity",
                    confidence=_README_LLM_CONFIDENCE,
                    username=username,
                ))
        except Exception as exc:
            logger.warning("[%s] README LLM extraction skipped for %s: %s", self.source_name, username, exc)
            return []
        return rfvs

    def _readme_rfv(
        self,
        candidate_key: str,
        field: str,
        value,
        username: str,
        method: str,
    ) -> RawFieldValue:
        return self._make_rfv(
            candidate_key=candidate_key,
            field=field,
            value=value,
            source="github_readme_regex",
            method=method,
            confidence=_README_REGEX_CONFIDENCE,
            username=username,
        )

    def _location_rfvs(
        self,
        candidate_key: str,
        location,
        username: str,
        source: str,
        method: str,
        confidence: float,
    ) -> list[RawFieldValue]:
        rfvs: list[RawFieldValue] = []
        for field, value in (
            ("location.city", location.city),
            ("location.region", location.region),
            ("location.country", location.country),
        ):
            if value:
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field=field,
                    value=value,
                    source=source,
                    method=method,
                    confidence=confidence,
                    username=username,
                ))
        return rfvs

    @staticmethod
    def _headline_from_readme(text: str, username: str) -> str | None:
        for line in text.splitlines():
            line = line.strip(" #*-`")
            if not line or username.lower() in line.lower() or line.lower().startswith(("hi ", "hello ", "welcome ")):
                continue
            if 20 <= len(line) <= 220:
                return line
        return None

    @staticmethod
    def _location_from_readme(text: str):
        for line in text.splitlines()[:30]:
            cleaned = line.strip(" #*-`")
            if not re.search(r"\b(?:location|based\s+in|current\s+location)\b", cleaned, re.I):
                continue
            location = parse_location_text(cleaned)
            if location:
                return location
        return None

    @staticmethod
    def _portfolio_urls_from_readme(text: str) -> list[str]:
        urls: list[str] = []
        for raw in _README_URL_RE.findall(text):
            url = raw.strip().rstrip(").,;")
            lowered = url.lower()
            if any(skip in lowered for skip in ("github.com", "linkedin.com", "shields.io", "github-readme-stats", "img.shields.io")):
                continue
            if _looks_like_readme_url_false_positive(url):
                continue
            if lowered not in {u.lower() for u in urls}:
                urls.append(url)
        if not urls:
            return []

        def score(url: str) -> tuple[int, int]:
            lowered = url.lower()
            value = 0
            if any(host in lowered for host in ("github.io", "vercel.app", "netlify.app", "render.com", "pages.dev")):
                value += 20
            if any(word in lowered for word in ("portfolio", "personal", "resume", "cv", "about")):
                value += 10
            if any(word in lowered for word in ("docs", "blog", "medium.com", "dev.to", "youtube.com", "twitter.com", "x.com")):
                value -= 10
            return value, -len(url)

        best = max(urls, key=score)
        return [best]

    @staticmethod
    def _skills_from_readme(text: str) -> list[str]:
        found: list[str] = []
        lowered = text.lower()
        for skill in _README_SKILL_TERMS:
            pattern = r"(?<![a-z0-9.+#-])" + re.escape(skill.lower()) + r"(?![a-z0-9.+#-])"
            if re.search(pattern, lowered) and skill not in found:
                found.append(skill)
        return found


def _strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", text)
    return text


def _looks_like_readme_url_false_positive(url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith(("http://", "https://", "www.")):
        return False
    host = lowered.split("/", 1)[0]
    labels = host.split(".")
    if len(labels) < 2:
        return True
    if len(labels[0]) <= 1:
        return True
    if host in {"node.js", "next.js", "react.js", "vue.js", "express.js", "three.js"}:
        return True
    return False
