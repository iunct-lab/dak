# Docker Deployment Guide

This guide covers deploying the Decentralized Agent Kit using Docker Compose.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose V2
- At least 4GB of free RAM
- Git

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/iunct-lab/dak.git
cd dak
```

### 2. Configure Environment Variables

```bash
cat env.example.d/*.env > .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)" >> .env   # required; compose stops without it
```

Edit `.env` and configure required variables:

```bash
# Required: API key matching MODEL_NAME (Gemini by default)
GOOGLE_API_KEY=your_google_api_key_here

# Optional: Alternative LLM providers
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
```

### 3. Build and Start Services

```bash
export COMPOSE_FILE=$(./scripts/compose_files.sh)
docker compose up --build -d
```

`scripts/compose_files.sh` lists `docker-compose.yml` and then `compose/base/*.yml`.
The variables each feature passes to the agent (Bedrock, web search) are in
`compose/base/<feature>.yml`, so a value you export in the shell reaches the agent only
through `COMPOSE_FILE`; values in `.env` reach it with a plain `docker compose` too. To pass
a new feature's variables, add one file `compose/base/<feature>.yml`
(`services.agent.environment`) and leave the existing files as they are.
Run the later commands in the same shell (or export `COMPOSE_FILE` again).

This will start:
- **Agent** (port 8000): Main DAK agent with LLM integration
- **MCP Server** (port 8001, this machine only): Tool server for MCP protocol
- **BFF UI** (port 8002): FastAPI + HTMX web interface
- **PostgreSQL** (port 5432, this machine only): Database for conversation history

Ollama (local LLM) is optional: `docker compose --profile local-llm up -d`.

### 4. Verify Deployment

Check all services are running:

```bash
docker compose ps
```

Expected output:
```
NAME                                      STATUS
decentralized-agent-kit-agent-1          Up
decentralized-agent-kit-bff-1            Up
decentralized-agent-kit-mcp-server-1     Up
decentralized-agent-kit-postgres-1       Up
```

### 5. Access the Application

- **Web UI (BFF)**: http://localhost:8002
- **Agent API**: http://localhost:8000
- **MCP Server**: http://localhost:8001

## Service Details

### Agent Service

**Container**: `decentralized-agent-kit-agent-1`
**Port**: `8000`
**Health Check**: `http://localhost:8000/list-apps`

**Responsibilities**:
- Main LLM interaction (via LiteLLM)
- MCP Client for tool discovery/execution
- Agent Skills (SKILL.md) loading
- State management with PostgreSQL
- A2A (Agent-to-Agent) protocol handler

**Logs**:
```bash
docker compose logs agent -f
```

### MCP Server

**Container**: `decentralized-agent-kit-mcp-server-1`
**Port**: `8001` (mapped from internal 8000), published on `127.0.0.1` only: `run_command` and the file tools have no auth, so only this machine reaches them. See [Reaching mcp-server or PostgreSQL from another machine on the LAN](#reaching-mcp-server-or-postgresql-from-another-machine-on-the-lan)
**Endpoint**: `http://localhost:8001/mcp`

**Responsibilities**:
- Expose tools via MCP protocol (streamable HTTP)
- Handle tool execution requests against the mounted `/projects` workspace

**Logs**:
```bash
docker compose logs mcp-server -f
```

### BFF UI Service

**Container**: `decentralized-agent-kit-bff-1`
**Port**: `8002` (mapped from internal 8000)
**Health Check**: `http://localhost:8002/`

**Responsibilities**:
- Web chat interface for agent interaction (FastAPI + HTMX)
- Renders agent tool calls as a "thinking process" view

**Logs**:
```bash
docker compose logs bff -f
```

### PostgreSQL

**Container**: `decentralized-agent-kit-postgres-1`
**Port**: `5432`, published on `127.0.0.1` only
**Credentials**: user `username`, password `POSTGRES_PASSWORD` from `.env` (no default; generate with `openssl rand -hex 32`)

```bash
docker compose exec postgres psql -U username -d postgres -c 'select 1'
```

## Configuration

### Environment Variables (Agent)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Yes* | - | Google Gemini API key |
| `OPENAI_API_KEY` | Yes* | - | OpenAI API key |
| `ANTHROPIC_API_KEY` | Yes* | - | Anthropic API key |
| `MODEL_NAME` | No | built-in (`DEFAULT_MODEL_NAME` in `agent/dak_agent/config.py`; current value shown in `env.example.d/10-llm.env`) | LiteLLM model name |
| `DATABASE_URL` | No | Auto-configured | PostgreSQL connection string |
| `MCP_SERVER_URL` | No | `http://mcp-server:8000/mcp` | Default MCP server URL |
| `ENABLE_ENFORCER_MODE` | No | `false` | Enable strict ReAct pattern (Ulysses Pact) |
| `ENABLE_AP2_PROTOCOL` | No | `false` | Enable agent-to-agent payments (experimental) |
| `SOLANA_USE_MOCK` | No | `true` | Mock Solana wallet (no real transactions) |
| `AGENT_SKILLS_DIRS` | No | `/app/skills` | Colon-separated skill directories |
| `LANGFUSE_PUBLIC_KEY` | No | - | LangFuse Public Key |
| `LANGFUSE_SECRET_KEY` | No | - | LangFuse Secret Key |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | LangFuse Host |
| `DAK_DEV_API` | No | unset (off) | `1` serves the development API: ADK's Dev UI, `/dev/**` (test runs, eval, builder, debug trace) and `/docs`, `/openapi.json`, `/redoc`. The default `docker-compose.yml` does not set it; for local development put `DAK_DEV_API=1` in `.env` |

*At least one LLM provider API key is required

Additional MCP servers and A2A peers are one file each in `agent/agent_config.d/`
(`mcp_servers/<name>.yaml`, `a2a_peers/<name>.yaml`); tool permission rules are in
`agent/agent_config.yaml`. docker-compose mounts both into the container.

`POSTGRES_PASSWORD` (required) is read by both the postgres service and the
agent's connection strings. Use hex (`openssl rand -hex 32`) so it goes into the
URL as-is.

### Reaching mcp-server or PostgreSQL from another machine on the LAN

The default `docker-compose.yml` publishes every service (the agent `8000`, mcp-server
`8001`, the BFF `8002`, PostgreSQL `5432`, Ollama `11434`) on `127.0.0.1` only. To reach
one of them from another machine, put a
`docker-compose.override.yml` next to `docker-compose.yml` (it is in
`.gitignore`). Compose reads it automatically only when you give neither `-f` nor
`COMPOSE_FILE`; with the entry above, add it last:
`export COMPOSE_FILE=$(./scripts/compose_files.sh):docker-compose.override.yml`.
The file:

```yaml
services:
  mcp-server:
    ports: !override
      - "8001:8000"
  postgres:
    ports: !override
      - "5432:5432"
```

(The same works for the agent and the BFF, but they have no authentication: put an
authenticating reverse proxy in front instead of publishing them.)

`!override` is required: without it compose appends the entries, and the port is
published on both `127.0.0.1` and every interface. Check with
`docker compose config` (no `host_ip` means every interface).

**Warning**: this opens `run_command` (any shell command, with the API keys in
`.env` readable) and the conversation history to everyone on the same network.
Only do it on a network where every machine is yours. Delete the file to go back.

### Volume Mounts

```yaml
volumes:
  postgres_data:    # PostgreSQL database
```

**Persistence**: Agent conversation history and state are persisted in these volumes.

**Backup**:
```bash
docker compose down
docker run --rm -v decentralized-agent-kit_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_backup.tar.gz /data
```

## Management Commands

### View Logs

All services:
```bash
docker compose logs -f
```

Specific service:
```bash
docker compose logs agent -f
docker compose logs mcp-server -f
docker compose logs bff -f
```

### Restart Services

All services:
```bash
docker compose restart
```

Specific service:
```bash
docker compose restart agent
docker compose restart mcp-server
```

### Stop Services

```bash
docker compose down
```

With volume cleanup:
```bash
docker compose down -v
```

### Rebuild After Code Changes

```bash
export COMPOSE_FILE=$(./scripts/compose_files.sh)   # as in "Build and Start Services"
docker compose up --build -d
```

Rebuild specific service:
```bash
docker compose up --build -d agent
```

### Shell Access

```bash
docker compose exec agent bash
docker compose exec mcp-server bash
```

## Integration Testing (no API keys)

The full stack can run against a deterministic fake LLM:

```bash
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait
(cd tests/integration && uv run pytest)
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose down -v
```

## Troubleshooting

### Service Won't Start

**Check logs**:
```bash
docker compose logs <service-name>
```

**Common issues**:
1. Port already in use → Change ports in `docker-compose.yml`
2. Environment variables missing → Check `.env` file
3. Resource limits → Increase Docker memory allocation

### Agent Can't Connect to MCP Server

**Symptoms**: `MCPClient Error listing tools`

**Solution**:
```bash
# Check if mcp-server is running
docker compose ps mcp-server

# Check network connectivity
docker compose exec agent ping mcp-server

# Restart both services
docker compose restart agent mcp-server
```

### Database Connection Issues

**Symptoms**: `Failed to connect to Database`

**Solution**:
```bash
# Check if PostgreSQL is running
docker compose ps postgres

# Restart database service
docker compose restart postgres
```

**Symptoms**: `password authentication failed for user "username"` after
updating. A `postgres_data` volume created before `POSTGRES_PASSWORD` was
required keeps the old password `password`; postgres only reads
`POSTGRES_PASSWORD` when it creates the volume.

**Solution**: if you don't need the history, `docker compose down -v`. To keep it,
set the volume's password to the one in `.env` (the container already has it
as `$POSTGRES_PASSWORD`, so it never goes into your shell history):
```bash
docker compose exec postgres sh -c 'psql -U username -d postgres -c "ALTER USER username PASSWORD '\''$POSTGRES_PASSWORD'\''"'
```

### BFF Can't Connect to Agent

**Symptoms**: "Session Error" or error bubbles in the chat UI

**Solution**:
1. Verify the agent is healthy: `curl http://localhost:8000/list-apps`
2. Check the BFF's `AGENT_URL` (defaults to `http://agent:8000` in compose)
3. Restart both services:
   ```bash
   docker compose restart agent bff
   ```

### Out of Memory

**Symptoms**: Services crashing or slow performance

**Solution**:
1. Increase Docker memory limit (minimum 4GB)
2. Reduce number of running services
3. Clear unused Docker resources:
   ```bash
   docker system prune -a
   ```

## Production Deployment

### Security Checklist

- [ ] Use HTTPS with proper SSL certificates and an authenticating reverse proxy
- [ ] Use strong database passwords
- [ ] Enable Docker secrets for sensitive values
- [ ] Restrict the MCP server's workspace mount (it executes shell commands)
- [ ] Do not set `DAK_DEV_API` (it is off by default). Check that the development routes `/dev-ui`, `/dev/**`, `/docs`, `/openapi.json`, `/redoc` are not reachable
- [ ] Set up regular database backups
- [ ] Configure log rotation
- [ ] Implement rate limiting

### Scaling

**External Database**:
Replace PostgreSQL with a managed PostgreSQL service (e.g., AWS RDS, Google Cloud SQL).

### Monitoring

**Health Checks**:
```bash
curl http://localhost:8000/list-apps
curl http://localhost:8002/
```

**Resource Usage**:
```bash
docker stats
```

## Additional Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [MCP Integration Guide](../guides/mcp_integration.md)
- [CLI Usage Guide](../guides/cli_usage.md)
