# DAK CLI Usage Guide

The `dak-cli` tool allows you to interact with the Decentralized Agent Kit directly from your terminal.

## Installation

```bash
cd cli
uv sync
```

## Commands

### Login

Authenticate with the Agent API. Currently supports local username-based authentication.

```bash
uv run dak-cli login --username <username> --agent-url <url>
```

- `--username`: Your username (e.g., `admin`).
- `--agent-url`: URL of the Agent API (default: `http://localhost:8000`).

### Chat

Start an interactive chat session with the agent.

```bash
uv run dak-cli chat
```

- Type your message and press Enter.
- Type `exit` or `quit` to end the session.

### Run

Execute a single command/prompt and get the response.

```bash
uv run dak-cli run "Your prompt here"
```

## Configuration

Configuration is stored in `~/.dak-cli/config.json`.

```bash
uv run dak-cli config
```
