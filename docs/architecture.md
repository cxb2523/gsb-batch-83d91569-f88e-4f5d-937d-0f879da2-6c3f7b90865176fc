# Olostep SDK Architecture

## Overview

The Olostep SDK is a Python package that provides both synchronous and asynchronous clients for interacting with the Olostep web scraping API. The architecture follows a layered design pattern with clear separation of concerns between transport, validation, calling logic, and user-facing interfaces.

## Architecture Layers

The SDK is organized into four main architectural layers:

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Layer                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐ │
│  │   Clients   │ │    Menu     │ │    Client State         │ │
│  │AsyncOlostep │ │   Classes   │ │   (stateful objects)    │ │
│  │   Olostep   │ │(scrapes,    │ │(ScrapeResult, Batch,    │ │
│  │             │ │ batches,    │ │ Crawl, Sitemap, etc.)   │ │
│  │             │ │ crawls,     │ │                         │ │
│  │             │ │ maps, etc.) │ │                         │ │
│  └─────────────┘ └─────────────┘ └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                    Backend Layer                            │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐ │
│  │   Caller    │ │  Transport  │ │     Validation          │ │
│  │ (endpoint   │ │ (HTTP layer)│ │   (Pydantic models)     │ │
│  │  logic)     │ │             │ │                         │ │
│  └─────────────┘ └─────────────┘ └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

- Transport is responsible to acquire responses for requests to the API
  - It raises errors if no answer can be received for whatever reason
  - If it receives an answer (even if it's an error-answer) it passes it through to it's caller
- Caller is responsible for calling endpoints as defined by EndpointContracts
  - It prepares and validates the to-be-sent request
  - Uses the provided Transport to call the API
  - Checks the Response for errors and validates it against a response model
- Client ties Frontend, Transport and Caller together
  - provides the top level UI of the SDK
  - Has a sync facade for old-school styles
  - Holds state (Retrieve ID's, Client Objects)

## Layer Descriptions

### 1. Backend Layer

The backend layer handles all low-level API communication, validation, and transport concerns.

#### Transport (`olostep/backend/transport.py`)

**Purpose**: Manages HTTP communication with the Olostep API. Raises error (only) if no response can be acquired.

**Key Components**:

- `HttpxTransport`: Async HTTP client implementation using httpx
- Implements the `Transport` protocol defined in `transport_protocol.py`
- Handles connection pooling, timeouts, and HTTP/2 support
- Provides optional I/O logging for debugging

**Responsibilities**:

- Implements the Transport Protocol (`olostep/backend/transport_protocol.py`)
- HTTP request/response handling
- Connection management and pooling
- Error handling for network-level issues
- Request/response logging (when enabled)

**Key Features**:

- HTTP/2 support for better multiplexing
- Configurable connection limits (100 keepalive, 200 max connections)
- Comprehensive error handling for connection issues
- Optional detailed I/O logging with request IDs
- Can be substituted for FakeTransport for testing so no API Key is needed.

#### Validation (`olostep/models/`)

**Purpose**: Provides comprehensive Pydantic models for API request/response validation.

**Key Components**:

- **Request Models** (`olostep/models/request.py`): `ScrapeUrlRequest`, `BatchStartRequest`, `CrawlStartRequest`, `MapCreateRequest`, `RetrieveGetRequest`, `AnswersRequest`, etc.
- **Response Models** (`olostep/models/response.py`): `CreateScrapeResponse`, `BatchCreateResponse`, `CrawlInfoResponse`, `MapResponse`, `RetrieveResponse`, `AnswersResponse`, etc.
- **Enums and Types** (`olostep/models/request.py`): `Country`, `Format`, `RetrieveFormat`, `ActionType`, `WaitAction`, `ClickAction`, `FillInputAction`, `ScrollAction`, etc.

**Responsibilities**:

- Input validation and serialization
- Response parsing and validation
- Type safety and data integrity
- API contract enforcement

**Key Features**:

- Comprehensive validation for all API endpoints
- Custom serialization logic for complex fields
- Support for optional fields and default values
- Detailed field validation with custom validators

#### API Endpoints (`olostep/backend/api_endpoints.py`)

**Purpose**: Central registry of all API endpoint definitions and contracts.

**Key Components**:

- `EndpointContract`: Dataclass defining endpoint metadata
- `CONTRACTS`: Registry mapping endpoint keys to contracts
- Individual endpoint definitions for all API operations

**Responsibilities**:

- Single source of truth for API endpoint definitions
- URL pattern management and parameter extraction
- Request/response model associations
- Documentation and examples

**Endpoint Categories**:

- **Scrapes**: `SCRAPE_URL` (key: `("scrape", "url")`), `SCRAPE_GET` (key: `("scrape", "get")`)
- **Batches**: `BATCH_START` (key: `("batch", "start")`), `BATCH_INFO` (key: `("batch", "info")`), `BATCH_ITEMS` (key: `("batch", "items")`)
- **Crawls**: `CRAWL_START` (key: `("crawl", "start")`), `CRAWL_INFO` (key: `("crawl", "info")`), `CRAWL_PAGES` (key: `("crawl", "pages")`)
- **Maps**: `MAP_CREATE` (key: `("map", "create")`)
- **Retrievals**: `RETRIEVE_GET` (key: `("retrieve", "get")`)
- **Answers**: `ANSWERS_CREATE` (key: `("answers", "create")`), `ANSWERS_GET` (key: `("answers", "get")`)

#### Caller (`olostep/backend/caller.py`)

**Purpose**: Orchestrates API calls using transport and validation layers.

**Key Components**:

- `EndpointCaller`: Main orchestrator class
- Error handling and response parsing
- Parameter splitting (path vs query parameters)

**Responsibilities**:

- Endpoint invocation using contracts
- Request/response validation
- Error handling and transformation
- JSON parsing and model instantiation

**Key Features**:

- Automatic parameter splitting between path and query
- Comprehensive error handling with specific exception types
- Pydantic model validation for requests and responses
- Raw JSON parsing with fallback handling

### 2. Frontend Layer

The frontend layer provides user-friendly interfaces and stateful objects for API interactions.

#### Clients (`olostep/clients/`)

**Purpose**: Entry points for SDK usage, providing both sync and async interfaces.

##### Async Client (`olostep/clients/async_client.py`)

**Key Components**:

- `AsyncOlostep`: Main async client class (default)
- Context manager support for resource cleanup
- Namespace exposure for different API operations

**Features**:

- Async/await support
- Automatic resource management
- Direct namespace access (`client.scrapes`, `client.batches`, etc.)
- Configurable transport injection for testing

##### Sync Client (`olostep/clients/sync_client.py`)

**Key Components**:

- `Olostep`: Synchronous facade over async client
- `_SyncProxy`: Dynamic proxy for method calls
- Event loop management for sync/async bridging

**Features**:

- Synchronous API that mirrors async client
- Automatic event loop detection and management
- Thread-based execution for nested event loops
- Same namespace structure as async client

#### Menu Classes (`olostep/frontend/`)

**Purpose**: Provides namespace-based API access through menu classes that expose endpoint methods.

**Key Components**:

- `ScrapeMenu`: Methods for scrape operations (`create()`, `get()`)
- `BatchMenu`: Methods for batch operations (`create()`, `info()`, `items()`)
- `CrawlMenu`: Methods for crawl operations (`create()`, `info()`, `pages()`)
- `SitemapMenu`: Methods for sitemap/map operations (`create()`)
- `RetrieveMenu`: Methods for retrieve operations (`get()`)
- `AnswersMenu`: Methods for answers operations (`create()`, `get()`)

**Responsibilities**:

- Namespace organization (scrapes, batches, crawls, maps, answers, retrieve)
- Method exposure and parameter forwarding
- Response object creation and state management
- Integration with EndpointCaller for API requests

**API Methods**:

- **scrapes**: `create()`, `get()`
- **batches**: `create()`, `info()`, `items()`
- **crawls**: `create()`, `info()`, `pages()`
- **maps**: `create()`
- **retrieve**: `get()`
- **answers**: `create()`, `get()`

#### Client State (`olostep/frontend/client_state.py`)

**Purpose**: Provides stateful, ergonomic objects for API responses.

**Key Components**:

- **Result Objects**: `ScrapeResult`, `AnswersResult`, `Batch`, `Crawl`, `Sitemap`
- **Info Objects**: `BatchInfo`, `CrawlInfo`
- **Item Objects**: `BatchItemResult`, `CrawlPage`
- **Utility Objects**: `RetrievableID`

**Responsibilities**:

- Stateful object management (IDs, cursors, pagination)
- Ergonomic follow-up operations (info, items, next, retrieve)
- Friendly property access and string representations
- Pagination and cursor management

**Key Features**:

- **Stateful Operations**: Objects remember their IDs and can perform follow-up operations
- **Pagination Support**: Built-in cursor management and `next()` methods
- **Ergonomic Access**: Properties for common data access patterns
- **Rich Representations**: Informative `__repr__` and `__str__` methods

## Data Flow

```
User Code
    ↓
Client (AsyncOlostep / Olostep)
    ↓
Menu Classes (client.scrapes, client.batches, client.crawls, etc.)
    ↓
Client State Objects (ScrapeResult, Batch, Crawl, Sitemap, etc.)
    ↓
Endpoint Caller
    ↓
Transport (HTTP)
    ↓
Olostep API
```

## Key Design Principles

### 1. Separation of Concerns

- **Transport**: Pure HTTP communication
- **Validation**: Data validation and serialization
- **Caller**: Orchestration and error handling
- **Frontend**: User experience and state management

### 2. Type Safety

- Comprehensive Pydantic models for all API interactions
- Type hints throughout the codebase
- Menu classes provide type-safe method signatures

### 3. Async-First Design

- Async client as the primary implementation
- Sync client as a thin facade
- Proper resource management with context managers

### 4. Stateful Objects

- Rich objects that remember their state
- Ergonomic follow-up operations
- Built-in pagination and cursor management

### 5. Testability

- Protocol-based transport for easy mocking
- Dependency injection throughout
- Clear separation between layers

## Error Handling

The SDK provides comprehensive error handling with a hierarchical exception structure but you can catch all errors via `Olostep_BaseError`.
For detailed error handling information, see [Error Handling](error_handling.md).

## Configuration

The SDK supports various configuration options:

- **API Key**: Environment variable or explicit parameter
- **Base URL**: Configurable API endpoint
- **Transport**: Custom transport implementations
- **I/O Logging**: Optional detailed request/response logging
- **Timeouts**: Configurable connection and request timeouts

## Usage Patterns

### Async Usage

```python
async with AsyncOlostep(api_key="...") as client:
    result = await client.scrapes.create(url_to_scrape="https://example.com")
    print(result.html_content)
```

### Sync Usage

```python
client = Olostep(api_key="...")
result = client.scrapes.create(url_to_scrape="https://example.com")
print(result.html_content)
```

### Stateful Operations

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Create a batch
batch = client.batches.create(items=[...])

# Check status
info = batch.info()
print(f"Progress: {info.completed_urls}/{info.total_urls}")

# Get items with pagination
for item in batch.items():
    content = item.retrieve(formats=["html"])
    print(content.html_content)
```

This architecture provides a robust, type-safe, and user-friendly SDK for interacting with the Olostep API while maintaining clear separation of concerns and excellent testability.
