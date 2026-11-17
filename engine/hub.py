"""Upload a training run to the Hugging Face Hub, or download one back.

The Hub is where trained models live between machines: Kaggle trains and
pushes, and later the daily dream job (or your laptop) pulls the model down.

Each run goes into its own folder of one model repo:

    <user>/arcadia-dreams            (private by default)
    ├── README.md                    model card, written on the first push
    ├── run1/
    │   ├── best.pt                  checkpoint with the lowest val loss
    │   ├── config.json              model + training settings, readable without torch
    │   ├── loss_log.csv
    │   └── sample.txt
    └── run2/ ...

Usage:
    python -m engine.hub push --repo <user>/arcadia-dreams --run_dir /kaggle/working/run1
    python -m engine.hub pull --repo <user>/arcadia-dreams --run run1 --out_dir checkpoints/run1
    python -m engine.hub push ... --dry_run      # show what would be uploaded, upload nothing

Authentication: set the HF_TOKEN environment variable to a Hugging Face
access token with write access (on Kaggle, store it as a notebook Secret).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

# Files from a run directory that get uploaded. ckpt.pt (the latest
# checkpoint) is left out by default: best.pt is the one worth keeping.
RUN_FILES = ["best.pt", "loss_log.csv", "sample.txt"]

MODEL_CARD = """---
license: other
tags:
- arcadia
- character-level
- gpt
---

# Arcadia dream model

A small GPT-style transformer trained from scratch to generate dreams for the
Arcadia simulated world. Code: https://github.com/DanielGregory/Arcadia

Each folder is one training run: `best.pt` (lowest validation loss),
`config.json`, `loss_log.csv` and an end-of-training `sample.txt`.

## Training data

Public-domain books from Project Gutenberg (Homer, Ovid, Theocritus, Virgil,
Hesiod, Aesop, Dunsany, MacDonald, Coleridge, Carroll, the Arabian Nights, and
a little Shelley, Thoreau, Grimm, Poe and Njal's Saga), plus 25% dream reports
from DreamBank (DReAMy-lib/DreamBank-dreams-en).

The DreamBank reports are real people's dreams. The model may reproduce
passages from them, so check generated text before publishing it.
"""


def git_commit() -> str | None:
    """The code version this run was trained with, if we're inside the git repo."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_upload(run_dir: Path, staging: Path, include_latest: bool) -> list[Path]:
    """Copy (or write) everything to upload into a staging folder; return the file list."""
    import shutil

    import torch

    files = RUN_FILES + (["ckpt.pt"] if include_latest else [])
    missing = [f for f in files if not (run_dir / f).exists()]
    if missing:
        raise SystemExit(f"{run_dir} is missing {missing}; is this a finished training run?")
    for f in files:
        shutil.copy2(run_dir / f, staging / f)

    # config.json: the settings stored inside best.pt, so anyone can see how
    # the model was built and trained without loading it.
    ckpt = torch.load(run_dir / "best.pt", map_location="cpu")
    info = {
        "step": ckpt["step"],
        "val_loss": ckpt["val_loss"],
        "vocab_size": len(ckpt["chars"]),
        "model_config": ckpt["model_config"],
        "train_config": ckpt["train_config"],
        "git_commit": git_commit(),
    }
    (staging / "config.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return sorted(staging.iterdir())


def push(args: argparse.Namespace) -> None:
    from huggingface_hub import HfApi

    run_dir = Path(args.run_dir)
    run_name = args.run or run_dir.name  # folder name inside the Hub repo, e.g. "run1"

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        files = build_upload(run_dir, staging, args.include_latest)
        total_mb = sum(f.stat().st_size for f in files) / 1e6
        print(f"{'would upload' if args.dry_run else 'uploading'} to {args.repo}/{run_name} ({total_mb:.1f} MB):")
        for f in files:
            print(f"  {f.name:<14} {f.stat().st_size / 1e6:8.2f} MB")
        if args.dry_run:
            print((staging / "config.json").read_text())
            return

        api = HfApi()  # reads the HF_TOKEN environment variable
        # 1. Make sure the repo exists. exist_ok means re-running is harmless.
        api.create_repo(args.repo, repo_type="model", private=not args.public, exist_ok=True)
        # 2. Write the model card once; later pushes leave any edits you made alone.
        if not api.file_exists(args.repo, "README.md"):
            api.upload_file(path_or_fileobj=MODEL_CARD.encode(), path_in_repo="README.md",
                            repo_id=args.repo, commit_message="Add model card")
        # 3. Upload the run as one commit.
        api.upload_folder(folder_path=staging, path_in_repo=run_name, repo_id=args.repo,
                          commit_message=f"Add {run_name} (step {json.loads((staging / 'config.json').read_text())['step']})")
    print(f"done: https://huggingface.co/{args.repo}/tree/main/{run_name}")


def pull(args: argparse.Namespace) -> None:
    from huggingface_hub import snapshot_download

    out_dir = Path(args.out_dir or f"checkpoints/{args.run}")
    # Download just this run's folder; files already present are not fetched again.
    snapshot_download(args.repo, allow_patterns=[f"{args.run}/*"], local_dir=out_dir.parent / "_hub")
    src = out_dir.parent / "_hub" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        f.replace(out_dir / f.name)
    print(f"downloaded {args.repo}/{args.run} to {out_dir}")
    print(f"sample with: python -m engine.sample --ckpt {out_dir / 'best.pt'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("push", help="upload a run directory")
    p.add_argument("--repo", required=True, help="Hub repo id, e.g. yourname/arcadia-dreams")
    p.add_argument("--run_dir", required=True, help="the --out_dir of a training run")
    p.add_argument("--run", help="folder name in the repo (default: the run_dir's name)")
    p.add_argument("--include_latest", action="store_true", help="also upload ckpt.pt")
    p.add_argument("--public", action="store_true", help="create the repo as public (default: private)")
    p.add_argument("--dry_run", action="store_true", help="show what would be uploaded, upload nothing")
    p.set_defaults(func=push)

    p = sub.add_parser("pull", help="download a run")
    p.add_argument("--repo", required=True)
    p.add_argument("--run", required=True, help="folder name in the repo, e.g. run1")
    p.add_argument("--out_dir", help="where to put it (default: checkpoints/<run>)")
    p.set_defaults(func=pull)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
