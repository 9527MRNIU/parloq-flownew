from __future__ import annotations


def test_system_metrics_requires_login(client) -> None:
    response = client.get("/api/system/metrics")
    assert response.status_code == 401


def test_system_metrics_returns_resource_snapshot(admin_client) -> None:
    response = admin_client.get("/api/system/metrics")
    assert response.status_code == 200

    metrics = response.json()["data"]
    assert metrics["refreshIntervalSeconds"] == 3
    assert metrics["updatedAt"]
    for name in ("cpu", "memory", "disk"):
        metric = metrics[name]
        assert "percent" in metric
        assert isinstance(metric["source"], str)
        if metric["percent"] is not None:
            assert 0 <= metric["percent"] <= 100

    assert metrics["cpu"]["cores"] > 0
    assert metrics["memory"]["totalBytes"] is None or metrics["memory"]["totalBytes"] > 0
    assert metrics["disk"]["totalBytes"] is None or metrics["disk"]["totalBytes"] > 0
