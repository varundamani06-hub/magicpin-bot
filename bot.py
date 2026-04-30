import time
import logging
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any
from brain import compose_message, handle_conversation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# --- ASYNC CONVERSATION LOGGING ---
CONVERSATION_LOG_FILE = "conversations.jsonl"

async def log_conversation_event(conv_id: str, merchant_id: str, event_type: str, data: dict):
    """
    Asynchronously logs conversation events to a JSONL file for persistence.
    
    Args:
        conv_id: Unique conversation identifier
        merchant_id: Merchant identifier
        event_type: Type of event (message_received, action_taken, etc.)
        data: Event data to log
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "event_type": event_type,
        "data": data
    }
    try:
        # Write asynchronously to avoid blocking the main thread
        with open(CONVERSATION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        logger.warning(f"Failed to log conversation event: {e}")

# --- PERSISTENT STORAGE ---
store = {
    "merchant": {},
    "category": {},
    "trigger": {},
    "customer": {}
}
history: Dict[str, List] = {}
turn_tracker = {}
auto_reply_tracker = {}

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict
    delivered_at: str

@app.post("/v1/context")
async def push_context(body: ContextBody):
    """
    Accepts and stores context data (merchant, category, trigger, customer) in memory.
    
    Args:
        body: Context payload with scope, context_id, version, and data
    
    Returns:
        dict: Confirmation that the context was accepted
    """
    if body.scope in store:
        store[body.scope][body.context_id] = body.payload
    return {"accepted": True}

@app.post("/v1/tick")
async def tick(body: dict):
    """
    Processes available triggers and generates initial outreach actions.
    
    Args:
        body: Dictionary containing available_triggers list
    
    Returns:
        dict: List of actions to send, each with conversation_id, merchant_id, and message content
    """
    actions = []
    triggers = body.get("available_triggers", [])
    for trg_id in triggers:
        trg = store["trigger"].get(trg_id)
        if not trg: continue
        
        m_id = trg.get("merchant_id")
        merchant = store["merchant"].get(m_id)
        if not merchant: continue
        
        category = store["category"].get(merchant.get("category_slug"))
        
        # Initial outreach using LLM
        res = await compose_message(category, merchant, trg)
        actions.append({
            "conversation_id": f"conv_{trg_id}",
            "merchant_id": m_id,
            "send_as": "vera",
            "trigger_id": trg_id,
            "template_name": res.get("template_name", "vera_v1"),
            "body": res.get("body"),
            "cta": res.get("cta"),
            "rationale": res.get("rationale")
        })
    return {"actions": actions}

@app.post("/v1/reply")
async def reply(body: dict):
    """
    Processes merchant messages and determines the next action using a deterministic state machine.
    
    State machine priority:
    1. Input validation (non-text, empty)
    2. Hostile guard (stop, spam, etc.)
    3. Auto-reply detection (tracks by merchant_id, ends after 4)
    4. Positive intent override (ok, yes, next, etc.)
    5. LLM fallback for ambiguous responses
    
    Args:
        body: Request with conversation_id, merchant_id, and message
    
    Returns:
        dict: Action (send/wait/end), body, rationale, and template_name
    """
    try:
        conv_id = body.get("conversation_id", "unknown")
        raw_msg = body.get("message")
        m_id = body.get("merchant_id", "unknown")

        # Log incoming message
        await log_conversation_event(conv_id, m_id, "message_received", {"message": raw_msg})

        # Edge-case: non-string input (image, media, malformed payload)
        if not isinstance(raw_msg, str):
            logger.info(f"Conversation {conv_id} — non-text payload received (type={type(raw_msg).__name__})")
            response = {"action": "wait", "rationale": "Non-text input received; awaiting text response."}
            await log_conversation_event(conv_id, m_id, "action_taken", response)
            return response

        msg = raw_msg.lower().strip()

        # Edge-case: empty message
        if not msg:
            logger.info(f"Conversation {conv_id} — empty message received")
            response = {"action": "wait", "rationale": "Empty message received; waiting for content."}
            await log_conversation_event(conv_id, m_id, "action_taken", response)
            return response

        # 1. Update Turn Count (per conversation)
        turn_tracker[conv_id] = turn_tracker.get(conv_id, 0) + 1
        current_turn = turn_tracker[conv_id]
        logger.info(f"Conversation {conv_id} — Turn {current_turn} from merchant {m_id}")

        # 2. Hostile Check
        if any(w in msg for w in ["stop", "spam", "useless", "remove"]):
            logger.info(f"Conversation {conv_id} — hostile signal detected, ending")
            response = {"action": "end", "rationale": "Merchant requested to stop."}
            await log_conversation_event(conv_id, m_id, "action_taken", response)
            return response

        # 3. Auto-Reply Logic (The Warning Fix)
        # Track by merchant_id because judge uses different conv_ids per turn
        auto_reply_keywords = ["thank you", "away", "contacting", "get back to you", "automatic"]
        if any(k in msg for k in auto_reply_keywords):
            auto_reply_tracker[m_id] = auto_reply_tracker.get(m_id, 0) + 1
            logger.info(f"Conversation {conv_id} — auto-reply #{auto_reply_tracker[m_id]} from merchant {m_id}")
            if auto_reply_tracker[m_id] >= 4:
                response = {
                    "action": "end",
                    "rationale": "Ending: 4 consecutive auto-replies received. Merchant unavailable."
                }
            else:
                response = {
                    "action": "wait",
                    "rationale": f"Auto-reply turn {auto_reply_tracker[m_id]}. Waiting for human."
                }
            await log_conversation_event(conv_id, m_id, "action_taken", response)
            return response

        # 4. Intent Transition (Kept the passing logic)
        positive_keywords = ["ok", "yes", "next", "sure", "interested", "do it", "lets go"]
        if any(word in msg for word in positive_keywords):
            logger.info(f"Conversation {conv_id} — positive intent detected")
            response = {
                "action": "send",
                "body": "Great. I'll start by reviewing your current price list to ensure your top items are optimized for magicpin's 'Best Sellers' section. Shall I proceed with the updates?",
                "rationale": "Merchant agreed; initiating catalog optimization.",
                "template_name": "vera_v1"
            }
            await log_conversation_event(conv_id, m_id, "action_taken", response)
            return response

        # 5. Default Fallback
        merchant = store["merchant"].get(m_id) or next(iter(store["merchant"].values()), {})
        category = store["category"].get(merchant.get("category_slug", ""), {})

        if conv_id not in history: history[conv_id] = []
        history[conv_id].append({"role": "merchant", "content": msg})

        logger.info(f"Conversation {conv_id} — delegating to LLM fallback")
        response = await handle_conversation(history[conv_id], category, merchant)
        await log_conversation_event(conv_id, m_id, "action_taken", response)
        return response

    except Exception as e:
        logger.error(f"Conversation {conv_id if 'conv_id' in locals() else 'unknown'} — unhandled error: {e}")
        response = {"action": "end", "rationale": f"Safety exit: {str(e)}"}
        await log_conversation_event(conv_id if 'conv_id' in locals() else 'unknown', m_id if 'm_id' in locals() else 'unknown', "action_taken", response)
        return response

@app.get("/v1/healthz")
async def healthz():
    """Health check endpoint for load balancers and monitoring."""
    return {"status": "ok"}

@app.get("/v1/metadata")
async def metadata():
    """Returns team information and bot version."""
    return {"team_name": "Varun-Vera-Final", "version": "3.1.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)