"""
Standardized DRF response helpers to unify success/error envelopes.
"""
from typing import Any, Dict, Optional
from rest_framework.response import Response

def ok(data: Any = None, message: str = "OK", **meta: Any) -> Response:
    """
    Return a standardized success JSON envelope.
    Example:
        return ok({"id": 1}, message="Created")
    """
    payload: Dict[str, Any] = {"success": True, "message": message, "data": data}
    if meta:
        payload["meta"] = meta
    return Response(payload)

def fail(message: str, *, code: str = "bad_request", status: int = 400, errors: Optional[Any] = None) -> Response:
    """
    Return a standardized error JSON envelope.
    Example:
        return fail("Invalid input", code="validation_error", status=422, errors=serializer.errors)
    """
    payload: Dict[str, Any] = {"success": False, "message": message, "code": code}
    if errors is not None:
        payload["errors"] = errors
    return Response(payload, status=status)
