# Multi-Source Candidate Data Transformer

Python pipeline for ingesting candidate data from multiple sources, resolving records that refer to the same person, merging fields with provenance and confidence scoring, and projecting the result into a runtime-configurable JSON shape.

The core design rule is: wrong-but-confident is worse than honestly-empty. The pipeline is deterministic and explainable; the merge and confidence logic does not use ML or LLM decisioning.

## Pipeline

`detect -> extract -> normalize -> resolve -> merge -> score -> project -> validate -> emit`

The system keeps three boundaries separate:

- `RawFieldValue`: one claim from one source about one field.
- `CanonicalRecord`: the full merged candidate record with provenance and per-field confidence.
- `Projection`: the runtime-configured output view, rebuilt from the canonical record each run.

## Requirements

- Python >= 3.10
- pip

Install in editable mode:

```bash
pip install -e .
```

For development and tests:

```bash
pip install -e ".[dev]"
```

Optional LLM resume extraction support:

```bash
pip install -e ".[llm]"
```

You can also install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Run The Web App

Start the FastAPI UI:

```bash
candidate-transformer
```

Or run the app directly:

```bash
uvicorn candidate_transformer.app:app --reload
```

Open:

```text
http://localhost:8000
```

The UI can run against bundled sample files or uploaded files.

Resume extraction defaults to the deterministic regex/section extractor. In the Source Data card, use `Resume Extraction` to choose:

- `Regex`: default behavior; no model required.
- `LLM (Qwen)`: uses the optional Qwen extractor only.
- `Both`: runs regex and Qwen extractors on the same resumes so the merger can reward agreement or flag conflicts.

## Run Headless

There is no separate CLI module. To run the engine directly from Python:

```bash
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(csv_path='sources/recruiter.csv', ats_path='sources/ats.json', config_path='configs/default.json', output_path='output/candidates.json'); print(r.stats.print_summary())"
```

If `config_path` is omitted or points to a missing file, the pipeline falls back to `configs/default.json`.

Headless resume extraction modes:

```bash
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(resumes_path='sources/resumes', resume_extraction_mode='regex'); print(r.stats.print_summary())"
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(resumes_path='sources/resumes', resume_extraction_mode='llm'); print(r.stats.print_summary())"
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(resumes_path='sources/resumes', resume_extraction_mode='both'); print(r.stats.print_summary())"
```

Recommended hosted Qwen mode uses Hugging Face's OpenAI-compatible router. It sends extracted PDF/DOCX resume text to a Qwen model:

```bash
set HF_TOKEN=your_hugging_face_token
set QWEN_PROVIDER=hf_vlm
set QWEN_HF_MODEL=Qwen/Qwen2.5-VL-32B-Instruct:novita
```

You can also put these values in a local `.env` file. The app checks `.env` in the project root first and also supports `src/candidate_transformer/extractors/.env` for local extractor-only setup. Restart the server after changing `.env` values.

Relevant environment variables:

- `QWEN_PROVIDER`: defaults to `hf_vlm` for Hugging Face VLM API calls. Use `openai` for another OpenAI-compatible text endpoint.
- `HF_TOKEN` or `HUGGINGFACEHUB_API_TOKEN`: required for `QWEN_PROVIDER=hf_vlm`.
- `QWEN_HF_MODEL`: defaults to `Qwen/Qwen2.5-VL-32B-Instruct:novita`, a larger-than-3B Qwen VL route chosen for stronger extraction quality while still using a hosted provider for speed.
- `QWEN_HF_ROUTER_URL`: defaults to `https://router.huggingface.co/v1/chat/completions`.
- `QWEN_VLM_MAX_PAGES`: defaults to `2` PDF pages for speed; increase if your resumes are longer.
- `QWEN_OPENAI_BASE_URL` and `QWEN_API_KEY`: used for OpenAI-compatible Qwen endpoints.
- `QWEN_TIMEOUT_SECONDS`: defaults to `90` for HF VLM.
- `QWEN_GITHUB_README_LLM`: defaults to `false`; set to `true` to opt into Qwen parsing for GitHub profile README text outside the UI.
- `PHONE_DEFAULT_REGION`: defaults to `US`; used only as the final fallback for local phone numbers when no inferred candidate region validates.

If Qwen is not installed, unreachable, times out, or returns malformed JSON, the LLM extractor logs a warning and returns no values. The pipeline continues with any other available sources.

## Source Inputs

Bundled sample inputs live in `sources/`:

- `sources/recruiter.csv`: recruiter spreadsheet data.
- `sources/ats.json`: ATS applicant data.
- `sources/github_urls.txt`: GitHub usernames/URLs for API extraction. If a public profile README exists at `username/username`, the GitHub extractor parses that README with regex. Qwen README parsing is opt-in via the UI or `QWEN_GITHUB_README_LLM=true`.
- `sources/resumes/`: PDF or DOCX resumes.

In the UI, choose `Use Sample Data` to select bundled sources, or `Upload Files` to provide custom CSV, ATS JSON, GitHub URL text, and resume files.

## Runtime Output Config

Configs are JSON files matching `ProjectionConfig`. The bundled examples are in `configs/`:

- `default.json`: full output shape with confidence and provenance.
- `minimal.json`: small output with name and skills only.
- `strict_email.json`: requires name and primary email, and reports projection errors when missing.

The UI supports both preset configs and arbitrary uploaded config JSON files. In `Output Configuration`, choose `Upload Custom Config`, drop a `.json` file, then run the pipeline.

Example config:

```json
{
  "fields": [
    { "path": "name", "from": "full_name", "type": "string", "required": true },
    { "path": "email", "from": "emails[0]", "type": "string" },
    { "path": "skills", "from": "skills[].name", "type": "string[]" }
  ],
  "include_confidence": true,
  "on_missing": "null"
}
```

Supported behavior:

- Field subsetting: only configured fields are emitted.
- Rename/remap: output `path` can differ from canonical `from`.
- Missing values: `on_missing` can be `null`, `omit`, or `error`.
- Optional projection-time normalization: for example E.164 phone or canonical skills.
- Dynamic validation derives rules from the active config, not a fixed output model.

## Produced Output

Each run writes JSON to `output/candidates_<run_id>.json` when run through the web app. A headless run writes to the `output_path` you pass to `run_pipeline`.

The default output includes fields such as:

- `full_name`
- `primary_email`
- `emails`
- `phone`
- `phones`
- `location`
- `links`
- `headline`
- `years_experience`
- `skills`
- `experience`
- `education`
- `overall_confidence`
- `provenance`

## Tests

Run the full suite:

```bash
pytest tests/ -v
```

Current suite coverage includes normalizers, extractors, entity resolution, merger/confidence behavior, projector behavior, dynamic validator behavior, and edge cases.

## Normalization Rules

| Field | Rule |
| --- | --- |
| Email | Lowercase and validate address shape; malformed emails are rejected. |
| Phone | Parse through `phonenumbers` and emit E.164; invalid numbers are rejected. During merge, local numbers try candidate regions inferred from `location.country` before falling back to `PHONE_DEFAULT_REGION`/US. |
| Date | Normalize common date forms to `YYYY-MM`; present/current end dates become null current roles. |
| Country | Normalize to ISO-3166 alpha-2 codes where possible. |
| Skills | Canonicalize known synonyms such as React.js/React and Kubernetes/k8s; unknown skills pass through with lower confidence. |
| Name | Trim whitespace, collapse internal spacing, and title-case obvious all-caps/lowercase names. |

Rejected values are recorded in the run summary, not silently guessed.

The optional `resume_llm` source uses `raw_confidence=0.55`, lower than `resume_pdf` regex/section extraction, because model inference is less directly auditable than literal regex or section matches. It still emits only `RawFieldValue` objects and never writes directly to `CanonicalRecord`.

## Merge And Confidence Policy

Entity resolution is intentionally conservative:

- Match first by normalized email.
- Then by normalized phone.
- Then by fuzzy full name plus same company at score >= 90.
- Bias toward under-merging over unsafe over-merging.

Per-field merge policy:

- A single valid source is accepted with its raw confidence.
- Multiple sources that agree receive a `+0.10` agreement bonus, capped at `1.0`.
- Conflicting scalar values choose the highest-priority source for that field and cap confidence at `0.60`.
- Provenance records the accepted source and method for each accepted field.
- Overall confidence is the average populated-field confidence multiplied by the ratio of populated expected fields, so sparse records do not appear overly certain.

## Candidate ID Generation

`candidate_id` is deterministic. If a primary email exists, it is the first 16 hex characters of `sha256(lowercase_primary_email)`. If no email exists, it uses `sha256(lowercase_full_name + "|" + lowercase_company)`. If neither exists, it hashes `"unknown"`. This makes repeated runs stable for the same resolved candidate identity.

## Known Limitations

- LinkedIn scraping/API ingestion is not implemented; existing link fields can still be carried when present in source data.
- Recruiter notes `.txt` extraction is not implemented.
- GitHub extraction depends on network access and public GitHub profile availability.
- The web app is the primary runnable interface; there is no separate `candidate_transformer.cli` module.

## Phone Region Design

Phone normalization keeps the original `normalize_phone(raw, default_region="US")` behavior for resolver and projection compatibility. The merger uses a cascading resolver for local numbers: first preserve already-international values, then try distinct `location.country` candidates ordered by confidence, then fall back to `PHONE_DEFAULT_REGION` or `US`. Region-inferred phone accepts are marked on the source value metadata with `region_used` and `region_source`; invalid parses are still rejected under the existing normalization-failed path.
