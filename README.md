# Multi-Source Candidate Data Transformer

Python pipeline for ingesting candidate data from multiple sources, resolving records that refer to the same person, merging fields with provenance and confidence scoring, and projecting the result into a runtime-configurable JSON shape.

## Install And Run First

These steps are the expected way to install, run, test, and inspect the project from a fresh clone.

### 1. Clone The Repository

```powershell
git clone https://github.com/umeshgupta05/Multi-Source-Candidate-Data-Transformer.git
cd Multi-Source-Candidate-Data-Transformer
```

If you already have the folder locally, open a terminal in the project root, the folder that contains `pyproject.toml`, `README.md`, `src/`, `sources/`, and `configs/`.

### 2. Create And Activate A Virtual Environment

Windows PowerShell:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation, run this once for the current terminal session and activate again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Python 3.10 or newer is required. The project has also been tested locally with Python 3.13.

### 3. Install Dependencies

For normal app usage:

```powershell
pip install -e .
```

For development and tests:

```powershell
pip install -e ".[dev]"
```

For optional LLM resume extraction with Qwen/Hugging Face/OpenAI-compatible endpoints:

```powershell
pip install -e ".[dev,llm]"
```

If extras are unavailable in your shell, install from `requirements.txt` instead:

```powershell
pip install -r requirements.txt
```

### 4. Run The Web App

Start the FastAPI app:

```powershell
candidate-transformer
```

Alternative direct command:

```powershell
uvicorn candidate_transformer.app:app --reload
```

Open the UI:

```text
http://localhost:8000
```

If port `8000` is already in use:

```powershell
uvicorn candidate_transformer.app:app --reload --port 8001
```

Then open:

```text
http://localhost:8001
```

### 5. Run The Sample Data In The UI

1. Open the app in the browser.
2. In `Source Data`, choose `Use Sample Data`.
3. Choose which sample sources to run: recruiter CSV, ATS JSON, GitHub URLs, and/or resume PDFs.
4. Choose `Resume Extraction` mode:
   - `Regex`: deterministic parser, no model or API key required.
   - `LLM (Qwen)`: Qwen-only resume extraction.
   - `Both`: runs regex and Qwen and lets the merger combine evidence.
5. In `Output Configuration`, select `default`, `minimal`, or `strict_email`.
6. Click `Run Pipeline`.
7. Review `Run Summary`, `Conflicts & Rejections`, candidate cards, confidence, provenance, and validation errors.
8. The app writes run output to `output/candidates_<run_id>.json`.

### 6. Upload Custom Inputs In The UI

Use `Upload Files` when testing your own data:

- Recruiter CSV: `.csv`
- ATS JSON: `.json`
- GitHub profiles: `.txt` with one username or GitHub URL per line
- Resumes: `.pdf` or `.docx`
- Optional projection config: `.json`

The upload tab has a clear/reset control so you can remove selected files before rerunning.

### 7. Optional LLM Configuration

Regex mode does not need an API key. LLM mode needs a provider configuration.

Hugging Face router example:

```powershell
$env:HF_TOKEN = "your_hugging_face_token"
$env:QWEN_PROVIDER = "hf_vlm"
$env:QWEN_HF_MODEL = "Qwen/Qwen2.5-VL-32B-Instruct:novita"
candidate-transformer
```

OpenAI-compatible endpoint example:

```powershell
$env:QWEN_PROVIDER = "openai"
$env:QWEN_OPENAI_BASE_URL = "https://your-provider.example.com/v1"
$env:QWEN_API_KEY = "your_api_key"
$env:QWEN_MODEL = "your-qwen-model"
candidate-transformer
```

Local Ollama fallback is supported when enabled by environment and when Ollama exposes an OpenAI-compatible endpoint:

```powershell
$env:QWEN_OLLAMA_FALLBACK = "true"
$env:QWEN_OLLAMA_URL = "http://localhost:11434/v1"
$env:QWEN_OLLAMA_MODEL = "qwen2.5vl:3b"
candidate-transformer
```

You can put environment variables in either:

- `.env` at the project root
- `src/candidate_transformer/extractors/.env`

Restart the server after changing `.env` values. Do not commit real API tokens.

### 8. Run Headless From Python

Run the full sample pipeline and write output:

```powershell
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(csv_path='sources/recruiter.csv', ats_path='sources/ats.json', github_urls_path='sources/github_urls.txt', resumes_path='sources/resumes', config_path='configs/default.json', output_path='output/candidates_sample.json', resume_extraction_mode='regex'); print(r.stats.print_summary())"
```

Run only resumes with regex:

```powershell
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(resumes_path='sources/resumes', config_path='configs/default.json', output_path='output/candidates_resumes_regex.json', resume_extraction_mode='regex'); print(r.stats.print_summary())"
```

Run only resumes with LLM:

```powershell
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(resumes_path='sources/resumes', config_path='configs/default.json', output_path='output/candidates_resumes_llm.json', resume_extraction_mode='llm'); print(r.stats.print_summary())"
```

Run regex and LLM together:

```powershell
python -c "from candidate_transformer.pipeline import run_pipeline; r = run_pipeline(resumes_path='sources/resumes', config_path='configs/default.json', output_path='output/candidates_resumes_both.json', resume_extraction_mode='both'); print(r.stats.print_summary())"
```

### 9. Run Tests

```powershell
pytest tests/ -v
```

Current coverage includes extractors, normalizers, entity resolution, merging/confidence, projection, validation, LLM JSON conversion, and edge cases.

### 10. Troubleshooting

- `candidate-transformer` is not recognized: activate `.venv`, then run `pip install -e .` again.
- `ModuleNotFoundError`: make sure the virtual environment is active and dependencies are installed.
- App starts but browser cannot connect: check the terminal for the actual port, or run `uvicorn candidate_transformer.app:app --reload --port 8001`.
- LLM mode returns no fields: check `HF_TOKEN`/`HUGGINGFACEHUB_API_TOKEN`, provider variables, network access, and the UI error feedback.
- Resume location looks wrong in LLM mode: rerun after restarting the server so the latest prompt and source-text reconciliation code is loaded.
- Generated outputs are written under `output/`; committed sample run outputs may be overwritten by later local runs.

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
