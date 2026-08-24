from collections.abc import Callable
from dataclasses import dataclass

from app.db.models.user import User


@dataclass(frozen=True)
class PermissionRule:
    permission: str
    description: str
    condition: Callable[[set[str], bool], bool]


# Ported from Legacy's 21 Policy ability-rules (app/Models/Policies/*Policy.php
# -- see project_osa_legacy_domain_map memory) into one centralized,
# testable matrix, 1:1 vb-api pattern. `role_names` is the set of Role.name
# values currently assigned to the user (planner/disponent/billing/scores/
# shorturls); `is_administrator` is the separate `users.administrator`
# boolean flag, never a role row.
#
# `clientUserAgentView` (Legacy's ClientUserAgentPolicy::view) was NOT
# ported: Legacy itself never gates any route on it (no controller ever
# calls Gate::authorize('view', ClientUserAgent::class)), so it was dead
# code there too -- porting it would just carry that dead code forward.
#
# The Performance-domain rules (performanceMaintain/-Cast/-ChangeUserStatus)
# only encode Legacy's ROLE gate here -- Legacy additionally requires the
# specific Performance's schedule to not be in the past (an object-level
# check, not a user-level one). That temporal check is layered on at the
# Performance service call site once the Performance domain exists
# (Schritt 5), not part of this matrix.
PERMISSION_RULES: list[PermissionRule] = [
    PermissionRule(
        permission="userMaintain",
        description="Rolle 'disponent' oder administrator-Flag",
        condition=lambda roles, is_admin: "disponent" in roles or is_admin,
    ),
    PermissionRule(
        permission="userAdministrate",
        description="administrator-Flag (Restore soft-deleted Users)",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="roleMaintain",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="artistMaintain",
        description="Rolle 'planner' oder 'disponent'",
        condition=lambda roles, _is_admin: bool({"planner", "disponent"} & roles),
    ),
    PermissionRule(
        permission="propriumworkMaintain",
        description="Rolle 'planner' oder 'disponent'",
        condition=lambda roles, _is_admin: bool({"planner", "disponent"} & roles),
    ),
    PermissionRule(
        permission="ordinariumworkMaintain",
        description="Rolle 'planner' oder 'disponent'",
        condition=lambda roles, _is_admin: bool({"planner", "disponent"} & roles),
    ),
    PermissionRule(
        permission="propriumelementMaintain",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="instrumentMaintain",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="voiceMaintain",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="choirjobMaintain",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="locationMaintain",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="feeMaintain",
        description="Rolle 'disponent'",
        condition=lambda roles, _is_admin: "disponent" in roles,
    ),
    PermissionRule(
        permission="scoreMaintain",
        description="Rolle 'scores'",
        condition=lambda roles, _is_admin: "scores" in roles,
    ),
    PermissionRule(
        permission="shorturlMaintain",
        description="Rolle 'shorturls'",
        condition=lambda roles, _is_admin: "shorturls" in roles,
    ),
    PermissionRule(
        permission="requestLogView",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="sentEmailView",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="sqlInspectorView",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="schedulerView",
        description="administrator-Flag",
        condition=lambda _roles, is_admin: is_admin,
    ),
    PermissionRule(
        permission="performanceMaintain",
        description=(
            "Rolle 'planner' oder 'disponent' "
            "(Vergangenheits-Sperre wird objektbezogen zusätzlich geprüft)"
        ),
        condition=lambda roles, _is_admin: bool({"planner", "disponent"} & roles),
    ),
    PermissionRule(
        permission="performanceCast",
        description=(
            "Rolle 'disponent' "
            "(Vergangenheits-Sperre wird objektbezogen zusätzlich geprüft)"
        ),
        condition=lambda roles, _is_admin: "disponent" in roles,
    ),
    PermissionRule(
        permission="performanceBilling",
        description="Rolle 'billing'",
        condition=lambda roles, _is_admin: "billing" in roles,
    ),
    PermissionRule(
        permission="performanceChangeUserStatus",
        description=(
            "Kein Rollen-Check, jeder eingeloggte User "
            "(Vergangenheits-Sperre wird objektbezogen zusätzlich geprüft)"
        ),
        condition=lambda _roles, _is_admin: True,
    ),
]

ALL_PERMISSIONS: list[str] = sorted({rule.permission for rule in PERMISSION_RULES})


def calculate_permissions(user: User) -> list[str]:
    """Derives a user's active permissions from their roles + administrator
    flag. `user.roles` must already be loaded (see api.deps.get_current_user)
    -- accessing an unloaded relationship here would be a lazy-load, i.e.
    exactly the N+1 pattern the test suite's query-count guards catch."""
    role_names = {role.name for role in user.roles}
    return [
        rule.permission
        for rule in PERMISSION_RULES
        if rule.condition(role_names, user.administrator)
    ]


def get_permission_rules_display() -> list[dict[str, str]]:
    return [
        {"permission": rule.permission, "description": rule.description}
        for rule in PERMISSION_RULES
    ]
