"""Shared Qwen provider client and JSON conversion helpers."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests

from candidate_transformer.models.raw import RawFieldValue
from candidate_transformer.normalizers.date import normalize_date
from candidate_transformer.normalizers.email import normalize_email
from candidate_transformer.normalizers.name import normalize_name
from candidate_transformer.normalizers.phone import normalize_phone
from candidate_transformer.normalizers.skills import normalize_skill

from ._location_parser import ParsedLocation, normalize_location_country, parse_location_text
from .resume_extractor import ResumeExtractor

logger = logging.getLogger(__name__)

_ENV_LOADED = False
RESUME_EXTRACTION_PROMPT = """Extract candidate information from the resume text below.

Return ONLY one JSON object. Do not include prose or markdown fences.
Use this exact shape:
{
  "full_name": str | null,
  "emails": [str],
  "phones": [str],
  "location": {"city": str|null, "region": str|null, "country": str|null},
  "links": {"linkedin": str|null, "github": str|null, "portfolio": str|null},
  "headline": str | null,
  "skills": [str],
  "experience": [{"company": str, "title": str, "start": str|null, "end": str|null, "summary": str|null}],
  "education": [{"institution": str, "degree": str|null, "field": str|null, "end_year": int|null}]
}

For "skills", list each individual skill as a separate string.
Do NOT group skills by category. For example, instead of
"Programming Languages: Java, Python", return ["Java", "Python"].

If a value is not explicitly present in the resume, use null or [].
Do not guess.

LOCATION RULES - follow exactly:
- "city" means locality/town/city only, for example Pune, Bengaluru, London,
  San Francisco.
- "region" means state/province/administrative subdivision only, for example
  CA, NY, Texas, Karnataka. If no state/province is explicitly present, set
  region to null.
- "country" means country only, returned as ISO-3166 alpha-2 code, for example
  IN for India, US for United States, GB for United Kingdom.
- Never default country to US. Use US only when the resume explicitly says
  United States, USA, US, or gives a clear US state such as CA/NY/TX together
  with a US city.
- Never put country codes in region. IN, US, GB, CA, AU, DE, FR, SG are
  country codes when they refer to countries. For Indian locations, IN is
  always country, never region.
- For Indian addresses like "Pune, India" or street address ending in
  "Pune, India", return city Pune, region null, country IN.

Location examples:
- "Pune, India" -> {"city": "Pune", "region": null, "country": "IN"}
- "Door No.: 12-34/A, Central Avenue 2nd Line, Example Colony, Pune, India" -> {"city": "Pune", "region": null, "country": "IN"}
- "Bengaluru, Karnataka, India" -> {"city": "Bengaluru", "region": "Karnataka", "country": "IN"}
- "San Francisco, CA" -> {"city": "San Francisco", "region": "CA", "country": "US"}
- "Cambridge, MA, United States" -> {"city": "Cambridge", "region": "MA", "country": "US"}
- "London, United Kingdom" -> {"city": "London", "region": null, "country": "GB"}

Invalid location output examples:
- Do NOT return {"city": "Pune", "region": "IN", "country": "US"}.
- Do NOT return {"city": "Pune", "region": "IN", "country": null}.
- Correct output is {"city": "Pune", "region": null, "country": "IN"}.

Resume text:
__RESUME_TEXT__
"""


def make_resume_prompt(resume_text: str) -> str:
    return RESUME_EXTRACTION_PROMPT.replace("__RESUME_TEXT__", resume_text[:20000])


def call_qwen_text(prompt: str, *, source_name: str = "qwen") -> str:
    """Call the configured Qwen provider with a text prompt."""
    load_env_files_once()
    provider = os.getenv("QWEN_PROVIDER", "hf_vlm").lower()

    if provider in {"hf_vlm", "huggingface_vlm", "hf"}:
        try:
            return call_huggingface_qwen_text(prompt)
        except Exception as exc:
            if os.getenv("QWEN_HF_TEXT_FALLBACK", "true").lower() in {"0", "false", "no"}:
                raise
            logger.warning(
                "[%s] HF Qwen route failed; falling back to HF text model: %s",
                source_name,
                exc,
            )
            try:
                return call_huggingface_text_fallback(prompt)
            except Exception as hf_text_exc:
                if os.getenv("QWEN_OLLAMA_FALLBACK", "true").lower() in {"0", "false", "no"}:
                    raise
                logger.warning(
                    "[%s] HF text fallback also failed: %s; trying local Ollama...",
                    source_name,
                    hf_text_exc,
                )
                return call_ollama_text(prompt)

    if provider == "openai" or os.getenv("QWEN_OPENAI_BASE_URL"):
        return call_openai_compatible_text(prompt)

    raise RuntimeError(f"Unsupported QWEN_PROVIDER: {provider}")


def call_huggingface_qwen_text(prompt: str) -> str:
    token = hf_token()
    model = os.getenv("QWEN_HF_MODEL", "Qwen/Qwen2.5-VL-72B-Instruct:featherless-ai")
    url = os.getenv("QWEN_HF_ROUTER_URL", "https://router.huggingface.co/v1/chat/completions")
    timeout = float(os.getenv("QWEN_TIMEOUT_SECONDS", "90"))
    return post_hf_chat_completion(
        token=token,
        url=url,
        model=model,
        messages=[
            {"role": "system", "content": "Return only valid JSON. Do not guess missing resume values."},
            {"role": "user", "content": prompt},
        ],
        timeout=timeout,
    )


def call_huggingface_text_fallback(prompt: str) -> str:
    token = hf_token()
    model = os.getenv("QWEN_HF_TEXT_MODEL", "Qwen/Qwen3-32B:groq")
    url = os.getenv("QWEN_HF_ROUTER_URL", "https://router.huggingface.co/v1/chat/completions")
    timeout = float(os.getenv("QWEN_TIMEOUT_SECONDS", "90"))
    return post_hf_chat_completion(
        token=token,
        url=url,
        model=model,
        messages=[
            {"role": "system", "content": "Return only valid JSON. Do not guess missing resume values."},
            {"role": "user", "content": prompt},
        ],
        timeout=timeout,
    )


def call_ollama_text(prompt: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the openai package for Ollama fallback") from exc

    model = os.getenv("QWEN_OLLAMA_MODEL", "qwen2.5vl:3b")
    base_url = os.getenv("QWEN_OLLAMA_URL", "http://localhost:11434/v1")
    timeout = float(os.getenv("QWEN_TIMEOUT_SECONDS", "180"))

    client = OpenAI(base_url=base_url, api_key="not-needed", timeout=timeout)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Return only valid JSON. Do not guess missing resume values."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return completion.choices[0].message.content or ""


def call_openai_compatible_text(prompt: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the optional llm extra for OpenAI-compatible Qwen endpoints") from exc

    model = os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    base_url = os.getenv("QWEN_OPENAI_BASE_URL")
    api_key = os.getenv("QWEN_API_KEY", "not-needed")
    timeout = float(os.getenv("QWEN_TIMEOUT_SECONDS", "60"))

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Return only valid JSON. Do not guess missing resume values."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return completion.choices[0].message.content or ""


def parse_qwen_json(response: str) -> dict[str, Any]:
    if not response or not response.strip():
        raise ValueError("empty model response")

    text = response.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S | re.I)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("model response is not a JSON object")
    return data


def qwen_json_to_rfvs(
    data: dict[str, Any],
    file_path: str,
    *,
    source: str,
    method: str,
    confidence: float,
    candidate_key_override: str | None = None,
    metadata: dict[str, Any] | None = None,
    fallback_text: str | None = None,
) -> list[RawFieldValue]:
    rfvs: list[RawFieldValue] = []
    metadata = metadata or {}

    full_name = clean_name(data.get("full_name"))
    emails = clean_emails(data.get("emails"))
    phones = clean_phones(data.get("phones"))
    candidate_key = candidate_key_override or (emails[0] if emails else None)
    candidate_key = candidate_key or (phones[0] if phones else (full_name or Path(file_path).stem).lower())

    def make(field: str, value: Any) -> RawFieldValue:
        return RawFieldValue(
            candidate_key=candidate_key,
            field=field,
            value=value,
            source=source,
            method=method,
            raw_confidence=confidence,
            metadata={"file_path": file_path, **metadata},
        )

    if full_name:
        rfvs.append(make("full_name", full_name))
    for email in emails:
        rfvs.append(make("emails", email))
    for phone in phones:
        rfvs.append(make("phones", phone))

    location = clean_location(data.get("location"), fallback_text=fallback_text)
    if location:
        for field, value in (
            ("location.city", location.city),
            ("location.region", location.region),
            ("location.country", location.country),
        ):
            if value:
                rfvs.append(make(field, value))

    links = data.get("links") or {}
    if isinstance(links, dict):
        for link_type in ("linkedin", "github", "portfolio"):
            url = clean_str(links.get(link_type))
            if url:
                rfvs.append(make(f"links.{link_type}", url))

    headline = clean_str(data.get("headline"))
    if headline:
        rfvs.append(make("headline", headline))

    for skill in clean_skills(data.get("skills")):
        rfvs.append(make("skills", skill))
    for experience in clean_experience(data.get("experience")):
        rfvs.append(make("experience", experience))
    for education in clean_education(data.get("education")):
        rfvs.append(make("education", education))

    return rfvs


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = ResumeExtractor._repair_spacing(str(value).strip())
    return cleaned or None


def clean_name(value: Any) -> str | None:
    cleaned = clean_str(value)
    return normalize_name(cleaned) if cleaned else None


def clean_emails(value: Any) -> list[str]:
    emails: list[str] = []
    for item in value if isinstance(value, list) else []:
        email = normalize_email(str(item))
        if email and email not in emails:
            emails.append(email)
    return emails


def clean_phones(value: Any) -> list[str]:
    phones: list[str] = []
    for item in value if isinstance(value, list) else []:
        phone = normalize_phone(str(item))
        if phone and phone not in phones:
            phones.append(phone)
    return phones


def clean_location(value: Any, fallback_text: str | None = None) -> ParsedLocation | None:
    fallback = location_from_resume_text(fallback_text)

    if isinstance(value, str):
        parsed = parse_location_text(value)
        return reconcile_location(parsed, fallback, raw_value=value)

    if not isinstance(value, dict):
        return fallback

    raw = clean_str(value.get("raw") or value.get("text") or value.get("full") or value.get("address"))
    if raw:
        parsed = parse_location_text(raw)
        if parsed:
            return reconcile_location(parsed, fallback, raw_value=raw)

    city = clean_str(value.get("city"))
    region = clean_str(value.get("region") or value.get("state") or value.get("province"))
    country = normalize_location_country(clean_str(value.get("country")))

    if country == "US" and fallback and fallback.country and fallback.country != "US":
        return ParsedLocation(
            city=fallback.city or city,
            region=fallback.region,
            country=fallback.country,
        )

    region_as_country = normalize_location_country(region)
    if region_as_country and len(region or "") <= 3 and not country:
        if not country or country != region_as_country:
            country = region_as_country
        region = None
        if city or country:
            return reconcile_location(
                ParsedLocation(city=city, region=region, country=country),
                fallback,
                raw_value=json.dumps(value),
            )

    if not city and not region and not country:
        return fallback

    if city and country:
        joined = ", ".join(part for part in (city, region, country) if part)
        parsed = parse_location_text(joined)
        if parsed:
            return reconcile_location(parsed, fallback, raw_value=json.dumps(value))

    return reconcile_location(
        ParsedLocation(city=city, region=region, country=country),
        fallback,
        raw_value=json.dumps(value),
    )


def location_from_resume_text(text: str | None) -> ParsedLocation | None:
    if not text or not text.strip():
        return None
    normalized = ResumeExtractor._normalize_text(text)
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    return ResumeExtractor._extract_location(lines)


def reconcile_location(
    llm_location: ParsedLocation | None,
    fallback_location: ParsedLocation | None,
    *,
    raw_value: str | None,
) -> ParsedLocation | None:
    if not llm_location:
        return fallback_location
    if not fallback_location:
        return llm_location

    if llm_location.country == "US" and fallback_location.country and fallback_location.country != "US":
        raw = (raw_value or "").lower()
        has_explicit_us = re.search(r"\b(?:united states|usa|u\.s\.a\.|u\.s\.|us)\b", raw)
        if not has_explicit_us:
            return ParsedLocation(
                city=fallback_location.city or llm_location.city,
                region=fallback_location.region,
                country=fallback_location.country,
            )

    return llm_location


def clean_skills(value: Any) -> list[str]:
    skills: list[str] = []
    for item in value if isinstance(value, list) else []:
        raw = clean_str(item)
        if not raw:
            continue
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        for part in re.split(r"[,;]", raw):
            part = part.strip()
            if not part:
                continue
            skill, _ = normalize_skill(part)
            if skill and skill not in skills:
                skills.append(skill)
    return skills


def clean_experience(value: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        company = clean_str(item.get("company"))
        title = clean_str(item.get("title"))
        if not company and not title:
            continue
        start, _ = normalize_date(item.get("start"))
        end, _ = normalize_date(item.get("end"))
        entries.append({
            "company": company or "",
            "title": title or "",
            "start": start,
            "end": end,
            "summary": clean_str(item.get("summary")),
        })
    return entries


def clean_education(value: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        institution = clean_str(item.get("institution"))
        if not institution:
            continue
        entries.append({
            "institution": institution,
            "degree": clean_str(item.get("degree")),
            "field": clean_str(item.get("field")),
            "end_year": clean_year(item.get("end_year")),
        })
    return entries


def clean_year(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d{4}", str(value))
    return int(match.group(0)) if match else None


def hf_token() -> str:
    load_env_files_once()
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN or HUGGINGFACEHUB_API_TOKEN is required for QWEN_PROVIDER=hf_vlm")
    return token


def post_hf_chat_completion(
    *,
    token: str,
    url: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
) -> str:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        },
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(format_hf_error(response))
    payload = response.json()
    return str(payload["choices"][0]["message"].get("content") or "")


def format_hf_error(response: requests.Response) -> str:
    message = response.text.strip()
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error)
        elif error:
            message = str(error)

    return f"Hugging Face router error {response.status_code}: {message}"


def load_env_files_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    seen: set[Path] = set()
    for path in candidate_env_paths():
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        load_env_file(resolved)

    _ENV_LOADED = True


def candidate_env_paths() -> list[Path]:
    module_path = Path(__file__).resolve()
    project_root = module_path.parents[3]
    return [
        Path.cwd() / ".env",
        project_root / ".env",
        module_path.parent / ".env",
    ]


def load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8-sig").splitlines()

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
