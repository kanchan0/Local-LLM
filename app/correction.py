from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .documents import DocumentError, build_corrected_docx, make_chunks, parse_document
from .ollama_service import OllamaService


ProgressCallback = Callable[[str, int, int], Awaitable[None]]


@dataclass
class CorrectionResult:
    output_path: Path
    output_name: str
    notes: list[str]
    block_count: int


async def correct_document(
    input_path: Path,
    output_path: Path,
    original_name: str,
    ollama: OllamaService,
    *,
    max_pdf_pages: int,
    max_docx_chars: int,
    progress: ProgressCallback | None = None,
) -> CorrectionResult:
    parsed = parse_document(
        input_path,
        max_pdf_pages=max_pdf_pages,
        max_docx_chars=max_docx_chars,
    )
    chunks = make_chunks(parsed.blocks)
    corrections: dict[str, str] = {}
    notes: list[str] = []

    for index, chunk in enumerate(chunks, start=1):
        if progress:
            await progress("correcting", index, len(chunks))
        response: dict[str, Any] = await ollama.correct_chunk(chunk)
        returned_ids: set[str] = set()
        for item in response.get("blocks", []):
            if not isinstance(item, dict):
                continue
            block_id = item.get("id")
            corrected_text = item.get("corrected_text")
            if not isinstance(block_id, str) or not isinstance(corrected_text, str):
                continue
            if block_id not in {block.block_id for block in chunk}:
                continue
            corrections[block_id] = corrected_text
            returned_ids.add(block_id)
            item_notes = item.get("notes", [])
            if isinstance(item_notes, list):
                notes.extend(str(note).strip() for note in item_notes if str(note).strip())
        for block in chunk:
            corrections.setdefault(block.block_id, block.text)
        if not returned_ids:
            raise DocumentError("The model did not return corrections for this document section.")

    if progress:
        await progress("writing", len(chunks), len(chunks))
    build_corrected_docx(parsed, corrections, output_path)
    unique_notes = list(dict.fromkeys(notes))[:30]
    if not unique_notes:
        unique_notes = ["The document was reviewed; no material corrections were reported."]
    return CorrectionResult(
        output_path=output_path,
        output_name=f"{Path(original_name).stem}_corrected.docx",
        notes=unique_notes,
        block_count=len(parsed.blocks),
    )
