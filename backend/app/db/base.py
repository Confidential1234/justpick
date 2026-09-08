"""Declarative base. Alembic autogenerate compares against this metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base every model inherits from, and Alembic's comparison target."""
