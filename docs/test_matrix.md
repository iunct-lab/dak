# Testing Matrix & Environment Variables

This document outlines the key environment variables that control the agent's behavior and defines the critical test scenarios for verifying these configurations.

## Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ENABLE_AP2_PROTOCOL` | `false` | Enables the AP2/x402 payment protocol features (PaymentRequired handling, Wallet tools). |
| `ENABLE_A2A_CONSUMER` | `false` | Enables Agent-to-Agent (A2A) consumer capabilities. |
| `ENABLE_ENFORCER_MODE` | `false` | Enables "Enforcer Mode" where the agent is restricted to tool usage only (no direct text). |
| `SOLANA_USE_MOCK` | `true` | **CRITICAL**: If `true` (the default), uses a mock Solana wallet with 1000 SOL. Set to `false` explicitly to connect to a real network. |
| `SOLANA_NETWORK` | `devnet` | Target Solana network (`devnet`, `mainnet`, or RPC URL). |
| `AGENT_INSTRUCTION` | (Default Prompt) | The system instruction for the agent. Critical for defining behavior (e.g., "You are a Consumer Agent"). |
| `MCP_SERVER_URL` | `http://mcp-server:8000/mcp` | URL of the Model Context Protocol server. |
| `LANGFUSE_PUBLIC_KEY` | - | Langfuse Public Key for observability. |
| `LANGFUSE_SECRET_KEY` | - | Langfuse Secret Key for observability. |

> [!NOTE]
> The scenarios below are automated in `tests/integration/` (run via
> `COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait`
> followed by `cd tests/integration && uv run pytest`). They also run in CI.

### Adding a feature's test services

The integration stack is `docker-compose.yml`, `docker-compose.test.yml`, then every
`compose/test/*.yml` in name order; `scripts/compose_files.sh test` lists them for
`COMPOSE_FILE`. A feature's test services and its values in the default `agent`
service (`environment`, `depends_on` in the map form, `volumes`) go into one new file,
`compose/test/<feature>.yml`; do not edit the existing files. Compose merges the
`agent` entries across the files. An optional overlay goes after the list:
`COMPOSE_FILE=$(./scripts/compose_files.sh test):docker-compose.local-llm.yml`.

## Test Scenarios

### 1. Default Behavior (Baseline)
**Configuration**:
- `ENABLE_AP2_PROTOCOL=false`
- `ENABLE_A2A_CONSUMER=false`
- `ENABLE_ENFORCER_MODE=false`

**Expected Behavior**:
- Agent behaves as a standard chatbot with basic tools (filesystem, etc.).
- Does **not** attempt to pay for services.
- Responds to "How are you?" with natural language.

### 2. Experimental Mode (Current Demo)
**Configuration**:
- `ENABLE_AP2_PROTOCOL=true`
- `ENABLE_A2A_CONSUMER=true`
- `SOLANA_USE_MOCK=true`
- `AGENT_INSTRUCTION` includes "Payment Policy..."

**Expected Behavior**:
- **AP2 Flow**: Can request premium services from `agent-provider`, receive `PaymentRequired` error, check balance, and pay.
- **A2A**: Can communicate with other agents.
- **Mock Wallet**: Balance shows 1000 SOL (initially).

### 3. Enforcer Mode
**Configuration**:
- `ENABLE_ENFORCER_MODE=true`

**Expected Behavior**:
- Agent **must** use a tool for every turn.
- Direct text responses are rejected by the validator.

## Browser Verification Plan (Manual/Agentic)

The following scenarios must be verified via the BFF web UI (`http://localhost:8002`) to ensure the user experience is correct.

1.  **Basic Chat & Tool Usage**:
    - Input: "Hello" -> Response: Greeting.
    - Input: "List files in current directory" -> Response: Tool execution result.
2.  **AP2 Payment Flow (Happy Path)**:
    - Input: "Ask agent_provider for premium analysis on AI."
    - Expected: Agent contacts provider -> Provider asks for payment -> Agent checks balance -> Agent pays -> Provider delivers report.
3.  **Insufficient Funds (Edge Case)**:
    - *Requires modifying mock balance to 0.*
    - Input: "Ask agent_provider for premium analysis."
    - Expected: Agent checks balance -> Reports insufficient funds -> Asks user for guidance.
