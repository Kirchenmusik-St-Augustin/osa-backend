from app.services.errors import FieldError


def field_errors_to_detail(errors: list[FieldError]) -> list[dict[str, object]]:
    """Shapes a list of field-level errors into FastAPI's own
    `{"detail": [...]}` validation-error format, so domain errors
    (duplicate name, "in use" delete conflicts, etc.) render identically
    to Pydantic's built-in 422s on the frontend."""
    return [
        {"loc": ["body", error.field], "msg": error.message, "type": "value_error"}
        for error in errors
    ]
