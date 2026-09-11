from scripts import detect_changed_services


def test_normalize_service_name_maps_runtrainer_postgres_to_postgres() -> None:
    assert detect_changed_services.normalize_service_name("runtrainer-postgres") == "postgres"


def test_build_outputs_marks_postgres_changed_for_renamed_service() -> None:
    outputs = detect_changed_services.build_outputs(
        ["compose.yml"],
        {"runtrainer-postgres"},
    )

    assert outputs["postgres_changed"] is True
    assert outputs["backend_changed"] is False
    assert outputs["worker_changed"] is False


def test_build_outputs_marks_backend_and_worker_for_backend_tree_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        ["backend/app/main.py"],
        set(),
    )

    assert outputs["backend_changed"] is True
    assert outputs["worker_changed"] is True


def test_build_outputs_marks_frontend_for_frontend_tree_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        ["frontend/pages/dashboard.js"],
        set(),
    )

    assert outputs["frontend_changed"] is True
    assert outputs["backend_changed"] is False


def test_build_outputs_ignores_backend_test_only_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        ["backend/tests/test_metrics.py"],
        set(),
    )

    assert outputs["backend_changed"] is False
    assert outputs["worker_changed"] is False


def test_build_outputs_ignores_frontend_test_only_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        ["frontend/tests/athlete-home-contract.test.js"],
        set(),
    )

    assert outputs["frontend_changed"] is False


def test_build_outputs_reconciles_every_service_for_deployment_control_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        [".github/workflows/ci-cd.yml"],
        set(),
    )

    assert outputs == {
        "postgres_changed": True,
        "influxdb_changed": True,
        "grafana_changed": True,
        "cloudflared_changed": True,
        "frontend_changed": True,
        "backend_changed": True,
        "worker_changed": True,
        "training_agent_changed": True,
    }


def test_build_outputs_reconciles_every_service_for_smoke_contract_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        ["scripts/smoke_production.py"],
        set(),
    )

    assert all(outputs.values())


def test_build_outputs_reconciles_every_service_for_runtime_recovery_changes() -> None:
    outputs = detect_changed_services.build_outputs(
        ["scripts/recover_stopped_compose_services.py"],
        set(),
    )

    assert all(outputs.values())
