import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, messages
from app.channels.registry import create_registry
from app.config import get_settings
from app.infrastructure.database import SessionFactory, engine
from app.infrastructure.redis_client import redis_client
from app.logging_config import LogContextMiddleware, configure_logging
from app.workers.scheduler import MessageScheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Owns startup/shutdown so connection pools are closed deterministically.
    
    This also manages the background scheduler for message processing.
    """
    # Start the background scheduler
    scheduler = MessageScheduler(SessionFactory, app.state.channels)
    scheduler_task = asyncio.create_task(scheduler.start())
    
    try:
        yield
    finally:
        # Stop the scheduler
        await scheduler.stop()
        try:
            await asyncio.wait_for(scheduler_task, timeout=5.0)
        except TimeoutError:
            scheduler_task.cancel()
        
        # Close connection pools
        await redis_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    
    # Configure structured logging
    configure_logging(level=settings.log_level)
    
    app = FastAPI(
        title="Resilient Hybrid Messaging Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
    )
    
    # Add logging middleware for request context
    app.add_middleware(LogContextMiddleware)
    
    app.include_router(health.router)
    app.include_router(messages.router)
    from app.api.routes import admin
    app.include_router(admin.router)
    app.state.settings = settings
    app.state.channels = create_registry(settings.telegram_bot_token)
    return app


app = create_app()
