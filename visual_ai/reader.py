"""
Visual AI Chart Reading Module (Second Opinion):
Sends rendered chart image to Google Gemini Vision API using a fixed, structured prompt.
Extracts: bias, confidence, patterns, key_levels, risks, and summary in JSON.
Never overrides rule-based stop loss, entry, or take profit. Adjusts confluence score within a strict safety limit (±5).
"""
import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class VisualAIReader:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def analyze_chart_image(self, image_path: str, symbol: str, timeframe: str) -> Dict[str, Any]:
        """
        Sends chart to Gemini Vision and parses structured JSON second opinion.
        Returns fallback default if API key is missing or service rate-limited.
        """
        fallback_res = {
            "bias": "NEUTRAL",
            "confidence": 50,
            "patterns": ["No visual AI key configured or service unavailable"],
            "key_levels": "Relying on rule-based algorithmic levels",
            "risks": ["Visual analysis skipped (rule-based risk rules active)"],
            "summary": "Algorithmic confluence rules applied without secondary visual opinion.",
            "is_available": False,
            "score_delta": 0
        }

        if not self.api_key:
            return fallback_res

        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)

            prompt = (
                f"You are a professional technical analyst reviewing this {symbol} ({timeframe}) trading chart. "
                "Analyze the price action, indicators, moving averages, and structure. "
                "Return ONLY a valid JSON object with the following keys:\n"
                "{\n"
                '  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",\n'
                '  "confidence": <integer from 0 to 100>,\n'
                '  "patterns": ["<pattern 1>", "<pattern 2>"],\n'
                '  "key_levels": "<description of key S/R levels>",\n'
                '  "risks": ["<risk factor 1>", "<risk factor 2>"],\n'
                '  "summary": "<2-sentence plain English summary>"\n'
                "}\n"
                "Do not include markdown code fence formatting or other text outside the JSON."
            )

            with open(image_path, "rb") as f:
                img_bytes = f.read()

            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=[
                    prompt,
                    {"mime_type": "image/png", "data": img_bytes}
                ]
            )

            text = response.text.strip()
            # Clean possible markdown fences
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            data = json.loads(text.strip())

            bias = data.get("bias", "NEUTRAL").upper()
            confidence = int(data.get("confidence", 50))
            score_delta = 0
            if confidence >= 70:
                score_delta = 5 if bias in ["BULLISH", "BEARISH"] else 0
            elif confidence <= 40:
                score_delta = -5

            return {
                "bias": bias,
                "confidence": confidence,
                "patterns": data.get("patterns", []),
                "key_levels": data.get("key_levels", ""),
                "risks": data.get("risks", []),
                "summary": data.get("summary", ""),
                "is_available": True,
                "score_delta": score_delta
            }
        except Exception as e:
            logger.warning(f"Gemini Visual AI analysis failed: {e}")
            fallback_res["summary"] = f"Visual AI unavailable: {str(e)[:60]}"
            return fallback_res
