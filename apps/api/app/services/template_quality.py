from __future__ import annotations

import gzip
import re
from html.parser import HTMLParser
from pathlib import PurePosixPath


JS_GZIP_BUDGET = 250 * 1024
CSS_GZIP_BUDGET = 80 * 1024
LARGE_IMAGE_BYTES = 1024 * 1024
JS_EXTENSIONS = {".js", ".mjs", ".cjs"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}
STANDARD_COMPONENTS = {
    "account-link-flow",
    "account-link-locale-switcher",
    "phone-number-field",
    "account-link-submit",
    "pairing-code-panel",
    "app-launch-actions",
    "account-link-status",
    "account-initialization-status",
}
EXTERNAL_URL_RE = re.compile(r"(?:https?:)?//", re.I)
SOURCE_MAP_RE = re.compile(r"sourceMappingURL\s*=", re.I)


class _TemplateHtmlInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []
        self.external_references: set[str] = set()
        self.iframes: list[str] = []
        self.component_tags: set[str] = set()
        self.viewport_content: str | None = None
        self.inline_scripts: list[str] = []
        self.inline_styles: list[str] = []
        self._text_resource_tag: str | None = None
        self._text_resource_data: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()
        attributes = {
            key.lower(): str(value or "")
            for key, value in attrs
        }
        if normalized_tag == "meta" and attributes.get("name", "").lower() == "viewport":
            self.viewport_content = attributes.get("content", "")
        if normalized_tag == "img":
            self.images.append(attributes)
        if normalized_tag == "iframe":
            self.iframes.append(attributes.get("src") or "iframe")
        if normalized_tag in STANDARD_COMPONENTS:
            self.component_tags.add(normalized_tag)
        resource_attributes = {
            "script": ("src",),
            "link": ("href",),
            "iframe": ("src",),
            "img": ("src", "srcset"),
            "source": ("src", "srcset"),
            "video": ("src", "poster"),
            "audio": ("src",),
            "object": ("data",),
        }.get(normalized_tag, ())
        for attribute in resource_attributes:
            value = attributes.get(attribute, "")
            if value and EXTERNAL_URL_RE.search(value):
                self.external_references.add(f"index.html <{normalized_tag}> {attribute}")
        if normalized_tag in {"script", "style"}:
            self._text_resource_tag = normalized_tag
            self._text_resource_data = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == self._text_resource_tag:
            content = "".join(self._text_resource_data)
            if self._text_resource_tag == "script" and content.strip():
                self.inline_scripts.append(content)
            if self._text_resource_tag == "style" and content.strip():
                self.inline_styles.append(content)
            self._text_resource_tag = None
            self._text_resource_data = []

    def handle_data(self, data: str) -> None:
        if self._text_resource_tag:
            self._text_resource_data.append(data)
            if EXTERNAL_URL_RE.search(data):
                self.external_references.add(
                    f"index.html <{self._text_resource_tag}>"
                )


def _gzip_size(content: bytes) -> int:
    return len(gzip.compress(content, compresslevel=9, mtime=0))


def _warning(
    code: str,
    message: str,
    paths: list[str] | None = None,
) -> dict:
    return {
        "code": code,
        "message": message,
        **({"paths": paths[:8]} if paths else {}),
    }


def unchecked_template_quality_report() -> dict:
    return {
        "version": "template-quality/v1",
        "status": "unchecked",
        "metrics": {},
        "warnings": [],
    }


def inspect_template_quality(
    *,
    manifest: dict,
    index_html: str,
    assets: list[tuple[str, str, bytes]],
    expanded_bytes: int,
) -> dict:
    inspector = _TemplateHtmlInspector()
    inspector.feed(index_html)
    inspector.close()

    js_assets = [
        asset
        for asset in assets
        if PurePosixPath(asset[0]).suffix.lower() in JS_EXTENSIONS
    ]
    css_assets = [asset for asset in assets if PurePosixPath(asset[0]).suffix.lower() == ".css"]
    image_assets = [
        asset
        for asset in assets
        if PurePosixPath(asset[0]).suffix.lower() in IMAGE_EXTENSIONS
    ]
    js_gzip_bytes = sum(_gzip_size(content) for _, _, content in js_assets) + sum(
        _gzip_size(content.encode()) for content in inspector.inline_scripts
    )
    css_gzip_bytes = sum(_gzip_size(content) for _, _, content in css_assets) + sum(
        _gzip_size(content.encode()) for content in inspector.inline_styles
    )
    warnings: list[dict] = []

    if js_gzip_bytes > JS_GZIP_BUDGET:
        warnings.append(
            _warning(
                "js_gzip_budget",
                f"JavaScript gzip 估算为 {js_gzip_bytes} B，建议不超过 {JS_GZIP_BUDGET} B。",
                [path for path, _, _ in js_assets]
                + (["index.html 内联脚本"] if inspector.inline_scripts else []),
            )
        )
    if css_gzip_bytes > CSS_GZIP_BUDGET:
        warnings.append(
            _warning(
                "css_gzip_budget",
                f"CSS gzip 估算为 {css_gzip_bytes} B，建议不超过 {CSS_GZIP_BUDGET} B。",
                [path for path, _, _ in css_assets]
                + (["index.html 内联样式"] if inspector.inline_styles else []),
            )
        )

    source_map_paths = [
        path
        for path, _, content in [*js_assets, *css_assets]
        if SOURCE_MAP_RE.search(content.decode("utf-8", errors="ignore"))
    ]
    if SOURCE_MAP_RE.search(index_html):
        source_map_paths.insert(0, "index.html")
    if source_map_paths:
        warnings.append(
            _warning(
                "source_map_reference",
                "发现 sourceMappingURL 引用；生产模板应关闭 source map。",
                source_map_paths,
            )
        )

    external_paths = set(inspector.external_references)
    for path, _, content in [*js_assets, *css_assets]:
        if EXTERNAL_URL_RE.search(content.decode("utf-8", errors="ignore")):
            external_paths.add(path)
    if external_paths:
        warnings.append(
            _warning(
                "external_resource",
                "发现外部资源地址；模板资源应自包含，运行时能力应通过集成管理配置。",
                sorted(external_paths),
            )
        )
    if inspector.iframes:
        warnings.append(
            _warning(
                "template_iframe",
                "模板自行包含 iframe；需要 iframe 时应通过平台集成管理统一注入。",
                inspector.iframes,
            )
        )

    large_images = [
        path for path, _, content in image_assets if len(content) > LARGE_IMAGE_BYTES
    ]
    if large_images:
        warnings.append(
            _warning(
                "large_images",
                f"发现 {len(large_images)} 张超过 1 MB 的图片，建议压缩或转换为 WebP/AVIF。",
                large_images,
            )
        )

    missing_alt = [image.get("src") or f"第 {index + 1} 张图片" for index, image in enumerate(inspector.images) if "alt" not in image]
    if missing_alt:
        warnings.append(
            _warning(
                "image_alt",
                f"有 {len(missing_alt)} 张图片缺少 alt 属性。",
                missing_alt,
            )
        )
    missing_dimensions = [
        image.get("src") or f"第 {index + 1} 张图片"
        for index, image in enumerate(inspector.images)
        if not image.get("width") or not image.get("height")
    ]
    if missing_dimensions:
        warnings.append(
            _warning(
                "image_dimensions",
                f"有 {len(missing_dimensions)} 张图片未同时声明 width 和 height，可能造成布局抖动。",
                missing_dimensions,
            )
        )
    missing_lazy = [
        image.get("src") or f"第 {index + 1} 张图片"
        for index, image in enumerate(inspector.images[1:], start=1)
        if image.get("loading", "").lower() != "lazy"
    ]
    if missing_lazy:
        warnings.append(
            _warning(
                "image_lazy_loading",
                f"除首张图片外，有 {len(missing_lazy)} 张图片未声明 loading=lazy。",
                missing_lazy,
            )
        )

    if inspector.viewport_content is None:
        warnings.append(
            _warning(
                "viewport_missing",
                "index.html 缺少移动端 viewport 声明。",
            )
        )
    else:
        viewport = inspector.viewport_content.lower().replace(" ", "")
        if "user-scalable=no" in viewport or re.search(
            r"maximum-scale=1(?:\.0+)?(?:,|$)", viewport
        ):
            warnings.append(
                _warning(
                    "viewport_zoom_locked",
                    "模板自行限制了页面缩放；缩放行为应交给平台模板策略。",
                )
            )

    schema = str(manifest.get("schema") or "")
    if schema != "promotion-template/v3":
        warnings.append(
            _warning(
                "unsupported_template_schema",
                "模板必须使用 promotion-template/v3。",
            )
        )
    else:
        components = manifest.get("components") or {}
        missing_components = sorted(STANDARD_COMPONENTS - inspector.component_tags)
        if (
            components.get("contract") != "account-link-elements/v1"
            or not components.get("entry")
            or missing_components
        ):
            warnings.append(
                _warning(
                    "bundled_component_kit",
                    "v3 模板必须声明并打包 account-link-elements/v1 组件。",
                    missing_components,
                )
            )

    return {
        "version": "template-quality/v1",
        "status": "warnings" if warnings else "passed",
        "metrics": {
            "expandedBytes": expanded_bytes,
            "assetCount": len(assets),
            "jsGzipBytes": js_gzip_bytes,
            "cssGzipBytes": css_gzip_bytes,
            "imageBytes": sum(len(content) for _, _, content in image_assets),
            "imageCount": len(image_assets),
        },
        "warnings": warnings,
    }
