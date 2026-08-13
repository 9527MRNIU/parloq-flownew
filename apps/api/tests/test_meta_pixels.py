from __future__ import annotations

from fastapi.testclient import TestClient


def test_meta_pixel_placeholder_crud_masks_capi_token(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/meta-pixels",
        json={
            "name": "Promotion Pixel",
            "datasetId": "1234567890",
            "capiToken": "meta-capi-secret",
        },
    )
    assert created.status_code == 201
    pixel = created.json()["data"]["pixel"]
    assert pixel["capiTokenMasked"] == "••••cret"
    assert "meta-capi-secret" not in created.text

    updated = admin_client.patch(
        f"/api/meta-pixels/{pixel['id']}", json={"enabled": False}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["pixel"]["enabled"] is False
