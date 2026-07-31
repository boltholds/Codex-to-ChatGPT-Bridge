from __future__ import annotations

from pathlib import Path

from ..config import ApprovalPolicy, SandboxMode


def resolve_allowed_cwd(cwd: str, allowed_roots: tuple[Path, ...]) -> Path:
    resolved = Path(cwd).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"Working directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Working directory is not a directory: {resolved}")
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        roots = ", ".join(str(root) for root in allowed_roots)
        raise PermissionError(f"Working directory {resolved} is outside allowed roots: {roots}")
    return resolved


def select_sandbox(requested: SandboxMode | None, default: SandboxMode) -> SandboxMode:
    value = requested or default
    if value not in ("read-only", "workspace-write"):
        raise ValueError(f"Unsupported sandbox mode: {value}")
    return value


def select_approval_policy(requested: ApprovalPolicy | None,
                           default: ApprovalPolicy) -> ApprovalPolicy:
    value = requested or default
    if value not in ("untrusted", "on-request", "never"):
        raise ValueError(f"Unsupported approval policy: {value}")
    return value


def require_verification_evidence(verification: str | None,
                                  commit_sha: str | None) -> None:
    if not ((verification and verification.strip()) or (commit_sha and commit_sha.strip())):
        raise ValueError(
            "Verified completion requires non-empty verification evidence or commit_sha"
        )
