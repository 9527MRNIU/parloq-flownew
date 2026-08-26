from fastapi.testclient import TestClient


def test_management_lists_use_the_server_pagination_contract(
    admin_client: TestClient,
) -> None:
    paths = [
        "/api/system/roles",
        "/api/account-groups",
        "/api/personal-accounts",
        "/api/materials",
        "/api/ip-proxies",
        "/api/protocol-definitions",
        "/api/protocol-nodes",
        "/api/protocol-pools",
        "/api/hyperlink/templates",
        "/api/hyperlink/strategies",
        "/api/hyperlink/data-packages",
        "/api/hyperlink/tasks",
        "/api/promotion/templates",
        "/api/promotion/channels",
        "/api/promotion/integrations",
        "/api/meta-pixels",
        "/api/direct-short-links/accounts",
        "/api/domains",
    ]

    for path in paths:
        response = admin_client.get(f"{path}?page=1&pageSize=1")
        assert response.status_code == 200, f"{path}: {response.text}"
        data = response.json()["data"]
        assert data["page"] == 1, path
        assert data["pageSize"] == 1, path
        assert isinstance(data["total"], int), path
        assert len(data["rows"]) <= 1, path


def test_unpaged_option_endpoints_remain_available_for_selectors(
    admin_client: TestClient,
) -> None:
    paths = [
        "/api/system/roles/options",
        "/api/account-groups/options",
        "/api/personal-accounts/options",
        "/api/materials/options",
        "/api/ip-proxies/options",
        "/api/ip-proxies/filter-options",
        "/api/protocol-nodes/options",
        "/api/protocol-pools/options",
        "/api/hyperlink/templates/options",
        "/api/hyperlink/strategies/options",
        "/api/hyperlink/data-packages/options",
        "/api/promotion/templates/options",
        "/api/promotion/channels/options",
        "/api/promotion/integrations/options",
        "/api/meta-pixels/options",
        "/api/direct-short-links/accounts/options",
    ]

    for path in paths:
        response = admin_client.get(path)
        assert response.status_code == 200, f"{path}: {response.text}"
        assert isinstance(response.json().get("data"), dict), path


def test_promotion_lists_accept_the_confirmed_filter_and_sort_contract(
    admin_client: TestClient,
) -> None:
    cases = [
        (
            "/api/promotion/templates",
            {
                "status": "active",
                "repositorySource": "offline",
                "sortBy": "channelCount",
                "sortOrder": "desc",
            },
        ),
        (
            "/api/promotion/integrations",
            {
                "integrationType": "script",
                "sourceDomainId": "all",
                "sortBy": "eventCount",
                "sortOrder": "desc",
            },
        ),
        (
            "/api/promotion/channels",
            {
                "countryCode": "ZZ",
                "channelType": "facebook",
                "metaDomainStatus": "unmonitored",
                "locale": "en",
                "sortBy": "locale",
                "sortOrder": "asc",
            },
        ),
        (
            "/api/meta-pixels",
            {
                "enabled": "true",
                "sortBy": "pixelId",
                "sortOrder": "asc",
            },
        ),
    ]

    for path, params in cases:
        response = admin_client.get(
            path,
            params={**params, "page": 1, "pageSize": 1},
        )
        assert response.status_code == 200, f"{path}: {response.text}"
        data = response.json()["data"]
        assert data["page"] == 1
        assert data["pageSize"] == 1

    invalid = admin_client.get(
        "/api/promotion/channels",
        params={"sortBy": "visits"},
    )
    assert invalid.status_code == 422
