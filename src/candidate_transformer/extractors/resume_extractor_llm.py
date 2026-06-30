"""Optional Qwen-based resume extractor."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

from candidate_transformer.models.raw import RawFieldValue

from . import _qwen_client as qwen_client
from .base import BaseExtractor
from .resume_extractor import ResumeExtractor

logger = logging.getLogger(__name__)

_METHOD = "llm_extraction_qwen"
_CONF_LLM = 0.55
_PROMPT = qwen_client.RESUME_EXTRACTION_PROMPT


class ResumeLLMExtractor(BaseExtractor):
    """Extract candidate data from PDF/DOCX resumes using a Qwen model."""

    source_name = "resume_llm"

    def __init__(self) -> None:
        qwen_client.load_env_files_once()
        self._resume_reader = ResumeExtractor()
        self.last_error: str | None = None

    def extract(self, source_path: str | Path) -> list[RawFieldValue]:
        """*source_path* can be a single file or a directory of resumes."""
        path = Path(source_path)

        if path.is_dir():
            results: list[RawFieldValue] = []
            for file in sorted(path.iterdir()):
                if file.suffix.lower() in (".pdf", ".docx"):
                    results.extend(self._extract_file(file))
            return results

        if path.is_file():
            return self._extract_file(path)

        logger.warning("[%s] Path not found: %s", self.source_name, path)
        self.last_error = f"path not found: {path}"
        return []

    def _extract_file(self, path: Path) -> list[RawFieldValue]:
        self.last_error = None
        try:
            text = self._read_text(path)
            if not text or not text.strip():
                raise ValueError("empty resume text")
            raw_response = self._call_qwen_for_text(text)
            data = self._parse_json_response(raw_response)
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("[%s] Qwen extraction skipped for %s: %s", self.source_name, path, self.last_error)
            return []

        rfvs = self._json_to_rfvs(data, str(path), resume_text=text)
        logger.info("[%s] Extracted %d fields from %s", self.source_name, len(rfvs), path)
        return rfvs

    def _read_text(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._resume_reader._read_pdf(path)
        if ext == ".docx":
            return self._resume_reader._read_docx(path)
        logger.warning("[%s] Unsupported format: %s", self.source_name, path)
        return ""

    def _call_qwen_for_path(self, path: Path) -> str:
        """Call Qwen for a resume path using the selected provider."""
        text = self._read_text(path)
        if not text or not text.strip():
            raise ValueError("empty resume text")
        return self._call_qwen_for_text(text)

    def _call_qwen_for_text(self, text: str) -> str:
        """Call Qwen for already-extracted resume text."""
        provider = os.getenv("QWEN_PROVIDER", "hf_vlm").lower()
        if provider in {"hf_vlm", "huggingface_vlm", "hf"}:
            return self._call_huggingface_vlm_text(text)
        if provider == "openai" or os.getenv("QWEN_OPENAI_BASE_URL"):
            return self._call_qwen(text)
        raise RuntimeError(f"Unsupported QWEN_PROVIDER: {provider}")

    def _call_qwen(self, resume_text: str) -> str:
        """Compatibility wrapper for the OpenAI-compatible text route."""
        return qwen_client.call_openai_compatible_text(qwen_client.make_resume_prompt(resume_text))

    def _call_huggingface_vlm_text(self, resume_text: str) -> str:
        """Compatibility wrapper for the HF route, which now sends text only."""
        return qwen_client.call_qwen_text(qwen_client.make_resume_prompt(resume_text), source_name=self.source_name)

    def _call_huggingface_vlm(self, path: Path) -> str:
        """Compatibility wrapper for older call sites that passed a path."""
        text = self._read_text(path)
        if not text or not text.strip():
            raise ValueError("empty resume text")
        return self._call_huggingface_vlm_text(text)

    def _call_huggingface_text(self, resume_text: str) -> str:
        """Compatibility wrapper for the HF text fallback route."""
        return qwen_client.call_huggingface_text_fallback(qwen_client.make_resume_prompt(resume_text))

    def _call_ollama(self, resume_text: str) -> str:
        """Compatibility wrapper for the local Ollama fallback route."""
        return qwen_client.call_ollama_text(qwen_client.make_resume_prompt(resume_text))

    def _call_openai_compatible(self, prompt: str) -> str:
        return qwen_client.call_openai_compatible_text(prompt)

    @staticmethod
    def _hf_token() -> str:
        return qwen_client.hf_token()

    @staticmethod
    def _post_hf_chat_completion(
        *,
        token: str,
        url: str,
        model: str,
        messages: list[dict[str, Any]],
        timeout: float,
    ) -> str:
        return qwen_client.post_hf_chat_completion(
            token=token,
            url=url,
            model=model,
            messages=messages,
            timeout=timeout,
        )

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        return qwen_client.parse_qwen_json(response)

    def _json_to_rfvs(
        self,
        data: dict[str, Any],
        file_path: str,
        resume_text: str | None = None,
    ) -> list[RawFieldValue]:
        return qwen_client.qwen_json_to_rfvs(
            data,
            file_path,
            source=self.source_name,
            method=_METHOD,
            confidence=_CONF_LLM,
            fallback_text=resume_text,
        )

    @staticmethod
    def _clean_str(value: Any) -> str | None:
        return qwen_client.clean_str(value)

    def _clean_name(self, value: Any) -> str | None:
        return qwen_client.clean_name(value)

    def _clean_emails(self, value: Any) -> list[str]:
        return qwen_client.clean_emails(value)

    def _clean_phones(self, value: Any) -> list[str]:
        return qwen_client.clean_phones(value)

    def _clean_skills(self, value: Any) -> list[str]:
        return qwen_client.clean_skills(value)

    def _clean_experience(self, value: Any) -> list[dict[str, Any]]:
        return qwen_client.clean_experience(value)

    def _clean_education(self, value: Any) -> list[dict[str, Any]]:
        return qwen_client.clean_education(value)

    @staticmethod
    def _clean_year(value: Any) -> int | None:
        return qwen_client.clean_year(value)


def _load_env_files_once() -> None:
    qwen_client.load_env_files_once()


def _candidate_env_paths() -> list[Path]:
    return qwen_client.candidate_env_paths()


def _load_env_file(path: Path) -> None:
    qwen_client.load_env_file(path)


def _format_hf_error(response: requests.Response) -> str:
    return qwen_client.format_hf_error(response)
