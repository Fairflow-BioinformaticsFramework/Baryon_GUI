
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from baryon_core import (
    BaryonError,
    build_execution_plan,
    parse_bala_text,
    schema_to_jsonable,
)

app = FastAPI(title="Baryon Runner")
JOBS_DIR = Path("/jobs")
JOBS_DIR.mkdir(exist_ok=True)
jobs: dict[str, dict[str, Any]] = {}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return Path("/app/static/index.html").read_text(encoding="utf-8")


@app.post("/parse-bala")
async def parse_bala(bala: UploadFile = File(...)) -> dict[str, Any]:
    text = (await bala.read()).decode("utf-8")
    schema = parse_bala_text(text)
    return {"schema": schema_to_jsonable(schema)}


@app.post("/run-bala")
async def run_bala(
    background_tasks: BackgroundTasks,
    bala: UploadFile = File(...),
    values_json: str = Form("{}"),
    named_files_json: str = Form("{}"),
    data: list[UploadFile] = File(default=[]),
) -> dict[str, str]:
    job_id = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    bala_path = job_dir / (bala.filename or "workflow.bala")
    bala_path.write_bytes(await bala.read())

    try:
        schema = parse_bala_text(bala_path.read_text(encoding="utf-8"))
        values = json.loads(values_json or "{}")
        named_files = json.loads(named_files_json or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError, BaryonError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    uploaded_paths: dict[str, Path] = {}
    uploads_dir = job_dir / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    for f in data:
        if not f.filename:
            continue
        target = uploads_dir / Path(f.filename).name
        target.write_bytes(await f.read())
        uploaded_paths[target.name] = target

    mapped_files: dict[str, Path] = {}
    used_uploaded_names: set[str] = set()
    for field_name, uploaded_name in named_files.items():
        if uploaded_name in uploaded_paths:
            mapped_files[field_name] = uploaded_paths[uploaded_name]
            used_uploaded_names.add(uploaded_name)

    extra_uploaded = [path for name, path in uploaded_paths.items() if name not in used_uploaded_names]

    jobs[job_id] = {
        "status": "running",
        "log": "",
        "workflow": bala.filename or "workflow.bala",
        "has_results": False,
        "kind": "bala",
    }

    background_tasks.add_task(execute_bala, job_id, job_dir, schema, values, mapped_files, extra_uploaded)
    return {"job_id": job_id}


@app.post("/generate-frontend")
async def generate_frontend(
    bala: UploadFile = File(...),
    target: str = Form(...),
) -> dict[str, str]:
    text = (await bala.read()).decode("utf-8")
    schema = parse_bala_text(text)
    ordered = schema.get("run", {}).get("ordered_names", [])
    msg = (
        f"GENERO front end per {target}\n"
        f"image={schema.get('run', {}).get('image', '')}\n"
        f"script={schema.get('run', {}).get('script', '')}\n"
        f"usage={schema.get('run', {}).get('usage', '')}\n"
        f"ordered={', '.join(ordered)}"
    )
    return {"message": msg}


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/download/{job_id}")
async def download(job_id: str):
    if job_id not in jobs or not jobs[job_id].get("has_results"):
        raise HTTPException(status_code=404, detail="Results not found")
    return FileResponse(JOBS_DIR / job_id / "results_archive.zip", filename=f"results_{job_id}.zip")


@app.get("/jobs")
async def list_jobs():
    return [{"job_id": jid, **job} for jid, job in jobs.items()]


def execute_bala(job_id: str, job_dir: Path, schema: dict[str, Any], values: dict[str, str], mapped_files: dict[str, Path], extra_uploaded: list[Path]) -> None:
    try:
        plan = build_execution_plan(schema, values, mapped_files, extra_uploaded, job_dir)
        result = subprocess.run(plan["cmd"], cwd=str(job_dir), capture_output=True, text=True, timeout=7200)
        generic = ""
        if plan.get("generic_uploaded_names"):
            generic = "\n[runner] copied generic data files into workDir: " + ", ".join(plan["generic_uploaded_names"]) + "\n"
        jobs[job_id]["log"] = (
            "$ " + " ".join(plan["cmd"]) + "\n" + generic + "\n" + result.stdout + "\n" + result.stderr
        )
        if result.returncode == 0:
            jobs[job_id]["status"] = "done"
            shutil.make_archive(str(job_dir / "results_archive"), "zip", str(job_dir))
            jobs[job_id]["has_results"] = True
        else:
            jobs[job_id]["status"] = "error"
    except subprocess.TimeoutExpired:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["log"] = "Timeout dopo 2 ore."
    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["log"] = str(exc)
