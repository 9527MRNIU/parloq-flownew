from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from app.config import get_settings


BINARY_MATERIAL_TYPES = {"image", "video", "audio", "document", "gif", "sticker"}
STRUCTURED_MATERIAL_TYPES = {"text", "contact"}
MATERIAL_TYPES = BINARY_MATERIAL_TYPES | STRUCTURED_MATERIAL_TYPES
MAX_MATERIAL_BYTES = {
    "image": 8 * 1024 * 1024,
    "video": 64 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 64 * 1024 * 1024,
    "gif": 16 * 1024 * 1024,
    "sticker": 1024 * 1024,
}
BLOCKED_DOCUMENT_EXTENSIONS = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".html",
    ".htm",
    ".js",
    ".mjs",
    ".php",
    ".ps1",
    ".py",
    ".sh",
}
SAFE_FILENAME = re.compile(r"[^\w.()\-\u4e00-\u9fff ]+", re.UNICODE)


def safe_filename(value: str | None, fallback: str = "material") -> str:
    raw = Path(str(value or "").replace("\\", "/")).name.strip()
    cleaned = SAFE_FILENAME.sub("_", raw).strip(" .")
    return (cleaned or fallback)[:180]


def _detect_content_type(material_type: str, filename: str, raw: bytes) -> str:
    lower = filename.lower()
    if material_type == "image":
        if raw.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return "image/webp"
        if len(raw) >= 12 and raw[4:8] == b"ftyp" and raw[8:12] in {b"avif", b"avis"}:
            return "image/avif"
        raise HTTPException(status_code=422, detail="图片仅支持 JPG、PNG、WebP 或 AVIF")
    if material_type == "gif":
        if raw.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        raise HTTPException(status_code=422, detail="GIF 素材必须上传 GIF 文件")
    if material_type == "sticker":
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return "image/webp"
        raise HTTPException(status_code=422, detail="贴纸素材必须上传 WebP 文件")
    if material_type == "video":
        if len(raw) >= 12 and raw[4:8] == b"ftyp":
            return "video/quicktime" if raw[8:12] == b"qt  " else "video/mp4"
        if raw.startswith(b"\x1aE\xdf\xa3"):
            return "video/webm"
        raise HTTPException(status_code=422, detail="视频仅支持 MP4、MOV 或 WebM")
    if material_type == "audio":
        if raw.startswith(b"ID3") or raw.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "audio/mpeg"
        if raw.startswith(b"OggS"):
            return "audio/ogg"
        if raw.startswith(b"fLaC"):
            return "audio/flac"
        if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
            return "audio/wav"
        if len(raw) >= 12 and raw[4:8] == b"ftyp":
            return "audio/mp4"
        raise HTTPException(status_code=422, detail="语音仅支持 MP3、M4A、OGG、WAV 或 FLAC")
    if material_type == "document":
        if Path(lower).suffix in BLOCKED_DOCUMENT_EXTENSIONS:
            raise HTTPException(status_code=422, detail="该文件类型不能作为文档素材上传")
        return "application/pdf" if raw.startswith(b"%PDF-") else "application/octet-stream"
    raise HTTPException(status_code=422, detail="该素材类型不支持文件上传")


async def read_material_upload(
    material_type: str,
    upload: UploadFile,
) -> tuple[bytes, str, str, str]:
    if material_type not in BINARY_MATERIAL_TYPES:
        raise HTTPException(status_code=422, detail="该素材类型不支持文件上传")
    filename = safe_filename(upload.filename)
    limit = MAX_MATERIAL_BYTES[material_type]
    raw = await upload.read(limit + 1)
    await upload.close()
    if not raw:
        raise HTTPException(status_code=422, detail="上传文件不能为空")
    if len(raw) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{material_type} 素材不能超过 {limit // (1024 * 1024)} MB",
        )
    detected_type = _detect_content_type(material_type, filename, raw)
    return raw, filename, detected_type, hashlib.sha256(raw).hexdigest()


def issue_material_access_token(
    material_id: int,
    sha256: str,
    *,
    ttl_seconds: int = 30 * 60,
) -> str:
    payload = {
        "id": str(material_id),
        "sha256": sha256,
        "exp": int(time.time()) + ttl_seconds,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_material_access_token(
    token: str,
    material_id: int,
    sha256: str,
) -> bool:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        padded = encoded + "=" * (-len(encoded) % 4)
        payload: dict[str, Any] = json.loads(
            base64.urlsafe_b64decode(padded.encode()).decode()
        )
        return (
            payload.get("id") == str(material_id)
            and payload.get("sha256") == sha256
            and int(payload.get("exp") or 0) >= int(time.time())
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def material_delivery_reference(material: Any) -> dict[str, Any]:
    if not material.file_sha256 or not material.content_type or not material.file_size:
        raise ValueError("关联素材尚未上传文件")
    return {
        "id": str(material.id),
        "token": issue_material_access_token(material.id, material.file_sha256),
        "fileName": material.file_name or "material",
        "mimeType": material.content_type,
        "size": material.file_size,
        "sha256": material.file_sha256,
    }
