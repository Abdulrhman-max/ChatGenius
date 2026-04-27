"""
Thorough testing suite for the fine-tuned ChatGenius model.
Runs automated tests across all knowledge categories + interactive mode.
"""

import json
import os
import sys
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "chatgenius-tinyllama")
BASE_MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

SYSTEM_MSG = (
    "You are ChatGenius AI, a friendly and knowledgeable sales assistant for ChatGenius — "
    "an AI-powered chatbot platform for small and medium businesses. "
    "Answer customer questions accurately and concisely using your training data. "
    "Be warm, professional, and helpful. Guide visitors toward starting a free trial when appropriate."
)


def load_model():
    """Load the fine-tuned model."""
    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)

    print("Loading base model...")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.float32,
    )

    print("Loading LoRA adapters...")
    model = PeftModel.from_pretrained(base_model, MODEL_DIR)
    model.eval()

    print("Model loaded successfully!\n")
    return model, tokenizer


def generate_response(model, tokenizer, user_message, max_new_tokens=256):
    """Generate a response from the model."""
    prompt = (
        f"<|system|>\n{SYSTEM_MSG}</s>\n"
        f"<|user|>\n{user_message}</s>\n"
        f"<|assistant|>\n"
    )

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            repetition_penalty=1.2,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode only the new tokens
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    # Clean up - stop at end markers
    for stop in ["</s>", "<|user|>", "<|system|>", "\n\n\n"]:
        if stop in response:
            response = response[:response.index(stop)].strip()

    return response


# ── Test Cases ──
TEST_CASES = {
    "Greetings": [
        {"input": "Hi there!", "expect_contains": ["chatgenius", "help", "welcome"]},
        {"input": "Hello, what do you do?", "expect_contains": ["chatbot", "business"]},
    ],
    "Pricing": [
        {"input": "How much does ChatGenius cost?", "expect_contains": ["149", "349", "799"]},
        {"input": "Is there a free trial?", "expect_contains": ["14", "free", "trial"]},
        {"input": "What's in the Pro plan?", "expect_contains": ["349", "pro"]},
        {"input": "Do you offer discounts?", "expect_contains": ["annual", "20%"]},
    ],
    "Features": [
        {"input": "What features do you offer?", "expect_contains": ["24/7", "lead", "appointment"]},
        {"input": "Can the chatbot book appointments?", "expect_contains": ["appointment", "booking", "calendar"]},
        {"input": "How does lead capture work?", "expect_contains": ["lead", "capture", "contact"]},
        {"input": "What languages do you support?", "expect_contains": ["language", "english"]},
    ],
    "Setup": [
        {"input": "How do I set it up%s", "expect_contains": ["setup", "minute", "code"]},
        {"input": "Do I need a developer?", "expect_contains": ["no", "code"]},
    ],
    "Industries": [
        {"input": "Does it work for dental offices%s", "expect_contains": ["dental", "appointment"]},
        {"input": "Can I use it for my restaurant%s", "expect_contains": ["restaurant", "menu"]},
        {"input": "What industries do you support?", "expect_contains": ["industry", "business"]},
    ],
    "Security": [
        {"input": "Is my data safe?", "expect_contains": ["encrypt", "gdpr", "safe", "secure"]},
        {"input": "Are you GDPR compliant?", "expect_contains": ["gdpr", "compliant"]},
    ],
    "Comparisons": [
        {"input": "How are you different from Intercom%s", "expect_contains": ["intercom"]},
        {"input": "Why choose ChatGenius over regular chatbots?", "expect_contains": ["ai", "chatbot"]},
    ],
    "Support": [
        {"input": "What support do you offer?", "expect_contains": ["support", "email"]},
    ],
    "Getting Started": [
        {"input": "I want to get started", "expect_contains": ["start", "free", "trial"]},
        {"input": "Do I need a credit card?", "expect_contains": ["credit card", "no"]},
    ],
    "Farewell": [
        {"input": "Thanks for the help!", "expect_contains": ["welcome", "question", "trial"]},
    ],
}


def run_automated_tests(model, tokenizer):
    """Run all automated test cases."""
    print("=" * 70)
    print("  AUTOMATED TEST SUITE")
    print("=" * 70)

    total = 0
    passed = 0
    failed_cases = []

    for category, tests in TEST_CASES.items():
        print(f"\n--- {category} ---")
        for test in tests:
            total += 1
            user_input = test["input"]
            expect = test["expect_contains"]

            response = generate_response(model, tokenizer, user_input)
            response_lower = response.lower()

            # Check if any expected keyword appears
            found = [kw for kw in expect if kw.lower() in response_lower]
            test_passed = len(found) > 0

            status = "PASS" if test_passed else "FAIL"
            if test_passed:
                passed += 1
            else:
                failed_cases.append({
                    "category": category,
                    "input": user_input,
                    "expected": expect,
                    "response": response,
                })

            print(f"  [{status}] \"{user_input}\"")
            print(f"         Response: {response[:120]}{'...' if len(response) > 120 else ''}")
            if not test_passed:
                print(f"         Expected one of: {expect}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  RESULTS: {passed}/{total} passed ({passed/total*100:.1f}%)")
    print(f"{'=' * 70}")

    if failed_cases:
        print(f"\n  Failed cases ({len(failed_cases)}):")
        for fc in failed_cases:
            print(f"    - [{fc['category']}] \"{fc['input']}\"")
            print(f"      Expected: {fc['expected']}")
            print(f"      Got: {fc['response'][:100]}")

    # Save results
    results_path = os.path.join(os.path.dirname(__file__), "..", "models", "test_results.json")
    results = {
        "total": total,
        "passed": passed,
        "pass_rate": f"{passed/total*100:.1f}%",
        "failed_cases": failed_cases,
    }
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to {results_path}")

    return passed, total


def run_quality_tests(model, tokenizer):
    """Test response quality: length, coherence, no hallucination."""
    print(f"\n{'=' * 70}")
    print("  QUALITY CHECKS")
    print("=" * 70)

    quality_tests = [
        {
            "name": "Response length (not too short)",
            "input": "Tell me about ChatGenius",
            "check": lambda r: len(r) > 50,
        },
        {
            "name": "Response length (not too long)",
            "input": "What's the price?",
            "check": lambda r: len(r) < 1500,
        },
        {
            "name": "No hallucinated prices",
            "input": "How much is the Basic plan?",
            "check": lambda r: "$149" in r or "149" in r,
        },
        {
            "name": "Stays on topic (doesn't talk about unrelated things)",
            "input": "What's the weather like?",
            "check": lambda r: any(w in r.lower() for w in ["chatgenius", "chatbot", "help", "question", "assist", "business"]),
        },
        {
            "name": "Doesn't generate gibberish",
            "input": "Can you help me?",
            "check": lambda r: len(r.split()) > 5 and not any(c * 5 in r for c in "abcdefghijklmnopqrstuvwxyz"),
        },
        {
            "name": "Handles unknown gracefully",
            "input": "What's the meaning of life?",
            "check": lambda r: len(r) > 10,  # Should respond somehow, not crash
        },
    ]

    passed = 0
    for test in quality_tests:
        response = generate_response(model, tokenizer, test["input"])
        result = test["check"](response)
        status = "PASS" if result else "FAIL"
        if result:
            passed += 1
        print(f"  [{status}] {test['name']}")
        print(f"         Input: \"{test['input']}\"")
        print(f"         Response: {response[:120]}{'...' if len(response) > 120 else ''}")

    print(f"\n  Quality: {passed}/{len(quality_tests)} passed")
    return passed, len(quality_tests)


def interactive_mode(model, tokenizer):
    """Interactive chat mode for manual testing."""
    print(f"\n{'=' * 70}")
    print("  INTERACTIVE CHAT MODE")
    print("  Type your messages to test. Type 'quit' to exit.")
    print("=" * 70)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Exiting interactive mode.")
            break

        response = generate_response(model, tokenizer, user_input)
        print(f"Bot: {response}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    model, tokenizer = load_model()

    if mode in ("all", "auto"):
        auto_passed, auto_total = run_automated_tests(model, tokenizer)
        qual_passed, qual_total = run_quality_tests(model, tokenizer)

        total_p = auto_passed + qual_passed
        total_t = auto_total + qual_total
        print(f"\n{'=' * 70}")
        print(f"  OVERALL: {total_p}/{total_t} tests passed ({total_p/total_t*100:.1f}%)")
        print(f"{'=' * 70}")

    if mode in ("all", "interactive"):
        interactive_mode(model, tokenizer)


if __name__ == "__main__":
    main()
