from scripts import recover_stopped_compose_services


class FakeCommandRunner:
    def __init__(self, outputs: dict[tuple[str, ...], str]):
        self.outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: list[str]) -> str:
        key = tuple(command)
        self.calls.append(key)
        return self.outputs.get(key, "")


def test_reconcile_starts_created_container_without_recreating_it() -> None:
    runner = FakeCommandRunner(
        {
            (
                "docker",
                "compose",
                "--env-file",
                ".env",
                "ps",
                "-a",
                "-q",
                "frontend",
            ): "frontend-cid\n",
            (
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}",
                "frontend-cid",
            ): "created\n",
        }
    )

    recover_stopped_compose_services.reconcile_services(
        ["frontend"], env_file=".env", run=runner
    )

    assert ("docker", "start", "frontend-cid") in runner.calls
    assert not any("up" in call for call in runner.calls)


def test_reconcile_leaves_running_container_untouched() -> None:
    runner = FakeCommandRunner(
        {
            (
                "docker",
                "compose",
                "--env-file",
                ".env",
                "ps",
                "-a",
                "-q",
                "backend",
            ): "backend-cid\n",
            (
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}",
                "backend-cid",
            ): "running\n",
        }
    )

    recover_stopped_compose_services.reconcile_services(
        ["backend"], env_file=".env", run=runner
    )

    assert not any(call[:2] == ("docker", "start") for call in runner.calls)


def test_reconcile_creates_missing_service_without_dependencies() -> None:
    runner = FakeCommandRunner({})

    recover_stopped_compose_services.reconcile_services(
        ["cloudflared"], env_file="dev.env", run=runner
    )

    assert (
        "docker",
        "compose",
        "--env-file",
        "dev.env",
        "up",
        "-d",
        "--no-deps",
        "cloudflared",
    ) in runner.calls
