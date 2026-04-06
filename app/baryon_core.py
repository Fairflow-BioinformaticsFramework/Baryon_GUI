from __future__ import annotations

import csv
import json
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

SECTION_RE = re.compile(r"^\[(.+?)\]\s*$")
KEYVAL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
TOKEN_RE = re.compile(r"<([^>]+)>")


class BaryonError(Exception):
    pass


def _norm_section(name: str) -> str:
    n = name.strip().lower()
    aliases = {
        "directory": "directory",
        "directoy": "directory",
        "dir": "directory",
        "file": "file",
        "parameter": "parameter",
        "run": "run",
        "research": "research",
    }
    return aliases.get(n, n)


def _parse_values_field(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []

    parsed = next(csv.reader([raw], skipinitialspace=True))
    values: list[str] = []

    for v in parsed:
        vv = v.strip()
        if vv == "":
            values.append(",")
        else:
            values.append(vv)

    return values


def parse_bala_text(text: str) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = SECTION_RE.match(line)
        if m:
            current = {
                "section_type": _norm_section(m.group(1)),
                "props": {},
                "line_no": line_no,
            }
            sections.append(current)
            continue

        kv = KEYVAL_RE.match(line)
        if kv and current is not None:
            key, value = kv.group(1).strip(), kv.group(2).strip()
            current["props"][key] = value

    research = next((s["props"] for s in sections if s["section_type"] == "research"), {})
    run = next((s["props"] for s in sections if s["section_type"] == "run"), None)
    if run is None:
        raise BaryonError("Missing [run] section")

    files: list[dict[str, Any]] = []
    directories: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    warnings: list[str] = []

    for sec in sections:
        props = sec["props"]

        if sec["section_type"] == "file":
            if "name" not in props:
                warnings.append(f"[file] at line {sec['line_no']} ignored: missing name")
                continue
            files.append({
                "name": props["name"],
                "flag": props.get("flag", "c") or "c",
                "description": props.get("description", ""),
            })

        elif sec["section_type"] == "directory":
            if "name" not in props:
                warnings.append(f"[directory] at line {sec['line_no']} ignored: missing name")
                continue
            directories.append({
                "name": props["name"],
                "description": props.get("description", ""),
            })

        elif sec["section_type"] == "parameter":
            if "name" not in props:
                warnings.append(f"[parameter] at line {sec['line_no']} ignored: missing name")
                continue

            values = _parse_values_field(props.get("values", ""))
            parameters.append({
                "name": props["name"],
                "description": props.get("description", ""),
                "default": props.get("value", ""),
                "values": values,
                "type": "select" if values else "text",
            })

    usage = run.get("usage", "").strip()
    ordered = TOKEN_RE.findall(usage) if usage else [x["name"] for x in files + directories + parameters]
    if not usage:
        warnings.append("No usage= found in [run]. Falling back to declaration order.")

    workdir_name = None
    for d in directories:
        if d["name"].lower() == "workdir":
            workdir_name = d["name"]
            break

    return {
        "research": research,
        "run": {
            "command": run.get("command", "docker run --rm"),
            "script": run.get("script", "").strip(),
            "image": run.get("image", "").strip(),
            "usage": usage,
            "ordered_names": ordered,
        },
        "files": files,
        "directories": directories,
        "parameters": parameters,
        "warnings": warnings,
        "workdir_name": workdir_name,
    }


def schema_to_jsonable(schema: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(schema))


def build_execution_plan(
    schema: dict[str, Any],
    values: dict[str, str],
    uploaded_files: dict[str, Path],
    extra_uploaded: list[Path],
    job_dir: Path,
) -> dict[str, Any]:
    image = schema["run"].get("image", "")
    script = schema["run"].get("script", "")
    command = schema["run"].get("command", "docker run --rm")

    if not image:
        raise BaryonError("[run] image= is required")
    if not script:
        raise BaryonError("[run] script= is required")

    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    token_values: dict[str, str] = {}
    workdir_name = schema.get("workdir_name")
    host_dirs: dict[str, Path] = {}

    for d in schema["directories"]:
        dir_name = d["name"]
        host_dir = job_dir / dir_name
        host_dir.mkdir(parents=True, exist_ok=True)
        host_dirs[dir_name] = host_dir
        token_values[dir_name] = str(host_dir)

    if not workdir_name and schema["files"]:
        workdir_name = "workDir"
        host_dir = job_dir / workdir_name
        host_dir.mkdir(parents=True, exist_ok=True)
        host_dirs[workdir_name] = host_dir
        token_values[workdir_name] = str(host_dir)

    uploaded_generic: list[str] = []

    for f in schema["files"]:
        name = f["name"]
        if name not in uploaded_files:
            raise BaryonError(f"Missing uploaded file for field: {name}")

        src = uploaded_files[name]
        input_copy = input_dir / src.name
        shutil.copy2(src, input_copy)

        if (f.get("flag") or "c").lower() == "c":
            target_workdir = host_dirs.get(workdir_name or "workDir")
            if target_workdir is None:
                raise BaryonError("No writable working directory available for copied files")
            copied = target_workdir / src.name
            shutil.copy2(src, copied)
            token_values[name] = src.name
        else:
            token_values[name] = f"/baryon/input/{src.name}"

    # Copy generic (extra) uploaded files into the workDir
    if extra_uploaded:
        target_workdir = host_dirs.get(workdir_name or "workDir")
        if target_workdir is not None:
            for src in extra_uploaded:
                if src.is_file():
                    dst = target_workdir / src.name
                    shutil.copy2(src, dst)
                    uploaded_generic.append(src.name)

    for p in schema["parameters"]:
        name = p["name"]
        val = values.get(name, "") or p.get("default", "")
        if p.get("values") and val and val not in p["values"]:
            raise BaryonError(
                f"Invalid value for {name}: {val}. Allowed: {', '.join(p['values'])}"
            )
        token_values[name] = val

    if schema["run"].get("usage", ""):
        expanded = TOKEN_RE.sub(lambda m: token_values.get(m.group(1), ""), schema["run"]["usage"])
        args = shlex.split(expanded)
    else:
        args = [
            token_values[name]
            for name in schema["run"].get("ordered_names", [])
            if name in token_values
        ]

    # Expand tokens in command= (handles -v <workDir>:/data etc.)
    cmd_tokens = shlex.split(command)

    final_cmd: list[str] = []
    skip_next = False
    for i, tok in enumerate(cmd_tokens):
        if skip_next:
            skip_next = False
            continue

        if tok in {"-v", "--volume"} and i + 1 < len(cmd_tokens):
            spec = cmd_tokens[i + 1]
            for key, host_path in token_values.items():
                spec = spec.replace(f"<{key}>", host_path)
            final_cmd.extend([tok, spec])
            skip_next = True
        else:
            replaced = tok
            for key, host_path in token_values.items():
                replaced = replaced.replace(f"<{key}>", host_path)
            final_cmd.append(replaced)

    if image not in final_cmd:
        final_cmd.append(image)

    final_cmd.extend(shlex.split(script))
    final_cmd.extend(args)

    return {
        "cmd": final_cmd,
        "token_values": token_values,
        "job_dir": str(job_dir),
        "generic_uploaded_names": uploaded_generic,
    }


def _usage_or_default(schema: dict[str, Any]) -> str:
    usage = schema["run"].get("usage", "").strip()
    return usage if usage else " ".join(f"<{name}>" for name in schema["run"].get("ordered_names", []))


def _replace_usage_tokens(text: str, repl: dict[str, str]) -> str:
    return TOKEN_RE.sub(lambda m: repl.get(m.group(1), m.group(0)), text)


def generate_bash_wrapper(schema: dict[str, Any]) -> str:
    names = schema["run"]["ordered_names"]
    params = " ".join(f'"${{{i+1}}}"' for i in range(len(names)))
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f"docker run --rm {schema['run']['image']} {schema['run']['script']} {params}\n"
    )


def generate_python_wrapper(schema: dict[str, Any]) -> str:
    items = schema["files"] + schema["directories"] + schema["parameters"]
    argspec = []
    names = []

    for item in items:
        names.append(item["name"])
        default = item.get("default", "")
        if default:
            argspec.append(f"    {item['name']}: str = {default!r},")
        else:
            argspec.append(f"    {item['name']}: str,")

    cmd_items = ", ".join(
        [repr(x) for x in ["docker", "run", "--rm", schema["run"]["image"], *schema["run"]["script"].split()]]
        + names
    )

    return (
        "import subprocess\n\n\n"
        "def run_pipeline(\n"
        + "\n".join(argspec)
        + "\n) -> int:\n"
        + f"    cmd = [{cmd_items}]\n"
        + "    return subprocess.call(cmd)\n"
    )


def generate_r_wrapper(schema: dict[str, Any]) -> str:
    arg_names = [x["name"] for x in schema["files"] + schema["directories"] + schema["parameters"]]
    parts = ["'run'", "'--rm'", f"'{schema['run']['image']}'"] + [repr(x) for x in schema["run"]["script"].split()] + arg_names
    return (
        "run_pipeline <- function(" + ", ".join(arg_names) + ") {\n"
        + "  system2('docker', args = c(" + ", ".join(parts) + "))\n"
        + "}\n"
    )


def generate_nextflow(schema: dict[str, Any]) -> tuple[str, str]:
    files = schema["files"]
    params_lines = [f"params.{f['name']} = '{f['name']}'" for f in files]

    for p in schema["parameters"]:
        default = p.get("default") or (p.get("values") or [""])[0]
        params_lines.append(f"params.{p['name']} = '{default}'")

    input_block = "\n    ".join([f"path {f['name']}" for f in files]) or "val dummy"
    cp_lines = [f"cp ${{{f['name']}}} /data/{f['name']} 2>/dev/null || true" for f in files]

    repl = {f["name"]: f"/data/{f['name']}" for f in files}
    repl.update({d["name"]: f"/data/{d['name']}" for d in schema["directories"]})
    for p in schema["parameters"]:
        repl[p["name"]] = f"${{params.{p['name']}}}"

    args = _replace_usage_tokens(_usage_or_default(schema), repl)
    workflow_setup = "; ".join([f"{f['name']}_ch = Channel.fromPath(params.{f['name']})" for f in files]) or "dummy_ch = Channel.value(1)"
    workflow_call = ", ".join([f"{f['name']}_ch" for f in files]) or "dummy_ch"
    cp_block = "\n    ".join(cp_lines)

    script = (
        "#!/usr/bin/env nextflow\n"
        "nextflow.enable.dsl=2\n\n"
        f"{chr(10).join(params_lines)}\n\n"
        "process baryonProcess {\n"
        f"    container '{schema['run']['image']}'\n"
        "    publishDir 'results', mode: 'copy'\n\n"
        "    input:\n"
        f"    {input_block}\n\n"
        "    output:\n"
        "    path '*', emit: out, optional: true\n\n"
        "    script:\n"
        "    '''\n"
        "    mkdir -p /data\n"
        f"    {cp_block}\n"
        f"    {schema['run']['script']} {args}\n"
        "    cp -r /data/* . 2>/dev/null || true\n"
        "    '''\n"
        "}\n\n"
        "workflow {\n"
        f"    {workflow_setup}\n"
        f"    baryonProcess({workflow_call})\n"
        "}\n"
    )

    config = (
        "docker {\n"
        "    enabled    = true\n"
        "    runOptions = '--platform linux/amd64'\n"
        "}\n"
    )

    return script, config


def generate_streamflow_yaml(schema: dict[str, Any]) -> str:
    return (
        "version: v1.0\n"
        "workflows:\n"
        "  baryon-workflow:\n"
        "    type: cwl\n"
        "    config:\n"
        "      file: baryon-tool.cwl\n"
        "      settings: params.yml\n"
        "    bindings:\n"
        "      - step: /\n"
        "        target:\n"
        "          model: docker-tool\n"
        "models:\n"
        "  docker-tool:\n"
        "    type: docker\n"
        "    config:\n"
        f"      image: {schema['run']['image']}\n"
    )


def generate_galaxy_xml(schema: dict[str, Any]) -> str:
    input_params = []

    for f in schema["files"]:
        input_params.append(
            f'        <param name="{f["name"]}" type="data" label="{f["name"]}" help="{f.get("description", "")}" />'
        )

    for p in schema["parameters"]:
        if p.get("values"):
            opts = "\n".join([f'            <option value="{v}">{v}</option>' for v in p["values"]])
            input_params.append(
                f'        <param name="{p["name"]}" type="select" label="{p["name"]}" help="{p.get("description", "")}">\n'
                f"{opts}\n"
                f"        </param>"
            )
        else:
            input_params.append(
                f'        <param name="{p["name"]}" type="text" value="{p.get("default", "")}" label="{p["name"]}" help="{p.get("description", "")}" />'
            )

    repl = {f["name"]: f"${f['name']}" for f in schema["files"]}
    repl.update({p["name"]: f"${p['name']}" for p in schema["parameters"]})
    repl.update({d["name"]: f"/data/{d['name']}" for d in schema["directories"]})
    args = _replace_usage_tokens(_usage_or_default(schema), repl)

    return (
        f'<tool id="baryon_tool" name="baryon_tool">\n'
        f"    <description>Generated from Baryon</description>\n"
        f"    <requirements>\n"
        f'        <container type="docker">{schema["run"]["image"]}</container>\n'
        f"    </requirements>\n"
        f"    <command><![CDATA[\n"
        f"        {schema['run']['script']} {args}\n"
        f"    ]]></command>\n"
        f"    <inputs>\n"
        + "\n".join(input_params)
        + "\n"
        + "    </inputs>\n"
        + '    <outputs>\n        <data name="results" format="data" label="Generated results" />\n    </outputs>\n'
        + "    <help>Generated from .bala</help>\n"
        + "</tool>\n"
    )


def generate_frontend_bundle(schema: dict[str, Any], target: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    base = "baryon_generated"

    if target == "bash":
        p = out_dir / f"{base}.sh"
        p.write_text(generate_bash_wrapper(schema), encoding="utf-8")
        created.append(p)
    elif target == "python":
        p = out_dir / f"{base}.py"
        p.write_text(generate_python_wrapper(schema), encoding="utf-8")
        created.append(p)
    elif target == "r":
        p = out_dir / f"{base}.R"
        p.write_text(generate_r_wrapper(schema), encoding="utf-8")
        created.append(p)
    elif target == "nextflow":
        nf, cfg = generate_nextflow(schema)
        p1 = out_dir / f"{base}.nf"
        p2 = out_dir / "nextflow.config"
        p1.write_text(nf, encoding="utf-8")
        p2.write_text(cfg, encoding="utf-8")
        created.extend([p1, p2])
    elif target == "streamflow":
        p = out_dir / f"{base}.yml"
        p.write_text(generate_streamflow_yaml(schema), encoding="utf-8")
        created.append(p)
    elif target == "galaxy":
        p = out_dir / f"{base}.xml"
        p.write_text(generate_galaxy_xml(schema), encoding="utf-8")
        created.append(p)
    else:
        raise BaryonError(f"Unsupported target: {target}")

    readme = out_dir / "README.txt"
    readme.write_text(
        "Generated from Baryon Runner\n\n"
        f"Target: {target}\n"
        f"Image: {schema['run'].get('image', '')}\n"
        f"Script: {schema['run'].get('script', '')}\n",
        encoding="utf-8",
    )
    created.append(readme)

    return created
