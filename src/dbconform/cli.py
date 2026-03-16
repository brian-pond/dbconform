"""
dbconform CLI: test workflow (container check, Postgres lifecycle, run tests).

See docs/requirements/01-functional.md (CLI scope) and .cursor/rules/cli-conventions.mdc.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

try:
    import typer
except ImportError:
    print("To enable the CLI, install dbconform with optional development packages:\n\tpip install dbconform[dev]", # noqa: E501
          file=sys.stderr)
    sys.exit(1)


# Container constants (match tests/docker-compose.yml image)
POSTGRES_IMAGE = "postgres:16-alpine"
CONTAINER_NAME = "dbconform-postgres"
POSTGRES_PORT = 15432
POSTGRES_URL = f"postgresql://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/postgres"


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


def _get_container_runtime_path_or_none() -> str | None:
    """Return docker or podman path if available, else None. Does not echo or exit."""
    cmd = os.environ.get("DBCONFORM_CONTAINER_CMD", "").strip()
    if cmd:
        return shutil.which(cmd)
    for name in ("docker", "podman"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _get_container_runtime_path() -> str:
    """
    Return docker or podman binary path: DBCONFORM_CONTAINER_CMD, or first of docker/podman in PATH.
    Exits 1 with message if not found.
    """
    path = _get_container_runtime_path_or_none()
    if path:
        return path
    typer.echo(
        "Container runtime not found (docker/podman). Set DBCONFORM_CONTAINER_CMD or install Docker/Podman.",
        err=True,
    )
    raise typer.Exit(1)


def _run_subprocess(
    args: list[str],
    *,
    capture: bool = True,
    timeout: int | None = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess; return CompletedProcess. Raises on timeout.
    If env is set, it replaces the process env."""
    kwargs: dict = {"capture_output": capture, "text": True, "timeout": timeout}
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(args, **kwargs)


# --- Root app ---
app = typer.Typer(
    name="dbconform",
    help="Conform database schema to models. Use 'test' for running tests and Postgres lifecycle.",
)


@app.callback(invoke_without_command=True)
def _main_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("version")
def show_version() -> None:
    """
    Show the installed dbconform package version.

    See docs/requirements/02-non-functional.md (Deployment).
    """
    try:
        v = pkg_version("dbconform")
    except PackageNotFoundError:
        typer.echo(
            "dbconform package version is unknown (distribution not installed).",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(v)


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
    runtime_path = _get_container_runtime_path()
    # --rm: remove when done. We use "sleep 2" (not pg_isready) because overriding CMD
    # prevents the image from starting Postgres, so pg_isready would have nothing to connect to.
    # This still verifies runtime + image pull + container start.
    proc = _run_subprocess(
        [runtime_path, "run", "--rm", POSTGRES_IMAGE, "sleep", "2"],
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
    proc = _run_subprocess([container_cmd, "ps", "-a", "-q", "-f", f"name={CONTAINER_NAME}"], timeout=5)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _container_running(container_cmd: str) -> bool:
    """Return True if CONTAINER_NAME is running (not just existing)."""
    proc = _run_subprocess([container_cmd, "ps", "-q", "-f", f"name={CONTAINER_NAME}"], timeout=5)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _psycopg_available() -> bool:
    """Return True if psycopg is installed (postgres extra)."""
    try:
        import psycopg  # noqa: F401

        return True
    except ImportError:
        return False


def _ensure_postgres_container_up(container_cmd: str) -> bool:
    """
    Ensure Postgres container is running. Start it if needed; wait for connection.
    Returns True if Postgres is ready at POSTGRES_URL; False on any failure.
    Cleans up partially-created containers on failure.
    """
    if _container_running(container_cmd):
        ok, _ = _try_connect_postgres(POSTGRES_URL, timeout=3)
        return ok
    if _container_exists(container_cmd):
        _run_subprocess([container_cmd, "start", CONTAINER_NAME], timeout=10)
    else:
        proc = _run_subprocess(
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
            _run_subprocess([container_cmd, "rm", "-f", CONTAINER_NAME], timeout=5)
            return False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ok, err_msg = _try_connect_postgres(POSTGRES_URL, timeout=3)
        if ok:
            return True
        if err_msg and "password authentication failed" in err_msg:
            _run_subprocess([container_cmd, "stop", CONTAINER_NAME], timeout=10)
            _run_subprocess([container_cmd, "rm", "-f", CONTAINER_NAME], timeout=5)
            return False
        time.sleep(1)
    _run_subprocess([container_cmd, "stop", CONTAINER_NAME], timeout=10)
    _run_subprocess([container_cmd, "rm", "-f", CONTAINER_NAME], timeout=5)
    return False


def _teardown_postgres_container(container_cmd: str) -> None:
    """Stop and remove the Postgres container. Idempotent if it does not exist."""
    if not _container_exists(container_cmd):
        return
    _run_subprocess([container_cmd, "stop", CONTAINER_NAME], timeout=30)
    _run_subprocess([container_cmd, "rm", CONTAINER_NAME], timeout=10)


@postgres_app.command("up")
def postgres_up() -> None:
    """
    Start a long-lived Postgres container (name dbconform-postgres, port 15432).
    Prints DBCONFORM_TEST_POSTGRES_URL to set before running tests.
    """
    container_cmd = _get_container_runtime_path()
    if _container_exists(container_cmd):
        typer.echo(
            f"Container {CONTAINER_NAME} already exists. Run 'dbconform test postgres down' first.",
            err=True,
        )
        raise typer.Exit(1)
    proc = _run_subprocess(
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
        # Remove partially-created container (podman may create then fail on port bind)
        _run_subprocess([container_cmd, "rm", "-f", CONTAINER_NAME], timeout=5)
        # Distinguish port conflict from container name conflict
        if "bind" in err and "already in use" in err:
            typer.echo(
                f"Port {POSTGRES_PORT} is already in use. "
                f"Stop the process using it, or run 'dbconform test postgres down' first.",
                err=True,
            )
        elif "already in use" in err or "Conflict" in err or "exists" in err:
            typer.echo(
                f"Container {CONTAINER_NAME} already exists. Run 'dbconform test postgres down' first.",
                err=True,
            )
        else:
            typer.echo(f"Start failed: {err}", err=True)
        raise typer.Exit(1)
    # Wait for Postgres to accept TCP connections with our password (up to 30s)
    ok, err_msg = _try_connect_postgres(POSTGRES_URL, timeout=3)
    if err_msg == "psycopg not installed":
        typer.echo(f"Set: DBCONFORM_TEST_POSTGRES_URL={POSTGRES_URL}")
        typer.echo(
            "Run 'dbconform test run' to run tests. (Install [postgres] extra to verify connection at start.)"
        )
        return
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ok, err_msg = _try_connect_postgres(POSTGRES_URL, timeout=3)
        if ok:
            typer.echo(f"Set: DBCONFORM_TEST_POSTGRES_URL={POSTGRES_URL}")
            typer.echo("Connection verified (SELECT 1).")
            typer.echo("Run 'dbconform test run' to run tests.")
            return
        if err_msg and "password authentication failed" in err_msg:
            _run_subprocess([container_cmd, "stop", CONTAINER_NAME], timeout=10)
            _run_subprocess([container_cmd, "rm", CONTAINER_NAME], timeout=5)
            typer.echo(
                f"Port {POSTGRES_PORT} is in use by another Postgres (password rejected). "
                "Stop that service, then run 'dbconform test postgres up' again. "
                "Or use a different port by setting DBCONFORM_TEST_POSTGRES_URL "
                "to your own instance.",
                err=True,
            )
            raise typer.Exit(1)
        time.sleep(1)
    _run_subprocess([container_cmd, "stop", CONTAINER_NAME], timeout=10)
    _run_subprocess([container_cmd, "rm", CONTAINER_NAME], timeout=5)
    typer.echo(
        "Container did not accept connections in 30s; removed it. "
        f"If another process was using port {POSTGRES_PORT}, stop it and "
        "run 'dbconform test postgres up' again.",
        err=True,
    )
    raise typer.Exit(1)


@postgres_app.command("down")
def postgres_down() -> None:
    """Stop and remove the long-lived Postgres container. Idempotent if container does not exist."""
    container_cmd = _get_container_runtime_path()
    if not _container_exists(container_cmd):
        return  # idempotent: nothing to do, exit 0
    stop = _run_subprocess([container_cmd, "stop", CONTAINER_NAME], timeout=30)
    if stop.returncode != 0:
        typer.echo(f"Stop failed: {stop.stderr or stop.stdout or 'unknown'}", err=True)
        raise typer.Exit(1)
    rm = _run_subprocess([container_cmd, "rm", CONTAINER_NAME], timeout=10)
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
    container_cmd = _get_container_runtime_path()
    if not _container_running(container_cmd):
        typer.echo(
            f"Container {CONTAINER_NAME} is not running. Run 'dbconform test postgres up' to start it.",
            err=True,
        )
        raise typer.Exit(1)
    proc = _run_subprocess(
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
def run_test_suite() -> None:
    """
    Run the test suite (pytest). Exit 0 if all pass; 1 on test failure.

    With [postgres] extra and container runtime: auto-starts Postgres, runs tests,
    stops container. Otherwise: runs SQLite tests only.
    """
    pytest_env = dict(os.environ)
    container_cmd = _get_container_runtime_path_or_none()
    use_postgres = False

    if _psycopg_available() and container_cmd and _ensure_postgres_container_up(container_cmd):
        use_postgres = True
        pytest_env["DBCONFORM_TEST_POSTGRES_URL"] = POSTGRES_URL
        typer.echo("Postgres container started. Running tests...")

    pkg_root = Path(__file__).resolve().parent.parent.parent
    tests_dir = pkg_root / "tests"
    if not tests_dir.is_dir():
        typer.echo(f"Tests directory not found: {tests_dir}", err=True)
        raise typer.Exit(1)

    for key, value in pytest_env.items():
        os.environ[key] = value

    try:
        import pytest as pytest_module

        exit_code = pytest_module.main([str(tests_dir), "-v", "-rs"])
    finally:
        if use_postgres and container_cmd:
            _teardown_postgres_container(container_cmd)
            typer.echo("Postgres container stopped.")

    raise typer.Exit(exit_code)


def main() -> None:
    """Entry point for the dbconform script."""
    app()


if __name__ == "__main__":
    main()
