"""Data package for Rentaliq persistence and synthetic repositories."""

from app.data.repository import Repository, SQLiteRepository, default_repository

__all__ = ["Repository", "SQLiteRepository", "default_repository"]
