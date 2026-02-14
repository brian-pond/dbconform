"""
modelsync CLI: test workflow (container check, Postgres lifecycle, run tests).

See docs/requirements/01-functional.md (CLI scope) and .cursor/rules/cli-conventions.mdc.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import typer

# Container constants (match tests/docker-compose.yml image)
POSTGRES_IMAGE = "postgres:16-alpine"
CONTAINER_NAME = "modelsync-postgres"
POSTGRES_PORT = 5433
POSTGRES_URL = f"postgresql://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/postgres"

# Exit code when tests were skipped due to no Postgres (plan: distinct from test failure)
EXIT_POSTGRES_UNAVAILABLE = 2

# Skip reason string we look for in pytest output (from tests/integration/conftest.py)
POSTGRES_SKIP_MARKER = "PostgreSQL not available"


def _try_connect_postgres(url: str, timeout: float = 5.0) -> tuple[bool, str | None]:
    """
    Try to connect to Postgres at url (postgresql:// or postgresql+psycopg://),
    run SELECT 1 to validate auth and database. Returns (True, None) on success;
    (False, error_message) on failure. Requires psycopg; returns (False, 'psycopg not installed')
    if missing.
    """
    try:
        import psycopg
    except ImportError:
        return (False, "psycopg not installed")
    conninfo = url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(conninfo, connect_timeout=timeout) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return (True, None)
    except psycopg.OperationalError as e:
        return (False, str(e).strip())
    except Exception as e:
        return (False, str(e).strip())


def _get_container_cmd_optional() -> str | None:
    """Return docker or podman path if available, else None. Does not echo or exit."""
    cmd = os.environ.get("MODELSYNC_CONTAINER_CMD", "").strip()
    if cmd:
        return shutil.which(cmd)
    for name in ("docker", "podman"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _get_container_cmd() -> str:
    """
    Return docker or podman binary: MODELSYNC_CONTAINER_CMD, or first of docker/podman in PATH.
    Exits 1 with message if not found.
    """
    path = _get_container_cmd_optional()
    if path:
        return path
    typer.echo(
        "Container runtime not found (docker/podman). Set MODELSYNC_CONTAINER_CMD "
        "or install Docker/Podman.",
        err=True,
    )
    raise typer.Exit(1)


def _run(
    args: list[str],
    *,
    capture: bool = True,
    timeout: int | None = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a command; return CompletedProcess. Raises on timeout.
    If env is set, it replaces the process env."""
    kwargs: dict = {"capture_output": capture, "text": True, "timeout": timeout}
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(args, **kwargs)


# --- Root app ---
app = typer.Typer(
    name="modelsync",
    help="Schema and model synchronization. Use 'test' for running tests and Postgres lifecycle.",
)


@app.callback(invoke_without_command=True)
def _main_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


# --- test group ---
test_app = typer.Typer(help="Test workflow: check container, Postgres up/down, run tests.")
app.add_typer(test_app, name="test")


@test_app.callback(invoke_without_command=True)
def _test_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@test_app.command("check-container")
def check_container() -> None:
    """
    Verify container runtime and Postgres image: run a short-lived container, then remove it.
    Exit 0 on success; exit 1 with a clear message on failure
    (runtime not found, image pull, start).
    """
    cmd = _get_container_cmd()
    # --rm: remove when done. We use "sleep 2" (not pg_isready) because overriding CMD
    # prevents the image from starting Postgres, so pg_isready would have nothing to connect to.
    # This still verifies runtime + image pull + container start.
    proc = _run(
        [cmd, "run", "--rm", POSTGRES_IMAGE, "sleep", "2"],
        timeout=30,
    )
    if proc.returncode == 0:
        typer.echo("Container runtime and Postgres image OK.")
        return
    stderr = (proc.stderr or "").strip().lower()
    if "pull" in stderr or "not found" in stderr or "does not exist" in stderr:
        typer.echo(f"Image pull failed: {proc.stderr or proc.stdout or 'unknown'}", err=True)
    else:
        typer.echo(f"Container start failed: {proc.stderr or proc.stdout or 'unknown'}", err=True)
    raise typer.Exit(1)


# --- test postgres subgroup ---
postgres_app = typer.Typer(help="Start or stop the long-lived Postgres container for tests.")
test_app.add_typer(postgres_app, name="postgres")


@postgres_app.callback(invoke_without_command=True)
def _postgres_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _container_exists(container_cmd: str) -> bool:
    """Return True if CONTAINER_NAME exists (running or stopped)."""
    proc = _run([container_cmd, "ps", "-a", "-q", "-f", f"name={CONTAINER_NAME}"], timeout=5)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _container_running(container_cmd: str) -> bool:
    """Return True if CONTAINER_NAME is running (not just existing)."""
    proc = _run([container_cmd, "ps", "-q", "-f", f"name={CONTAINER_NAME}"], timeout=5)
    return proc.returncode == 0 and bool(proc.stdout.strip())


@postgres_app.command("up")
def postgres_up() -> None:
    """
    Start a long-lived Postgres container (name modelsync-postgres, port 5433).
    Prints MODELSYNC_TEST_POSTGRES_URL to set before running tests.
    """
    container_cmd = _get_container_cmd()
    if _container_exists(container_cmd):
        typer.echo(
            f"Container {CONTAINER_NAME} already exists. Run 'modelsync test postgres down' first.",
            err=True,
        )
        raise typer.Exit(1)
    proc = _run(
        [
            container_cmd,
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{POSTGRES_PORT}:5432",
            "-e",
            "POSTGRES_PASSWORD=postgres",
            POSTGRES_IMAGE,
        ],
        timeout=300,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "already in use" in err or "Conflict" in err or "exists" in err:
            typer.echo(
                f"Container {CONTAINER_NAME} already exists. "
                "Run 'modelsync test postgres down' first.",
                err=True,
            )
        else:
            typer.echo(f"Start failed: {err}", err=True)
        raise typer.Exit(1)
    # Wait for Postgres to accept TCP connections with our password (up to 30s)
    ok, err_msg = _try_connect_postgres(POSTGRES_URL, timeout=3)
    if err_msg == "psycopg not installed":
        typer.echo(f"Set: MODELSYNC_TEST_POSTGRES_URL={POSTGRES_URL}")
        typer.echo(
            "Run 'modelsync test run' to run tests. "
            "(Install [postgres] extra to verify connection at start.)"
        )
        return
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ok, err_msg = _try_connect_postgres(POSTGRES_URL, timeout=3)
        if ok:
            typer.echo(f"Set: MODELSYNC_TEST_POSTGRES_URL={POSTGRES_URL}")
            typer.echo("Connection verified (SELECT 1).")
            typer.echo("Run 'modelsync test run' to run tests.")
            return
        if err_msg and "password authentication failed" in err_msg:
            _run([container_cmd, "stop", CONTAINER_NAME], timeout=10)
            _run([container_cmd, "rm", CONTAINER_NAME], timeout=5)
            typer.echo(
                "Port 5433 is in use by another Postgres (password rejected). "
                "Stop that service, then run 'modelsync test postgres up' again. "
                "Or use a different port by setting MODELSYNC_TEST_POSTGRES_URL "
                "to your own instance.",
                err=True,
            )
            raise typer.Exit(1)
        time.sleep(1)
    _run([container_cmd, "stop", CONTAINER_NAME], timeout=10)
    _run([container_cmd, "rm", CONTAINER_NAME], timeout=5)
    typer.echo(
        "Container did not accept connections in 30s; removed it. "
        "If another process was using port 5433, stop it and "
        "run 'modelsync test postgres up' again.",
        err=True,
    )
    raise typer.Exit(1)


@postgres_app.command("down")
def postgres_down() -> None:
    """Stop and remove the long-lived Postgres container. Idempotent if container does not exist."""
    container_cmd = _get_container_cmd()
    if not _container_exists(container_cmd):
        return  # idempotent: nothing to do, exit 0
    stop = _run([container_cmd, "stop", CONTAINER_NAME], timeout=30)
    if stop.returncode != 0:
        typer.echo(f"Stop failed: {stop.stderr or stop.stdout or 'unknown'}", err=True)
        raise typer.Exit(1)
    rm = _run([container_cmd, "rm", CONTAINER_NAME], timeout=10)
    if rm.returncode != 0:
        typer.echo(f"Remove failed: {rm.stderr or rm.stdout or 'unknown'}", err=True)
        raise typer.Exit(1)
    typer.echo("Container stopped and removed.")


@postgres_app.command("status")
def postgres_status() -> None:
    """
    Check that the long-lived Postgres container is running and accepting connections.
    Runs SELECT 1 inside the container via exec. Exit 0 on success;
    1 if container not running or query fails.
    """
    container_cmd = _get_container_cmd()
    if not _container_running(container_cmd):
        typer.echo(
            f"Container {CONTAINER_NAME} is not running. "
            "Run 'modelsync test postgres up' to start it.",
            err=True,
        )
        raise typer.Exit(1)
    proc = _run(
        [
            container_cmd,
            "exec",
            CONTAINER_NAME,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-t",
            "-c",
            "SELECT 1",
        ],
        timeout=10,
    )
    if proc.returncode != 0:
        typer.echo(
            f"Query failed: {proc.stderr or proc.stdout or 'unknown'}",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo("Postgres is running and accepting connections.")


@test_app.command("run")
def test_run() -> None:
    """
    Run the test suite (pytest). Exit 0 if all pass; 1 on test failure; 2 if skipped
    (e.g. Postgres not available: run check-container, postgres up, set URL, try again).
    """
    # If MODELSYNC_TEST_POSTGRES_URL unset but our perpetual container is running,
    # use its URL for pytest
    pytest_env = dict(os.environ)
    if not pytest_env.get("MODELSYNC_TEST_POSTGRES_URL"):
        container_cmd = _get_container_cmd_optional()
        if container_cmd and _container_running(container_cmd):
            pytest_env["MODELSYNC_TEST_POSTGRES_URL"] = POSTGRES_URL
        else:
            # Fail-fast: no URL and container not running
            if container_cmd:
                typer.echo(
                    "Postgres tests need a running Postgres. Run 'modelsync test check-container', "
                    "then 'modelsync test postgres up', set MODELSYNC_TEST_POSTGRES_URL "
                    "as printed, then 'modelsync test run' again. "
                    "Or start Postgres and set MODELSYNC_TEST_POSTGRES_URL.",
                    err=True,
                )
                raise typer.Exit(EXIT_POSTGRES_UNAVAILABLE)
    # If Postgres will be used, psycopg must be installed and connection must succeed
    if pytest_env.get("MODELSYNC_TEST_POSTGRES_URL"):
        url = pytest_env["MODELSYNC_TEST_POSTGRES_URL"]
        ok, err_msg = _try_connect_postgres(url, timeout=5)
        if not ok:
            if err_msg == "psycopg not installed":
                typer.echo(
                    "Postgres tests require the 'psycopg' package. "
                    "Install it with: uv sync --extra postgres "
                    "(or pip install 'modelsync[postgres]').",
                    err=True,
                )
            elif err_msg and "password authentication failed" in err_msg:
                typer.echo(
                    "Could not connect to Postgres: password authentication failed. "
                    "If using the CLI container, run 'modelsync test postgres down' then "
                    "'modelsync test postgres up' to recreate it. "
                    "Otherwise check user/password in MODELSYNC_TEST_POSTGRES_URL.",
                    err=True,
                )
            else:
                typer.echo(f"Could not connect to Postgres: {err_msg or 'unknown'}", err=True)
            raise typer.Exit(1)
        typer.echo("Pre-flight: Postgres connection OK (SELECT 1).")
    # Locate tests dir (package root's tests/)
    pkg_root = Path(__file__).resolve().parent.parent.parent
    tests_dir = pkg_root / "tests"
    if not tests_dir.is_dir():
        typer.echo(f"Tests directory not found: {tests_dir}", err=True)
        raise typer.Exit(1)
    # Run pytest in-process so it sees the same os.environ we validated
    # (avoids subprocess env issues).
    for key, value in pytest_env.items():
        os.environ[key] = value
    import pytest as pytest_module

    exit_code = pytest_module.main([str(tests_dir), "-v", "-rs"])
    raise typer.Exit(exit_code)


def main() -> None:
    """Entry point for the modelsync script."""
    app()


if __name__ == "__main__":
    main()
