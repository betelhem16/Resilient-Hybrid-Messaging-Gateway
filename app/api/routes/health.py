from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_session
from app.infrastructure.redis_client import redis_client
from app.observability.metrics import HealthChecker, MetricsCollector

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: is this process running?

    Deliberately checks no dependencies. A failing liveness probe means
    "restart me" — and restarting the API cannot fix a down database.
    """
    return {"status": "alive"}


@router.get("/ready")
async def ready(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """Readiness: can this process serve traffic right now?

    Checks every dependency needed to accept a message. A failure means
    "stop routing requests here", not "restart me".
    """
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    all_ok = all(v == "ok" for v in checks.values())
    body = {"status": "ready" if all_ok else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if all_ok else 503, content=body)


@router.get("/metrics")
async def get_metrics(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Get system metrics and statistics.

    Returns information about message processing rates, delivery success,
    and system load.
    """
    collector = MetricsCollector(session)
    metrics = await collector.collect()

    return {
        "total_messages": metrics.total_messages,
        "messages_by_state": metrics.messages_by_state,
        "messages_acknowledged": metrics.messages_acknowledged,
        "messages_failed": metrics.messages_failed,
        "messages_dead_letter": metrics.messages_dead_letter,
        "delivery_success_rate_24h": metrics.delivery_success_rate(),
        "successful_deliveries_24h": metrics.successful_deliveries_24h,
        "failed_deliveries_24h": metrics.failed_deliveries_24h,
        "avg_time_to_acknowledge_seconds": metrics.avg_time_to_acknowledge_seconds,
    }


@router.get("/health/detailed")
async def get_detailed_health(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Get detailed system health status.

    Includes dependency checks and counts of messages in concerning states.
    """
    checker = HealthChecker(session)
    health = await checker.check_health()

    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    return {
        "healthy": health.is_healthy,
        "ready": health.is_ready,
        "checks": checks,
        "messages_pending": health.messages_pending,
        "messages_escalation_pending": health.messages_escalation_pending,
        "messages_dead_letter": health.messages_dead_letter,
        "warnings": health.warnings,
        "last_check_at": health.last_check_at.isoformat() if health.last_check_at else None,
    }
