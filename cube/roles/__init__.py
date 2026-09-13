"""Role definitions: pydantic model over roles/<role>.yaml and prompt assembly."""

from cube.roles.loader import (
    Role,
    RoleError,
    RoleEscalation,
    assemble_prompt,
    load_all,
    load_role,
    result_schema,
)

__all__ = [
    "Role",
    "RoleError",
    "RoleEscalation",
    "assemble_prompt",
    "load_all",
    "load_role",
    "result_schema",
]
