"""
app/utils/pagination.py — Pagination helpers.
Supports simple page/limit pagination compatible with MongoDB skip/limit.
"""

from typing import Any, Dict, List
from flask import request


def get_pagination_params(default_limit: int = 20, max_limit: int = 100) -> tuple:
    """
    Parse `page` and `limit` from the current request's query string.
    Returns (page: int, limit: int, skip: int).
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(max(1, int(request.args.get("limit", default_limit))), max_limit)
    except (TypeError, ValueError):
        page, limit = 1, default_limit

    skip = (page - 1) * limit
    return page, limit, skip


def paginate_response(
    items: List[Any],
    total: int,
    page: int,
    limit: int,
    serializer=None,
) -> Dict:
    """
    Build a standardised paginated response envelope.

    Args:
        items:      List of documents from MongoDB (may be plain dicts).
        total:      Total count of matching documents (used for page math).
        page:       Current page number (1-indexed).
        limit:      Items per page.
        serializer: Optional callable(doc) → dict for field selection / ObjectId handling.
    """
    if serializer:
        items = [serializer(item) for item in items]

    total_pages = max(1, (total + limit - 1) // limit)

    return {
        "data": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }
