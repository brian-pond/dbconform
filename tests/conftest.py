"""
Pytest configuration for the tests package.

Ensures pytest-docker uses tests/docker-compose.yml when running PostgreSQL
integration tests (see integration/conftest.py empty_postgres_db).
Supports Podman via MODELSYNC_TEST_POSTGRES_COMPOSE_CMD.
"""

import os

import pytest


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig: pytest.Config) -> str:
    """Point pytest-docker at tests/docker-compose.yml (Postgres service)."""
    root = pytestconfig.rootpath
    return str(root / "tests" / "docker-compose.yml")


@pytest.fixture(scope="session")
def docker_compose_command() -> str:
    """
    Compose command for pytest-docker (default: docker compose).

    Override with MODELSYNC_TEST_POSTGRES_COMPOSE_CMD to use Podman or another
    Docker-compatible CLI, e.g. export MODELSYNC_TEST_POSTGRES_COMPOSE_CMD='podman compose'.
    """
    return os.environ.get("MODELSYNC_TEST_POSTGRES_COMPOSE_CMD", "docker compose")


@pytest.fixture(scope="session")
def docker_setup(docker_compose_command: str) -> list[str]:
    """
    Compose commands for spawn: down then up.

    podman-compose does not support --wait, so we omit it and rely on
    empty_postgres_db to wait for Postgres to be ready.
    """
    cmd = docker_compose_command.strip().lower()
    if cmd == "podman-compose" or cmd.endswith("podman-compose"):
        return ["down -v", "up --build"]
    return ["down -v", "up --build --wait"]
