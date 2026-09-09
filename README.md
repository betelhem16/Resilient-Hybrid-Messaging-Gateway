# RHMG (Resilient Hybrid Messaging Gateway) - Complete Project Documentation

**Last Updated**: 2026-09-09  
**Project Status**: Current milestone complete: 27 automated tests passing  
**Python Version**: 3.11+  
**Framework**: FastAPI 0.115.6 with SQLAlchemy 2.0.36 async ORM

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Technology Stack](#technology-stack)
3. [Architecture & Design](#architecture--design)
4. [Directory Structure](#directory-structure)
5. [Implementation Details - File by File](#implementation-details---file-by-file)
6. [How Each Feature Works](#how-each-feature-works)
7. [Git Commit Strategy](#git-commit-strategy)

---

## Project Overview

**RHMG** is a **production-grade message delivery system** that:
- Accepts messages from various sources (HTTP API)
- Attempts delivery to primary channels (Telegram, Email, SMS, etc.)
- Automatically escalates to fallback channels if primary fails
- Retries with exponential backoff on transient failures
- Tracks full audit trail of all message states and events
- Provides operational monitoring, health checks, and debugging endpoints
- Runs background workers for deadline checking, fallback attempts, and retry scheduling

**Key Problem Solved**: Ensures critical messages reach users even if primary delivery channels are temporarily unavailable, with automatic retry and escalation logic.

---

## Technology Stack

### Backend Framework
- **FastAPI 0.115.6** - Async web framework for HTTP API endpoints and request routing
- **Uvicorn 0.34.0** - ASGI server that runs the FastAPI app

### Database
- **PostgreSQL (Production)** - Relational database for persistence with async driver
- **SQLite (Testing)** - Lightweight database for unit tests with async support
- **SQLAlchemy 2.0.36** - Async ORM for database abstraction and query building
- **Alembic 1.14.0** - Database schema versioning and migrations

### Async Driver
- **asyncpg 0.30.0** - High-performance async PostgreSQL driver

### Data Validation
- **Pydantic 2.10.4** - Request/response schema validation
- **pydantic-settings 2.7.0** - Environment-based configuration management

### Caching & Async Messaging
- **Redis 5.2.1** - In-memory cache and message queue (future use for distributed workers)
- **httpx 0.28.1** - Async HTTP client for external API calls

### Observability
- **structlog 24.4.0** - Structured JSON logging for machine-parseable output

### Testing
- **pytest 8.3.4** - Test runner and framework
- **pytest-asyncio 0.25.0** - Async test support with `asyncio_mode="auto"`

---

## Architecture & Design

### High-Level Flow

```
HTTP Request
    ↓
[FastAPI Endpoint] → Parse & validate with Pydantic
    ↓
[MessageService] → Create MessageRecord in PENDING state
    ↓
[MessageProcessor] → Queue message (PENDING → QUEUED)
    ↓
[MessageProcessor] → Send to primary channel (QUEUED → SENDING → SENT_TO_CHANNEL)
    ↓
    ├─→ Success: Wait for acknowledgement
    │   ├─→ Acknowledged within deadline → ACKNOWLEDGED (terminal, success)
    │   └─→ Deadline passed, no ack → Auto-escalate to fallback
    │
    └─→ Failure: Record error
        ├─→ Fallback available → ESCALATION_PENDING
        │   └─→ [MessageScheduler] attempts fallback every 15s
        │       ├─→ Success → FALLBACK_DELIVERED (terminal, success)
        │       └─→ Failure → Retry or DEAD_LETTER
        │
        └─→ No fallback → DEAD_LETTER (terminal, failure)

[MessageScheduler - Background Workers]
├─→ Deadline Check Loop (10s) - Checks for messages past ack deadline
├─→ Fallback Attempt Loop (15s) - Attempts fallback for escalated messages
└─→ Retry Check Loop (20s) - Processes messages scheduled for retry
```

### State Machine Transitions

Messages transition through states in strict order (enforced):

```
PENDING (initial)
   ↓
QUEUED
   ↓
SENDING
   ↓
SENT_TO_CHANNEL
   ├─→ ACKNOWLEDGED (via external ACK webhook or manual)
   └─→ ESCALATION_PENDING (auto-escalate or manual trigger)
       ├─→ FALLBACK_SENDING
       │   ├─→ FALLBACK_DELIVERED (terminal)
       │   └─→ DEAD_LETTER (terminal)
       └─→ DEAD_LETTER (if no fallback available)

Terminal States: ACKNOWLEDGED, FALLBACK_DELIVERED, DEAD_LETTER, FAILED
```

### Retry & Backoff Strategy

- **Primary Retry Policy**: Max 3 retries, start at 5s, exponential backoff (2x multiplier), cap at 300s
- **Fallback Retry Policy**: Max 2 retries, start at 10s, exponential backoff (2x multiplier), cap at 600s
- **Jitter**: +/- 10% random variation to prevent thundering herd

Formula: `delay = min(initial * (multiplier ^ attempt), max_backoff)` with jitter applied

---

## Directory Structure

```
rhmg/
├── app/                          # Main application package
│   ├── __init__.py              # Package marker
│   ├── main.py                  # FastAPI app creation, lifespan, middleware
│   ├── config.py                # Settings/environment configuration (Pydantic)
│   ├── logging_config.py         # Structured logging setup, request middleware
│   │
│   ├── api/                      # HTTP API routes
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py         # Health checks, metrics, liveness/readiness probes
│   │       ├── messages.py       # Message submission, ACK webhook endpoints
│   │       └── admin.py          # Debugging endpoints (list, stats, manual escalate/retry)
│   │
│   ├── domain/                   # Core business logic (state machines, entities)
│   │   ├── __init__.py
│   │   ├── message.py            # MessageRecord dataclass, state tracking
│   │   ├── message_state.py      # MessageState enum (PENDING, QUEUED, etc.)
│   │   ├── message_event.py      # MessageEvent for audit trail
│   │   ├── state_machine.py      # State transition validation logic
│   │   └── retry_policy.py       # RetryPolicy: backoff calculation, retry scheduling
│   │
│   ├── infrastructure/           # Low-level persistence & I/O
│   │   ├── __init__.py
│   │   ├── database.py           # SQLAlchemy engine, session factory, async setup
│   │   ├── models.py             # ORM models (Message, MessageEvent tables)
│   │   └── redis_client.py       # Redis async client initialization
│   │
│   ├── repositories/             # Data access layer (abstraction over ORM)
│   │   └── message_repository.py # CRUD ops, queries (list_due_for_retry, etc.)
│   │
│   ├── services/                 # Application logic (orchestration)
│   │   └── message_service.py    # High-level message operations (create, process)
│   │
│   ├── channels/                 # Delivery channel implementations
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract Channel interface
│   │   ├── telegram.py          # Telegram Bot API implementation
│   │   └── registry.py          # ChannelRegistry - factory for channel instances
│   │
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── message.py            # CreateMessageRequest, MessageResponse
│   │   └── message_event.py      # Event schema for JSON serialization
│   │
│   ├── workers/                  # Background job processing
│   │   ├── __init__.py
│   │   ├── events.py             # Lifecycle event recorder and event constants
│   │   ├── processor.py          # MessageProcessor - core state transitions, delivery logic
│   │   └── scheduler.py          # MessageScheduler - periodic task runner
│   │
│   └── observability/            # Monitoring & operational insights
│       ├── __init__.py
│       └── metrics.py             # MetricsCollector, HealthChecker
│
├── migrations/                    # Alembic database migrations
│   ├── env.py                    # Migration environment configuration
│   ├── script.py.mako            # Migration template
│   └── versions/
│       ├── 20260819_000001_create_messages_and_events.py   # Initial schema
│       └── 20260809_000002_add_next_retry_at.py            # Retry scheduling column
│
├── tests/                        # Unit and integration tests
│   ├── test_message_processor.py       # MessageProcessor state transitions
│   ├── test_message_state.py           # State machine validation
│   ├── test_message_events.py          # Event recording
│   ├── test_domain_state_machine.py    # State transition rules
│   ├── test_message_api_contract.py    # HTTP API endpoints
│   ├── test_scheduler.py               # MessageScheduler background workers
│   ├── test_admin.py                   # Admin endpoint functionality
│   └── test_metrics.py                 # Health checks and metrics collection
│
├── alembic.ini                   # Alembic configuration (database migrations)
├── pyproject.toml                # Python project metadata, tool configs
├── requirements.txt              # Production dependencies
├── requirements-dev.txt          # Development dependencies (pytest, etc.)
├── docker-compose.yml            # Local dev environment (PostgreSQL, Redis)
├── Dockerfile                    # Container image definition
├── .env.example                  # Example environment variables
└── .gitignore                    # Git ignore rules
```

---

## Implementation Details - File by File

### **app/main.py** - Application Bootstrap & Lifecycle
**Purpose**: Entry point, FastAPI app creation, middleware setup, background worker management

**Key Code Sections**:

1. **Lifespan Context Manager** (handles app startup/shutdown)
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI) -> AsyncIterator[None]:
       # On startup:
       # - Create MessageScheduler instance
       # - Start scheduler as asyncio background task
       # - Yield control to FastAPI
       #
       # On shutdown:
       # - Stop scheduler
       # - Close database connection pool
       # - Close Redis connection pool
   ```
   **Why**: Ensures clean startup/shutdown of async resources (DB, Redis, background tasks)

2. **create_app() Function**
   ```python
   # Initializes:
   # - Structured logging via structlog
   # - LogContextMiddleware for request tracing
   # - FastAPI instance with metadata
   # - Routes: /health, /messages, /admin
   # - Channel registry (Telegram, etc.)
   ```

**Dependencies**: FastAPI, SQLAlchemy, structlog, MessageScheduler

---

### **app/config.py** - Configuration Management
**Purpose**: Load and validate environment variables using Pydantic

**Key Components**:

```python
class Settings(BaseSettings):
    # Database
    database_url: str  # PostgreSQL connection string
    db_pool_size: int  # Connection pool size
    
    # Logging
    log_level: str  # INFO, DEBUG, WARNING
    
    # Channels
    telegram_bot_token: str  # For Telegram Bot API
    
    # Retry policy
    retry_max_attempts: int
    retry_initial_backoff_seconds: int
    
    # App behavior
    message_acknowledgement_deadline_seconds: int
```

**Key Feature**: Uses `RHMG_` prefix for environment variables (e.g., `RHMG_DATABASE_URL`)

---

### **app/logging_config.py** - Structured Logging Setup
**Purpose**: Configure structlog for JSON output + request context tracking

**Key Components**:

1. **configure_logging(level: str)** Function
   ```python
   # Sets up structlog processors:
   # - TimeStamper: adds timestamp to each log entry
   # - JSONRenderer: outputs logs as JSON (machine-parseable)
   # Integrates with Python's stdlib logging
   ```

2. **LogContextMiddleware** (ASGI Middleware)
   ```python
   # For each HTTP request:
   # - Generate unique request_id
   # - Bind request_id, path, method to structlog context
   # - Add x-request-id header to response
   # - All logs in this request include the request_id automatically
   ```
   **Use Case**: Trace messages across logs using request_id

3. **get_logger(name: str)** Function
   ```python
   # Returns structlog logger instance for use in modules
   # Usage: logger = get_logger(__name__)
   ```

**Why This Matters**: JSON output enables parsing/filtering logs in production monitoring systems (ELK, DataDog, etc.)

---

### **app/domain/message.py** - Domain Model
**Purpose**: Core business entity representing a message

**Key Components**:

```python
@dataclass
class MessageRecord:
    id: str
    sender: str
    recipient: str
    content: str
    policy: MessagePolicy  # Retry policy
    current_state: MessageState
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]
    acknowledged_at: Optional[datetime]
    escalated_at: Optional[datetime]
    
    # Delivery tracking
    external_message_id: Optional[str]  # ID from channel (Telegram message_id)
    idempotency_key: Optional[str]  # For deduplication
    
    # Retry state
    retry_count: int
    next_retry_at: Optional[datetime]
    last_error: Optional[str]
    ack_deadline_at: Optional[datetime]  # Deadline for acknowledgement
    
    metadata: dict  # Arbitrary extra data
    
    # Methods
    def arm_deadline(self, now: datetime) -> None:
        # Set ack_deadline_at = now + policy.acknowledgement_deadline_seconds
        
    def is_acknowledged(self) -> bool:
        # Return acknowledged_at is not None
```

---

### **app/domain/message_state.py** - State Machine States
**Purpose**: Enum of all valid message states

```python
class MessageState(Enum):
    PENDING = "pending"                    # Initial state after creation
    QUEUED = "queued"                      # Waiting to be sent
    SENDING = "sending"                    # Currently attempting delivery
    SENT_TO_CHANNEL = "sent_to_channel"    # Sent, waiting for ack
    ESCALATION_PENDING = "escalation_pending"  # Attempting fallback
    FALLBACK_SENDING = "fallback_sending"  # Sending via fallback channel
    ACKNOWLEDGED = "acknowledged"          # Terminal: success
    FALLBACK_DELIVERED = "fallback_delivered"  # Terminal: success via fallback
    FAILED = "failed"                      # Terminal: all attempts failed
    DEAD_LETTER = "dead_letter"            # Terminal: unrecoverable error
```

---

### **app/domain/message_event.py** - Audit Trail
**Purpose**: Record every state change and action for audit trail

```python
@dataclass
class MessageEvent:
    id: int
    message_id: str
    event_type: str  # E.g., "QUEUED", "ESCALATION_TRIGGERED", "ACKNOWLEDGED"
    payload: dict  # Event-specific data (e.g., {channel: "telegram", error: "timeout"})
    created_at: datetime
```

**Why**: Enables debugging and compliance (who did what, when)

---

### **app/domain/state_machine.py** - State Transition Validation
**Purpose**: Enforce valid state transitions, prevent invalid flows

**Key Code**:

```python
class StateMachine:
    _VALID_TRANSITIONS = {
        MessageState.PENDING: [MessageState.QUEUED],
        MessageState.QUEUED: [MessageState.SENDING],
        MessageState.SENDING: [MessageState.SENT_TO_CHANNEL, MessageState.FAILED],
        MessageState.SENT_TO_CHANNEL: [
            MessageState.ACKNOWLEDGED,
            MessageState.ESCALATION_PENDING,
        ],
        # ... etc for all states
    }
    
    async def apply_transition(
        self,
        message: MessageRecord,
        new_state: MessageState,
        event_type: str,
        event_payload: dict,
    ) -> None:
        # 1. Validate new_state is in _VALID_TRANSITIONS[current_state]
        # 2. If invalid, raise StateTransitionError
        # 3. Update message.current_state
        # 4. Record event in message_events table
```

**Why**: Prevents logical errors (e.g., going from ACKNOWLEDGED back to QUEUED)

---

### **app/domain/retry_policy.py** - Exponential Backoff
**Purpose**: Calculate retry delays with exponential backoff and jitter

**Key Code**:

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int
    initial_backoff_seconds: float
    max_backoff_seconds: float
    backoff_multiplier: float
    
    def should_retry(self, retry_count: int) -> bool:
        return retry_count < self.max_retries
    
    def next_retry_at(
        self,
        retry_count: int,
        now: Optional[datetime] = None,
    ) -> datetime:
        # Calculate delay:
        # delay = initial * (multiplier ^ retry_count)
        # delay = min(delay, max_backoff)
        # Add ±10% jitter to spread retries
        # Return now + timedelta(seconds=delay)

# Predefined policies
PRIMARY_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    initial_backoff_seconds=5.0,
    max_backoff_seconds=300.0,
    backoff_multiplier=2.0,
)

FALLBACK_RETRY_POLICY = RetryPolicy(
    max_retries=2,
    initial_backoff_seconds=10.0,
    max_backoff_seconds=600.0,
    backoff_multiplier=2.0,
)
```

**Example**: If first attempt fails, retry at 5s; if second fails, retry at 10s; if third fails, retry at 20s; if fourth fails, give up.

---

### **app/infrastructure/database.py** - Database Setup
**Purpose**: Initialize SQLAlchemy engine and session factory

**Key Code**:

```python
# Create async engine connected to PostgreSQL (or SQLite for tests)
engine = create_async_engine(
    settings.database_url,
    echo=settings.echo_sql,
    pool_size=settings.db_pool_size,
    max_overflow=0,
)

# Create async session factory
SessionFactory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    future=True,
)

async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        yield session
```

**Why Async**: Non-blocking database queries allow handling many concurrent requests

---

### **app/infrastructure/models.py** - ORM Models
**Purpose**: SQLAlchemy table definitions (database schema)

**Message Table**:
```python
class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sender: Mapped[str]
    recipient: Mapped[str]
    content: Mapped[str]
    priority: Mapped[str]  # e.g., "HIGH", "NORMAL"
    
    # State tracking
    current_state: Mapped[MessageState]  # Enum column
    
    # Timestamps
    created_at: Mapped[datetime]  # Set once at creation
    updated_at: Mapped[datetime]  # Updated on every change
    sent_at: Mapped[Optional[datetime]]  # When delivery attempted
    acknowledged_at: Mapped[Optional[datetime]]  # When ack received
    escalated_at: Mapped[Optional[datetime]]  # When escalated to fallback
    ack_deadline_at: Mapped[Optional[datetime]]  # Deadline for acknowledgement
    
    # Delivery tracking
    external_message_id: Mapped[Optional[str]]  # ID from Telegram, etc.
    idempotency_key: Mapped[Optional[str]]  # For deduplication
    
    # Retry state
    retry_count: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[Optional[str]]
    next_retry_at: Mapped[Optional[datetime]]  # When to next retry (set by retry policy)
    
    metadata: Mapped[dict] = mapped_column(JSON, default={})
    
    # Relationships
    events: Mapped[List["MessageEvent"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )
    
    # Indexes for query performance
    __table_args__ = (
        Index("ix_messages_sender", "sender"),
        Index("ix_messages_recipient", "recipient"),
        Index("ix_messages_current_state", "current_state"),
        Index("ix_messages_next_retry_at", "next_retry_at"),
    )

class MessageEvent(Base):
    __tablename__ = "message_events"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    event_type: Mapped[str]  # E.g., "QUEUED", "ESCALATION_TRIGGERED"
    payload: Mapped[dict] = mapped_column(JSON)  # Event data
    created_at: Mapped[datetime]
    
    message: Mapped["Message"] = relationship(back_populates="events")
```

---

### **app/repositories/message_repository.py** - Data Access Layer
**Purpose**: Abstraction over ORM for database operations

**Key Methods**:

1. **create(message: MessageRecord) -> MessageRecord**
   ```python
   # Instantiate Message ORM object
   # Add to session, flush to DB
   # Return converted MessageRecord
   ```

2. **get_by_id(id: str) -> MessageRecord**
   ```python
   # SELECT * FROM messages WHERE id = ?
   # Convert ORM → MessageRecord domain object
   ```

3. **update(message: MessageRecord) -> MessageRecord**
   ```python
   # Find existing message by id
   # Update all fields (state, timestamps, retry info)
   # Flush to DB
   ```

4. **list_due_for_escalation(now: datetime) -> List[MessageRecord]**
   ```python
   # SELECT * FROM messages WHERE
   #   current_state = 'sent_to_channel' AND
   #   acknowledged_at IS NULL AND
   #   ack_deadline_at < now
   # Used by scheduler to find messages past deadline
   ```

5. **list_by_state(state: MessageState) -> List[MessageRecord]**
   ```python
   # SELECT * FROM messages WHERE current_state = ?
   # Used to find messages in escalation_pending for fallback attempts
   ```

6. **list_due_for_retry(now: datetime) -> List[MessageRecord]**
   ```python
   # SELECT * FROM messages WHERE
   #   next_retry_at IS NOT NULL AND
   #   next_retry_at <= now
   # Used by scheduler to find messages ready to retry
   ```

---

### **app/services/message_service.py** - Application Logic
**Purpose**: High-level message operations (orchestration)

**Key Methods**:

1. **create(request: CreateMessageRequest) -> MessageRecord**
   ```python
   # Generate unique message ID
   # Create MessageRecord in PENDING state
   # Set ack_deadline_at = now + policy.acknowledgement_deadline_seconds
   # Save to database via repository
   # Record CREATED event
   ```

2. **process_message(id: str) -> MessageRecord**
   ```python
   # Fetch message by id
   # Call processor.process_new_message()
   # Call processor.attempt_delivery()
   # Return updated message
   ```

---

### **app/workers/processor.py** - Core State Machine Logic
**Purpose**: Implements all message state transitions and delivery orchestration

**Key Methods**:

1. **process_new_message(message: MessageRecord) -> None**
   ```python
   # Transition: PENDING → QUEUED
   # Record QUEUED event
   ```

2. **attempt_delivery(message: MessageRecord, channel_name: str) -> None**
   ```python
   # Transition: QUEUED → SENDING
   # Call channel.send(message)
   # If success:
   #   - Transition: SENDING → SENT_TO_CHANNEL
   #   - Set external_message_id (from channel)
   #   - Arm deadline timer
   # If failure:
   #   - Increment retry_count
   #   - Record error in last_error
   #   - Check if should escalate (if primary failed, escalate)
   #   - If escalating: Transition → ESCALATION_PENDING
   #   - Otherwise: set next_retry_at, attempt retry later
   ```

3. **check_deadlines() -> None**
   ```python
   # Called by scheduler every 10 seconds
   # Query messages with current_state=SENT_TO_CHANNEL, ack_deadline_at < now
   # For each: _escalate_message()
   ```

4. **acknowledge_message(message_id: str) -> None**
   ```python
   # Called when ACK webhook received
   # Set acknowledged_at = now
   # Transition: SENT_TO_CHANNEL → ACKNOWLEDGED (terminal)
   # Record ACKNOWLEDGED event
   ```

5. **_escalate_message(message: MessageRecord) -> None**
   ```python
   # Transition: SENT_TO_CHANNEL → ESCALATION_PENDING
   # Record ESCALATION_TRIGGERED event with list of fallback channels
   # Set escalated_at timestamp
   ```

6. **attempt_fallback(message_id: str, channel_name: str) -> None**
   ```python
   # Fetch message in ESCALATION_PENDING state
   # Transition: ESCALATION_PENDING → FALLBACK_SENDING
   # Call channel.send(message)
   # If success:
   #   - Transition: FALLBACK_SENDING → FALLBACK_DELIVERED (terminal)
   #   - Record success event
   # If failure:
   #   - Increment retry_count
   #   - If should_retry (retry_count < max):
   #     - Calculate next_retry_at with fallback retry policy
   #     - Go back to ESCALATION_PENDING
   #   - Else:
   #     - Transition: FALLBACK_SENDING → DEAD_LETTER (terminal)
   #     - Record final failure event
   ```

---

### **app/workers/scheduler.py** - Background Task Runner
**Purpose**: Periodic background jobs (deadline checking, fallback attempts, retries)

**Key Components**:

```python
class MessageScheduler:
    def __init__(
        self,
        session_factory: sessionmaker,
        channels: ChannelRegistry,
        deadline_check_interval: int = 10,
        fallback_attempt_interval: int = 15,
        retry_check_interval: int = 20,
    ):
        # Store configuration for loop intervals
        
    async def start(self) -> None:
        # Launch three concurrent asyncio loops using asyncio.gather():
        # 1. _deadline_check_loop() - every 10 seconds
        # 2. _fallback_attempt_loop() - every 15 seconds
        # 3. _retry_check_loop() - every 20 seconds
        
    async def _deadline_check_loop(self) -> None:
        # Every 10 seconds:
        # - Call processor.check_deadlines()
        # - This finds messages past ack_deadline_at
        # - Auto-escalates them to fallback
        
    async def _fallback_attempt_loop(self) -> None:
        # Every 15 seconds:
        # - Query messages in ESCALATION_PENDING state
        # - For each: attempt fallback delivery
        # - If success → FALLBACK_DELIVERED
        # - If failure → retry later or DEAD_LETTER
        
    async def _retry_check_loop(self) -> None:
        # Every 20 seconds:
        # - Query messages with next_retry_at <= now
        # - Based on current_state:
        #   - If SENDING: retry primary channel
        #   - If FALLBACK_SENDING: retry fallback channel
        # - Schedule next retry if fails again
```

**Why Separate Loops**: Different intervals for different tasks. Deadline checking urgent (10s), fallback attempts less urgent (15s), retries least urgent (20s).

---

### **app/channels/base.py** - Channel Interface
**Purpose**: Abstract interface all delivery channels implement

```python
class Channel(ABC):
    @abstractmethod
    async def send(self, message: MessageRecord) -> ChannelResult:
        """Send message via this channel.
        
        Returns:
            ChannelResult with success=True/False and optional external_id
        """
        pass

@dataclass
class ChannelResult:
    success: bool
    external_id: Optional[str] = None  # ID from channel (e.g., Telegram message_id)
    error: Optional[str] = None  # Error message if failed
```

---

### **app/channels/telegram.py** - Telegram Bot Integration
**Purpose**: Send messages via Telegram Bot API

```python
class TelegramChannel(Channel):
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.api_url = "https://api.telegram.org/bot{token}"
        
    async def send(self, message: MessageRecord) -> ChannelResult:
        # Parse recipient as Telegram chat_id
        # Call Telegram Bot API: POST /sendMessage
        # Return ChannelResult with message_id from response
        # On network error: ChannelResult(success=False, error="...")
```

---

### **app/channels/registry.py** - Channel Factory
**Purpose**: Create and manage channel instances

```python
class ChannelRegistry:
    def __init__(self):
        self.channels = {}  # name → Channel instance
        
    def register(self, name: str, channel: Channel) -> None:
        self.channels[name] = channel
        
    def get(self, name: str) -> Channel:
        return self.channels.get(name)

def create_registry(telegram_token: str) -> ChannelRegistry:
    registry = ChannelRegistry()
    registry.register("telegram", TelegramChannel(telegram_token))
    return registry
```

---

### **app/schemas/message.py** - Request/Response Schemas
**Purpose**: Pydantic validation for HTTP payloads

```python
class CreateMessageRequest(BaseModel):
    sender: str
    recipient: str  # Telegram chat_id or email
    content: str
    priority: Optional[str] = "NORMAL"
    idempotency_key: Optional[str]  # For deduplication
    metadata: Optional[dict] = {}

class MessageResponse(BaseModel):
    id: str
    current_state: str  # MessageState.value
    created_at: datetime
    external_message_id: Optional[str]
    retry_count: int
```

---

### **app/api/routes/health.py** - Health Checks & Monitoring
**Purpose**: Operational endpoints for liveness, readiness, metrics

**Endpoints**:

1. **GET /health** → `{"status": "alive"}`
   - Liveness probe: Is the app running?
   - No dependency checks

2. **GET /ready** → `{"status": "ready"}` or 503
   - Readiness probe: Can it handle traffic?
   - Checks: PostgreSQL connection, Redis connection

3. **GET /metrics** → Metrics JSON
   ```json
   {
     "total_messages": 1234,
     "messages_by_state": {
       "pending": 10,
       "acknowledged": 500,
       "dead_letter": 5
     },
     "delivery_success_rate_24h": 0.987,
     "avg_time_to_acknowledge_seconds": 2.5,
     "latencies": {...}
   }
   ```

4. **GET /health/detailed** → Detailed health status
   ```json
   {
     "is_healthy": true,
     "messages": {...},
     "warnings": [],
     "dependencies": {
       "database": "connected",
       "redis": "connected"
     }
   }
   ```

---

### **app/api/routes/messages.py** - Message Management API
**Purpose**: HTTP endpoints for message submission and acknowledgement

**Endpoints**:

1. **POST /messages** - Create and queue new message
   - Request: CreateMessageRequest
   - Response: MessageResponse (with id)

2. **POST /messages/{id}/acknowledge** - External ACK webhook
   - Called by channel system when message is acknowledged
   - Transitions message → ACKNOWLEDGED state

---

### **app/api/routes/admin.py** - Debugging Endpoints
**Purpose**: Operational debugging (not for production frontend)

**Endpoints**:

1. **GET /admin/messages?state=...&limit=20** - List messages
   - Optional filter by MessageState
   - Returns array of MessageRecord summaries

2. **GET /admin/messages/{id}/events** - Event audit trail
   - Returns array of MessageEvent for given message
   - Shows all state changes and actions

3. **GET /admin/stats** - Message state distribution
   ```json
   {
     "pending": 5,
     "queued": 2,
     "sent_to_channel": 10,
     "escalation_pending": 3,
     "acknowledged": 500,
     "dead_letter": 2
   }
   ```

4. **POST /admin/messages/{id}/escalate** - Manual escalation
   - Manually move message to ESCALATION_PENDING
   - Triggers fallback attempts

5. **POST /admin/messages/{id}/retry-fallback?channel=telegram** - Manual retry
   - Manually attempt fallback delivery via specified channel

---

### **app/observability/metrics.py** - Health & Metrics Collection
**Purpose**: Collect operational metrics and health status

```python
class MessageMetrics:
    total_messages: int
    messages_by_state: dict  # state → count
    messages_acknowledged: int
    messages_failed: int
    delivery_success_rate_24h: float  # % of messages delivered in last 24h
    avg_time_to_acknowledge_seconds: Optional[float]

class MetricsCollector:
    async def collect(self) -> MessageMetrics:
        # Execute 6+ SQL queries:
        # 1. COUNT all messages
        # 2. COUNT messages by state
        # 3. COUNT messages created in last 24h
        # 4. COUNT messages in terminal states (success/failure)
        # 5. CALCULATE 24h success rate
        # 6. CALCULATE avg acknowledgement latency (in Python)
        # Return aggregated MessageMetrics
        
class SystemHealth:
    is_healthy: bool  # False if dead_letter_count > 100
    warnings: List[str]  # Warning conditions
    
class HealthChecker:
    async def check_health(self) -> SystemHealth:
        metrics = collector.collect()
        warnings = []
        is_healthy = metrics.messages_failed < 100
        if metrics.escalation_pending > 500:
            warnings.append("High escalation_pending count")
        return SystemHealth(is_healthy=is_healthy, warnings=warnings)
```

---

## How Each Feature Works

### Feature 1: Message Creation & Queuing
**Flow**:
1. HTTP POST `/messages` with CreateMessageRequest
2. MessageService.create() → MessageRecord in PENDING state
3. MessageProcessor.process_new_message() → PENDING → QUEUED
4. MessageProcessor.attempt_delivery() → QUEUED → SENDING
5. Channel.send() called (Telegram Bot API, etc.)
6. On success → SENT_TO_CHANNEL + ack_deadline_at armed
7. Wait for external ACK webhook

**Files Involved**: messages.py, message_service.py, processor.py, channels/

---

### Feature 2: Automatic Deadline-Based Escalation
**Flow**:
1. MessageScheduler._deadline_check_loop() runs every 10 seconds
2. Queries: `SELECT * FROM messages WHERE current_state='sent_to_channel' AND ack_deadline_at < now`
3. For each overdue message: processor._escalate_message()
4. Transition: SENT_TO_CHANNEL → ESCALATION_PENDING
5. Record ESCALATION_TRIGGERED event with fallback channels

**Files Involved**: scheduler.py, processor.py, repository.py

---

### Feature 3: Fallback Channel Attempts
**Flow**:
1. MessageScheduler._fallback_attempt_loop() runs every 15 seconds
2. Queries: `SELECT * FROM messages WHERE current_state='escalation_pending'`
3. For each: processor.attempt_fallback(message_id, channel_name)
4. Transition: ESCALATION_PENDING → FALLBACK_SENDING
5. Call alternate channel (e.g., Email if Telegram failed)
6. On success → FALLBACK_DELIVERED (terminal)
7. On failure + should_retry → back to ESCALATION_PENDING with next_retry_at set
8. On failure + max_retries exceeded → DEAD_LETTER (terminal)

**Files Involved**: scheduler.py, processor.py, channels/

---

### Feature 4: Exponential Backoff Retries
**Flow**:
1. Primary delivery fails → set next_retry_at = now + 5s, increment retry_count
2. MessageScheduler._retry_check_loop() every 20 seconds
3. Queries: `SELECT * FROM messages WHERE next_retry_at <= now`
4. Retry based on current_state (SENDING vs FALLBACK_SENDING)
5. If fails again: next_retry_at = now + 10s, next_retry_at = now + 20s, etc.
6. Cap delay at max_backoff_seconds (300s primary, 600s fallback)
7. Add ±10% jitter to prevent thundering herd

**Files Involved**: retry_policy.py, scheduler.py, processor.py

---

### Feature 5: Structured Observability Logging
**Flow**:
1. configure_logging() called at app startup
2. Every log entry includes: timestamp, level, message, context
3. LogContextMiddleware binds request_id, path, method to context
4. All logs in that request include request_id automatically
5. Logs output as JSON for machine parsing
6. Production: ship JSON logs to ELK, DataDog, Splunk, etc.

**Files Involved**: logging_config.py, main.py

---

### Feature 6: Health Checks & Metrics
**Flow**:
1. GET /ready → Checks DB + Redis connectivity
2. GET /health → Returns liveness status
3. GET /metrics → MetricsCollector.collect()
   - Counts messages by state
   - Calculates 24h success rate
   - Computes average acknowledgement latency
4. GET /health/detailed → Detailed status with warnings

**Files Involved**: health.py, metrics.py

---

## Database Migrations

### Migration 1: Initial Schema (20260819_000001)
**What**: Creates Message and MessageEvent tables
**Columns**: All message tracking fields, indexes on sender/recipient/state
**Why**: Foundation for message persistence

### Migration 2: Retry Scheduling (20260809_000002)
**What**: Adds next_retry_at column to Message table
**Column**: `next_retry_at DateTime(timezone=True) nullable`
**Index**: `ix_messages_next_retry_at` for efficient query
**Why**: Needed for retry loop to find messages ready to retry

---

## Testing Strategy

### Test Categories (27 tests total)

1. **Domain Logic Tests** (5 tests)
   - State machine transitions validate rules
   - Message state changes work correctly

2. **Message Processing Tests** (10 tests)
   - Happy path: PENDING → QUEUED → SENDING → SENT_TO_CHANNEL → ACKNOWLEDGED
   - Deadline checking escalates overdue messages
   - Fallback attempts on primary failure
   - Retry scheduling on transient failures
   - Event recording accuracy

3. **Scheduler Tests** (2 tests)
   - Deadline checking runs periodically
   - Fallback attempts run periodically

4. **Admin Endpoint Tests** (4 tests)
   - List messages endpoint
   - Get message events endpoint
   - Get stats endpoint
   - Manual escalation and retry

5. **Metrics Tests** (4 tests)
   - Message counting by state
   - 24h success rate calculation
   - Acknowledgement latency calculation
   - Health status detection

6. **API Contract Tests** (2 tests)
   - POST /messages creates message
   - POST /acknowledge updates state

### Test Database
- Uses SQLite with async support (aiosqlite)
- Auto-created on test startup
- Auto-rolled back after each test (no state leakage)
- All queries use async/await just like production

### Running Tests
```bash
pytest -q                    # Run all tests, quiet output
pytest tests/test_scheduler.py  # Run specific test file
pytest -v                    # Verbose output with test names
```

---

## Git Commit Strategy

Each commit represents a logical feature or component:

### Commit 1: Project Setup
**Message**: `Initial project setup with FastAPI, SQLAlchemy, and Docker`
**Files**:
- pyproject.toml
- requirements.txt, requirements-dev.txt
- Dockerfile, docker-compose.yml
- .env.example, .gitignore
- app/__init__.py

### Commit 2: Domain Models & State Machine
**Message**: `Add domain models: Message, MessageState, StateMachine`
**Files**:
- app/domain/message.py
- app/domain/message_state.py
- app/domain/message_event.py
- app/domain/state_machine.py
- Validates state transitions, audit trail

### Commit 3: Database & ORM
**Message**: `Set up SQLAlchemy async ORM and database models`
**Files**:
- app/infrastructure/database.py
- app/infrastructure/models.py
- app/infrastructure/redis_client.py
- app/config.py
- Tests: test_message_state.py

### Commit 4: Retry Policy & Backoff
**Message**: `Implement exponential backoff retry policy`
**Files**:
- app/domain/retry_policy.py
- RetryPolicy: max_retries, backoff calculation, jitter
- PRIMARY and FALLBACK policies with different settings

### Commit 5: Repository & Service Layer
**Message**: `Add data access layer and message service`
**Files**:
- app/repositories/message_repository.py
- app/services/message_service.py
- CRUD operations + specialized queries (list_due_for_retry, etc.)

### Commit 6: Core Processor Logic
**Message**: `Implement MessageProcessor with state transitions`
**Files**:
- app/workers/processor.py
- process_new_message(), attempt_delivery(), acknowledge_message()
- _escalate_message(), attempt_fallback()
- Tests: test_message_processor.py (16 tests)

### Commit 7: Channel System
**Message**: `Add Telegram delivery channel and channel registry`
**Files**:
- app/channels/base.py
- app/channels/telegram.py
- app/channels/registry.py
- Enables multiple delivery backends; test doubles are defined in the test suite

### Commit 8: HTTP API Routes
**Message**: `Add FastAPI routes for messages and health`
**Files**:
- app/api/routes/messages.py
- app/api/routes/health.py
- app/schemas/message.py
- app/schemas/message_event.py
- POST /messages, POST /acknowledge, GET /health, GET /ready

### Commit 9: Database Migrations
**Message**: `Set up Alembic migrations: initial schema`
**Files**:
- alembic.ini
- migrations/env.py
- migrations/script.py.mako
- migrations/versions/20260819_000001_create_messages_and_events.py
- Creates Message and MessageEvent tables with indexes

### Commit 10: Structured Logging
**Message**: `Add structured JSON logging with request context`
**Files**:
- app/logging_config.py
- LogContextMiddleware for request tracing
- structlog configuration with JSON output
- Tests: Embedded in test setup

### Commit 11: Background Scheduler
**Message**: `Implement MessageScheduler with three concurrent loops`
**Files**:
- app/workers/scheduler.py
- Deadline checking loop (10s interval)
- Fallback attempt loop (15s interval)
- Retry check loop (20s interval)
- Tests: test_scheduler.py (2 tests)

### Commit 12: Admin Debugging Endpoints
**Message**: `Add admin endpoints for operations and debugging`
**Files**:
- app/api/routes/admin.py
- GET /admin/messages (list with filters)
- GET /admin/messages/{id}/events (audit trail)
- GET /admin/stats (state distribution)
- POST /admin/messages/{id}/escalate (manual action)
- POST /admin/messages/{id}/retry-fallback (manual retry)
- Tests: test_admin.py (4 tests)

### Commit 13: Retry Scheduling Column
**Message**: `Add next_retry_at column for retry scheduling`
**Files**:
- migrations/versions/20260809_000002_add_next_retry_at.py
- Alembic migration adding DateTime column with index
- Enables scheduler to find messages ready for retry

### Commit 14: Observability & Metrics
**Message**: `Add health checks, metrics collection, and monitoring`
**Files**:
- app/observability/metrics.py
- MetricsCollector: message counts, success rates, latency
- HealthChecker: health status with warnings
- Routes: GET /metrics, GET /health/detailed
- Tests: test_metrics.py (4 tests)

### Commit 15: App Bootstrap & Lifespan
**Message**: `Integrate all components into FastAPI app with lifecycle management`
**Files**:
- app/main.py
- create_app() function
- Lifespan context manager (startup/shutdown)
- Middleware registration, route inclusion
- MessageScheduler integration

### Commit 16: Complete Test Suite
**Message**: `Add comprehensive test coverage (27 total tests)`
**Files**:
- tests/test_domain_state_machine.py
- tests/test_message_events.py
- tests/test_message_state.py
- tests/test_message_api_contract.py
- All tests passing with pytest-asyncio

---

## Summary: What Was Built

### Core Components (9)
1. **Domain Models** - MessageRecord, MessageState, MessageEvent
2. **State Machine** - Enforces valid transitions
3. **Database Layer** - SQLAlchemy async ORM
4. **Retry Policy** - Exponential backoff with jitter
5. **Message Processor** - Core business logic
6. **Delivery Channels** - Telegram Bot API and extensible registry
7. **Background Scheduler** - Periodic task runner
8. **HTTP API** - Message submission, acknowledgement, health
9. **Observability** - Structured logging, metrics, health checks

### Features (6)
1. ✅ Message creation & queuing
2. ✅ Primary channel delivery attempts
3. ✅ Automatic deadline-based escalation to fallback
4. ✅ Exponential backoff retry logic
5. ✅ Structured JSON observability logging
6. ✅ Health checks & metrics endpoints

### Not Yet Implemented (for remaining 50%)
- Additional delivery channels beyond Telegram
- Redis Streams for distributed work queues
- Circuit breaker pattern for fault tolerance
- Cascading fallback logic (try SMS, then Email, etc.)
- Request authentication/authorization
- Rate limiting per sender
- TTL-based message cleanup
- Prometheus metrics export
- Production deployment scripts

---

## Actual Local Git History

The repository was initialized locally on `main` with **62 focused commits**. Each commit adds one real project file or a closely scoped foundation file, and each commit message explains the responsibility introduced by that file. This is intentionally more granular than the original 16-stage feature plan so the history can be reviewed and pushed incrementally.

The remote is configured as:

`https://github.com/betelhem16/Resilient-Hybrid-Messaging-Gateway.git`

The complete local history has been pushed to the public `main` branch. The test suite currently reports 27 passing tests.
