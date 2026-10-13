import json
from typing import Any, Dict

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.part_library import PartLibraryError, load_catalog
from rhinoclaw.utils.responses import from_exception, ok


def _score(part: Dict[str, Any], query: str) -> int:
    """Rank: exact id/article > exact name > prefix > substring > keyword.
    0 = no match. Tolerant of missing fields."""
    part_id = str(part.get("id") or "").lower()
    name = str(part.get("display_name") or "").lower()
    vendor = str(part.get("vendor") or "").lower()
    article = str(part.get("article_no") or "").lower()
    block = str(part.get("block_name") or "").lower()
    keywords = [str(k).lower() for k in part.get("keywords") or []]

    if part_id == query or article == query:
        return 100
    if name == query:
        return 90
    if part_id.startswith(query) or name.startswith(query):
        return 80
    if query in name or query in part_id or query in block:
        return 60
    if query in keywords:
        return 55
    tokens = query.split()
    haystack = " ".join([part_id, name, vendor, article, block] + keywords)
    if len(tokens) > 1 and all(token in haystack for token in tokens):
        return 50
    if query in vendor or query in article:
        return 45
    if any(query in k for k in keywords):
        return 40
    if any(token in haystack for token in tokens):
        return 25
    return 0


@mcp.tool()
def find_library_part(
    ctx: Context,
    query: str,
    limit: int = 5,
) -> str:
    """
    Search the file-based part library (door hardware etc.) by name,
    vendor, article number, or keyword.

    Reads <RHINOCLAW_LIBRARY_DIR>/catalog.json — a pure offline lookup, no
    Rhino call. Use the returned `id` with insert_library_part(part_id=...)
    to place a part with its verified insertion frame.

    Parameters:
    - query: Search words (e.g. "glutz topaz", "5632C", "schliessblech").
    - limit: Max results (default 5).

    Returns:
        {"success": true, "data": {"matches": [{"id", "display_name",
            "vendor", "article_no", "block_name", "frames", ...}],
         "catalog": {"part_count": ..., "meta": {...}}}}
    """
    try:
        if not query or not query.strip():
            raise ValueError("query is required")
        q = query.strip().lower()
        limit = max(1, min(int(limit), 50))

        catalog = load_catalog()
        parts = catalog["parts"]
        scored = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            score = _score(part, q)
            if score:
                name = str(part.get("display_name") or part.get("id") or "")
                # tie-break: shorter name = more canonical/specific
                scored.append((score, len(name), name, part))
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        matches = [p for _, _, _, p in scored[:limit]]

        meta = catalog.get("meta") or {}
        if not matches:
            return json.dumps(ok(
                message=f"No part matches '{query}'",
                data={
                    "matches": [],
                    "hint": "try fewer/other words, the vendor name, or the article number",
                    "catalog": {"part_count": len(parts), "meta": meta},
                },
            ))

        best = matches[0]
        best_label = best.get("display_name") or best.get("id") or "?"
        return json.dumps(ok(
            message=f"{len(matches)} match(es) for '{query}' — best: "
                    f"{best_label} (id: {best.get('id')})",
            data={
                "matches": matches,
                "catalog": {"part_count": len(parts), "meta": meta},
            },
        ))
    except PartLibraryError as e:
        logger.error(f"Part library not available: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error searching part library: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
