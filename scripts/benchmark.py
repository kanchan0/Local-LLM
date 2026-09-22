from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ollama import Client


PROMPTS = [
    "Explain a difficult technical concept in simple language.",
    "Correct the grammar and punctuation in: This sentence have several errors and it need correction.",
    "Write a short Python function that validates an email address and explain it.",
    "Summarize the following paragraph in five bullet points: Local inference keeps prompts on infrastructure controlled by the operator, but performance depends on available memory, model size, and concurrent requests.",
    "हिंदी वाक्य को व्याकरण और वर्तनी के अनुसार सुधारें: यह एक उदाहरण वाक्य है जिसमे कुछ गलतिया है।",
]


def benchmark_model(client: Client, model: str) -> dict:
    results = []
    for prompt in PROMPTS:
        started = time.perf_counter()
        first_token_at = None
        final = None
        parts = []
        stream = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in stream:
            text = getattr(getattr(chunk, "message", None), "content", "") or ""
            if text and first_token_at is None:
                first_token_at = time.perf_counter()
            parts.append(text)
            if getattr(chunk, "done", False):
                final = chunk
        ended = time.perf_counter()
        eval_count = getattr(final, "eval_count", None) if final else None
        eval_duration = getattr(final, "eval_duration", None) if final else None
        results.append(
            {
                "prompt": prompt,
                "response_chars": len("".join(parts)),
                "time_to_first_token_seconds": (first_token_at - started) if first_token_at else None,
                "wall_seconds": ended - started,
                "tokens_per_second": (eval_count / (eval_duration / 1_000_000_000)) if eval_count and eval_duration else None,
            }
        )
    return {"model": model, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark candidate Ollama models")
    parser.add_argument("models", nargs="+", help="Ollama model tags to benchmark")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()

    client = Client(host=args.host)
    report = {"host": args.host, "models": [benchmark_model(client, model) for model in args.models]}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
