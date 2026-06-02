"""Machine capability probe.

Writes <repo>/.brain/machine/<hostname>.md with tool inventory,
hardware info, and active project list.
Also writes ~/.brain/raw/machine_<hostname>.md for global sync.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import platform
import shutil
import subprocess
import sys

import yaml

from .config import GLOBAL_RAW, ensure_dirs, repo_machine_dir

TOOLS_TO_PROBE = [
    "git", "gh", "brew", "apt", "conda", "pip3",
    "node", "npm", "npx", "bun",
    "python3", "uv", "pipx",
    "ollama", "renode", "arduino-cli", "pio",
    "code", "cursor",
    "syncthing", "fly", "docker", "docker-compose",
    "ffmpeg", "nvidia-smi", "nvcc",
    "huggingface-cli", "cargo", "rustc", "go", "java",
    "make", "cmake", "ninja",
]


def _get_tool_version(tool: str) -> str | None:
    try:
        out = subprocess.check_output(
            [tool, "--version"], stderr=subprocess.STDOUT, timeout=3, text=True
        )
        return out.splitlines()[0].strip()[:80]
    except Exception:
        return None


def _get_ram_gb() -> int:
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], timeout=3, text=True
            )
            return int(out.strip()) // (1024 ** 3)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // (1024 ** 2)
    except Exception:
        pass
    return 0


def _get_gpu() -> dict:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader"],
                timeout=5, text=True
            )
            parts = [p.strip() for p in out.strip().split(",")]
            return {"model": parts[0], "vram": parts[1], "driver": parts[2]} if len(parts) >= 3 else {"raw": out.strip()}
        except Exception:
            pass
    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"], timeout=5, text=True
            )
            for line in out.splitlines():
                if "Chipset Model" in line:
                    return {"model": line.split(":")[1].strip()}
        except Exception:
            pass
    return {}


def _get_recent_projects(hostname: str) -> list[str]:
    """Infer recently active projects from ~/.claude/projects/ session activity (last 7d)."""
    projects_dir = pathlib.Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []
    cutoff = datetime.datetime.now().timestamp() - (7 * 86400)
    recent: list[str] = []
    for proj_dir in sorted(projects_dir.iterdir()):
        jsonls = list(proj_dir.glob("*.jsonl"))
        if any(j.stat().st_mtime > cutoff for j in jsonls):
            name = proj_dir.name.lstrip("-").replace("-", "/", 2)
            recent.append("/" + name)
    return recent[:10]


def run(hostname: str | None = None, cwd: str | None = None) -> dict:
    hostname = hostname or os.uname().nodename
    machine_tag = "mac" if platform.system() == "Darwin" else "linux"
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

    identity = {
        "hostname": hostname,
        "os": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "python_path": shutil.which("python3") or "absent",
        "ram_gb": _get_ram_gb(),
        "disk_free_gb": shutil.disk_usage("/").free // (1024 ** 3),
    }

    tools: dict[str, str] = {}
    for t in TOOLS_TO_PROBE:
        path = shutil.which(t)
        if path:
            ver = _get_tool_version(t)
            tools[t] = ver or "present"

    gpu = _get_gpu()
    recent_projects = _get_recent_projects(hostname)

    data = {
        "identity": identity,
        "tools": tools,
        "gpu": gpu,
        "recent_projects": recent_projects,
        "machine_tag": machine_tag,
        "probe_timestamp": now,
    }

    _write_global_profile(data, hostname)
    if cwd:
        _write_repo_profile(data, hostname, cwd)

    return data


def _build_content(data: dict, hostname: str) -> str:
    machine_tag = data["machine_tag"]
    ram = data["identity"]["ram_gb"]
    gpu_str = data["gpu"].get("model", "no-GPU")
    tool_count = len(data["tools"])
    description = f"{machine_tag.capitalize()} {data['identity']['os']} — {ram}GB RAM, {gpu_str}, {tool_count} tools"

    frontmatter = {
        "name": f"machine-{hostname.replace('.', '-').lower()}",
        "description": description,
        "metadata": {
            "type": "machine",
            "machines": [machine_tag],
            "updated": data["probe_timestamp"],
            "ttl": "14d",
            "confidence": 1.0,
            "status": "active",
            "last_accessed": data["probe_timestamp"],
            "access_count": 0,
        },
    }

    lines = [
        "---",
        yaml.dump(frontmatter, default_flow_style=False).rstrip(),
        "---",
        "",
        f"# Machine Profile: {hostname}",
        "",
        "## Identity",
    ]
    for k, v in data["identity"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Available Tools"]
    for t, v in sorted(data["tools"].items()):
        lines.append(f"- {t}: {v}")
    lines += ["", "## GPU"]
    if data["gpu"]:
        for k, v in data["gpu"].items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- model: none detected")
    lines += ["", "## Recent Active Projects"]
    for p in data["recent_projects"]:
        lines.append(f"- {p}")
    lines += ["", f"*Probe timestamp: {data['probe_timestamp']}*", ""]

    return "\n".join(lines)


def _write_global_profile(data: dict, hostname: str) -> None:
    ensure_dirs()
    content = _build_content(data, hostname)
    path = GLOBAL_RAW / f"machine_{hostname}.md"
    path.write_text(content)


def _write_repo_profile(data: dict, hostname: str, cwd: str) -> None:
    machine_dir = repo_machine_dir(cwd)
    machine_dir.mkdir(parents=True, exist_ok=True)
    content = _build_content(data, hostname)
    (machine_dir / f"{hostname}.md").write_text(content)
