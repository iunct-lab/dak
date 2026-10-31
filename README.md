# Decentralized Agent Kit (DAK)

An intelligent agent framework with LLM integration, Model Context Protocol (MCP) tool support, and Agent-to-Agent (A2A) communication capabilities.

## How this repository works

This repository is a read-only copy of a private development repository: its `main` is that repository's `main` tree, sent here by a sync as one commit at a time, without the private history. Nothing is developed here.

- **Issue and pull request numbers** (`#N`) in files and commit messages refer to the private tracker and cannot be opened here.
- **Pull requests are not accepted.** A pull request opened here is answered with this policy and closed automatically.
- **Requests and bug reports** go to an Issue of the kind *Request* (the only Issue form here). A request is read and taken into the private backlog; the Issue is answered there and closed with the outcome.
- **Vulnerabilities** are reported privately through a GitHub Security Advisory: https://github.com/iunct-lab/dak/security/advisories/new (see `SECURITY.md`). Not in a public Issue or Discussion.
- **Questions and discussion** go to Discussions: https://github.com/iunct-lab/dak/discussions

## Features

- **Multi-LLM Support**: Gemini, OpenAI, Anthropic, Amazon Bedrock, Local LLM (Ollama / llama.cpp) via LiteLLM
- **MCP Protocol**: Dynamic tool discovery and execution via Model Context Protocol (multiple servers supported)
- **Agent Skills**: Extend the agent with `SKILL.md`-based skills loaded from one or more directories
- **A2A Protocol**: Agent-to-Agent communication for collaborative workflows
- **Web UI (BFF)**: Lightweight HTMX-based chat interface
- **CLI Tool**: Command-line interface for direct agent interaction
- **Persistent State**: Conversation history with PostgreSQL
- **Enforcer Mode**: Strict ReAct pattern with "Ulysses Pact" for reliability
- **Observability**: OpenTelemetry tracing with LangFuse integration

### Experimental Features

- **AP2 Payment Protocol**: Agent-to-Agent payments with a Solana wallet (mock mode by default). See [Solana Integration](docs/experimental/solana_integration.md).
- **Dynamic Mode Switching**: The agent refreshes its instruction and toolset when the context window fills up or when it decides to switch focus.

## Quick Start with Docker

```bash
# 1. Clone and configure
git clone https://github.com/iunct-lab/dak.git
cd dak
cat env.example.d/*.env > .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)" >> .env   # required

# 2. Add your LLM API key to .env
echo "GOOGLE_API_KEY=your_key_here" >> .env

# 3. Start all services
export COMPOSE_FILE=$(./scripts/compose_files.sh)
docker compose up --build -d

# 4. Access the application
# Web UI (BFF): http://localhost:8002
# Agent API:    http://localhost:8000
# MCP Server:   http://localhost:8001 (this machine only, like PostgreSQL)
```

Step 3 goes through `scripts/compose_files.sh`: the variables each feature passes to
the agent (Bedrock, web search) are in `compose/base/<feature>.yml`, so a value you
export in the shell reaches the agent only this way. Values in `.env` reach it with a
plain `docker compose` too.

For a guided walkthrough that boots the stack and verifies **each feature**
(basic chat, skill discovery + MCP tools, Enforcer mode, AP2 mock payment) from
both the **UI and the CLI** — including a no-API-key local-LLM path — see
**[docs/quickstart.md](docs/quickstart.md)**.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  BFF (UI)   │────▶│  DAK Agent   │────▶│ MCP Server  │
│ FastAPI +   │     │ (google-adk) │     │  (FastMCP)  │
│ HTMX        │     │              │     │             │
│             │     │ • LLM Client │     │ • deep_think│
│  CLI ───────┼────▶│ • Skills     │     │ • file tools│
│             │     │ • MCP Client │     │ • run_cmd   │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │ PostgreSQL  │
                    │ (Sessions)  │
                    └─────────────┘
```

## Directory Structure

- **`agent/`**: Python agent service (google-adk based `AdaptiveAgent`, skills, wallet)
- **`mcp-server/`**: Model Context Protocol server for tool execution
- **`bff/`**: HTMX-based web UI (Backend For Frontend pattern)
- **`cli/`**: Command-line tool for agent interaction
- **`tests/integration/`**: Docker-based integration test suite (no API keys required)
- **`docs/`**: Documentation

## Documentation

### Getting Started
- [Docker Deployment Guide](docs/getting-started/docker_deployment.md)
- [Installation & Setup](docs/getting-started/installation.md)
- [Web Search (Tavily)](docs/getting-started/web-search.md): optional `web_search` skill, on only with your own `TAVILY_API_KEY`

### Guides
- [MCP Integration Guide](docs/guides/mcp_integration.md) - Tool development and usage
- [CLI Usage Guide](docs/guides/cli_usage.md)
- [Enforcer Mode Guide](docs/enforcer_mode.md)
- [Agent Skills Guide](docs/agent_skills.md): Extend the agent with new capabilities
- [Built-in Tools Reference](docs/built_in_tools.md): `list_skills`, `enable_skill`, `switch_mode`, etc.

### Architecture
- [System Overview](docs/architecture/overview.md)
- [BFF Architecture](docs/bff_architecture.md)
- [Chat History Specification](docs/architecture/chat_history.md)
- [Dynamic Mode Switching](docs/dynamic_mode_switching.md)

## Using the CLI

```bash
cd cli
uv sync

# Single query
uv run dak-cli run "What is consciousness?"

# With MCP tool
uv run dak-cli run "Use deep_think to analyze AI ethics"

# Interactive chat
uv run dak-cli chat

# Pending approvals of any client's session (e.g. one started in the web UI), and answering one
uv run dak-cli approvals --session <session-id> --user <user-id>
uv run dak-cli approve <id> --session <session-id> --user <user-id>   # --always, or --reject --reason "..."
```

## Adding MCP Servers

The agent can connect to multiple MCP servers. Add one file per server to
`agent/agent_config.d/mcp_servers/` (A2A peers likewise go in
`agent/agent_config.d/a2a_peers/`), e.g. `agent/agent_config.d/mcp_servers/my-extra-mcp.yaml`:

```yaml
name: "my-extra-mcp"
url: "http://my-extra-mcp:8000/mcp"
type: "http"          # "http" (streamable HTTP) or "sse"
```

The same `name` in two places stops the agent at startup with both file names.
`agent/agent_config.yaml` keeps the tool permission rules (`permissions:`).

Skills can target a specific server with a `mcp_server: <name>` field in their
`SKILL.md` frontmatter; tools without a skill use the default server
(`MCP_SERVER_URL`). When running in Docker, make sure the extra server is
reachable from the `agent` container (add it as one file in `compose/base/`,
which `scripts/compose_files.sh` adds to the stack).

## Development

After cloning, enable the git hooks (secret scanning with gitleaks before each commit and push; this repository is public):

```bash
scripts/setup/install_hooks.sh
```

Before a push or PR, `scripts/security/check.sh` checks the hooks, scans the changes, and lists what to review by eye (`docs/security/review-checklist.md`).

### Local Setup (without Docker)

#### Agent Service

```bash
cd agent
uv sync
export GOOGLE_API_KEY=your_key
export MCP_SERVER_URL=http://localhost:8001/mcp
uv run adk web --host 0.0.0.0
```

#### MCP Server

```bash
cd mcp-server
uv sync
uv run python main.py
```

#### BFF UI

```bash
cd bff
uv sync
AGENT_URL=http://localhost:8000 uv run uvicorn main:app --reload --port 8002
```

### Running Tests

Each component has its own unit test suite (no API keys or network required):

```bash
cd agent && uv run pytest        # also: cli, mcp-server, bff
```

Integration tests run the full stack with a deterministic fake LLM
(no API keys required):

```bash
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait
(cd tests/integration && uv run pytest)
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose down -v
```

CI runs both suites on every pull request (`.github/workflows/ci.yml`).

#### Real-LLM smoke tests (local model, no API keys)

The fake-LLM suite verifies the pipeline deterministically but not real model
behavior (prompt quality, tool selection). To check that end-to-end against a
real model **without spending API credits**, run the smoke suite against a local
[Ollama](https://ollama.com) model. On macOS the agents connect to the host's
Metal-accelerated Ollama (a containerized Ollama gets no GPU under colima):

```bash
ollama pull llama3.1:8b         # ~4.9GB, runs on 16GB RAM
./scripts/smoke_local_llm.sh    # boots the stack + runs the smoke tests
```

`llama3.1:8b` is the default because it reliably emits **structured** tool calls
even when the agent exposes many tools at once, and it has no "thinking" phase so
turns stay under the 120s per-turn timeout. Model choice here is about
tool-calling reliability, not size or recency:

| Model | Result |
|-------|--------|
| `llama3.1:8b` | ✅ all 4 tests pass (~2m43s) — **default** |
| `qwen3:8b` | ⚠️ tool-calling works, but `<think>` blocks blow the 120s per-turn timeout on a 16GB laptop |
| `qwen3.5` (4b/9b) | ❌ emits tool calls as raw JSON *text* under a multi-tool prompt → breaks the ReAct loop, any size |
| `qwen3:14b` | ⚠️ 2 of 5 pass, 2 time out (`test_skill_discovery_and_use`, `test_ap2_payment_flow_with_real_llm`); measured 2026-10-14/15 on GitHub-hosted CPU runners, 2 runs |

Candidate comparison (`qwen3:14b`; `gemma4:e4b` / `gemma4:12b` not measured): [docs/eval/local-models.md](docs/eval/local-models.md).

Override the model with `LOCAL_OLLAMA_MODEL=mistral-nemo ./scripts/smoke_local_llm.sh`,
or `--keep` to leave the stack up. These tests are tolerant of a local model's
non-determinism — they assert the pipeline reaches a sane outcome, not exact
wording. They are gated behind `DAK_SMOKE_REAL_LLM=1` and are not part of CI.

The same suite can also run against a cheap **cloud** model (a run costs a few
cents; useful when local hardware is busy or to vet a provider):

```bash
./scripts/smoke_cloud_llm.sh                                  # openai/gpt-5.6-luna
CLOUD_MODEL_NAME=gemini/gemini-3.5-flash-lite ./scripts/smoke_cloud_llm.sh   # free-tier option
```

The Gemini free tier may use your data to improve Google products: send nothing sensitive through it.

A [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` also works
(same OpenAI-compatible path; the server can run locally, on a Colab GPU behind
an SSH forward, or on a LAN GPU box — see
[docs/guides/local_llm_llamacpp.md](docs/guides/local_llm_llamacpp.md)):

```bash
llama-server -hf bartowski/Meta-Llama-3.1-8B-Instruct-GGUF:Q4_K_M --port 18080 --jinja &
./scripts/smoke_llamacpp.sh    # waits for the server; first run downloads ~4.9GB,
                               # so allow more time with LLAMACPP_WAIT=1200
```

The UI is also covered by a real browser E2E (Playwright/Chromium) that types
into the HTMX chat, asserts the rendered DOM, and saves screenshots:

```bash
cd tests/integration && uv run playwright install chromium   # once
DAK_SMOKE_REAL_LLM=1 uv run pytest test_bff_ui.py            # against the running local-llm stack
```

## Environment Configuration

Key environment variables (see `env.example.d/` for the full list):

```bash
# LLM Provider (at least one required)
GOOGLE_API_KEY=your_google_api_key
OPENAI_API_KEY=your_openai_key        # optional
ANTHROPIC_API_KEY=your_anthropic_key  # optional

# LLM Configuration
MODEL_NAME=<litellm-model>   # optional. Any LiteLLM name: a Gemini model,
                             # 'openai/gpt-5.6-luna', 'anthropic/claude-...',
                             # 'bedrock/...' (model IDs & auth:
                             # docs/getting-started/bedrock.md), local model.
                             # Unset = the built-in default; env.example.d/10-llm.env shows
                             # its current value (defined once, in
                             # agent/dak_agent/config.py DEFAULT_MODEL_NAME).
DAK_ALLOWED_MODELS=openai/gpt-5.6-luna,ollama/qwen3  # optional. Models a caller
                             # may pick per call with `dak:model`
                             # (docs/architecture/call_config.md). Unset = no
                             # caller may pick a model.
DAK_ALLOWED_MCP_URLS=https://example.com/mcp  # optional. MCP servers a caller may
                             # pass per call with `dak:tools.mcp_servers`
                             # (docs/architecture/call_config.md). Unset = no
                             # caller may pass one.
DAK_ALLOWED_INSPECTION_URLS=https://example.com/validate  # optional. Inspection
                             # endpoints a caller may name per call with
                             # `dak:inspection` (docs/architecture/call_config.md).
                             # Unset = no caller may name one.

# Enforcer Mode
ENABLE_ENFORCER_MODE=true    # Enable strict ReAct pattern (Ulysses Pact)

# AP2 Payment Protocol (experimental)
ENABLE_AP2_PROTOCOL=false
SOLANA_USE_MOCK=true         # mock wallet by default

# Agent Skills
AGENT_SKILLS_DIRS=/app/skills:/app/provider_skills  # colon-separated

# LangFuse Monitoring (optional)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Local LLM (Ollama) — start with (COMPOSE_FILE as in "Quick Start with Docker"): docker compose --profile local-llm up,
# pull a model (docker compose exec ollama ollama pull llama3.2), then:
MODEL_NAME=ollama_chat/llama3.2
# OLLAMA_API_BASE needs no setting: docker-compose.yml passes http://ollama:11434
```

## Dependency Licenses

Each component's runtime dependencies (dev dependencies excluded) are checked against the license policy in
[`maintenance/license-policy.toml`](maintenance/license-policy.toml): the allowed licenses, and the few dependencies
allowed one by one, with the reason. Why the policy is what it is, and how the licenses are read:
[docs/maintenance/license-policy.md](docs/maintenance/license-policy.md).

The CI `license` job fails when a dependency has a license outside the policy or no license information, and keeps
the full list per component as the `license-report-<component>` artifact. To check locally:

```bash
./scripts/license_check.sh agent     # or mcp-server / bff / cli / maintenance; the list goes to ./license-report/
cd agent && uv sync                  # the check reinstalls the component without dev dependencies; this restores them
```

## License

Apache 2.0 - See [LICENSE](LICENSE) file for details.
