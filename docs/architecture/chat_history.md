# Chat History Specification

## Overview
The DAK Agent maintains conversation history to provide context-aware responses. This document outlines the data structure, storage mechanisms, and integration logic for chat history management.

## Data Structure

Conversation history is represented as a list of message objects.

```json
[
  {
    "role": "User",
    "content": "Hello, how are you?"
  },
  {
    "role": "Assistant",
    "content": "I am doing well, thank you. How can I help you today?"
  }
]
```

- **role**: The sender of the message (`"User"` or `"Assistant"`).
- **content**: The text content of the message.

## Storage Mechanisms

The system supports two storage backends, determined by the `MONGO_URI` environment variable.

### 1. PostgreSQL (Persistent)
Used when `SESSION_SERVICE_URI` is set.

- **Schema**: Managed by `google-adk` (SQLAlchemy).
- **Operations**: Handled by `google-adk`'s `SqlAlchemySessionService`.

### 2. In-Memory (Ephemeral)
Used as a fallback when `MONGO_URI` is not set or connection fails.

- **Structure**: Nested Python Dictionary
  ```python
  store[user_id][session_id] = [
      {"role": "User", "content": "..."},
      ...
  ]
  ```
- **Lifecycle**: Data is lost when the Agent service restarts.

## Integration Logic

The `DAKAgent` class manages the interaction with the State Manager.

1.  **Initialization**:
    - `google-adk` initializes `SqlAlchemySessionService` if `SESSION_SERVICE_URI` is present.
    - Otherwise defaults to `InMemorySessionService`.

2.  **Execution Flow (`run` method)**:
    - **Input**: `input_text`, `user_id`, `session_id`.
    - **Step 1: Retrieve History**: Fetches existing messages for the user/session.
    - **Step 2: Construct Prompt**: Concatenates System Prompt + History + Current User Input.
    - **Step 3: Generate Response**: Sends full prompt to LLM.
    - **Step 4: Update History**:
        - Appends User message.
        - Appends Assistant response.
    - **Output**: Returns Assistant response.

## Key Identifiers

- **User ID (`user_id`)**:
    - **Authenticated (UI)**: Extracted from JWT or OAuth provider ID (e.g., `admin`, `google_12345`).
    - **CLI**: Provided via `--username` flag (e.g., `admin`).
    - **Debug**: Defaults to `debug_user`.

- **Session ID (`session_id`)**:
    - **UI/CLI**: Currently derived from username (e.g., `session_<username>`) or passed via `X-Session-ID` header.
    - **Debug**: Defaults to `debug_session`.
