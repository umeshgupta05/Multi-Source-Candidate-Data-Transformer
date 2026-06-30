"""Entity Resolver — matches the same person across multiple sources.

Matching priority (first match wins, in this order):
1. Exact normalized email match.
2. Exact normalized phone match (E.164).
3. Fuzzy name + company match — rapidfuzz token_sort_ratio ≥ 90 AND
   same normalized current company.
4. No match → new candidate.

Design decision: intentionally biases toward **under-merging** (creating a
duplicate candidate) over **over-merging** (corrupting one candidate with
another's data), because a duplicate is a cheap, visible, fixable error and
a bad merge is silent and dangerous.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from rapidfuzz import fuzz

from candidate_transformer.models.raw import RawFieldValue
from candidate_transformer.normalizers.email import normalize_email
from candidate_transformer.normalizers.phone import normalize_phone
from candidate_transformer.normalizers.name import normalize_name

logger = logging.getLogger(__name__)

# Fuzzy-match threshold for name similarity.
_NAME_THRESHOLD = 90


class EntityResolver:
    """Groups ``RawFieldValue`` lists from different sources by candidate."""

    def resolve(
        self, all_rfvs: list[RawFieldValue]
    ) -> dict[str, list[RawFieldValue]]:
        """Cluster *all_rfvs* into groups keyed by a synthetic cluster ID.

        Returns:
            ``{cluster_id: [RawFieldValue, ...]}`` — one cluster per
            resolved candidate entity.
        """
        source_candidates: list[_SourceCandidate] = self._build_source_candidates(all_rfvs)
        clusters: list[list[_SourceCandidate]] = []
        email_index: dict[str, set[int]] = defaultdict(set)
        phone_index: dict[str, set[int]] = defaultdict(set)
        github_index: dict[str, set[int]] = defaultdict(set)
        company_index: dict[str, list[int]] = defaultdict(list)

        for sc in source_candidates:
            cluster_idx = self._find_cluster_index(
                sc,
                clusters,
                email_index,
                phone_index,
                github_index,
                company_index,
            )
            if cluster_idx is None:
                cluster_idx = len(clusters)
                clusters.append([sc])
            else:
                clusters[cluster_idx].append(sc)
            self._update_indexes(sc, cluster_idx, email_index, phone_index, github_index, company_index)

        # Flatten clusters → dict of {cluster_id: [RFVs]}.
        result: dict[str, list[RawFieldValue]] = {}
        for idx, cluster in enumerate(clusters):
            cluster_id = f"cluster_{idx}"
            rfvs: list[RawFieldValue] = []
            for sc in cluster:
                rfvs.extend(sc.rfvs)
            result[cluster_id] = rfvs

        logger.info(
            "Entity resolution: %d source candidates → %d clusters",
            len(source_candidates),
            len(clusters),
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_cluster_index(
        self,
        sc: "_SourceCandidate",
        clusters: list[list["_SourceCandidate"]],
        email_index: dict[str, set[int]],
        phone_index: dict[str, set[int]],
        github_index: dict[str, set[int]],
        company_index: dict[str, list[int]],
    ) -> int | None:
        """Find the earliest existing cluster that matches this source candidate."""
        exact_hits: set[int] = set()
        for email in sc.emails:
            exact_hits.update(email_index.get(email, set()))
        for phone in sc.phones:
            exact_hits.update(phone_index.get(phone, set()))
        for github in sc.github_profiles:
            exact_hits.update(github_index.get(github, set()))

        for idx in sorted(exact_hits):
            if self._matches_cluster(sc, clusters[idx]):
                return idx

        if not (sc.name and sc.company):
            return None

        for idx in company_index.get(sc.company, []):
            if self._matches_cluster(sc, clusters[idx]):
                return idx
        return None

    @staticmethod
    def _update_indexes(
        sc: "_SourceCandidate",
        cluster_idx: int,
        email_index: dict[str, set[int]],
        phone_index: dict[str, set[int]],
        github_index: dict[str, set[int]],
        company_index: dict[str, list[int]],
    ) -> None:
        """Add a placed source candidate to the resolver lookup indexes."""
        for email in sc.emails:
            email_index[email].add(cluster_idx)
        for phone in sc.phones:
            phone_index[phone].add(cluster_idx)
        for github in sc.github_profiles:
            github_index[github].add(cluster_idx)
        if sc.company and cluster_idx not in company_index[sc.company]:
            company_index[sc.company].append(cluster_idx)

    def _build_source_candidates(
        self, all_rfvs: list[RawFieldValue]
    ) -> list[_SourceCandidate]:
        """Group RFVs by (source, candidate_key) → one _SourceCandidate each."""
        groups: dict[tuple[str, str], list[RawFieldValue]] = defaultdict(list)
        for rfv in all_rfvs:
            key = (rfv.source, rfv.candidate_key)
            groups[key].append(rfv)

        candidates = []
        for (source, ckey), rfvs in groups.items():
            sc = _SourceCandidate(source=source, candidate_key=ckey, rfvs=rfvs)
            sc.extract_identity_signals()
            candidates.append(sc)

        return candidates

    def _matches_cluster(
        self, sc: _SourceCandidate, cluster: list[_SourceCandidate]
    ) -> bool:
        """Check if *sc* matches any member of *cluster*."""
        for member in cluster:
            if self._matches(sc, member):
                return True
        return False

    def _matches(self, a: _SourceCandidate, b: _SourceCandidate) -> bool:
        """Check if two source candidates refer to the same person.

        Priority:
        1. Exact normalized email match.
        2. Exact E.164 phone match.
        3. Exact GitHub profile match.
        4. Fuzzy name + company match (both must pass).
        """
        # 1. Email match.
        if a.emails & b.emails:
            return True

        # 2. Phone match.
        if a.phones & b.phones:
            return True

        # 3. GitHub profile match.
        if a.github_profiles & b.github_profiles:
            return True

        # 4. Fuzzy name + company.
        if a.name and b.name and a.company and b.company:
            name_score = fuzz.token_sort_ratio(a.name, b.name)
            company_match = a.company == b.company
            if name_score >= _NAME_THRESHOLD and company_match:
                return True

        return False


class _SourceCandidate:
    """Internal: one candidate from one source, with identity signals extracted."""

    def __init__(self, source: str, candidate_key: str, rfvs: list[RawFieldValue]):
        self.source = source
        self.candidate_key = candidate_key
        self.rfvs = rfvs
        self.emails: set[str] = set()
        self.phones: set[str] = set()
        self.github_profiles: set[str] = set()
        self.name: str | None = None
        self.company: str | None = None

    def extract_identity_signals(self) -> None:
        """Pull identity fields from the RFVs for matching."""
        for rfv in self.rfvs:
            if rfv.field == "emails":
                email = normalize_email(str(rfv.value))
                if email:
                    self.emails.add(email)
            elif rfv.field == "phones":
                phone = normalize_phone(str(rfv.value))
                if phone:
                    self.phones.add(phone)
            elif rfv.field == "links.github":
                github = _normalize_github_profile(str(rfv.value))
                if github:
                    self.github_profiles.add(github)
            elif rfv.field == "full_name" and not self.name:
                self.name = normalize_name(str(rfv.value))
            elif rfv.field == "current_company" and not self.company:
                val = str(rfv.value).strip().lower()
                if val:
                    self.company = val


def _normalize_github_profile(value: str) -> str | None:
    """Return a stable username from a GitHub profile URL or username."""
    raw = value.strip()
    if not raw:
        return None
    raw = re.sub(r"^https?://", "", raw, flags=re.I)
    raw = re.sub(r"^www\.", "", raw, flags=re.I)
    if raw.lower().startswith("github.com/"):
        raw = raw.split("/", 1)[1]
    elif "/" in raw or "." in raw:
        return None
    username = raw.strip().strip("/").split("/", 1)[0]
    username = re.split(r"[?#]", username, maxsplit=1)[0].lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?", username):
        return None
    return username
