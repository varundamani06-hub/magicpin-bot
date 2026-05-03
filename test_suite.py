"""
Mock Test Suite for magicpin-bot
Tests 6 trigger kinds with 3-turn conversations to validate:
- Context Locking (no retail drift)
- PARSE action for clarifying questions
- Slot-filling for customer bookings
"""

import asyncio
import httpx
import json
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_URL = "http://localhost:8080"

# Test data for 6 trigger kinds
TEST_TRIGGERS = [
    {
        "name": "regulation_change",
        "trigger": {
            "type": "regulation_change",
            "trigger_id": "reg_001",
            "merchant_id": "m_health_001",
            "digest_id": "dci_circular_2026",
            "title": "DCI Circular: Revised Radiograph Dose Limits"
        },
        "merchant": {
            "identity": {"name": "Dr. Meera's Dental Clinic", "languages": ["hi-en"]},
            "category_slug": "healthcare_dental",
            "data": {"ctr": 2.1, "leads": 45, "signals": 120}
        },
        "category": {
            "voice": {"tone": "professional", "register": "peer", "code_mix": "hinglish"},
            "peer_stats": {"median_ctr": 3.0, "median_leads": 60, "median_signals": 150},
            "digest": {
                "dci_circular_2026": {
                    "summary": "DCI revised radiograph dose limits effective Dec 15, 2026",
                    "source": "Dental Council of India",
                    "actionable_insight": "D-speed film will be non-compliant after Dec 15"
                }
            }
        },
        "expected_keywords": ["compliance", "audit", "dose", "DCI", "IOPA"],
        "forbidden_keywords": ["price list", "best sellers", "menu", "catalog"]
    },
    {
        "name": "inventory_stockout",
        "trigger": {
            "type": "inventory_stockout",
            "trigger_id": "stock_001",
            "merchant_id": "m_retail_001",
            "product": "Premium Basmati Rice",
            "stock_level": 0
        },
        "merchant": {
            "identity": {"name": "FreshMart Grocery", "languages": ["en"]},
            "category_slug": "grocery",
            "data": {"ctr": 1.8, "leads": 89, "signals": 200}
        },
        "category": {
            "voice": {"tone": "friendly", "register": "casual", "code_mix": "english"},
            "peer_stats": {"median_ctr": 2.5, "median_leads": 100, "median_signals": 180}
        },
        "expected_keywords": ["restock", "inventory", "stock", "reorder"],
        "forbidden_keywords": ["compliance", "audit", "regulation"]
    },
    {
        "name": "competitor_alert",
        "trigger": {
            "type": "competitor_alert",
            "trigger_id": "comp_001",
            "merchant_id": "m_fashion_001",
            "competitor": "StyleHub",
            "action": "price_drop_20pct"
        },
        "merchant": {
            "identity": {"name": "TrendSetters Boutique", "languages": ["en"]},
            "category_slug": "fashion",
            "data": {"ctr": 2.5, "leads": 67, "signals": 145}
        },
        "category": {
            "voice": {"tone": "urgent", "register": "professional", "code_mix": "english"},
            "peer_stats": {"median_ctr": 3.2, "median_leads": 80, "median_signals": 160}
        },
        "expected_keywords": ["competitor", "price", "promotion", "match"],
        "forbidden_keywords": ["compliance", "audit", "regulation"]
    },
    {
        "name": "festive_surge",
        "trigger": {
            "type": "festive_surge",
            "trigger_id": "fest_001",
            "merchant_id": "m_sweet_001",
            "festival": "Diwali",
            "expected_demand_surge": "3x"
        },
        "merchant": {
            "identity": {"name": "Mithai Palace", "languages": ["hi-en"]},
            "category_slug": "sweets",
            "data": {"ctr": 3.1, "leads": 112, "signals": 250}
        },
        "category": {
            "voice": {"tone": "celebratory", "register": "warm", "code_mix": "hinglish"},
            "peer_stats": {"median_ctr": 2.8, "median_leads": 95, "median_signals": 200}
        },
        "expected_keywords": ["Diwali", "stock", "demand", "festival"],
        "forbidden_keywords": ["compliance", "audit", "regulation"]
    },
    {
        "name": "low_rating",
        "trigger": {
            "type": "low_rating",
            "trigger_id": "rating_001",
            "merchant_id": "m_salon_001",
            "current_rating": 3.2,
            "review_count": 24,
            "common_complaint": "long wait times"
        },
        "merchant": {
            "identity": {"name": "Glamour Studio", "languages": ["en"]},
            "category_slug": "salon",
            "data": {"ctr": 1.5, "leads": 34, "signals": 78}
        },
        "category": {
            "voice": {"tone": "constructive", "register": "professional", "code_mix": "english"},
            "peer_stats": {"median_ctr": 2.2, "median_leads": 50, "median_signals": 120}
        },
        "expected_keywords": ["rating", "review", "improve", "feedback"],
        "forbidden_keywords": ["compliance", "audit", "regulation"]
    },
    {
        "name": "trend_shift",
        "trigger": {
            "type": "trend_shift",
            "trigger_id": "trend_001",
            "merchant_id": "m_cafe_001",
            "trend": "plant-based_milk",
            "growth_rate": "45%"
        },
        "merchant": {
            "identity": {"name": "Brew & Bean Cafe", "languages": ["en"]},
            "category_slug": "cafe",
            "data": {"ctr": 2.0, "leads": 56, "signals": 130}
        },
        "category": {
            "voice": {"tone": "insightful", "register": "peer", "code_mix": "english"},
            "peer_stats": {"median_ctr": 2.7, "median_leads": 70, "median_signals": 150}
        },
        "expected_keywords": ["trend", "plant-based", "oat", "almond", "menu"],
        "forbidden_keywords": ["compliance", "audit", "regulation"]
    }
]


async def test_trigger(test_case):
    """Test a single trigger with 3-turn conversation"""
    print(f"\n{'='*60}")
    print(f"Testing: {test_case['name']}")
    print(f"{'='*60}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Push context
            print("  Pushing merchant context...")
            ctx1 = await client.post(f"{BASE_URL}/v1/context", json={
                "scope": "merchant",
                "context_id": test_case["trigger"]["merchant_id"],
                "version": 1,
                "payload": test_case["merchant"],
                "delivered_at": "2026-05-03T10:00:00Z"
            })
            print(f"    Status: {ctx1.status_code}")
            
            print("  Pushing category context...")
            ctx2 = await client.post(f"{BASE_URL}/v1/context", json={
                "scope": "category",
                "context_id": test_case["merchant"]["category_slug"],
                "version": 1,
                "payload": test_case["category"],
                "delivered_at": "2026-05-03T10:00:00Z"
            })
            print(f"    Status: {ctx2.status_code}")
            
            print("  Pushing trigger context...")
            ctx3 = await client.post(f"{BASE_URL}/v1/context", json={
                "scope": "trigger",
                "context_id": test_case["trigger"]["trigger_id"],
                "version": 1,
                "payload": test_case["trigger"],
                "delivered_at": "2026-05-03T10:00:00Z"
            })
            print(f"    Status: {ctx3.status_code}")
            
            # Step 2: Generate initial message (Turn 1)
            print("  Generating initial message...")
            tick_response = await client.post(f"{BASE_URL}/v1/tick", json={
                "available_triggers": [test_case["trigger"]["trigger_id"]]
            })
            print(f"    Tick Status: {tick_response.status_code}")
            
            if tick_response.status_code != 200:
                print(f"    [X] Tick failed: {tick_response.text}")
                return None
            
            tick_data = tick_response.json()
            print(f"    Tick data: {tick_data}")
            
            if tick_data.get("actions"):
                action = tick_data["actions"][0]
                conv_id = action["conversation_id"]
                initial_body = action.get("body", "")
                
                print(f"\nTurn 1 - Bot Message:")
                print(f"  {initial_body[:200]}...")
                
                # Check for retail drift
                forbidden_found = [kw for kw in test_case["forbidden_keywords"] if kw.lower() in initial_body.lower()]
                if forbidden_found:
                    print(f"  [X] RETAIL DRIFT DETECTED: Found forbidden keywords: {forbidden_found}")
                else:
                    print(f"  [OK] No retail drift")
                
                # Check for expected keywords
                expected_found = [kw for kw in test_case["expected_keywords"] if kw.lower() in initial_body.lower()]
                print(f"  Expected keywords found: {expected_found}/{len(test_case['expected_keywords'])}")
                
                # Step 3: Merchant asks clarifying question (Turn 2 - PARSE test)
                print(f"\n  Sending merchant reply...")
                reply_response = await client.post(f"{BASE_URL}/v1/reply", json={
                    "conversation_id": conv_id,
                    "merchant_id": test_case["trigger"]["merchant_id"],
                    "message": "Can you explain more about this?"
                })
                print(f"    Reply Status: {reply_response.status_code}")
                
                if reply_response.status_code != 200:
                    print(f"    [X] Reply failed: {reply_response.text}")
                    return None
                
                reply_data = reply_response.json()
                
                print(f"\nTurn 2 - Merchant: 'Can you explain more about this?'")
                print(f"  Bot Action: {reply_data.get('action')}")
                if reply_data.get('action') == 'parse':
                    print(f"  [OK] Correctly used PARSE for clarifying question")
                else:
                    print(f"  [!] Expected PARSE, got {reply_data.get('action')}")
                
                # Step 4: Customer picks slot (Turn 3 - Slot-filling test)
                print(f"\n  Sending customer reply...")
                customer_reply = await client.post(f"{BASE_URL}/v1/reply", json={
                    "conversation_id": conv_id,
                    "merchant_id": test_case["trigger"]["merchant_id"],
                    "customer_id": "c_test_001",
                    "message": "Yes please book me for Wed 5 Nov, 6pm."
                })
                print(f"    Customer Reply Status: {customer_reply.status_code}")
                
                if customer_reply.status_code != 200:
                    print(f"    [X] Customer reply failed: {customer_reply.text}")
                    return None
                
                customer_data = customer_reply.json()
                
                print(f"\nTurn 3 - Customer: 'Yes please book me for Wed 5 Nov, 6pm.'")
                print(f"  Bot Action: {customer_data.get('action')}")
                customer_body = customer_data.get("body", "")
                print(f"  Response: {customer_body[:200]}...")
                
                # Check if slot was echoed back
                if "wed" in customer_body.lower() and ("nov" in customer_body.lower() or "5" in customer_body) and "6pm" in customer_body.lower():
                    print(f"  [OK] Slot correctly echoed back")
                else:
                    print(f"  [X] Slot NOT echoed back - missing specific date/time")
                
                # Final retail drift check
                final_forbidden = [kw for kw in test_case["forbidden_keywords"] if kw.lower() in customer_body.lower()]
                if final_forbidden:
                    print(f"  [X] FINAL RETAIL DRIFT: {final_forbidden}")
                else:
                    print(f"  [OK] No retail drift in final response")
                
                return {
                    "trigger": test_case["name"],
                    "initial_drift": len(forbidden_found) > 0,
                    "parse_correct": reply_data.get('action') == 'parse',
                    "slot_echoed": "wed" in customer_body.lower() and "6pm" in customer_body.lower(),
                    "final_drift": len(final_forbidden) > 0
                }
            else:
                print(f"  [X] No actions returned from tick")
                return None
    except Exception as e:
        print(f"  [X] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def run_test_suite():
    """Run all 6 trigger tests"""
    print("\n" + "="*60)
    print("MOCK TEST SUITE - 6 Trigger Kinds")
    print("="*60)
    
    results = []
    for i, test_case in enumerate(TEST_TRIGGERS):
        result = await test_trigger(test_case)
        if result:
            results.append(result)
        
        # Add delay between tests to avoid API rate limits (free tier: 5 req/min)
        if i < len(TEST_TRIGGERS) - 1:
            print(f"\n  Waiting 15 seconds to avoid API rate limit...")
            await asyncio.sleep(15)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    if not results:
        print("[X] No tests completed successfully")
        print("Check the bot is running and API key is configured")
        return
    
    passed = 0
    for r in results:
        status = "[OK] PASS" if all([not r["initial_drift"], r["parse_correct"], r["slot_echoed"], not r["final_drift"]]) else "[X] FAIL"
        print(f"{r['trigger']}: {status}")
        if all([not r["initial_drift"], r["parse_correct"], r["slot_echoed"], not r["final_drift"]]):
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    print(f"Score Estimate: {int((passed/len(results)) * 100)}/100")


if __name__ == "__main__":
    asyncio.run(run_test_suite())
