# Multi-Source Candidate Data Transformer

Python pipeline for ingesting candidate data from recruiter CSV, ATS JSON, GitHub profiles, and resumes; resolving records that refer to the same person; merging fields with provenance and confidence; and projecting the result into a runtime-configurable JSON shape.

## Install And Run

Requirements:

- Python 3.10 or newer
- pip

Clone and enter the project:

```bash
git clone https://github.com/umeshgupta05/Multi-Source-Candidate-Data-Transformer.git
cd Multi-Source-Candidate-Data-Transformer
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Install the app:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Start the web app:

```bash
candidate-transformer
```

Open:

```text
http://localhost:8000
```

If port `8000` is busy:

```bash
uvicorn candidate_transformer.app:app --reload --port 8001
```

Then open `http://localhost:8001`.

## Run The Pipeline

Use the web UI for the main workflow:

1. Choose `Use Sample Data` or `Upload Files`.
2. Select the sources to process: recruiter CSV, ATS JSON, GitHub profiles, and/or resumes.
3. Choose resume extraction mode: `Regex`, `LLM (Qwen)`, or `Both`.
4. Choose an output config: `default`, `minimal`, `strict_email`, or upload a custom config JSON.
5. Click `Run Pipeline`.
6. Review candidate cards, confidence, provenance, conflicts, rejections, and validation errors.

Each web run writes JSON to:

```text
output/candidates_<run_id>.json
```

Headless Python example:

```bash
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(csv_path='sources/recruiter.csv', ats_path='sources/ats.json', github_urls_path='sources/github_urls.txt', resumes_path='sources/resumes', config_path='configs/default.json', output_path='output/candidates_sample.json', resume_extraction_mode='regex'); print(r.stats.print_summary())"
```

Run tests:

```bash
pytest tests/ -v
```

## Optional LLM Setup

Regex mode is deterministic and does not require an API key. LLM mode is optional and fail-soft: if the provider is unavailable, the pipeline logs the issue and continues with other sources.

Install LLM dependencies:

```bash
pip install -e ".[dev,llm]"
```

Hugging Face router example:

```bash
export HF_TOKEN="your_hugging_face_token"
export QWEN_PROVIDER="hf_vlm"
export QWEN_HF_MODEL="Qwen/Qwen2.5-VL-32B-Instruct:novita"
candidate-transformer
```

Windows PowerShell:

```powershell
$env:HF_TOKEN = "your_hugging_face_token"
$env:QWEN_PROVIDER = "hf_vlm"
$env:QWEN_HF_MODEL = "Qwen/Qwen2.5-VL-32B-Instruct:novita"
candidate-transformer
```

Supported local env files:

- `.env`
- `src/candidate_transformer/extractors/.env`

Do not commit real API tokens.

GitHub README LLM parsing is opt-in. Use the UI toggle or set:

```bash
QWEN_GITHUB_README_LLM=true
```

## Source Inputs

Bundled sample inputs:

- `sources/recruiter.csv`: recruiter spreadsheet data.
- `sources/ats.json`: applicant tracking system data.
- `sources/github_urls.txt`: GitHub usernames or profile URLs.
- `sources/resumes/`: PDF and DOCX resumes.

Upload mode accepts:

- Recruiter CSV: `.csv`
- ATS JSON: `.json`
- GitHub profiles: `.txt`, one username or URL per line
- Resumes: `.pdf` or `.docx`
- Optional projection config: `.json`

## Output Config

Projection configs live in `configs/`:

- `default.json`: full output with confidence and provenance.
- `minimal.json`: compact output with selected fields.
- `strict_email.json`: requires name and primary email.

Configs support field selection, renaming, required fields, missing-value behavior, and projection-time normalization.

Example:

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

## Pipeline

```text
detect -> extract -> normalize -> resolve -> merge -> score -> project -> validate -> emit
```

Core data boundaries:

- `RawFieldValue`: one claim from one source about one field.
- `CanonicalRecord`: the resolved and merged candidate record.
- `Projection`: the runtime-configured output view.

The pipeline is deterministic and explainable. LLM extraction is isolated to optional source extraction and still emits normal `RawFieldValue` claims; it does not bypass merge, confidence, projection, or validation.

## Normalization And Merge Rules

| Field | Rule |
| --- | --- |
| Email | Lowercase and validate shape. |
| Phone | Parse with `phonenumbers` and emit E.164; local numbers try inferred candidate regions before final fallback. |
| Date | Normalize common date forms to `YYYY-MM`; current roles use null end dates. |
| Country | Normalize to ISO-3166 alpha-2 when possible. |
| Skills | Canonicalize known synonyms; preserve unknown skills with lower confidence. |
| Name | Trim, collapse spacing, and title-case obvious all-caps/lowercase names. |

Entity resolution:

- Match first by normalized email.
- Then by normalized phone.
- Then by fuzzy full name plus same company at score `>= 90`.
- Prefer under-merging over unsafe over-merging.

Merge policy:

- A single valid source is accepted with its raw confidence.
- Agreement across sources receives a `+0.10` confidence bonus, capped at `1.0`.
- Conflicting scalar values choose the highest-priority source and cap confidence at `0.60`.
- Rejected values and provenance are retained for auditability.

## Produced Output

Default output can include:

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

## Known Limitations

- LinkedIn scraping/API ingestion is not implemented.
- Recruiter notes `.txt` extraction is not implemented.
- GitHub extraction depends on public profile availability and network access.
- The web app is the primary interface; there is no separate `candidate_transformer.cli` module.
