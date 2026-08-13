from app.services.permission_service import (
    ALL_PERMISSIONS,
    PERMISSION_RULES,
    calculate_permissions,
    get_permission_rules_display,
)


def test_administrator_gets_all_administrator_gated_permissions(make_user):
    user = make_user(administrator=True)

    permissions = calculate_permissions(user)

    for permission in (
        "userMaintain",
        "userAdministrate",
        "roleMaintain",
        "propriumelementMaintain",
        "instrumentMaintain",
        "voiceMaintain",
        "choirjobMaintain",
        "locationMaintain",
        "requestLogView",
        "sentEmailView",
        "sqlInspectorView",
        "schedulerView",
    ):
        assert permission in permissions


def test_user_with_no_roles_and_no_admin_flag_gets_only_open_permission(
    make_user,
):
    user = make_user(administrator=False)

    permissions = calculate_permissions(user)

    # performanceChangeUserStatus has no role gate at all in Legacy.
    assert permissions == ["performanceChangeUserStatus"]


def test_planner_role_grants_artist_and_repertoire_maintain(make_user):
    user = make_user(roles=["planner"])

    permissions = calculate_permissions(user)

    assert "artistMaintain" in permissions
    assert "propriumworkMaintain" in permissions
    assert "ordinariumworkMaintain" in permissions
    assert "performanceMaintain" in permissions
    assert "performanceCast" not in permissions  # planner alone, no disponent


def test_disponent_role_grants_broader_surface_than_planner(make_user):
    user = make_user(roles=["disponent"])

    permissions = calculate_permissions(user)

    assert "userMaintain" in permissions
    assert "artistMaintain" in permissions
    assert "feeMaintain" in permissions
    assert "performanceCast" in permissions
    assert "roleMaintain" not in permissions  # disponent alone, no administrator


def test_billing_role_grants_only_performance_billing(make_user):
    user = make_user(roles=["billing"])

    permissions = calculate_permissions(user)

    assert permissions == ["performanceBilling", "performanceChangeUserStatus"]


def test_scores_role_grants_only_score_maintain(make_user):
    user = make_user(roles=["scores"])

    permissions = calculate_permissions(user)

    assert permissions == ["scoreMaintain", "performanceChangeUserStatus"]


def test_shorturls_role_grants_only_shorturl_maintain(make_user):
    user = make_user(roles=["shorturls"])

    permissions = calculate_permissions(user)

    assert permissions == ["shorturlMaintain", "performanceChangeUserStatus"]


def test_all_permissions_matches_rule_count():
    assert len(ALL_PERMISSIONS) == len(PERMISSION_RULES) == 22


def test_permission_rules_display_has_description_per_rule():
    display = get_permission_rules_display()

    assert len(display) == len(PERMISSION_RULES)
    for entry in display:
        assert entry["permission"]
        assert entry["description"]
