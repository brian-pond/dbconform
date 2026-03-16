
import enum
from datetime import date
import sys
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class MyBase(DeclarativeBase):
    """Project-wide declarative base.  All models inherit from this.  Mandatory per SQLAlchemy rules."""
    pass

class Habitat(MyBase):
    """A named environment that one or more animals call home.
 
    Kept intentionally lean — the goal is to give Animal a meaningful
    relationship target without pulling focus from the primary model.
    """
    __tablename__ = "habitat"
 
    id:          Mapped[int]           = mapped_column(Integer, primary_key=True)
    name:        Mapped[str]           = mapped_column(String(100), nullable=False, unique=True)
    climate:     Mapped[Optional[str]] = mapped_column(String(50))   # e.g. "tropical", "arid"
    description: Mapped[Optional[str]] = mapped_column(Text)
 
    # Back-reference populated automatically by Animal.habitat relationship.
    animals: Mapped[list["Animal"]] = relationship("Animal", back_populates="habitat")
 
    def __repr__(self) -> str:
        return f"<Habitat id={self.id} name={self.name!r}>"

if __name__ == "__main__":
    from dbconform import DbConform, ConformError

    url = "postgresql+psycopg://myrootuser:My_Secret_PG_Password@127.0.0.1/postgres"
    from dbconform.sql_dialect.postgresql import try_connect_to_postgres
    if not try_connect_to_postgres(url)[0]:
        print("Error while attempting to connect to PostgreSQL database.")
        sys.exit(1)

    conform = DbConform(
        credentials={"url": url},
        target_schema="demo"
    )
    plan = conform.compare([Habitat], allow_shrink_column=True)

    if isinstance(plan, ConformError):
        print("Compare failed:", plan.messages)
    elif not plan.steps:
        if not plan.skipped_steps:
            print("Database is up to date.")
        else:
            plan.print_summary()
        sys.exit(0)
    else:
        for step in plan.steps:
            print(f"* {step}")
        print(plan.sql())  # Full DDL script

    apply_changes: bool = input("Apply changes? ")
    if apply_changes and apply_changes.lower() == 'y':
        plan = conform.apply_changes([Habitat], allow_shrink_column=True)
