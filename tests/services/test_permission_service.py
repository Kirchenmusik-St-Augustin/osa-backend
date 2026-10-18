from app.services.permission_service import (
    ALL_PERMISSIONS,
    PERMISSION_RULES,
    calculate_permissions,
    get_permission_rules_display,
    has_permission,
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

    # performanceChangeUserStatus has no role gate at all.
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


def test_a_role_the_matrix_does_not_know_grants_nothing(make_user):
    # Role names are matched by value: look-alikes must not be treated as the
    # real role.
    baseline = calculate_permissions(make_user(roles=[]))

    look_alikes = make_user(roles=["Planner", "admin", "planner "])

    assert calculate_permissions(look_alikes) == baseline


def test_the_administrator_flag_alone_never_grants_the_role_gated_permissions(
    make_user,
):
    permissions = calculate_permissions(make_user(administrator=True))

    for role_gated in (
        "performanceCast",
        "performanceBilling",
        "feeMaintain",
        "scoreMaintain",
        "shorturlMaintain",
    ):
        assert role_gated not in permissions


def test_has_permission_agrees_with_calculate_permissions(make_user):
    user = make_user(administrator=True)

    for permission in ALL_PERMISSIONS:
        assert has_permission(user, permission) == (
            permission in calculate_permissions(user)
        )
