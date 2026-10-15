"""Puts the secret that signs login tokens into backend/.env, without ever showing it.

    .venv\\Scripts\\python scripts\\create_jwt_secret.py

setup.bat runs this. It does nothing when a usable JWT_SECRET is already there. To replace one,
delete its line from backend/.env, run this again and restart the backend: the tokens in use stop
working at once and browsers that are logged in get new ones by themselves. The value is random,
stays on this machine and must never be committed or shared.
"""
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_SECRET_BYTES = 32


def ensure_secret(env_file: Path, example_file: Path) -> str:
    """Makes sure env_file holds a JWT_SECRET. Returns "kept" or "added"; raises ValueError for a line only a person can decide about."""
    if not env_file.exists():
        if example_file.exists():
            shutil.copyfile(example_file, env_file)
        else:
            env_file.write_bytes(b"")
    lines = env_file.read_bytes().decode("utf-8").splitlines(keepends=True)
    at = next((index for index, line in enumerate(lines) if line.split("=", 1)[0].strip() == "JWT_SECRET" and "=" in line), None)
    value = lines[at].split("=", 1)[1].strip().strip("\"'") if at is not None else ""
    if len(value.encode("utf-8")) >= MIN_SECRET_BYTES:
        return "kept"
    if value:
        raise ValueError("JWT_SECRET in backend\\.env is shorter than 32 characters. Delete that line and run this again; a new one will be written.")
    ending = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    entry = f"JWT_SECRET={secrets.token_urlsafe(48)}{ending}"
    if at is not None:
        lines[at] = entry
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += ending
        lines.append(entry)
    env_file.write_bytes("".join(lines).encode("utf-8"))
    return "added"


def main() -> int:
    try:
        done = ensure_secret(ROOT / ".env", ROOT / ".env.example")
    except ValueError as problem:
        print(problem)
        return 1
    if done == "added":
        print("JWT_SECRET was written to backend\\.env. It is not shown, and it must never be committed or shared.")
    else:
        print("backend\\.env already has a JWT_SECRET. Nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
