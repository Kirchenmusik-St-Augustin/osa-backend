def field_errors_to_detail(errors: list[tuple[str, str]]) -> list[dict[str, object]]:
    """Shapes a list of (field, message) tuples into FastAPI's own
    `{"detail": [...]}` validation-error format, so field-level domain
    errors (duplicate name, "in use" delete conflicts, etc.) render
    identically to Pydantic's built-in 422s on the frontend."""
    return [
        {"loc": ["body", field], "msg": msg, "type": "value_error"}
        for field, msg in errors
    ]
