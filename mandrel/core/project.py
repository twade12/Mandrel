"""Per-project directory management with git versioning.

Each Mandrel project lives at {workspace}/{project_id}/.
Neutral interchange files (netlists, STEP, gerbers, BOM) are committed to
this per-project git repo as stages complete, giving a rollback-able artifact
history independent of the DesignState history in Postgres.
"""

from __future__ import annotations

from pathlib import Path

import git


class ProjectDir:
    def __init__(self, project_id: str, workspace: Path) -> None:
        self.project_id = project_id
        self.root = workspace / project_id
        self._repo: git.Repo | None = None

    def init(self) -> None:
        """Create the project directory and git-initialize it."""
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._repo = git.Repo.init(self.root)
        else:
            self._repo = git.Repo(self.root)

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            self._repo = git.Repo(self.root)
        return self._repo

    def subdir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def commit_artifacts(self, stage_name: str, paths: list[Path]) -> str | None:
        """Stage and commit a list of artifact paths; return the commit SHA."""
        if not paths:
            return None
        relative = []
        for p in paths:
            try:
                relative.append(str(p.relative_to(self.root)))
            except ValueError:
                relative.append(str(p))

        self.repo.index.add(relative)
        if not self.repo.index.diff("HEAD") and not self.repo.untracked_files:
            return None

        commit = self.repo.index.commit(f"stage: {stage_name}")
        return commit.hexsha

    def artifact_history(self) -> list[dict]:
        """Return commit log as a list of dicts (sha, message, authored_date)."""
        return [
            {
                "sha": c.hexsha[:12],
                "message": c.message.strip(),
                "authored_date": c.authored_date,
            }
            for c in self.repo.iter_commits()
        ]
