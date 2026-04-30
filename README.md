# magicpin AI Challenge — Vera Bot

A production-ready FastAPI backend that drives merchant engagement via an LLM-powered conversational agent. Built for the magicpin AI Challenge.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Judge     │────▶│   Bot API   │────▶│   Brain     │
│Simulator    │◀────│  (FastAPI)  │◀────│ (Gemini)    │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │ State Store │
                    │  (In-Mem)   │
                    └─────────────┘
```

| Component | File | Purpose |
|-----------|------|---------|
| **Brain** | `brain.py` | Gemini 2.5 Flash integration, system prompt engineering, graceful LLM fallback |
| **Bot** | `bot.py` | FastAPI routes (`/v1/tick`, `/v1/reply`, `/v1/context`), deterministic state machine, structured logging |
| **Judge** | `judge_simulator.py` | LLM-powered evaluation harness |

## Tech Stack

- **FastAPI** — high-performance async web framework
- **Google GenAI SDK** — native Gemini 2.5 Flash integration with JSON-mode
- **Pydantic** — request validation
- **python-dotenv** — environment variable management from .env files
- **Python `logging`** — production-grade observability

## Key Design Decisions

### 1. Deterministic State Machine (`/v1/reply`)

The reply endpoint is built as a **priority-ordered state machine** to guarantee predictable behavior under test:

1. **Hostile Guard** — ends immediately on keywords like "stop" / "spam". Zero LLM latency.
2. **Auto-Reply Breaker** — tracks consecutive auto-replies **by `merchant_id`** (not `conversation_id`) and ends the loop after 4 turns. This was critical because the judge simulator generates a *new* `conversation_id` on every auto-reply turn.
3. **Positive Intent Override** — bypasses the LLM entirely for "ok", "yes", "next", etc., returning a specific, action-oriented message. Eliminates hallucination risk on high-stakes transitions.
4. **LLM Fallback** — delegates to `handle_conversation()` only for truly ambiguous merchant responses.

### 2. Graceful Degradation

- **Non-text input** (images, media, malformed payloads) → `action: wait` with explanatory rationale.
- **Empty messages** → `action: wait`.
- **LLM API failure / rate limit** → try-except wrappers in `brain.py` return safe fallback responses instead of crashing.
- **Unhandled exceptions** → caught at the FastAPI route level, returning `action: end` to prevent infinite loops.

### 3. Observability

Structured logging is configured via Python’s standard `logging` module:

```
2024-01-15 10:23:45,123 [INFO] Conversation conv_auto_1 — Turn 1 from merchant m_test_001
2024-01-15 10:23:45,456 [INFO] Conversation conv_auto_1 — auto-reply #1 from merchant m_test_001
```

This enables quick post-mortem debugging without scattering `print()` statements.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key |

**Option 1: Using .env file (recommended)**
```bash
cp .env.example .env
# Edit .env and add your API key
python bot.py
```

**Option 2: Environment variable**
```bash
export GEMINI_API_KEY="your-key-here"
python bot.py
```

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set up your API key (copy .env.example to .env and add your key)
cp .env.example .env

# Start the bot
python bot.py               # starts on http://localhost:8080

# Run the judge simulator (in a separate terminal)
python judge_simulator.py # evaluates against localhost:8080
```

## Test Results

The bot passes all LLM judge tests with a **100% PASS** scorecard:

```
======================================================================
                  magicpin AI Challenge — LLM Judge
======================================================================

[PASS] LLM connected successfully
[PASS] Bot correctly switched to ACTION mode
[PASS] Turn 1: Bot WAITING
[PASS] Turn 2: Bot WAITING
[PASS] Turn 4: Bot ENDED — detected auto-reply pattern!
[PASS] Bot correctly ENDED on hostile message
[PASS] warmup
[PASS] auto_reply
[PASS] intent
[PASS] hostile
```

**Scorecard: 100% PASS — No warnings, no failures.**

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/context` | Push merchant / category / trigger context |
| `POST` | `/v1/tick` | Generate initial outreach actions |
| `POST` | `/v1/reply` | Respond to merchant messages (state machine) |
| `GET`  | `/v1/healthz` | Health check |
| `GET`  | `/v1/metadata` | Team info |

## Stress Testing & Edge Cases

| Scenario | Behavior |
|----------|----------|
| Merchant sends an image | `action: wait`, rationale explains non-text input |
| Merchant sends empty string | `action: wait`, rationale explains empty message |
| Gemini API rate-limited | `brain.py` catches exception, returns safe fallback message |
| 4 consecutive auto-replies | `action: end`, conversation closed to save resources |
| Hostile keyword detected | `action: end`, immediate termination |

## Production Notes

- **In-memory stores** (`store`, `history`, `turn_tracker`) work for the simulator and single-node deployments.
- For horizontal scale, migrate state to **Redis** (TTL on conversation keys) or **PostgreSQL** for persistence across restarts and multi-replica consistency.

## Team

- **Name**: Varun-Vera-Final
- **Version**: 3.1.0
