"""FastAPI web application — beautiful UI for the candidate transformer pipeline.

Serves a stunning single-page web app and provides REST API endpoints for
running the pipeline, managing configs, and viewing results.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from candidate_transformer.models.config import ProjectionConfig
from candidate_transformer.pipeline import run_pipeline, PipelineResult

# Configure logging.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Resolve paths.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATIC_DIR = _PROJECT_ROOT / "static"
_CONFIGS_DIR = _PROJECT_ROOT / "configs"
_SOURCES_DIR = _PROJECT_ROOT / "sources"
_OUTPUT_DIR = _PROJECT_ROOT / "output"

app = FastAPI(
    title="Candidate Data Transformer",
    description="Multi-Source Candidate Data Transformer — Eightfold Engineering Assignment",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files.
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ======================================================================
# Routes
# ======================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main UI page."""
    index_path = _STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Static files not found</h1>", status_code=500)


@app.get("/api/configs")
async def list_configs():
    """List available projection configs."""
    configs = []
    if _CONFIGS_DIR.exists():
        for f in sorted(_CONFIGS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                configs.append({
                    "name": f.stem,
                    "filename": f.name,
                    "fields_count": len(data.get("fields", [])),
                    "include_confidence": data.get("include_confidence", True),
                    "on_missing": data.get("on_missing", "null"),
                })
            except Exception:
                configs.append({"name": f.stem, "filename": f.name, "error": "parse_failed"})
    return {"configs": configs}


@app.get("/api/configs/{config_name}")
async def get_config(config_name: str):
    """Get a specific config's content."""
    config_path = _CONFIGS_DIR / f"{config_name}.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Config '{config_name}' not found")
    return json.loads(config_path.read_text(encoding="utf-8"))


@app.get("/api/sample-sources")
async def list_sample_sources():
    """List available sample source files."""
    sources = {}
    if _SOURCES_DIR.exists():
        csv_files = list(_SOURCES_DIR.glob("*.csv"))
        sources["csv"] = [{"name": f.name, "path": str(f)} for f in csv_files]

        json_files = list(_SOURCES_DIR.glob("*.json"))
        sources["ats"] = [{"name": f.name, "path": str(f)} for f in json_files]

        github_files = list(_SOURCES_DIR.glob("*.txt"))
        sources["github"] = [{"name": f.name, "path": str(f)} for f in github_files]

        resumes_dir = _SOURCES_DIR / "resumes"
        if resumes_dir.exists():
            resume_files = list(resumes_dir.glob("*.pdf")) + list(resumes_dir.glob("*.docx"))
            sources["resumes"] = [{"name": f.name, "path": str(f)} for f in resume_files]
        else:
            sources["resumes"] = []

    return {"sources": sources}


@app.post("/api/run")
async def run_transform(
    csv_file: UploadFile | None = File(None),
    ats_file: UploadFile | None = File(None),
    github_file: UploadFile | None = File(None),
    resume_files: list[UploadFile] = File(default=[]),
    config_file: UploadFile | None = File(None),
    config_name: str = Form(default="default"),
    use_sample_data: bool = Form(default=False),
    sample_csv: bool = Form(default=True),
    sample_ats: bool = Form(default=True),
    sample_github: bool = Form(default=False),
    sample_resume: bool = Form(default=False),
    resume_extraction_mode: str = Form(default="regex"),
    github_readme_llm: bool = Form(default=False),
):
    """Run the transformation pipeline on uploaded or sample source files."""
    run_id = str(uuid.uuid4())[:8]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"ct_{run_id}_"))

    try:
        csv_path = None
        ats_path = None
        github_urls_path = None
        resumes_path = None

        if use_sample_data:
            # Use sample source files — only those toggled on by the user.
            if sample_csv:
                sample_csv_file = _SOURCES_DIR / "recruiter.csv"
                if sample_csv_file.exists():
                    csv_path = str(sample_csv_file)

            if sample_ats:
                sample_ats_file = _SOURCES_DIR / "ats.json"
                if sample_ats_file.exists():
                    ats_path = str(sample_ats_file)

            if sample_github:
                sample_github_file = _SOURCES_DIR / "github_urls.txt"
                if sample_github_file.exists():
                    github_urls_path = str(sample_github_file)

            if sample_resume:
                sample_resumes_dir = _SOURCES_DIR / "resumes"
                if sample_resumes_dir.exists() and any(sample_resumes_dir.iterdir()):
                    resumes_path = str(sample_resumes_dir)
        else:
            # Use uploaded files.
            if csv_file and csv_file.filename:
                csv_path = str(tmp_dir / "recruiter.csv")
                with open(csv_path, "wb") as f:
                    f.write(await csv_file.read())

            if ats_file and ats_file.filename:
                ats_path = str(tmp_dir / "ats.json")
                with open(ats_path, "wb") as f:
                    f.write(await ats_file.read())

            if github_file and github_file.filename:
                github_urls_path = str(tmp_dir / "github_urls.txt")
                with open(github_urls_path, "wb") as f:
                    f.write(await github_file.read())

            if resume_files:
                resume_dir = tmp_dir / "resumes"
                resume_dir.mkdir()
                for rf in resume_files:
                    if rf.filename:
                        dest = resume_dir / rf.filename
                        with open(dest, "wb") as f:
                            f.write(await rf.read())
                if any(resume_dir.iterdir()):
                    resumes_path = str(resume_dir)

        # Check we have at least one source.
        if not any([csv_path, ats_path, github_urls_path, resumes_path]):
            raise HTTPException(
                status_code=400,
                detail="At least one source file is required.",
            )

        if resume_extraction_mode not in {"regex", "llm", "both"}:
            raise HTTPException(
                status_code=400,
                detail="resume_extraction_mode must be one of: regex, llm, both.",
            )

        # Resolve config path. Uploaded configs are validated here so users get
        # a clear 400 for malformed runtime output schemas.
        if config_file and config_file.filename:
            config_path = str(tmp_dir / "projection_config.json")
            config_bytes = await config_file.read()
            try:
                config_data = json.loads(config_bytes.decode("utf-8"))
                ProjectionConfig(**config_data)
            except UnicodeDecodeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Config file must be UTF-8 JSON: {exc}",
                )
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid config JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}",
                )
            except ValidationError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid projection config: {exc}",
                )
            Path(config_path).write_bytes(config_bytes)
        else:
            config_path = str(_CONFIGS_DIR / f"{config_name}.json")
            if not Path(config_path).exists():
                config_path = str(_CONFIGS_DIR / "default.json")

        # Output path.
        output_path = str(_OUTPUT_DIR / f"candidates_{run_id}.json")

        # Run the pipeline.
        result: PipelineResult = run_pipeline(
            csv_path=csv_path,
            ats_path=ats_path,
            github_urls_path=github_urls_path,
            resumes_path=resumes_path,
            config_path=config_path,
            output_path=output_path,
            resume_extraction_mode=resume_extraction_mode,
            github_readme_llm=github_readme_llm,
        )

        return {
            "run_id": run_id,
            "candidates": result.candidates,
            "stats": result.stats.to_dict(),
            "validation_errors": result.validation_errors,
            "output_file": f"candidates_{run_id}.json",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Pipeline failed for run %s", run_id)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        # Clean up temp files.
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/api/output/{filename}")
async def download_output(filename: str):
    """Download a generated output file."""
    file_path = _OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(str(file_path), media_type="application/json", filename=filename)


def main():
    """Entry point for the console script."""
    print("\n>> Starting Candidate Data Transformer...")
    print("   Open http://localhost:8000 in your browser\n")
    uvicorn.run(
        "candidate_transformer.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(_PROJECT_ROOT / "src")],
    )


if __name__ == "__main__":
    main()
