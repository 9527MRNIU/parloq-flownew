from __future__ import annotations

import hashlib

from app.services.template_quality import inspect_template_quality


def _v2_manifest() -> dict:
    return {
        "schema": "promotion-template/v2",
        "requirements": {
            "pairingContract": "promotion-public-pairing/v1",
            "componentKit": "account-link-elements/v1",
        },
    }


def test_template_quality_passes_platform_component_template() -> None:
    html = """<!doctype html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
    <body><account-link-flow><phone-number-field></phone-number-field>
    <account-link-submit></account-link-submit><pairing-code-panel></pairing-code-panel>
    <app-launch-actions></app-launch-actions><account-link-status></account-link-status>
    <account-initialization-status></account-initialization-status></account-link-flow></body></html>
    """
    report = inspect_template_quality(
        manifest=_v2_manifest(),
        index_html=html,
        assets=[("assets/theme.css", "text/css", b"body{margin:0}")],
        expanded_bytes=len(html),
    )

    assert report["status"] == "passed"
    assert report["warnings"] == []
    assert report["metrics"]["cssGzipBytes"] > 0


def test_template_quality_groups_actionable_warnings() -> None:
    large_javascript = b"".join(
        hashlib.sha256(index.to_bytes(4, "big")).digest()
        for index in range(10_000)
    )
    report = inspect_template_quality(
        manifest={"schema": "promotion-template/v1"},
        index_html=(
            '<html><head><meta name="viewport" '
            'content="width=device-width,maximum-scale=1,user-scalable=no">'
            '<link rel="stylesheet" href="https://cdn.example.test/site.css"></head>'
            '<body><iframe src="frame.html"></iframe><img src="hero.png">'
            '<img src="detail.png"></body></html>'
        ),
        assets=[
            ("assets/app.js", "application/javascript", large_javascript),
            (
                "assets/app.css",
                "text/css",
                b"body{background:url(https://cdn.example.test/bg.png)}/*# sourceMappingURL=app.css.map */",
            ),
            ("hero.png", "image/png", b"image"),
        ],
        expanded_bytes=400_000,
    )

    codes = {warning["code"] for warning in report["warnings"]}
    assert report["status"] == "warnings"
    assert {
        "js_gzip_budget",
        "source_map_reference",
        "external_resource",
        "template_iframe",
        "image_alt",
        "image_dimensions",
        "image_lazy_loading",
        "viewport_zoom_locked",
        "legacy_template_schema",
    } <= codes


def test_template_quality_counts_inline_script_and_style() -> None:
    html = """<!doctype html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script>window.inlineValue = 'inline'</script>
    <style>body { color: #111; }</style></head><body>
    <account-link-flow><phone-number-field></phone-number-field>
    <account-link-submit></account-link-submit><pairing-code-panel></pairing-code-panel>
    <app-launch-actions></app-launch-actions><account-link-status></account-link-status>
    <account-initialization-status></account-initialization-status>
    </account-link-flow></body></html>"""
    report = inspect_template_quality(
        manifest=_v2_manifest(),
        index_html=html,
        assets=[],
        expanded_bytes=len(html),
    )

    assert report["metrics"]["jsGzipBytes"] > 0
    assert report["metrics"]["cssGzipBytes"] > 0
