# Installation & Setup

## Prerequisites

- **Docker & Docker Compose**: Required for running the full stack.
- **Python 3.11+**: Required for local development.
- **uv**: Python package manager (used by every component).

## Quick Start (Docker)

The easiest way to run DAK is using Docker Compose.

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd dak
    ```

2.  **Configure Environment**:
    ```bash
    cat env.example.d/*.env > .env
    # Edit .env to add your LLM API key (Google Gemini, etc.)
    ```

    The template is split into one file per section under `env.example.d/`
    (`10-llm.env`, `20-agent.env`, ...); the command concatenates them in
    name order. To document a new feature's variables, add one file there
    instead of editing the existing ones: name it with an unused two-digit
    number for its place in the order (`NN-<section>.env`), and end it with
    a blank line.

3.  **Start Services**:
    ```bash
    export COMPOSE_FILE=$(./scripts/compose_files.sh)   # the features' agent variables are in compose/base/
    docker compose up --build
    ```

4.  **Access the Web UI (BFF)**:
    Open `http://localhost:8002` in your browser.

## Local Development

### Agent

```bash
cd agent
uv sync
export GOOGLE_API_KEY=your_key
export MCP_SERVER_URL=http://localhost:8001/mcp
uv run adk web --host 0.0.0.0
```

### MCP Server

```bash
cd mcp-server
uv sync
uv run python main.py
```

### BFF UI

```bash
cd bff
uv sync
AGENT_URL=http://localhost:8000 uv run uvicorn main:app --reload --port 8002
```

### CLI

```bash
cd cli
uv sync
uv run dak-cli --help
```

## Running Tests

```bash
# Unit tests, per component
cd agent && uv run pytest        # also: cli, mcp-server, bff

# Integration tests (full stack, fake LLM, no API keys)
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait
(cd tests/integration && uv run pytest)
```
