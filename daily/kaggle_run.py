"""Run an Arcadia notebook on Kaggle's GPU and bring the results home.

    python daily/kaggle_run.py images        # notebooks/kaggle_images.ipynb  -> assets/generated/, then upload_review
    python daily/kaggle_run.py run3          # notebooks/kaggle_train_run3.ipynb -> checkpoints/run3/
    python daily/kaggle_run.py images --no_push   # just wait for / download the current version
    python daily/kaggle_run.py gpu-minutes danieltgregory/arcaida2   # GPU minutes of an existing run

Steps: push the notebook as a new version (GPU T4, internet on), poll its status
every minute, download its output and log, report GPU minutes (Kaggle bills a
GPU session for its whole run time, read from the last timestamp in the log),
and, for image runs, upload everything to the review gallery
(daily/upload_review.py).

Uses the Kaggle CLI with ~/.kaggle/kaggle.json (never in the repo).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER = "danieltgregory"
KAGGLE = [sys.executable, "-m", "kaggle.cli"] if shutil.which("kaggle") is None else ["kaggle"]

JOBS = {
    "images": {"notebook": "notebooks/kaggle_images.ipynb", "slug": "arcadia-images", "title": "Arcadia Images",
               "output_subdir": "images", "dest": "assets/generated", "upload_review": True},
    "run3": {"notebook": "notebooks/kaggle_train_run3.ipynb", "slug": "arcadia-run3", "title": "Arcadia Run3",
             "output_subdir": "run3", "dest": "checkpoints/run3", "upload_review": False},
}


def kaggle(*args: str, check: bool = True) -> str:
    out = subprocess.run([*KAGGLE, *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        sys.exit(f"kaggle {' '.join(args)} failed:\n{out.stdout}{out.stderr}")
    return out.stdout + out.stderr


def push(job: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(ROOT / job["notebook"], Path(tmp) / Path(job["notebook"]).name)
        meta = {
            "id": f"{USER}/{job['slug']}", "title": job["title"], "code_file": Path(job["notebook"]).name,
            "language": "python", "kernel_type": "notebook", "is_private": "true",
            "enable_gpu": "true", "enable_tpu": "false", "enable_internet": "true", "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": [],
        }
        (Path(tmp) / "kernel-metadata.json").write_text(json.dumps(meta, indent=1))
        print(kaggle("kernels", "push", "-p", tmp).strip())


def wait(kernel: str, poll: int = 60) -> str:
    last = None
    while True:
        status = kaggle("kernels", "status", kernel, check=False).strip().split()[-1].strip('"')
        if status != last:
            print(f"{time.strftime('%H:%M:%S')} {status}", flush=True)
            last = status
        if any(s in status for s in ("COMPLETE", "ERROR", "CANCEL")):
            return status
        time.sleep(poll)


def gpu_minutes(log_path: Path) -> float:
    """Kaggle's log is a JSON list of {stream_name, time, data}; time is seconds since the session started."""
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    return max(e["time"] for e in entries) / 60 if entries else 0.0


def download(kernel: str, job: dict) -> float:
    dest = ROOT / job["dest"]
    with tempfile.TemporaryDirectory() as tmp:
        print(kaggle("kernels", "output", kernel, "-p", tmp, "--force").strip().splitlines()[-1])
        out = Path(tmp)
        log = next(out.glob("*.log"), None)
        src = out / job["output_subdir"]
        if src.exists():
            dest.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                shutil.copy2(f, dest / f.name)
            print(f"copied {len(list(src.iterdir()))} files to {dest.relative_to(ROOT)}")
        else:
            print(f"warning: the run produced no {job['output_subdir']}/ folder")
        if log:
            shutil.copy2(log, dest / "kaggle.log") if dest.exists() else None
            return gpu_minutes(log)
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=[*JOBS, "gpu-minutes"])
    parser.add_argument("kernel", nargs="?", help="for gpu-minutes: owner/slug of an existing run")
    parser.add_argument("--no_push", action="store_true", help="don't push a new version; wait for and download the current one")
    args = parser.parse_args()

    if args.job == "gpu-minutes":
        with tempfile.TemporaryDirectory() as tmp:
            kaggle("kernels", "output", args.kernel, "-p", tmp, "--file-pattern", "^$")
            log = next(Path(tmp).glob("*.log"))
            print(f"{args.kernel}: {gpu_minutes(log):.1f} GPU minutes")
        return

    job = JOBS[args.job]
    kernel = f"{USER}/{job['slug']}"
    if not args.no_push:
        push(job)
    status = wait(kernel)
    minutes = download(kernel, job)
    print(f"{kernel}: {status} | {minutes:.1f} GPU minutes")
    if "COMPLETE" in status and job["upload_review"]:
        subprocess.run([sys.executable, str(ROOT / "daily/upload_review.py")], check=True)


if __name__ == "__main__":
    main()
