"""The world engine's state between runs: the sandbox SQLite file, kept in the PRIVATE model repo.

    python -m world.state push     # upload data/world/sandbox.db
    python -m world.state pull     # download it (a fresh machine, e.g. the nightly run)

The sandbox file holds everything the engine knows, private truths and the sealed location included, so
it never goes anywhere public: not git, not the public Supabase bucket. It lives in the private Hugging
Face repo DannyGregs/arcadia-dreams (where the dream model's checkpoints already are), at world/sandbox.db;
the repo's commit history keeps every earlier day. The run 5 checkpoint comes from the same repo.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from world.db import DB_PATH, ROOT

REPO = "DannyGregs/arcadia-dreams"
REMOTE = "world/sandbox.db"
CHECKPOINT = ROOT / "checkpoints/run5/best.pt"
# Binary uploads through Hugging Face's newer storage backend (Xet) hang behind this machine's network proxy;
# the classic upload path works.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def push(message: str = "world: sandbox state") -> None:
    from huggingface_hub import HfApi
    HfApi().upload_file(path_or_fileobj=str(DB_PATH), path_in_repo=REMOTE, repo_id=REPO, commit_message=message)
    print(f"state pushed to {REPO}/{REMOTE}")


def pull() -> None:
    from huggingface_hub import hf_hub_download
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(hf_hub_download(REPO, REMOTE, force_download=True), DB_PATH)
    print(f"state pulled from {REPO}/{REMOTE}")


def ensure_checkpoint() -> None:
    if CHECKPOINT.exists():
        return
    from huggingface_hub import hf_hub_download
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(hf_hub_download(REPO, "run5/best.pt"), CHECKPOINT)
    print(f"run 5 checkpoint pulled from {REPO}")


if __name__ == "__main__":
    {"push": push, "pull": pull, "checkpoint": ensure_checkpoint}[sys.argv[1]]()
