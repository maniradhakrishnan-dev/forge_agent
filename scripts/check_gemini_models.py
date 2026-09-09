"""
Standalone script to check available Gemini models and test API connectivity.
Lists all models, checks rate limits, and tests a simple completion.

Usage:
    uv run python scripts/check_gemini_models.py
"""

import os
import json
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()


async def list_models(api_key: str):
    """List all available Gemini models for this API key."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        
        if resp.status_code != 200:
            print(f"❌ Failed to list models. HTTP {resp.status_code}")
            print(f"   Response: {resp.text[:500]}")
            return []
        
        data = resp.json()
        models = data.get("models", [])
        return models


async def test_completion(api_key: str, model: str):
    """Test a simple completion with the given model."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Say hello in exactly 3 words."}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 50}
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        
        if resp.status_code != 200:
            try:
                err = resp.json().get("error", {})
                detail = err.get("message", resp.text[:300])
            except Exception:
                detail = resp.text[:300]
            print(f"  ❌ HTTP {resp.status_code}: {detail}")
            return False
        
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            print(f"  ✅ Response: \"{text.strip()}\"")
            return True
        else:
            print(f"  ⚠️  Empty candidates (possible content filter)")
            return False


async def main():
    api_key = os.getenv("GEMINI_API_KEY")
    target_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    if not api_key:
        print("❌ GEMINI_API_KEY not set in .env")
        return
    
    print("=" * 70)
    print(" 🔍 Gemini API Model Checker")
    print("=" * 70)
    print(f"API Key:      {api_key[:10]}...{api_key[-4:]}")
    print(f"Target Model: {target_model}")
    print("-" * 70)
    
    # 1. List all available models
    print("\n📋 Available Gemini Models:")
    models = await list_models(api_key)
    
    if not models:
        print("  No models returned. API key may be invalid.")
        return
    
    # Filter to generative models only
    gen_models = [m for m in models if "generateContent" in m.get("supportedGenerationMethods", [])]
    
    print(f"  Found {len(gen_models)} generative models:\n")
    
    target_found = False
    for m in gen_models:
        name = m.get("name", "").replace("models/", "")
        display = m.get("displayName", "")
        input_limit = m.get("inputTokenLimit", "?")
        output_limit = m.get("outputTokenLimit", "?")
        
        marker = " ◀ YOUR MODEL" if name == target_model else ""
        if name == target_model:
            target_found = True
        
        print(f"  • {name:40s}  input:{input_limit:>10}  output:{output_limit:>10}{marker}")
    
    # 2. Test target model
    print(f"\n{'=' * 70}")
    print(f"🧪 Testing completion with: {target_model}")
    
    if not target_found:
        print(f"  ⚠️  Model '{target_model}' NOT FOUND in available models list!")
        print(f"  Trying anyway (it might be a preview/experimental model)...")
    
    await test_completion(api_key, target_model)
    
    # 3. Suggest alternatives if target failed
    if not target_found:
        print(f"\n💡 Suggested alternatives (flash models):")
        flash_models = [m.get("name", "").replace("models/", "") for m in gen_models if "flash" in m.get("name", "").lower()]
        for fm in flash_models:
            print(f"  • {fm}")


if __name__ == "__main__":
    asyncio.run(main())
