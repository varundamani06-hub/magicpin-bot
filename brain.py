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

CATEGORY-SPECIFIC CONTEXT LOCK:
- If trigger_type is 'regulation_change' (Healthcare/Clinic): STRICTLY FORBID mentions of "Price Lists", "Best Sellers", "Menu Updates", "Catalog optimization". Focus ONLY on "Compliance", "Audits", "Operational Standards", "Regulatory requirements".
- If trigger_type is 'promo' or 'catalog': Focus on "Price Lists", "Best Sellers", "Menu Updates", "Catalog optimization".
- NEVER mix topics - stay locked to the trigger's category domain.

COMPELLING MESSAGE ELEMENTS:
- Reciprocity: Show you've already done work ("I've already pulled the abstract for you")
- Curiosity: Reference specific cohorts or data points ("This affects your 124 high-risk patients")
- Data Anchoring: Compare merchant metrics to peer medians ("Your CTR is 2.1% vs peer median of 3.0%")

ACTION RULES:
- ACTION 'send': Use when merchant is interested or when confirming a customer booking. Mention a SPECIFIC business goal anchored in their data.
- ACTION 'parse': Use when merchant asks a clarifying question or needs more information before proceeding. This indicates intent understanding is needed.
- ACTION 'wait': Use for auto-replies.
- ACTION 'end': Use for hostile merchants OR after 3+ auto-replies.

SLOT-FILLING FOR CUSTOMER BOOKINGS:
- If a customer provides a date/time (e.g., "Wed 5 Nov, 6pm"), you MUST explicitly repeat that slot in your response: "Confirmed for Wednesday, Nov 5th at 6pm."
- Never give a generic confirmation - always echo back the specific details.

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
    
    # Determine if this is a customer-facing message
    is_customer_facing = customer is not None
    
    # Adjust task instruction based on scope
    if is_customer_facing:
        task_instruction = f"""
Task: Write a message FROM THE MERCHANT to the CUSTOMER. 
- Address the customer by name: {customer.get('identity', {}).get('name', 'there')}
- The merchant ({merchant.get('identity', {}).get('name', 'your business')}) is sending this message
- Mention the specific trigger reason from the customer's perspective
- This should feel like a personal message from the business to their customer
"""
    else:
        # Enhanced Hinglish instruction for regulation_change triggers
        trigger_type = trigger.get("type", "")
        if trigger_type == "regulation_change":
            task_instruction = """
Task: Write the first message to the merchant about a REGULATION CHANGE.
- Use NATURAL HINGLISH mixing: Mix Hindi phrases with English technical terms
- Example style: "IOPA exposure ke liye maximum dose kam ho gaya hai. Agar aap D-speed film use karte hain..."
- Keep technical terms in English (IOPA, DCI, RVG, dose limits)
- Explain the regulation clearly, then offer a compliance audit
- End with a low-friction CTA about scheduling the audit
"""
        else:
            task_instruction = """
Task: Write the first message to the merchant. Mention the specific trigger reason.
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

{task_instruction}
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

def calculate_relevance_score(response_body: str, trigger_context: dict, is_customer_facing: bool) -> float:
    """
    Calculates relevance score of response to current conversation context.
    Returns score between 0.0 and 1.0.
    """
    if not trigger_context:
        return 1.0  # No context to check against
    
    trigger = trigger_context.get("trigger", {})
    trigger_type = trigger.get("type", "")
    initial_msg = trigger_context.get("initial_message", "").lower()
    response_lower = response_body.lower()
    
    score = 1.0
    
    # Retail drift detection - penalize irrelevant topic mentions
    if trigger_type == "regulation_change":
        # For regulation_change, penalize retail terms
        retail_terms = ["price list", "best sellers", "menu", "catalog", "inventory", "stock"]
        for term in retail_terms:
            if term in response_lower:
                score -= 0.3
                logger.warning(f"Retail drift detected: '{term}' in regulation_change conversation")
    
    elif trigger_type in ["promo", "catalog", "inventory_stockout"]:
        # For retail triggers, penalize compliance terms
        compliance_terms = ["compliance", "audit", "regulation", "dci", "dose"]
        for term in compliance_terms:
            if term in response_lower:
                score -= 0.3
                logger.warning(f"Topic drift detected: '{term}' in retail conversation")
    
    # Slot-filling check for customer conversations
    if is_customer_facing:
        # Check if customer mentioned date/time in previous message
        if history := trigger_context.get("history", []):
            last_msg = history[-1].get("content", "").lower() if history else ""
            # Simple date/time indicators
            date_indicators = ["mon", "tue", "wed", "thu", "fri", "sat", "sun", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            if any(ind in last_msg for ind in date_indicators):
                # Customer mentioned a date - check if response echoes it
                if not any(ind in response_lower for ind in date_indicators):
                    score -= 0.4
                    logger.warning("Slot-filling failure: Date mentioned but not echoed in response")
    
    return max(0.0, score)


async def handle_conversation(history: list, category: dict, merchant: dict, customer: dict = None, trigger_context: dict = None):
    """
    Handles multi-turn chat interactions with a merchant or customer.
    
    Args:
        history: List of conversation messages with role and content
        category: Category rules and voice settings
        merchant: Merchant profile and context
        customer: Optional customer context for customer-facing conversations
        trigger_context: Original trigger that started this conversation for state awareness
    
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
    
    # Extract the last message for context
    last_message = history[-1].get("content", "") if history else ""
    
    # Determine if this is a customer-facing conversation
    is_customer_facing = customer is not None
    
    # Build trigger context for state awareness
    trigger_context_str = ""
    if trigger_context:
        trigger = trigger_context.get("trigger", {})
        initial_msg = trigger_context.get("initial_message", "")
        trigger_type = trigger.get("type", "unknown")
        trigger_context_str = f"""
ORIGINAL TRIGGER CONTEXT:
- Trigger Type: {trigger_type}
- Trigger Details: {json.dumps(trigger)}
- Initial Message Sent: "{initial_msg}"

CRITICAL STATE AWARENESS: This conversation started because of the above trigger. 
STAY ON TOPIC related to this trigger. Do NOT switch to unrelated topics like generic price lists or catalog optimization.
If the trigger was about regulation_change/X-ray compliance, continue discussing X-ray audits/compliance.
If the trigger was about a customer booking, continue discussing the booking/scheduling.
"""
    
    # Adjust task instruction based on scope
    if is_customer_facing:
        # Extract date/time from customer message for slot confirmation
        import re
        date_time_pattern = r'(?:on|at|for)?\s*(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)[a-z]*\s*(?:\d{1,2}(?:st|nd|rd|th)?\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)?(?:\s*,?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?'
        date_time_match = re.search(date_time_pattern, last_message, re.IGNORECASE)
        detected_slot = date_time_match.group(0) if date_time_match else ""
        
        task_instruction = f"""
Task: Respond to the CUSTOMER's message on behalf of the MERCHANT.
- Customer: {customer.get('identity', {}).get('name', 'there')}
- Merchant: {merchant.get('identity', {}).get('name', 'your business')}
- DETECTED SLOT: "{detected_slot}" - If this is non-empty, the customer mentioned a specific date/time
- If the customer is booking a slot (mentions date/time), you MUST CONFIRM by repeating the EXACT date/time they mentioned in your response
- Example: If they say "book me for Wed 5 Nov, 6pm", respond with "Confirmed for Wednesday, Nov 5th at 6pm."
- If the customer agrees to something, provide the next step or confirmation
- Keep it personal and warm, as if from the business owner to their customer
- NO business metrics or peer comparisons - this is B2C communication
"""
    else:
        # Check if merchant agreed to move forward
        last_msg_lower = last_message.lower()
        is_agreement = any(phrase in last_msg_lower for phrase in ["ok lets do it", "ok let's do it", "what's next", "whats next", "lets start", "let's start", "yes let's", "yes lets", "sounds good", "great"])
        
        if is_agreement:
            task_instruction = """
Task: Merchant has AGREED to move forward. Provide the NEXT STEP.
- The merchant said "Ok lets do it" or similar agreement phrase
- Tell them EXACTLY what happens next (e.g., "I'll schedule the audit", "I'll prepare the report", "Let me draft the proposal")
- Be specific about the action you will take
- End with a confirmation or timeline
- NO vague responses like "I'll look into it" or "I've started looking"
"""
        else:
            task_instruction = """
Task: Respond to the merchant's last message. 
- READ AND UNDERSTAND their specific request or question
- Provide a DIRECT, RELEVANT response to what they asked
- If they asked about a specific topic (e.g., X-ray setup, pricing, etc.), address that specifically
- NEVER give generic responses about unrelated topics like "price list optimization" unless that's what they asked about
"""
    
    prompt = f"""
CONVERSATION HISTORY:
{json.dumps(history)}

MERCHANT CONTEXT:
{json.dumps(merchant)}
{metrics_context}
{hinglish_instruction}
CUSTOMER CONTEXT:
{json.dumps(customer) if customer else "N/A"}
{trigger_context_str}

{task_instruction}

COMPELLING ELEMENTS TO INCLUDE:
- Data Anchoring: Reference specific metrics compared to peer medians (ONLY for merchant conversations)
- Reciprocity: Show you've already done work
- Curiosity: Reference specific cohorts or data points (ONLY for merchant conversations)
- Low-friction CTA: End with "Want me to draft this?", "Should I pull the abstract?", or "Reply 1 to approve" (ONLY for merchant conversations)

CRITICAL RESPONSE RULES:
1. STAY ON THE ORIGINAL TRIGGER TOPIC - Do not switch to generic merchant optimization topics
2. For merchant conversations: If they mentioned X-ray equipment, talk about X-ray equipment. If they mentioned pricing, talk about pricing.
3. For customer conversations: If they're booking a slot, CONFIRM the specific date/time they mentioned (e.g., "Got it! I've booked you for Wed 5 Nov at 6pm").
4. Never give a generic "price list optimization" response unless the conversation is actually about pricing/catalogs.
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
        result = json.loads(response.text)
        
        # Confidence check with context recovery
        relevance_score = calculate_relevance_score(result.get("body", ""), trigger_context, is_customer_facing)
        
        if relevance_score < 0.8:
            logger.warning(f"Low relevance score ({relevance_score:.2f}) - triggering context recovery")
            
            # Context recovery prompt
            recovery_prompt = f"""
CONTEXT RECOVERY NEEDED:
The previous response had low relevance ({relevance_score:.2f}) to the conversation context.

ORIGINAL TRIGGER CONTEXT:
- Trigger Type: {trigger_context.get('trigger', {}).get('type', 'unknown') if trigger_context else 'unknown'}
- Initial Message: "{trigger_context.get('initial_message', '') if trigger_context else ''}"

PREVIOUS RESPONSE (LOW RELEVANCE):
{json.dumps(result)}

TASK: Rewrite the response to be HIGHLY RELEVANT to the original trigger topic.
- If trigger was regulation_change: Focus ONLY on compliance/audits, NO retail terms
- If trigger was retail-related: Focus on inventory/pricing, NO compliance terms
- If customer mentioned a date/time: ECHO that specific date/time in your response
- Stay locked to the original conversation topic

Return ONLY JSON with "action", "body", "rationale", "template_name", and "cta".
"""
            
            try:
                recovery_response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=recovery_prompt,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "response_mime_type": "application/json"
                    }
                )
                recovery_result = json.loads(recovery_response.text)
                recovery_result["rationale"] = f"{recovery_result.get('rationale', '')} (Context recovery applied)"
                logger.info("Context recovery successful")
                return recovery_result
            except Exception as recovery_error:
                logger.warning(f"Context recovery failed: {recovery_error}")
                return result
        
        return result
    except Exception as e:
        logger.warning(f"LLM fallback in handle_conversation: {e}")
        return {
            "action": "end",
            "rationale": f"Safety exit due to LLM error: {str(e)}"
        }