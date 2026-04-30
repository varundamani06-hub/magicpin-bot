import json
import os
import logging
from pathlib import Path
from google import genai

# --- CONFIGURATION ---
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set. Set it in your environment or .env file.")
client = genai.Client(api_key=API_KEY)
logger = logging.getLogger(__name__)
MODEL_ID = "gemini-2.5-flash"

SYSTEM_PROMPT = """
You are Vera, a peer-level business consultant for magicpin merchants.
Your goal is to drive growth through curiosity, research, and data.

STRICT RULES:
1. Use the 'Voice' guidelines from the Category Context (Tone, Register, Code-mix).
2. NEVER use Taboo words: "guaranteed", "miracle", "best in city", "100%", "assure", "promise".
3. Anchor your claims in the Merchant's specific data (CTR, Leads, Signals) with peer comparisons.
4. If a Trigger is provided, that is the ONLY reason you are messaging.
5. End with a low-friction CTA (e.g., "Want me to draft this?", "Should I pull the abstract?", "Reply 1 to approve").
6. Use Hinglish if the merchant's language preference includes 'hi' (e.g., "Apke liye", "Check kar lijiye", "Karte hain").

COMPELLING MESSAGE ELEMENTS:
- Reciprocity: Show you've already done work ("I've already pulled the abstract for you")
- Curiosity: Reference specific cohorts or data points ("This affects your 124 high-risk patients")
- Data Anchoring: Compare merchant metrics to peer medians ("Your CTR is 2.1% vs peer median of 3.0%")

ACTION RULES:
- ACTION 'send': Use when merchant is interested. Mention a SPECIFIC business goal anchored in their data.
- ACTION 'wait': Use for auto-replies.
- ACTION 'end': Use for hostile merchants OR after 3+ auto-replies.

Return ONLY JSON with "action", "body", "rationale", "template_name", and "cta".
"""

async def compose_message(category: dict, merchant: dict, trigger: dict, customer: dict = None):
    """
    Generates the initial outreach message based on a specific business trigger.
    
    Args:
        category: Category rules and voice settings
        merchant: Merchant profile and context
        trigger: Trigger event that initiated the outreach
        customer: Optional customer context for customer-facing messages
    
    Returns:
        dict: JSON response with body, cta, template_name, and rationale
    """
    # Data-driven metrics injection with peer comparison
    metrics_context = ""
    merchant_data = merchant.get("data", {})
    peer_stats = category.get("peer_stats", {})
    
    # CTR comparison
    merchant_ctr = merchant_data.get("ctr", 0)
    peer_ctr = peer_stats.get("median_ctr", 0)
    if merchant_ctr > 0 and peer_ctr > 0:
        metrics_context += f"\n- CTR: {merchant_ctr}% (peer median: {peer_ctr}%)"
    
    # Leads comparison
    merchant_leads = merchant_data.get("leads", 0)
    peer_leads = peer_stats.get("median_leads", 0)
    if merchant_leads > 0 and peer_leads > 0:
        metrics_context += f"\n- Leads: {merchant_leads} (peer median: {peer_leads})"
    
    # Signals comparison
    merchant_signals = merchant_data.get("signals", 0)
    peer_signals = peer_stats.get("median_signals", 0)
    if merchant_signals > 0 and peer_signals > 0:
        metrics_context += f"\n- Signals: {merchant_signals} (peer median: {peer_signals})"
    
    if metrics_context:
        metrics_context = f"\nMERCHANT METRICS VS PEER MEDIAN:{metrics_context}"
    
    # Hinglish support based on merchant's language preference
    hinglish_instruction = ""
    merchant_identity = merchant.get("identity", {})
    merchant_languages = merchant_identity.get("languages", [])
    if "hi" in merchant_languages or "hi-en" in merchant_languages:
        hinglish_instruction = "\n\nHINGLISH INSTRUCTION: Talk like a fellow business owner in India. Use natural phrases like 'Apke liye', 'Check kar lijiye', 'Karte hain', 'Chaliye' where appropriate, but keep technical terms (ROI, Scaling, CTR) in English."
    
    # Context injection for research_digest triggers
    digest_context = ""
    if trigger.get("type") == "research_digest" and "digest_id" in trigger:
        digest_id = trigger["digest_id"]
        digests = category.get("digest", {})
        if digest_id in digests:
            digest = digests[digest_id]
            digest_context = f"""
RESEARCH DIGEST:
- Summary: {digest.get('summary', 'N/A')}
- Source: {digest.get('source', 'N/A')}
- Actionable Insight: {digest.get('actionable_insight', 'N/A')}
"""
    
    # Contrarian logic: Check if trigger conflicts with merchant data
    contrarian_context = ""
    if trigger.get("type") == "promo" and "day" in trigger:
        promo_day = trigger["day"].lower()
        
        # Check capacity/footfall data for the promo day
        day_capacity = merchant_data.get(f"{promo_day}_capacity", 0)
        day_footfall = merchant_data.get(f"{promo_day}_footfall", 0)
        
        # If merchant is already at high capacity on promo day, suggest alternative
        if day_capacity > 0 and day_footfall / day_capacity > 0.85:
            # Find low-footfall day as alternative
            low_footfall_day = promo_day
            min_footfall_ratio = 1.0
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
                if day != promo_day:
                    cap = merchant_data.get(f"{day}_capacity", 0)
                    foot = merchant_data.get(f"{day}_footfall", 0)
                    if cap > 0 and foot / cap < min_footfall_ratio:
                        min_footfall_ratio = foot / cap
                        low_footfall_day = day
            
            contrarian_context = f"""
CONTRARIAN INSIGHT:
- The trigger suggests a {promo_day} promo, but the merchant is at {int(day_footfall/day_capacity*100)}% capacity on {promo_day}.
- Consider suggesting moving the promo to {low_footfall_day} instead to fill low-footfall slots.
"""
    
    prompt = f"""
CONTEXT:
- Category Rules: {json.dumps(category)}
- Merchant Info: {json.dumps(merchant)}
- Trigger Event: {json.dumps(trigger)}
- Customer Context: {json.dumps(customer) if customer else "N/A"}
{metrics_context}
{digest_context}
{contrarian_context}
{hinglish_instruction}

Task: Write the first message to the merchant. Mention the specific trigger reason.
COMPELLING ELEMENTS TO INCLUDE:
- Data Anchoring: Reference specific metrics compared to peer medians
- Reciprocity: Show you've already done work ("I've already pulled the abstract for you")
- Curiosity: Reference specific cohorts or data points
- Low-friction CTA: End with "Want me to draft this?", "Should I pull the abstract?", or "Reply 1 to approve"

If a research digest is provided, anchor your message in the digest's actionable insight.
If a contrarian insight is provided, use judgment to suggest a better alternative when the trigger conflicts with merchant data.
"""
    
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json"
            }
        )
        return json.loads(response.text)
    except Exception as e:
        logger.warning(f"LLM fallback in compose_message: {e}")
        return {
            "body": "Hi! I noticed an opportunity to boost your visibility on magicpin. Would you like a quick tip?",
            "cta": "open_ended",
            "template_name": "vera_v1",
            "rationale": f"LLM error fallback: {str(e)}"
        }

async def handle_conversation(history: list, category: dict, merchant: dict):
    """
    Handles multi-turn chat interactions with a merchant.
    
    Args:
        history: List of conversation messages with role and content
        category: Category rules and voice settings
        merchant: Merchant profile and context
    
    Returns:
        dict: JSON response with action, body, rationale, template_name, and cta
    """
    # Data-driven metrics injection with peer comparison
    metrics_context = ""
    merchant_data = merchant.get("data", {})
    peer_stats = category.get("peer_stats", {})
    
    # CTR comparison
    merchant_ctr = merchant_data.get("ctr", 0)
    peer_ctr = peer_stats.get("median_ctr", 0)
    if merchant_ctr > 0 and peer_ctr > 0:
        metrics_context += f"\n- CTR: {merchant_ctr}% (peer median: {peer_ctr}%)"
    
    # Leads comparison
    merchant_leads = merchant_data.get("leads", 0)
    peer_leads = peer_stats.get("median_leads", 0)
    if merchant_leads > 0 and peer_leads > 0:
        metrics_context += f"\n- Leads: {merchant_leads} (peer median: {peer_leads})"
    
    # Signals comparison
    merchant_signals = merchant_data.get("signals", 0)
    peer_signals = peer_stats.get("median_signals", 0)
    if merchant_signals > 0 and peer_signals > 0:
        metrics_context += f"\n- Signals: {merchant_signals} (peer median: {peer_signals})"
    
    if metrics_context:
        metrics_context = f"\nMERCHANT METRICS VS PEER MEDIAN:{metrics_context}"
    
    # Hinglish support based on merchant's language preference
    hinglish_instruction = ""
    merchant_identity = merchant.get("identity", {})
    merchant_languages = merchant_identity.get("languages", [])
    if "hi" in merchant_languages or "hi-en" in merchant_languages:
        hinglish_instruction = "\n\nHINGLISH INSTRUCTION: Talk like a fellow business owner in India. Use natural phrases like 'Apke liye', 'Check kar lijiye', 'Karte hain', 'Chaliye' where appropriate, but keep technical terms (ROI, Scaling, CTR) in English."
    
    prompt = f"""
CONVERSATION HISTORY:
{json.dumps(history)}

MERCHANT CONTEXT:
{json.dumps(merchant)}
{metrics_context}
{hinglish_instruction}

Task: Respond to the merchant's last message. If they agreed to move forward,
provide the very next step in the magicpin onboarding or growth process.

COMPELLING ELEMENTS TO INCLUDE:
- Data Anchoring: Reference specific metrics compared to peer medians
- Reciprocity: Show you've already done work
- Curiosity: Reference specific cohorts or data points
- Low-friction CTA: End with "Want me to draft this?", "Should I pull the abstract?", or "Reply 1 to approve"
"""

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json"
            }
        )
        return json.loads(response.text)
    except Exception as e:
        logger.warning(f"LLM fallback in handle_conversation: {e}")
        return {
            "action": "end",
            "rationale": f"Safety exit due to LLM error: {str(e)}"
        }