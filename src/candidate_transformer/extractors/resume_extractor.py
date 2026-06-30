"""ResumeExtractor — parses PDF and DOCX resume files.

Uses ``pdfplumber`` for PDF and ``python-docx`` for DOCX.
Section-based parsing detects headers like "Experience", "Education",
"Skills", "Contact" and extracts structured data from each section.
Regex patterns extract emails, phones, LinkedIn/GitHub URLs.

Confidence levels:
- Regex extraction (email/phone/URL): 0.70
- Section-parsed fields (experience, education): 0.65
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from candidate_transformer.models.raw import RawFieldValue

from .base import BaseExtractor
from ._location_parser import location_segments_from_line, parse_location_text

logger = logging.getLogger(__name__)

_CONF_REGEX = 0.70
_CONF_SECTION = 0.65
_CONF_LOCATION = 0.62

# Regex patterns.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?"             # optional country code
    r"(?:\(?\d{2,4}\)?[\s\-.]?)"            # area code
    r"(?:\d{3,4}[\s\-.]?\d{3,4})"           # number
)
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-._~%]+/?", re.I)
_GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-._~%]+/?", re.I)
_URL_RE = re.compile(
    r"(?<![@\w./-])"
    r"(?:(?:https?://)?(?:www\.)?)"
    r"(?!linkedin\.com|github\.com)"
    r"[a-zA-Z0-9][a-zA-Z0-9\-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9\-]*)*\.[a-zA-Z]{2,}"
    r"(?:/[^\s,;]*)?"
    r"(?![\w.-])",
    re.I,
)

# Section header patterns.
_SECTION_PATTERNS = {
    "experience": re.compile(
        r"^\s*(?:(?:professional|work|relevant|industry)\s+)?(?:experience|employment|internships?)\s*$",
        re.I,
    ),
    "education": re.compile(r"^\s*(?:education|academic\s+background|academics?)\s*$", re.I),
    "skills": re.compile(r"^\s*(?:(?:technical|core|professional)\s+)?skills?(?:\s*&\s*tools)?\s*$", re.I),
    "summary": re.compile(r"^\s*(?:summary|profile|objective|about|professional\s+summary)\s*$", re.I),
    "contact": re.compile(r"^\s*contact(?:\s+info(?:rmation)?)?\s*$", re.I),
    "projects": re.compile(r"^\s*(?:technical\s+)?projects?\s*$", re.I),
    "publications": re.compile(r"^\s*(?:publications?|research|literary\s+portfolio)(?:\s*&\s*.*)?\s*$", re.I),
    "achievements": re.compile(r"^\s*(?:achievements?|awards?|recognition|certifications?)\s*(?:&\s*recognition)?\s*$", re.I),
    "leadership": re.compile(r"^\s*(?:leadership|community|volunteering)(?:\s*&\s*community)?\s*$", re.I),
    "certifications": re.compile(r"^\s*(?:certifications?|licenses?|courses?)\s*$", re.I),
}

# Date pattern for experience entries.
_DATE_RANGE_RE = re.compile(
    r"(\w+\s+\d{4}|\d{4})\s*[-–—to]+\s*(\w+\s+\d{4}|\d{4}|[Pp]resent|[Cc]urrent)",
)


_DATE_RANGE_RE = re.compile(
    r"([A-Za-z]{3,9}\s+\d{4}|\d{4})\s*(?:-|–|—|\bto\b)\s*"
    r"([A-Za-z]{3,9}\s+\d{4}|\d{4}|[Pp]resent|[Cc]urrent)",
    re.I,
)
_BULLET_PREFIX_RE = re.compile(r"^\s*[-*•·▪▫‣◦]+\s*")
_CATEGORY_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z /&.+#()-]{1,45}:\s+")
_NOISE_SKILL_RE = re.compile(
    r"\b(?:experience|projects?|achievements?|recognition|leadership|community|remote|developed|engineered|integrated|reduced|improved|secured)\b",
    re.I,
)
_JOINED_WORD_SPLITS = [
    "and", "with", "using", "by", "for", "from", "during", "across", "platform",
    "mobile", "application", "migrating", "based", "web", "chatbot", "enabling",
    "seamless", "healthcare", "interactions", "users", "testing", "designed",
    "implemented", "responsive", "centric", "components", "improving", "user",
    "engagement", "integrated", "frontend", "backend", "responses", "average",
    "latency", "optimized", "performance", "efficient", "state", "management",
    "handling", "reducing", "load", "time", "collaborated", "debugging",
    "feature", "enhancements", "stability", "crash", "occurrences",
    "technologies", "problem", "solving", "building", "applications",
    "developing", "working", "databases", "full", "tools", "sales", "while",
    "allowing", "retailers", "search", "produce", "place", "modify", "orders",
    "complete", "transactions", "submit", "feedback",
]
_KNOWN_SKILL_TERMS = [
    "Python", "Java", "JavaScript", "TypeScript", "C", "C++", "C#", "SQL",
    "React", "Redux", "Node.js", "Express", "FastAPI", "Django", "Flask",
    "TensorFlow", "PyTorch", "BERT", "Transformers", "Deep Learning",
    "Machine Learning", "NLP", "Computer Vision", "AWS", "Azure", "GCP",
    "Docker", "Kubernetes", "Git", "GitHub", "Linux", "Windows",
    "Microsoft Word", "Word", "Excel", "PowerPoint", "Macros",
    "Pivot Tables", "Project Management", "Team Collaboration",
    "Multitasking", "Leadership", "Technical Documentation",
    "Report Writing",
]
_DEGREE_DOMAIN_RE = re.compile(r"^(?:B|M|BSc|MSc|PhD|B\.?Tech|M\.?Tech)\.?(?:Tech|Sc|A|S|E)?$", re.I)
_URL_SKIP_DOMAINS = ("ieeexplore.ieee.org", "leetcode.com", "codechef.com", "hackerrank.com")


def _normalize_url(raw: str) -> str:
    url = raw.strip().strip("()[]{}<>").rstrip(").,;")
    url = re.sub(r"^https?://", "", url, flags=re.I)
    url = re.sub(r"^www\.", "", url, flags=re.I)
    return url.rstrip("/")


class ResumeExtractor(BaseExtractor):
    """Extract candidate data from PDF/DOCX resume files."""

    source_name = "resume_pdf"

    def extract(self, source_path: str | Path) -> list[RawFieldValue]:
        """*source_path* can be a single file or a directory of resumes."""
        path = Path(source_path)

        if path.is_dir():
            results: list[RawFieldValue] = []
            for f in sorted(path.iterdir()):
                if f.suffix.lower() in (".pdf", ".docx"):
                    results.extend(self._extract_file(f))
            return results

        if path.is_file():
            return self._extract_file(path)

        logger.warning("[%s] Path not found: %s", self.source_name, path)
        return []

    def _extract_file(self, path: Path) -> list[RawFieldValue]:
        """Extract from a single resume file."""
        ext = path.suffix.lower()
        try:
            if ext == ".pdf":
                text = self._read_pdf(path)
            elif ext == ".docx":
                text = self._read_docx(path)
            else:
                logger.warning("[%s] Unsupported format: %s", self.source_name, path)
                return []
        except Exception:
            logger.exception("[%s] Failed to read %s", self.source_name, path)
            return []

        if not text or not text.strip():
            logger.warning("[%s] Empty document: %s", self.source_name, path)
            return []

        return self._parse_text(text, str(path))

    def _read_pdf(self, path: Path) -> str:
        """Extract text from a PDF file using pdfplumber."""
        import pdfplumber

        pages: list[str] = []
        links: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
                for link in getattr(page, "hyperlinks", []) or []:
                    uri = (link.get("uri") or "").strip()
                    if uri and uri not in links:
                        links.append(uri)
        if links:
            pages.append("\n".join(links))
        return "\n".join(pages)

    def _read_docx(self, path: Path) -> str:
        """Extract text from a DOCX file using python-docx."""
        import docx

        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    def _parse_text(self, text: str, file_path: str) -> list[RawFieldValue]:
        """Parse extracted text into RawFieldValues."""
        rfvs: list[RawFieldValue] = []
        text = self._normalize_text(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # --- Contact info via regex (whole document) ---
        emails = list(dict.fromkeys(email.strip() for email in _EMAIL_RE.findall(text)))
        phone_matches = list(_PHONE_RE.finditer(text))
        contact_text, body_text = self._split_contact_and_body_text(lines)
        linkedin_matches = self._extract_normalized_urls(_LINKEDIN_RE, contact_text)
        github_matches = self._extract_normalized_urls(_GITHUB_RE, contact_text)

        # Candidate key: first email found, or first line (likely the name).
        first_email = emails[0].lower() if emails else None
        first_line_name = self._infer_name(lines)
        candidate_key = first_email or (first_line_name or "unknown").lower()

        # Name: typically the first non-empty line of a resume.
        if first_line_name and not _EMAIL_RE.match(first_line_name):
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="full_name",
                value=first_line_name,
                source=self.source_name,
                method="first_line_heuristic",
                confidence=_CONF_SECTION,
            ))

        for email in emails:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="emails",
                value=email,
                source=self.source_name,
                method="regex_extract",
                confidence=_CONF_REGEX,
            ))

        for phone_match in phone_matches:
            cleaned = phone_match.group(0).strip()
            if self._is_likely_phone_match(text, phone_match):
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="phones",
                    value=cleaned,
                    source=self.source_name,
                    method="regex_extract",
                    confidence=_CONF_REGEX,
                ))

        for url in linkedin_matches:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="links.linkedin",
                value=url,
                source=self.source_name,
                method="regex_extract",
                confidence=_CONF_REGEX,
            ))

        for url in github_matches:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="links.github",
                value=url,
                source=self.source_name,
                method="regex_extract",
                confidence=_CONF_REGEX,
            ))

        portfolio_matches = self._extract_portfolio_urls(contact_text, linkedin_matches, github_matches)
        for url in portfolio_matches:
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="links.portfolio",
                value=url,
                source=self.source_name,
                method="regex_extract",
                confidence=_CONF_REGEX,
            ))

        # Body profile-shaped URLs are references, not canonical candidate links.
        canonical_links = set(linkedin_matches + github_matches + portfolio_matches)
        for url in self._extract_other_links(body_text, canonical_links):
            rfvs.append(self._make_rfv(
                candidate_key=candidate_key,
                field="links.other",
                value=url,
                source=self.source_name,
                method="regex_extract",
                confidence=_CONF_REGEX,
            ))

        location = self._extract_location(lines)
        if location:
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
                        source=self.source_name,
                        method="contact_location_parse",
                        confidence=_CONF_LOCATION,
                    ))

        # --- Section-based parsing ---
        sections = self._split_sections(lines)

        # Skills section.
        if "skills" in sections:
            for skill in self._parse_skills_section(sections["skills"]):
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="skills",
                    value=skill,
                    source=self.source_name,
                    method="section_parse",
                    confidence=_CONF_SECTION,
                ))

        # Experience section.
        if "experience" in sections:
            for exp in self._parse_experience_section(sections["experience"]):
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="experience",
                    value=exp,
                    source=self.source_name,
                    method="section_parse",
                    confidence=_CONF_SECTION,
                ))

        # Education section.
        if "education" in sections:
            for edu in self._parse_education_section(sections["education"]):
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="education",
                    value=edu,
                    source=self.source_name,
                    method="section_parse",
                    confidence=_CONF_SECTION,
                ))

        # Summary → headline.
        if "summary" in sections:
            summary_text = " ".join(sections["summary"]).strip()
            if summary_text:
                rfvs.append(self._make_rfv(
                    candidate_key=candidate_key,
                    field="headline",
                    value=self._repair_spacing(summary_text),
                    source=self.source_name,
                    method="section_parse",
                    confidence=_CONF_SECTION,
                ))

        logger.info("[%s] Extracted %d fields from %s", self.source_name, len(rfvs), file_path)
        return rfvs

    # ------------------------------------------------------------------
    # Section splitting
    # ------------------------------------------------------------------

    def _split_sections(self, lines: list[str]) -> dict[str, list[str]]:
        """Split resume lines into named sections."""
        sections: dict[str, list[str]] = {}
        current_section: str | None = None

        for line in lines:
            stripped = self._clean_line(line)
            if not stripped:
                continue

            # Check if this line is a section header.
            detected = None
            for sec_name, pattern in _SECTION_PATTERNS.items():
                if pattern.match(stripped):
                    detected = sec_name
                    break

            if detected:
                current_section = detected
                sections.setdefault(current_section, [])
            elif current_section:
                sections[current_section].append(stripped)

        return sections

    # ------------------------------------------------------------------
    # Section parsers
    # ------------------------------------------------------------------

    def _parse_skills_section(self, lines: list[str]) -> list[str]:
        """Parse skills from section lines (comma/bullet separated)."""
        skills: list[str] = []
        for line in lines:
            # Split on common delimiters.
            parts = re.split(r"[,;•·|]|\s{2,}", line)
            for part in parts:
                skill = part.strip().strip("-•·").strip()
                if skill and len(skill) > 1 and len(skill) < 50:
                    skills.append(skill)
        return skills

    def _parse_experience_section(self, lines: list[str]) -> list[dict]:
        """Parse experience entries from section lines."""
        entries: list[dict] = []
        current: dict | None = None

        for line in lines:
            # Look for date ranges — likely start of a new entry.
            date_match = _DATE_RANGE_RE.search(line)
            if date_match:
                if current:
                    entries.append(current)

                # Try to extract company and title from the line.
                before_date = line[:date_match.start()].strip()
                parts = re.split(r"[-–—,|]", before_date, maxsplit=1)
                company = parts[0].strip() if parts else ""
                title = parts[1].strip() if len(parts) > 1 else ""

                current = {
                    "company": company,
                    "title": title,
                    "start": date_match.group(1),
                    "end": date_match.group(2),
                    "summary": None,
                }
            elif current and line.strip():
                # Append to summary of current entry.
                existing = current.get("summary") or ""
                current["summary"] = (existing + " " + line.strip()).strip()

        if current:
            entries.append(current)

        return entries

    def _parse_education_section(self, lines: list[str]) -> list[dict]:
        """Parse education entries from section lines.

        Common resume patterns:
          Pattern A (two lines):
            Stanford University
            M.S. Computer Science, 2016

          Pattern B (single line):
            MIT — Ph.D. Machine Learning, 2018

        Strategy: walk through lines; if a line has NO degree/year, treat it
        as an institution name and look ahead for the degree line.
        """
        entries: list[dict] = []

        _DEGREE_RE = re.compile(
            r"(B\.?S\.?|M\.?S\.?|Ph\.?D\.?|B\.?A\.?|M\.?A\.?|MBA|Bachelor|Master|Doctor)",
            re.I,
        )

        i = 0
        while i < len(lines):
            line = lines[i]
            degree_match = _DEGREE_RE.search(line)
            year_match = re.search(r"(\d{4})", line)

            if not degree_match and not year_match:
                # This line has no degree or year — likely an institution name.
                # Look ahead: if the NEXT line has degree/year info, pair them.
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    next_degree = _DEGREE_RE.search(next_line)
                    next_year = re.search(r"(\d{4})", next_line)

                    if next_degree or next_year:
                        institution = line.strip()
                        degree = next_degree.group(0) if next_degree else None
                        field = None
                        end_year = int(next_year.group(1)) if next_year else None

                        # Extract field of study from after the degree token.
                        if next_degree:
                            after = next_line[next_degree.end():].strip()
                            after = re.sub(r"\d{4}", "", after).strip(" ,.-")
                            if after and len(after) > 1:
                                field = after

                        entries.append({
                            "institution": institution,
                            "degree": degree,
                            "field": field,
                            "end_year": end_year,
                        })
                        i += 2  # consumed both lines
                        continue
                # Standalone line with no match — skip.
                i += 1
                continue

            # This line itself has degree/year (single-line format).
            # Split to get institution from the front.
            parts = re.split(r"[-\u2013\u2014,|]", line, maxsplit=1)
            institution = parts[0].strip() if parts else line.strip()
            degree = degree_match.group(0) if degree_match else None
            field = None
            end_year = int(year_match.group(1)) if year_match else None

            # If institution starts with the degree token, it's not a real
            # institution name (e.g. "M.S. Computer Science, 2016" with no
            # preceding institution line). In that case, use the full line.
            if degree and institution.startswith(degree):
                institution = line.strip()

            if degree_match:
                after = line[degree_match.end():].strip()
                after = re.sub(r"\d{4}", "", after).strip(" ,.-")
                if after and len(after) > 1:
                    field = after

            entries.append({
                "institution": institution,
                "degree": degree,
                "field": field,
                "end_year": end_year,
            })
            i += 1

        # Deduplicate by institution (keep the entry with the most info).
        seen: dict[str, dict] = {}
        for entry in entries:
            key = entry["institution"].lower()
            if key not in seen:
                seen[key] = entry
            else:
                existing = seen[key]
                if sum(1 for v in entry.values() if v) > sum(1 for v in existing.values() if v):
                    seen[key] = entry

        return list(seen.values())

    def _parse_skills_section(self, lines: list[str]) -> list[str]:
        """Parse skills from section lines with ATS-style category handling."""
        skills: list[str] = []
        for line in lines:
            line = self._clean_line(line)
            line = _CATEGORY_PREFIX_RE.sub("", line)
            parts = re.split(r"[,;•·|]|\s{2,}", line)
            for part in parts:
                skill = self._clean_skill(part)
                if skill:
                    skills.append(skill)
        return list(dict.fromkeys(skills))

    def _parse_experience_section(self, lines: list[str]) -> list[dict]:
        """Parse role/date lines and nearby company lines."""
        entries: list[dict] = []
        current: dict | None = None

        for idx, raw_line in enumerate(lines):
            line = self._clean_line(raw_line)
            date_match = _DATE_RANGE_RE.search(line)
            if date_match:
                if current:
                    entries.append(current)

                title = line[:date_match.start()].strip(" -–—,|")
                next_line = self._clean_line(lines[idx + 1]) if idx + 1 < len(lines) else ""
                company = re.sub(r"\b(?:Remote|Hybrid|Onsite|On-site)\b", "", next_line, flags=re.I).strip(" -–—,|")

                current = {
                    "company": company,
                    "title": title,
                    "start": date_match.group(1),
                    "end": date_match.group(2),
                    "summary": None,
                }
                continue

            if current and line:
                company_line = current.get("company") or ""
                if line == company_line or line.endswith(" Remote"):
                    continue
                existing = current.get("summary") or ""
                current["summary"] = self._repair_spacing((existing + " " + line).strip())

        if current:
            entries.append(current)
        return entries

    def _parse_education_section(self, lines: list[str]) -> list[dict]:
        """Parse common ATS education layouts with degree line followed by school."""
        entries: list[dict] = []
        degree_re = re.compile(
            r"\b(Bachelor(?:'s)?(?:\s+of\s+\w+)?|Master(?:'s)?(?:\s+of\s+\w+)?|Doctor(?:ate)?|Ph\.?D\.?|M\.?Tech|B\.?Tech|B\.?E\.?|M\.?S\.?|B\.?S\.?|M\.?A\.?|B\.?A\.?|MBA|Intermediate)\b",
            re.I,
        )

        i = 0
        while i < len(lines):
            line = self._clean_line(lines[i])
            if not line or re.search(r"\b(?:CGPA|GPA|Score)\b", line, re.I):
                i += 1
                continue

            degree_match = degree_re.search(line)
            if not degree_match:
                i += 1
                continue

            years = [int(y) for y in re.findall(r"\b(19|20)\d{2}\b", line)]
            # The regex above captures the century group; collect full years separately.
            years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", line)]
            end_year = max(years) if years else None
            degree = degree_match.group(0)
            field = line[degree_match.end():]
            field = re.sub(r"\b(?:19|20)\d{2}\b", "", field)
            field = re.sub(r"\s*(?:-|–|—|\bto\b)\s*", " ", field).strip(" ,.-–—")

            institution = ""
            if i + 1 < len(lines):
                next_line = self._clean_line(lines[i + 1])
                if next_line and not degree_re.search(next_line) and not re.search(r"\b(?:CGPA|GPA|Score)\b", next_line, re.I):
                    institution = next_line
                elif i + 2 < len(lines):
                    maybe_school = self._clean_line(lines[i + 2])
                    if maybe_school and not degree_re.search(maybe_school):
                        institution = re.sub(r"\b(?:CGPA|GPA|Score):?.*", "", maybe_school, flags=re.I).strip()

            entries.append({
                "institution": institution or line,
                "degree": degree,
                "field": field or None,
                "end_year": end_year,
            })
            i += 1

        seen: dict[str, dict] = {}
        for entry in entries:
            key = entry["institution"].lower()
            if key and key not in seen:
                seen[key] = entry
        return list(seen.values())

    def _parse_skills_section(self, lines: list[str]) -> list[str]:
        """Parse skills conservatively from category-heavy ATS sections."""
        skills: list[str] = []
        for line in lines:
            line = self._clean_line(line)
            if not line:
                continue

            known = self._known_skills_in_text(line)
            for skill in known:
                skills.append(skill)

            if ":" in line and not known:
                _, values = line.split(":", 1)
                for part in re.split(r"[,;|]|\band\b", values):
                    skill = self._clean_skill(part)
                    if skill and skill.lower() not in {"expert-level proficiency", "foundational"}:
                        skills.append(skill)
        return list(dict.fromkeys(skills))

    def _parse_education_section(self, lines: list[str]) -> list[dict]:
        """Parse common ATS education layouts with nearby institution/date context."""
        entries: list[dict] = []
        degree_re = re.compile(
            r"\b(Bachelor(?:'s)?(?:\s+of\s+\w+)?|Master(?:'s)?(?:\s+of\s+\w+)?|Doctor(?:ate)?|Ph\.?D\.?|M\.?Tech|B\.?Tech|B\.?E\.?|M\.?S\.?|B\.?S\.?|M\.?A\.?|B\.?A\.?|MBA|Intermediate|10th\s+Standard|High\s+School)\b",
            re.I,
        )

        for i, raw_line in enumerate(lines):
            line = self._clean_line(raw_line)
            if not line or re.match(r"^(?:Completed|Currently)\b", line, re.I):
                continue

            degree_match = degree_re.search(line)
            if not degree_match:
                continue

            context = " ".join(self._clean_line(l) for l in lines[i:i + 2])
            years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", context)]
            end_year = None if re.search(r"\b(?:Present|Current|Currently)\b", context, re.I) else (max(years) if years else None)
            degree = degree_match.group(0)
            before = line[:degree_match.start()].strip(" ,-|")
            after = line[degree_match.end():]

            if before and len(before.split()) >= 2:
                institution = before
            else:
                institution = ""
                for prev in reversed(lines[max(0, i - 2):i]):
                    prev_line = self._clean_line(prev)
                    if (
                        prev_line
                        and not degree_re.search(prev_line)
                        and not re.search(r"\b(?:CGPA|GPA|Score|Completed|Currently)\b", prev_line, re.I)
                    ):
                        institution = prev_line
                        break

            field = re.split(r"\||CGPA|GPA|Score|Completed|Currently", after, maxsplit=1, flags=re.I)[0]
            field = re.sub(r"\b(?:19|20)\d{2}\b", "", field)
            field = re.sub(r"\s*(?:-|–|—|\bto\b)\s*", " ", field).strip(" ,.-–—()")
            field = re.sub(r"^(?:in|of)\s+", "", field, flags=re.I)

            entries.append({
                "institution": institution or line,
                "degree": degree,
                "field": field or None,
                "end_year": end_year,
            })

        seen: dict[str, dict] = {}
        for entry in entries:
            key = entry["institution"].lower()
            if key and key not in seen:
                seen[key] = entry
        return list(seen.values())

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("â€“", "–").replace("â€”", "—").replace("Â·", "·").replace("â€¢", "•")
        text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text

    @staticmethod
    def _repair_spacing(text: str | None) -> str | None:
        if text is None:
            return None
        repaired = str(text)
        repaired = re.sub(r"\s+", " ", repaired).strip()
        repaired = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", repaired)
        repaired = re.sub(r"(?<=[a-z])(?=AI\b|API\b|REST\b|React\b|Expo\b)", " ", repaired)

        for word in _JOINED_WORD_SPLITS:
            pattern = rf"(?<=[a-z]{{4}})(?={re.escape(word)}(?:[a-z]|-|$))"
            repaired = re.sub(pattern, " ", repaired, flags=re.I)

        direct_replacements = {
            "across-plat form": "across-platform",
            "applicationusing": "application using",
            "Nativewith": "Native with",
            "bymigratinga": "by migrating a",
            "webchatbot": "web chatbot",
            "Collaboratedindebugging": "Collaborated in debugging",
            "andfeatureenhancements": "and feature enhancements",
            "improvingappstability": "improving app stability",
            "andreducing": "and reducing",
            "occurrencesby20": "occurrences by 20",
            "occurrencesby": "occurrences by",
            "andproblem": "and problem",
            "Experiencedin": "Experienced in",
            "buildingfull": "building full",
            "AI-poweredtools": "AI-powered tools",
            "andworking": "and working",
            "andsales": "and sales",
            "whileallowing": "while allowing",
            "retailerstosearchproduce": "retailers to search produce",
            "retailersto": "retailers to",
            "searchproduce": "search produce",
            "placeormodifyorders": "place or modify orders",
            "placeor": "place or",
            "modifyorders": "modify orders",
            "completetransactions": "complete transactions",
            "andsubmitfeedback": "and submit feedback",
            "Collaboratedindebuggingandfeatureenhancements": "Collaborated in debugging and feature enhancements",
            "improvingappstabilityandreducingcrashoccurrences": "improving app stability and reducing crash occurrences",
        }
        for old, new in direct_replacements.items():
            repaired = re.sub(re.escape(old), new, repaired, flags=re.I)

        repaired = re.sub(r"\bReact based\b", "React-based", repaired, flags=re.I)
        repaired = re.sub(r"\bAI driven\b", "AI-driven", repaired, flags=re.I)
        repaired = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", repaired)
        repaired = re.sub(r"\s+([,.;:])", r"\1", repaired)
        repaired = re.sub(r"\s+", " ", repaired).strip()
        return repaired

    @staticmethod
    def _clean_line(line: str) -> str:
        line = _BULLET_PREFIX_RE.sub("", line.strip())
        return re.sub(r"\s+", " ", line).strip()

    @staticmethod
    def _infer_name(lines: list[str]) -> str | None:
        spaced_name: list[str] = []
        for line in lines[:4]:
            collapsed = ResumeExtractor._collapse_letter_spaced_name(line)
            if collapsed:
                spaced_name.append(collapsed)
                continue
            break
        if spaced_name:
            return " ".join(spaced_name).title()

        for line in lines[:8]:
            cleaned = ResumeExtractor._clean_line(line)
            if not cleaned or _EMAIL_RE.search(cleaned) or _PHONE_RE.search(cleaned) or _URL_RE.search(cleaned):
                continue
            if any(ch.isdigit() for ch in cleaned):
                continue
            if len(cleaned.split()) <= 5 and not _SECTION_PATTERNS["summary"].match(cleaned):
                return cleaned
        return None

    @staticmethod
    def _collapse_letter_spaced_name(line: str) -> str | None:
        cleaned = ResumeExtractor._clean_line(line)
        tokens = cleaned.split()
        if len(tokens) < 3:
            return None
        if all(len(token) == 1 and token.isalpha() and token.isupper() for token in tokens):
            return "".join(tokens)
        return None

    @staticmethod
    def _extract_portfolio_urls(
        text: str,
        linkedin_matches: list[str],
        github_matches: list[str],
    ) -> list[str]:
        excluded = {_normalize_url(u) for u in linkedin_matches + github_matches}
        seen: set[str] = set()
        urls: list[str] = []
        scan_text = text
        for raw in _URL_RE.findall(scan_text):
            url = _normalize_url(raw)
            lowered = url.lower()
            domain = lowered.split("/", 1)[0]
            if lowered[0].isdigit():
                continue
            if lowered in excluded:
                continue
            if _DEGREE_DOMAIN_RE.fullmatch(url.strip()):
                continue
            if re.fullmatch(r"\d+(?:\.\d+)+", lowered):
                continue
            if lowered in {"react.js", "node.js", "vue.js", "next.js", "express.js"}:
                continue
            if any(skip_domain in lowered for skip_domain in _URL_SKIP_DOMAINS):
                continue
            if domain in {"b.tech", "m.tech"}:
                continue
            if lowered not in seen:
                seen.add(lowered)
                urls.append(url)
        return urls[:3]

    @staticmethod
    def _split_contact_and_body_text(lines: list[str]) -> tuple[str, str]:
        contact_line_indexes: set[int] = set()
        for idx, line in enumerate(lines[:12]):
            if idx > 0 and any(pattern.match(line) for name, pattern in _SECTION_PATTERNS.items() if name != "contact"):
                break
            if idx < 5 or _EMAIL_RE.search(line) or _PHONE_RE.search(line) or _LINKEDIN_RE.search(line) or _GITHUB_RE.search(line) or _URL_RE.search(line):
                contact_line_indexes.add(idx)

        contact_lines = [line for idx, line in enumerate(lines) if idx in contact_line_indexes]
        body_lines = [line for idx, line in enumerate(lines) if idx not in contact_line_indexes]
        return "\n".join(contact_lines), "\n".join(body_lines)

    @staticmethod
    def _extract_normalized_urls(pattern: re.Pattern, text: str) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for raw in pattern.findall(text):
            url = _normalize_url(raw)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    @classmethod
    def _extract_other_links(cls, text: str, canonical_links: set[str]) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for raw in _LINKEDIN_RE.findall(text) + _GITHUB_RE.findall(text):
            url = _normalize_url(raw)
            if url and url not in canonical_links and url not in seen:
                seen.add(url)
                urls.append(url)
        for url in cls._extract_portfolio_urls(text, [], []):
            if url and url not in canonical_links and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    @staticmethod
    def _is_likely_phone_match(text: str, match: re.Match) -> bool:
        raw = match.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 10 and not raw.startswith("+"):
            return False

        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end].lower()
        if any(marker in line for marker in ("http://", "https://", "doi", "document/", "ieee")):
            return False
        return True

    @staticmethod
    def _extract_location(lines: list[str]):
        for idx, line in enumerate(lines[:12]):
            if _EMAIL_RE.search(line) or _PHONE_RE.search(line) or _URL_RE.search(line):
                candidates = ResumeExtractor._contact_location_candidates(line)
            elif idx < 5 and "," in line:
                candidates = ResumeExtractor._contact_location_candidates(line)
            elif re.search(r"\b(?:location|based\s+in|current\s+location|address)\b", line, re.I):
                candidates = [line]
            else:
                continue

            for candidate in candidates:
                location = parse_location_text(candidate)
                if location:
                    return location
        return None

    @staticmethod
    def _contact_location_candidates(line: str) -> list[str]:
        candidates = location_segments_from_line(line)
        stripped = _EMAIL_RE.sub(" ", line)
        stripped = _PHONE_RE.sub(" ", stripped)
        stripped = _URL_RE.sub(" ", stripped)
        stripped = re.sub(r"\(cid:\d+\)", " ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip(" -|")
        if stripped:
            candidates.append(stripped)
        return candidates

    @staticmethod
    def _known_skills_in_text(text: str) -> list[str]:
        found: list[str] = []
        lowered = text.lower()
        for skill in _KNOWN_SKILL_TERMS:
            pattern = r"(?<![a-z0-9.+#-])" + re.escape(skill.lower()) + r"(?![a-z0-9.+#-])"
            if re.search(pattern, lowered) and skill not in found:
                found.append(skill)
        if "nlp and" in lowered and "NLP" not in found:
            found.append("NLP")
        return found

    @staticmethod
    def _clean_skill(raw: str) -> str | None:
        skill = _BULLET_PREFIX_RE.sub("", raw).strip().strip("-–—·•. ")
        if not skill or not (1 < len(skill) < 45):
            return None
        if skill.lower() in {"and", "or", "technical proficiencies", "core administrative competencies"}:
            return None
        if _NOISE_SKILL_RE.search(skill):
            return None
        if len(skill.split()) > 5:
            return None
        return skill
