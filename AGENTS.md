# AGENTS.md

> [!NOTE]
> This file is intended for AI coding agents (Coding LLMs). It provides context, architectural guidelines, and commands necessary to work on the `Decentralized-Agent-Kit` repository.

## Project Overview

**Decentralized-Agent-Kit** is a P2P AI Agent ecosystem MVP (Minimum Viable Product) based on the "A2A (Agent-to-Agent)" and "MCP (Model Context Protocol)" concepts.
The core philosophy is **"Loosely Coupled"**, **"Independent Containers"**, and **"LLM Autonomy"**. Each component (Agent, MCP Server, UI, CLI) runs as an independent Docker container and communicates only via standard protocols.

## Core Philosophy & Architecture

### 1. Independent Containers
Each component must be able to run independently. Dependencies are minimized. Communication is via MCP, HTTP/REST, or A2A.

### 2. Loosely Coupled
Respect interfaces (API, Protocol). Do not rely on internal implementations of other containers.

### 3. LLM Autonomy (Crucial)
The System **ENABLES**, the Agent **DECIDES**.
*   **No Magic**: The system should never perform critical actions (like payments) implicitly "under the hood".
*   **Explicit Tools**: The Agent must explicitly call a tool to perform an action.
*   **Observation-Driven**: When the system encounters a barrier (e.g., Payment Required), it returns a structured **Observation** (Error) to the Agent. The Agent then **Reasons** and **Decides** what to do next.

### 4. Adaptive Agent Architecture
The core agent is an `AdaptiveAgent` that wraps the standard LLM loop with dynamic capabilities:
*   **Dynamic Mode Switching**: The agent monitors its context window. If it gets too full, it switches "Modes" (e.g., from "General" to "Coding" or "Data Analysis") by refreshing its system instruction and toolset.
*   **Skill Registry**: Tools are grouped into "Skills".
    *   **Curated Skills**: High-quality, local toolsets with specific instructions (e.g., `solana_wallet`, `git_control`).
    *   **Zero-Config Tools**: Remote tools discovered dynamically from MCP servers.
*   **Enforcer Mode (Ulysses Pact)**: For critical tasks, the Agent can bind itself to a specific plan using the `planner` tool. The system enforces this plan, blocking any tool usage that deviates from it.

### 5. AP2 Protocol (Agent-to-Agent Payment Protocol)
*   **No Auto-Pay**: The system NEVER pays for a tool call automatically.
*   **Workflow**:
    1.  Agent calls a paid tool (e.g., `premium_search`).
    2.  System catches `PaymentRequiredError` and returns a structured observation: "Payment Required: 0.01 SOL to [Address]".
    3.  Agent sees this observation.
    4.  Agent decides to pay using `send_sol_payment`.
    5.  Agent retries the original tool call with the proof of payment.

## Directory Structure & Components

| Directory | Component | Role | Tech Stack |
| :--- | :--- | :--- | :--- |
| `/agent` | **Agent** | AI Brain. Adaptive Agent, Skills, Payment Handler. | Python, LangChain/LangGraph, Docker |
| `/mcp-server` | **MCP Server** | Tools & Resources provider (stateless). | Python, MCP SDK, Docker |
| `/bff` | **BFF (HTMX UI)** | **Primary Verification UI**. Lightweight, fast feedback. | Python, FastAPI, HTMX |
| `/ui` | **UI (React)** | Consumer-facing Chat & Settings. | TypeScript, Next.js, Tailwind CSS |
| `/cli` | **CLI** | Command Line Interface. Dev & Headless ops. | Python, Click/Typer |
| `/db` | **Database** | Persistence layer. | PostgreSQL / FerretDB |

## Service Connectivity & Ports

Understanding the connectivity between containers is crucial for debugging and development.

| Service | Host Port (Localhost) | Internal Docker Address | Protocol | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Agent** | `8000` | `http://agent:8000` | HTTP/REST | Main API. |
| **MCP Server** | `8001` | `http://mcp-server:8000` | SSE (Server-Sent Events) | Tools provider. Note the internal port is 8000. |
| **BFF (HTMX UI)** | `8002` | `http://bff:8000` | HTTP | **Use this for testing**. Access at `http://localhost:8002`. |
| **UI (React)** | `3000` | `http://ui:3000` | HTTP | Consumer UI. Access at `http://localhost:3000`. |
| **Postgres** | `5432` | `postgres:5432` | TCP | Database. |
| **Ollama** | `11434` | `http://ollama:11434` | HTTP | Local LLM provider (optional). |

> [!IMPORTANT]
> **Connectivity Rule**: When running inside a Docker container (e.g., Agent), ALWAYS use the **Internal Docker Address** (e.g., `http://mcp-server:8000`). NEVER use `localhost`, as that refers to the container itself.

## Build & Test Commands

### Global
*   **Run all services**: `docker compose up --build`
*   **Stop all services**: `docker compose down`

### Agent (`/agent`)
*   **Dependency Management**: `uv sync`
*   **Run Tests**: `uv run pytest`

### CLI (`/cli`)
*   **Dependency Management**: `uv sync`
*   **Run Tool**: `uv run dak-cli [COMMAND]`
*   **Run Tests**: `uv run pytest`
*   **Key Commands**:
    *   `chat`: Start an interactive chat session with the agent.
    *   `config`: Manage configuration settings.

### UI (`/ui`)
*   **Install Dependencies**: `npm install`
*   **Run Dev Server**: `npm run dev`
*   **Build**: `npm run build`

## Development Guidelines

### General Rules
1.  **Docker First**: Assume execution in `docker-compose`.
2.  **Python**: Use `uv` for dependency management. Do not use `pip` directly.
3.  **Configuration**: Use `.env` files. Never hardcode secrets.
4.  **Public repository sync**: Use `ops-kit public-sync` (the kit's `bin/ops-kit`; `--dry-run` prints the result without pushing). The target, excluded files, and rewritten files live in `publicSync` in the root `ops.config.json`. See the kit README section "公開リポジトリへの同期" for how it works, and `docs/maintenance/public-repo.md` for this repository's procedure. Development happens in a private development repository; the public repository is `iunct-lab/dak`.
5.  **Shared files**: A change that touches a shared file (`docker-compose.yml`, `docker-compose.test.yml`, `agent/agent_config.yaml`, `.github/workflows/*.yml`, `CLAUDE.md`) goes into the first Task of the PBI (最初の Task), kept small and merged first. Per-feature files go in `env.example.d/<NN>-<section>.env` (environment variables), `agent/agent_config.d/mcp_servers/<name>.yaml` and `agent/agent_config.d/a2a_peers/<name>.yaml` (MCP servers and A2A peers), and compose services in `compose/base/<feature>.yml` (default stack) or `compose/test/<feature>.yml` (feature tests). A Task that adds them must name the file, not the directory (ファイル名で名指し), because the parallel guard treats a named directory as overlapping everything inside it.

### Hosted credentials
*   On a host that manages secrets in AWS Systems Manager Parameter Store, credentials must be stored there as `SecureString`. This overrides the general `.env` guidance for secrets.
*   Never ask the user to save credentials in local `.env` files, local credential files, or temporary files. Local maintenance (`dak-maint`) takes `MAINT_LLM_API_KEY` from the environment only when explicitly authorized by the user. Never print decrypted values or include them in command arguments, logs, issues, or PRs.
*   Read the authorized parameter at launch and pass the value only to the consuming process in memory (see `agent/ssm_exec.py`). Keep API keys separate from other tools' OAuth tokens.
*   Before adding a credential, check the host's SSM read permissions. They may be an explicit list of parameter names; a new parameter then needs the corresponding IAM permission and consuming wrapper.
*   The requested Anthropic model is `claude-haiku-5-5` (`anthropic/claude-haiku-5-5` for LiteLLM). Check the provider's migration requirements before switching a running service; Haiku 5.5 rejects `temperature=0`.

### Component-Specific Guidelines

#### Agent
*   **Do**: Implement reasoning and planning logic. Use `AdaptiveAgent` patterns.
*   **Don't**: Hardcode tool logic inside the agent loop. Always use MCP tools or Skills.
*   **Don't**: Auto-handle payments. Always delegate to the LLM.

#### MCP Server
*   **Do**: Provide atomic, stateless tools.
*   **Don't**: Manage complex state (delegate to Agent/DB).

#### CLI
*   **Do**: Provide a robust interface for developers and headless operation.
*   **Structure**:
    *   `src/main.py`: Entry point.
    *   `src/commands/`: Command implementations (e.g., `chat.py`, `config.py`).
    *   `src/client/`: API client to communicate with Agent/MCP.
*   **Note**: The CLI acts as a client to the Agent, similar to the UI. It should not directly import Agent code but communicate via API/Socket.

#### UI
*   **Do**: Focus on UX/UI.
*   **Don't**: Implement business logic that belongs in the Agent.
