"""Recursive type aliases for arbitrary JSON-shaped data -- Postgres
JSONB columns (see app.db.models.request_log/auth_log) and request/
response bodies parsed off the wire (see
app.api.middleware.request_logging). `JsonValue` covers any valid JSON
value at any nesting depth (including `None`, i.e. a JSON `null`);
`JsonObject` narrows it to the object case, for values that are
structurally always a JSON object at the top level (never a bare list,
string, or number) -- e.g. a parsed request body or an audit-log
payload."""

type JsonValue = (
    dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
)
type JsonObject = dict[str, JsonValue]
