from __future__ import annotations

import threading
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import (
    AccountGroupWakeupEvent,
    DataPackageRecipient,
    HyperlinkTask,
    HyperlinkTaskAccountSlot,
    HyperlinkTaskDelivery,
    PersonalAccount,
)
from app.services.account_group_wakeups import dispatch_pending_group_wakeups
from app.snowflake import new_public_id
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.hyperlink_strategy import HyperlinkStrategyPolicy
from app.task_worker import (
    AccountSendLimiter,
    SendJob,
    process_task,
    recover_running_tasks,
)
from app.task_queue import dispatch_due_hyperlink_tasks, schedule_hyperlink_task


def _resources(client: TestClient, prefix: str, recipient_count: int = 2) -> dict:
    group = client.post(
        "/api/account-groups", json={"name": f"{prefix} senders"}
    ).json()["data"]["group"]
    template = client.post(
        "/api/hyperlink/templates",
        json={"name": f"{prefix} template", "contentJson": {"text": "Hello"}},
    ).json()["data"]["template"]
    strategy = client.post(
        "/api/hyperlink/strategies",
        json={
            "name": f"{prefix} strategy",
            "maxQps": 10,
            "concurrency": 1,
        },
    ).json()["data"]["strategy"]
    package = client.post(
        "/api/hyperlink/data-packages",
        json={
            "name": f"{prefix} package",
            "recipients": [
                {"phone": f"+12025553{index:03d}", "countryCode": "US"}
                for index in range(recipient_count)
            ],
        },
    ).json()["data"]["dataPackage"]
    return {
        "group": group,
        "template": template,
        "strategy": strategy,
        "package": package,
    }


def _create_task(client: TestClient, prefix: str, resources: dict) -> dict:
    response = client.post(
        "/api/hyperlink/tasks",
        json={
            "name": f"{prefix} task",
            "templateId": resources["template"]["id"],
            "strategyId": resources["strategy"]["id"],
            "dataPackageId": resources["package"]["id"],
            "accountGroupId": resources["group"]["id"],
        },
    )
    assert response.status_code == 201, response.text
    task = response.json()["data"]["task"]
    assert task["accountGroupId"] == resources["group"]["id"]
    assert task["senderMode"] == "dynamic_group"
    assert "accountIds" not in task
    return task


def _available_account(
    client: TestClient, *, name: str, phone: str, group_id: str
) -> dict:
    response = client.post(
        "/api/personal-accounts",
        json={"name": name, "phone": phone, "groupId": group_id},
    )
    assert response.status_code == 201, response.text
    account = response.json()["data"]["account"]
    with SessionLocal() as db:
        stored = db.get(PersonalAccount, int(account["id"]))
        assert stored is not None
        stored.validation_status = "ready"
        stored.status = "online_idle"
        db.commit()
    return account


def test_empty_group_waits_and_periodic_recovery_continues_after_account_added(
    admin_client: TestClient, monkeypatch
) -> None:
    resources = _resources(admin_client, "dynamic-empty", recipient_count=1)
    task = _create_task(admin_client, "dynamic-empty", resources)

    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text
    assert started.json()["data"]["task"]["status"] == "waiting_accounts"
    repeated = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert repeated.status_code == 202
    assert repeated.json()["data"]["alreadyRunning"] is True
    assert repeated.json()["data"]["task"]["status"] == "waiting_accounts"
    with SessionLocal() as db:
        deliveries = db.scalars(
            select(HyperlinkTaskDelivery).where(
                HyperlinkTaskDelivery.task_id == int(task["id"])
            )
        ).all()
        assert len(deliveries) == 1
        assert deliveries[0].account_id is None

    account = _available_account(
        admin_client,
        name="dynamic recovered sender",
        phone="+12025553901",
        group_id=resources["group"]["id"],
    )
    queued: list[str] = []
    monkeypatch.setattr(
        "app.task_worker.enqueue_hyperlink_task",
        lambda task_id: queued.append(task_id) or True,
    )
    assert recover_running_tasks() >= 1
    assert task["id"] in queued

    process_task(task["id"])
    with SessionLocal() as db:
        stored_task = db.get(HyperlinkTask, int(task["id"]))
        delivery = db.scalar(
            select(HyperlinkTaskDelivery).where(
                HyperlinkTaskDelivery.task_id == stored_task.id
            )
        )
        assert stored_task.status == "running"
        assert delivery.account_id == int(account["id"])
        assert delivery.submission_status == "accepted"


def test_group_change_event_immediately_wakes_waiting_task(
    admin_client: TestClient, monkeypatch
) -> None:
    resources = _resources(admin_client, "event-wakeup", recipient_count=1)
    task = _create_task(admin_client, "event-wakeup", resources)
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text
    assert started.json()["data"]["task"]["status"] == "waiting_accounts"

    account = admin_client.post(
        "/api/personal-accounts",
        json={"name": "event sender", "phone": "+12025553902"},
    ).json()["data"]["account"]
    moved = admin_client.patch(
        f"/api/personal-accounts/{account['id']}",
        json={"groupId": resources["group"]["id"]},
    )
    assert moved.status_code == 200, moved.text

    with SessionLocal() as db:
        pending = db.scalars(
            select(AccountGroupWakeupEvent).where(
                AccountGroupWakeupEvent.group_id
                == int(resources["group"]["id"]),
                AccountGroupWakeupEvent.processed_at.is_(None),
            )
        ).all()
        assert any(event.reason == "account_joined_group" for event in pending)

    settings = get_settings()
    queued: list[str] = []
    monkeypatch.setattr(
        "app.services.account_group_wakeups.get_settings",
        lambda: replace(settings, task_queue_mock=False),
    )
    monkeypatch.setattr(
        "app.services.account_group_wakeups.enqueue_hyperlink_task",
        lambda task_id: queued.append(task_id) or True,
    )
    event_count, task_count = dispatch_pending_group_wakeups(
        group_id=int(resources["group"]["id"])
    )
    assert event_count >= 1
    assert task_count == 1
    assert queued == [task["id"]]
    with SessionLocal() as db:
        assert db.scalar(
            select(AccountGroupWakeupEvent).where(
                AccountGroupWakeupEvent.group_id
                == int(resources["group"]["id"]),
                AccountGroupWakeupEvent.processed_at.is_(None),
            )
        ) is None


def test_running_task_keeps_healthy_account_when_group_gains_another_account(
    admin_client: TestClient, monkeypatch
) -> None:
    resources = _resources(admin_client, "dynamic-live", recipient_count=2)
    first = _available_account(
        admin_client,
        name="dynamic first sender",
        phone="+12025553911",
        group_id=resources["group"]["id"],
    )
    task = _create_task(admin_client, "dynamic-live", resources)
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202
    assert started.json()["data"]["task"]["status"] == "running"
    with SessionLocal() as db:
        assert set(
            db.scalars(
                select(HyperlinkTaskDelivery.account_id).where(
                    HyperlinkTaskDelivery.task_id == int(task["id"])
                )
            ).all()
        ) == {None}

    original_send = WaGatewayClient.send
    added: list[dict] = []

    def send_and_add_account(self, *args, **kwargs):
        result = original_send(self, *args, **kwargs)
        if not added:
            added.append(
                _available_account(
                    admin_client,
                    name="dynamic second sender",
                    phone="+12025553912",
                    group_id=resources["group"]["id"],
                )
            )
        return result

    monkeypatch.setattr(WaGatewayClient, "send", send_and_add_account)
    process_task(task["id"])
    second = added[0]
    with SessionLocal() as db:
        assigned = set(
            db.scalars(
                select(HyperlinkTaskDelivery.account_id).where(
                    HyperlinkTaskDelivery.task_id == int(task["id"])
                )
            ).all()
        )
    assert assigned == {int(first["id"])}
    assert int(second["id"]) not in assigned


def test_legacy_fixed_task_keeps_its_frozen_account_assignments(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "legacy-fixed", recipient_count=1)
    account = _available_account(
        admin_client,
        name="legacy fixed sender",
        phone="+12025553921",
        group_id=resources["group"]["id"],
    )
    with SessionLocal() as db:
        stored_account = db.get(PersonalAccount, int(account["id"]))
        task = HyperlinkTask(
            public_id=new_public_id("htsk"),
            name="historical fixed task",
            template_id=int(resources["template"]["id"]),
            strategy_id=int(resources["strategy"]["id"]),
            data_package_id=int(resources["package"]["id"]),
            account_group_id=None,
            sender_mode="legacy_fixed",
            account_public_ids=[account["id"]],
            status="draft",
            created_by=stored_account.created_by,
        )
        db.add(task)
        db.commit()
        task_id = str(task.id)

    started = admin_client.post(f"/api/hyperlink/tasks/{task_id}/start")
    assert started.status_code == 202, started.text
    task_row = started.json()["data"]["task"]
    assert task_row["senderMode"] == "legacy_fixed"
    assert task_row["accountIds"] == [account["id"]]
    assert task_row["accountGroupId"] is None
    with SessionLocal() as db:
        delivery = db.scalar(
            select(HyperlinkTaskDelivery).where(
                HyperlinkTaskDelivery.task_id == int(task_id)
            )
        )
        assert delivery.account_id == int(account["id"])


def _operator(admin: TestClient, username: str) -> TestClient:
    groups = admin.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    created = admin.post(
        "/api/users",
        json={
            "username": username,
            "password": "dynamic-group-pass-123",
            "groupId": operator["id"],
        },
    )
    assert created.status_code == 201, created.text
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": username, "password": "dynamic-group-pass-123"},
    ).status_code == 200
    return client


def test_dynamic_task_rejects_another_tenants_account_group(
    admin_client: TestClient,
) -> None:
    first = _operator(admin_client, "dynamic-task-tenant-a")
    second = _operator(admin_client, "dynamic-task-tenant-b")
    try:
        resources = _resources(first, "dynamic-tenant-a", recipient_count=1)
        foreign_group = second.post(
            "/api/account-groups", json={"name": "dynamic tenant B senders"}
        ).json()["data"]["group"]
        response = first.post(
            "/api/hyperlink/tasks",
            json={
                "name": "cross tenant dynamic task",
                "templateId": resources["template"]["id"],
                "strategyId": resources["strategy"]["id"],
                "dataPackageId": resources["package"]["id"],
                "accountGroupId": foreign_group["id"],
            },
        )
        assert response.status_code == 404
    finally:
        first.close()
        second.close()


def test_strategy_rules_round_trip_and_pause_when_group_is_empty(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "strategy-policy", recipient_count=1)
    strategy_id = resources["strategy"]["id"]
    updated = admin_client.patch(
        f"/api/hyperlink/strategies/{strategy_id}",
        json={
            "maxQps": 7,
            "concurrency": 6,
            "retryLimit": 3,
            "retryBackoffSeconds": 12,
            "noAccountAction": "pause",
            "sendJitterMs": 80,
            "accountFailureThreshold": 4,
            "accountCooldownSeconds": 180,
        },
    )
    assert updated.status_code == 200, updated.text
    strategy = updated.json()["data"]["strategy"]
    assert {
            key: strategy[key]
            for key in (
                "maxQps",
                "concurrency",
                "retryLimit",
                "retryBackoffSeconds",
                "noAccountAction",
                "sendJitterMs",
                "accountFailureThreshold",
                "accountCooldownSeconds",
            )
        } == {
            "maxQps": 7,
            "concurrency": 6,
            "retryLimit": 3,
            "retryBackoffSeconds": 12,
            "noAccountAction": "pause",
            "sendJitterMs": 80,
            "accountFailureThreshold": 4,
            "accountCooldownSeconds": 180,
        }

    task = _create_task(admin_client, "strategy-policy", resources)
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text
    assert started.json()["data"]["task"]["status"] == "paused"


def test_concurrent_account_slots_keep_their_accounts_for_the_whole_task(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "strategy-round-robin", recipient_count=4)
    strategy_id = resources["strategy"]["id"]
    response = admin_client.patch(
        f"/api/hyperlink/strategies/{strategy_id}",
        json={
            "maxQps": 100,
            "concurrency": 2,
        },
    )
    assert response.status_code == 200, response.text
    first = _available_account(
        admin_client,
        name="round robin sender one",
        phone="+12025553931",
        group_id=resources["group"]["id"],
    )
    second = _available_account(
        admin_client,
        name="round robin sender two",
        phone="+12025553932",
        group_id=resources["group"]["id"],
    )
    task = _create_task(admin_client, "strategy-round-robin", resources)
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text

    process_task(task["id"])
    with SessionLocal() as db:
        assigned = list(
            db.scalars(
                select(HyperlinkTaskDelivery.account_id)
                .where(HyperlinkTaskDelivery.task_id == int(task["id"]))
                .order_by(HyperlinkTaskDelivery.id)
            ).all()
        )
    assert assigned == [
        int(first["id"]),
        int(second["id"]),
        int(first["id"]),
        int(second["id"]),
    ]


def test_unhealthy_sticky_account_is_replaced_and_retry_continues(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "sticky-replace", recipient_count=1)
    updated = admin_client.patch(
        f"/api/hyperlink/strategies/{resources['strategy']['id']}",
        json={
            "concurrency": 1,
            "maxQps": 100,
            "retryLimit": 2,
            "retryBackoffSeconds": 0,
            "accountFailureThreshold": 1,
            "accountCooldownSeconds": 60,
        },
    )
    assert updated.status_code == 200, updated.text
    first = _available_account(
        admin_client,
        name="sticky failed sender",
        phone="+12025553941",
        group_id=resources["group"]["id"],
    )
    second = _available_account(
        admin_client,
        name="sticky replacement sender",
        phone="+12025553942",
        group_id=resources["group"]["id"],
    )
    task = _create_task(admin_client, "sticky-replace", resources)
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text

    calls: list[str] = []

    class FlakyGateway:
        def send(self, gateway_account_id, *_args, **_kwargs):
            calls.append(gateway_account_id)
            if len(calls) == 1:
                raise GatewayError("simulated account failure")
            return {"status": "queued", "providerMessageId": "provider-ok"}

    process_task(task["id"], gateway=FlakyGateway())

    with SessionLocal() as db:
        stored_first = db.get(PersonalAccount, int(first["id"]))
        delivery = db.scalar(
            select(HyperlinkTaskDelivery).where(
                HyperlinkTaskDelivery.task_id == int(task["id"])
            )
        )
        slots = db.scalars(
            select(HyperlinkTaskAccountSlot).where(
                HyperlinkTaskAccountSlot.task_id == int(task["id"])
            )
        ).all()
        assert stored_first.sending_cooldown_until is not None
        assert delivery.account_id == int(second["id"])
        assert delivery.submission_status == "accepted"
        assert delivery.attempt_count == 2
        assert any(slot.switch_count == 1 for slot in slots)
    assert len(calls) == 2


def test_data_package_revision_is_frozen_per_started_task(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "package-snapshot", recipient_count=2)
    _available_account(
        admin_client,
        name="package snapshot sender",
        phone="+12025553951",
        group_id=resources["group"]["id"],
    )
    first_task = _create_task(admin_client, "package-snapshot-first", resources)
    first_start = admin_client.post(
        f"/api/hyperlink/tasks/{first_task['id']}/start"
    )
    assert first_start.status_code == 202, first_start.text
    frozen_revision = first_start.json()["data"]["task"]["dataPackageRevision"]

    package_id = resources["package"]["id"]
    before = admin_client.get(
        f"/api/hyperlink/data-packages/{package_id}/recipients"
    ).json()["data"]["rows"]
    removed = admin_client.delete(
        f"/api/hyperlink/data-packages/{package_id}/recipients/{before[1]['id']}"
    )
    assert removed.status_code == 200, removed.text
    added = admin_client.post(
        f"/api/hyperlink/data-packages/{package_id}/recipients",
        json={"recipients": [{"phone": "+12025553959", "countryCode": "US"}]},
    )
    assert added.status_code == 200, added.text
    latest_revision = added.json()["data"]["dataPackage"]["revision"]
    assert latest_revision > frozen_revision

    second_task = _create_task(admin_client, "package-snapshot-second", resources)
    second_start = admin_client.post(
        f"/api/hyperlink/tasks/{second_task['id']}/start"
    )
    assert second_start.status_code == 202, second_start.text
    assert (
        second_start.json()["data"]["task"]["dataPackageRevision"]
        == latest_revision
    )
    detail_page = admin_client.get(
        f"/api/hyperlink/tasks/{second_task['id']}/recipients?page=1&pageSize=1"
    )
    assert detail_page.status_code == 200, detail_page.text
    assert detail_page.json()["data"]["total"] == 2
    assert len(detail_page.json()["data"]["rows"]) == 1
    assert detail_page.json()["data"]["rows"][0]["executionStatus"] == "pending"

    with SessionLocal() as db:
        def phones_for(task_id: str) -> set[str]:
            return set(
                db.scalars(
                    select(DataPackageRecipient.phone_e164)
                    .join(
                        HyperlinkTaskDelivery,
                        HyperlinkTaskDelivery.recipient_id
                        == DataPackageRecipient.id,
                    )
                    .where(HyperlinkTaskDelivery.task_id == int(task_id))
                ).all()
            )

        assert phones_for(first_task["id"]) == {
            "+12025553000",
            "+12025553001",
        }
        assert phones_for(second_task["id"]) == {
            "+12025553000",
            "+12025553959",
        }


def test_pause_and_cancel_distinguish_safe_leases_from_inflight_submissions(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "task-control", recipient_count=3)
    _available_account(
        admin_client,
        name="task control sender",
        phone="+12025553961",
        group_id=resources["group"]["id"],
    )
    task = _create_task(admin_client, "task-control", resources)
    assert admin_client.post(
        f"/api/hyperlink/tasks/{task['id']}/start"
    ).status_code == 202

    with SessionLocal() as db:
        deliveries = db.scalars(
            select(HyperlinkTaskDelivery)
            .where(HyperlinkTaskDelivery.task_id == int(task["id"]))
            .order_by(HyperlinkTaskDelivery.id)
        ).all()
        deliveries[0].submission_status = "leased"
        deliveries[0].lease_token = "safe-lease"
        deliveries[1].submission_status = "submitting"
        deliveries[1].lease_token = "inflight-lease"
        db.commit()

    paused = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/pause")
    assert paused.status_code == 200, paused.text
    with SessionLocal() as db:
        deliveries = db.scalars(
            select(HyperlinkTaskDelivery)
            .where(HyperlinkTaskDelivery.task_id == int(task["id"]))
            .order_by(HyperlinkTaskDelivery.id)
        ).all()
        assert deliveries[0].submission_status == "pending"
        assert deliveries[0].lease_token is None
        assert deliveries[1].submission_status == "reconciling"
        assert deliveries[2].submission_status == "pending"

    resumed = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert resumed.status_code == 202, resumed.text
    cancelled = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    with SessionLocal() as db:
        deliveries = db.scalars(
            select(HyperlinkTaskDelivery)
            .where(HyperlinkTaskDelivery.task_id == int(task["id"]))
            .order_by(HyperlinkTaskDelivery.id)
        ).all()
        assert deliveries[0].submission_status == "cancelled"
        assert deliveries[1].submission_status == "reconciling"
        assert deliveries[2].submission_status == "cancelled"


def test_disabled_strategy_cannot_be_selected_or_started(
    admin_client: TestClient,
) -> None:
    resources = _resources(admin_client, "strategy-disabled", recipient_count=1)
    task = _create_task(admin_client, "strategy-disabled", resources)
    strategy_id = resources["strategy"]["id"]
    disabled = admin_client.patch(
        f"/api/hyperlink/strategies/{strategy_id}", json={"enabled": False}
    )
    assert disabled.status_code == 200, disabled.text

    rejected = admin_client.post(
        "/api/hyperlink/tasks",
        json={
            "name": "disabled strategy task",
            "templateId": resources["template"]["id"],
            "strategyId": strategy_id,
            "dataPackageId": resources["package"]["id"],
            "accountGroupId": resources["group"]["id"],
        },
    )
    assert rejected.status_code == 409
    start = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert start.status_code == 409


def test_account_limiter_applies_qps_independently_per_account(monkeypatch) -> None:
    policy = HyperlinkStrategyPolicy(
        max_qps=10,
        concurrency=4,
        buffer_size=10,
        retry_limit=1,
        retry_backoff_seconds=5,
        no_account_action="wait",
        send_jitter_ms=0,
        account_failure_threshold=3,
        account_cooldown_seconds=300,
        delivery_lease_seconds=120,
    )
    limiter = AccountSendLimiter(policy)
    times = iter([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    sleeps: list[float] = []
    monkeypatch.setattr("app.task_worker.time.monotonic", lambda: next(times))
    monkeypatch.setattr("app.task_worker.time.sleep", sleeps.append)
    monkeypatch.setattr("app.task_worker._begin_submission", lambda _job: True)
    gateway = WaGatewayClient()

    def job(message_id: str, account_id: int) -> SendJob:
        return SendJob(
            task_id=1,
            task_delivery_id=account_id,
            message_delivery_id=account_id,
            slot_id=account_id,
            lease_token=f"lease-{account_id}",
            account_id=account_id,
            gateway_account_id=f"gateway-{account_id}",
            message_id=message_id,
            recipient_e164="+12025553999",
            message={"text": "hello"},
        )

    limiter.send(job("first", 1), gateway)
    limiter.send(job("second", 1), gateway)
    limiter.send(job("other-account", 2), gateway)
    assert sleeps == [0.1]


def test_account_limiter_stops_before_submission_after_worker_lock_loss(
    monkeypatch,
) -> None:
    policy = HyperlinkStrategyPolicy(
        max_qps=10,
        concurrency=1,
        buffer_size=10,
        retry_limit=1,
        retry_backoff_seconds=5,
        no_account_action="wait",
        send_jitter_ms=0,
        account_failure_threshold=3,
        account_cooldown_seconds=300,
        delivery_lease_seconds=120,
    )
    stopped = threading.Event()
    stopped.set()
    limiter = AccountSendLimiter(policy, stop_event=stopped)
    began: list[int] = []
    monkeypatch.setattr(
        "app.task_worker._begin_submission", lambda job: began.append(job.task_id)
    )
    job = SendJob(
        task_id=1,
        task_delivery_id=1,
        message_delivery_id=1,
        slot_id=1,
        lease_token="lease",
        account_id=1,
        gateway_account_id="gateway-1",
        message_id="message-1",
        recipient_e164="+12025553999",
        message={"text": "hello"},
    )

    _job, _response, error = limiter.send(job, WaGatewayClient())
    assert error is not None
    assert began == []


def test_retry_schedule_and_due_dispatch_use_the_durable_redis_queue(
    monkeypatch,
) -> None:
    class StubRedis:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple, dict]] = []

        def eval(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return 1

    stub = StubRedis()
    monkeypatch.setattr(
        "app.task_queue.get_settings",
        lambda: replace(get_settings(), task_queue_mock=False),
    )
    monkeypatch.setattr("app.task_queue.redis_client", lambda: stub)
    monkeypatch.setattr("app.task_queue.time.time", lambda: 100.0)

    assert schedule_hyperlink_task("4780486454931715", 12) is True
    args, _kwargs = stub.calls[0]
    assert args[-2:] == ("4780486454931715", 112.0)

    queued: list[str] = []
    monkeypatch.setattr(
        "app.task_queue.redis_client",
        lambda: type(
            "DueRedis",
            (),
            {"eval": lambda self, *args, **kwargs: ["101", "102"]},
        )(),
    )
    monkeypatch.setattr(
        "app.task_queue.enqueue_hyperlink_task",
        lambda task_id: queued.append(task_id) is None,
    )
    assert dispatch_due_hyperlink_tasks(limit=20) == 2
    assert queued == ["101", "102"]
