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
