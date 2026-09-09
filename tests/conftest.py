"""Pytest configuration and fixtures for database tests."""

from __future__ import annotations

import os
from typing import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.models import Base


@pytest.fixture
async def test_db_engine():
    """Create an in-memory SQLite engine for testing."""
    # Use SQLite for testing; it's fast and requires no external setup
    db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(db_url, echo=False)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session(test_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test session for each test."""
    SessionFactory = async_sessionmaker(test_db_engine, expire_on_commit=False)

    async with SessionFactory() as session:
        yield session
