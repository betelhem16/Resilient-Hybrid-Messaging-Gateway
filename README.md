# Resilient Hybrid Messaging Gateway

RHMG is an asynchronous message delivery gateway built with FastAPI. It delivers important messages through a primary channel, tracks acknowledgement deadlines, retries temporary failures, and escalates undelivered messages to fallback channels.

The project is designed for systems where delivery reliability, traceability, and operational visibility matter.

## Features

- Asynchronous FastAPI HTTP API
- Message lifecycle state machine with validated transitions
- Primary-channel delivery with acknowledgement tracking
- Idempotent message submission using a unique request key
- Deadline-based escalation to fallback channels
- Exponential retry backoff with jitter
- Immutable message event history for auditing and debugging
- PostgreSQL persistence with SQLAlchemy async ORM
- Redis integration for operational infrastructure
- Structured JSON logging with request IDs
- Liveness, readiness, metrics, and detailed health endpoints
- Admin endpoints for message inspection and manual intervention
- Automated test suite with SQLite-based async fixtures

## Message Lifecycle

```text
PENDING
   |
QUEUED -> SENDING -> SENT_TO_CHANNEL -> ACKNOWLEDGED
                         |
                         v
                ESCALATION_PENDING
                         |
                         v
                 FALLBACK_SENDING
                    |          |
                    v          v
          FALLBACK_DELIVERED  DEAD_LETTER
```

Every transition is validated by the domain state machine and recorded in the message event history.

## Architecture

```text
Client
  |
  v
FastAPI routes -> Message service -> Message processor -> Channel registry
                         |                    |
                         v                    v
                   Repository          Primary/fallback channels
                         |
                         v
                  PostgreSQL database

Background scheduler
  |- checks acknowledgement deadlines
  |- attempts fallback delivery
  `- processes scheduled retries
```

### Main Components

| Component | Responsibility |
| --- | --- |
| `app/api` | HTTP routes for messages, health, metrics, and administration |
| `app/domain` | Message entities, states, transitions, and retry policies |
| `app/services` | Application-level message orchestration |
| `app/repositories` | Database access and message queries |
| `app/channels` | Delivery-channel contracts and implementations |
| `app/workers` | Delivery processing, event recording, and scheduling |
| `app/infrastructure` | SQLAlchemy, PostgreSQL, ORM models, and Redis |
| `app/observability` | Metrics collection and health evaluation |
| `migrations` | Alembic database schema migrations |
| `tests` | Domain, API, worker, admin, and observability tests |

## Technology Stack

- Python 3.11+
- FastAPI and Uvicorn
- SQLAlchemy 2 async ORM
- PostgreSQL with asyncpg
- Redis
- Alembic
- Pydantic Settings
- structlog
- pytest and pytest-asyncio

## Getting Started

### Prerequisites

- Python 3.11 or newer
- Docker Desktop, recommended for PostgreSQL and Redis
- Git

### 1. Clone the repository

```bash
git clone https://github.com/betelhem16/Resilient-Hybrid-Messaging-Gateway.git
cd Resilient-Hybrid-Messaging-Gateway
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

### 4. Configure the environment

```powershell
Copy-Item .env.example .env
```

Update `.env` when needed. The default local configuration expects PostgreSQL at the Docker Compose service name `postgres` and Redis at `redis`.

### 5. Start local infrastructure

```bash
docker compose up -d postgres redis
```

### 6. Run database migrations

```bash
alembic upgrade head
```

### 7. Start the API

```bash
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

Interactive API documentation is available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`

## API Overview

### Create a message

```http
POST /messages
Content-Type: application/json
```

Example request:

```json
{
  "sender": "notification-service",
  "recipient": "telegram-chat-id",
  "content": "Your order is ready",
  "priority": "HIGH"
}
```

### Retrieve a message

```http
GET /messages/{message_id}
```

### Health and operations

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness check |
| `GET /ready` | Database and Redis readiness check |
| `GET /metrics` | Message counts, success rates, and latency metrics |
| `GET /health/detailed` | Health status with warnings and dependency information |
| `GET /admin/messages` | Inspect messages, optionally by state |
| `GET /admin/messages/{id}/events` | View a message audit trail |
| `GET /admin/stats` | View message counts by state |

Admin endpoints are open in local development when `RHMG_ADMIN_API_KEY` is empty. Set this value in production and send it with every admin request:

```http
X-Admin-API-Key: your-secret-key
```

Production admin access fails closed when no key is configured.

## Retry and Escalation

RHMG uses separate retry policies for primary and fallback delivery:

- Primary delivery: up to 3 retries, starting at 5 seconds
- Fallback delivery: up to 2 retries, starting at 10 seconds
- Exponential backoff with configurable maximum delays
- Small random jitter to avoid synchronized retry bursts
- Messages that cannot be delivered are moved to `DEAD_LETTER`

The background scheduler runs three independent loops for deadline checks, fallback attempts, and retry processing.

## Configuration

Configuration is loaded from environment variables with the `RHMG_` prefix. Common settings include:

```env
RHMG_DATABASE_URL=postgresql+asyncpg://rhmg:rhmg_local_dev_only@postgres:5432/rhmg
RHMG_REDIS_URL=redis://redis:6379/0
RHMG_ENV=local
RHMG_LOG_LEVEL=INFO
RHMG_ADMIN_API_KEY=
RHMG_TELEGRAM_BOT_TOKEN=
```

Never commit `.env` or real credentials. Use `.env.example` as the template for local configuration.

## Testing

Run the complete test suite:

```bash
python -m pytest -q
```

The tests use an asynchronous SQLite database so the domain and application behavior can be verified without requiring a running PostgreSQL instance. The current suite covers state transitions, message processing, API contracts, scheduler behavior, admin operations, event history, metrics, and health checks.

Useful development commands:

```bash
python -m pytest -v
ruff check .
mypy app
```

## Project Status

The current milestone includes the core delivery workflow, deadline escalation, retry framework, background scheduler, structured logging, operational endpoints, metrics, migrations, and test coverage.

Planned production hardening includes:

- Additional delivery channels and cascading fallback policies
- Redis Streams for distributed workers
- Circuit breakers and rate limiting
- Prometheus-compatible metrics export
- Message retention and cleanup policies
- Production deployment configuration

## Contributing

1. Create a feature branch.
2. Keep changes focused and covered by tests.
3. Run the test and lint commands locally.
4. Use a clear commit message describing the change.
5. Open a pull request with a concise description and test results.

## License

License information has not yet been added to this repository.
