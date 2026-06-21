"""
dbconform dbt integration — generate dbt schema.yml from SQLAlchemy models.

Requires the ``[dbt]`` extra: ``pip install 'dbconform[dbt]'``.

Example usage::

    from dbconform.integrations.dbt import generate_schema_yml
    from pathlib import Path

    # Return YAML string
    yaml_str = generate_schema_yml(MyModel)

    # Write a unified schema.yml
    generate_schema_yml([User, Order], output_path=Path("schema.yml"))

    # Write one file per model
    generate_schema_yml([User, Order], output_dir=Path("models/"), per_model=True)

See docs/requirements/01-functional.md (BR-DBT-001 – BR-DBT-007).
"""

from dbconform.integrations.dbt._generate import generate_schema_yml

__all__ = ["generate_schema_yml"]
