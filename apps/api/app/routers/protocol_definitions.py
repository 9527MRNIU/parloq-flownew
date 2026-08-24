from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import ProtocolDefinitionCreate
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.models import ProtocolBuildJob, ProtocolDefinition, ProtocolNode
from app.services.protocol_adapters import validate_protocol_source
from app.services.protocol_builds import queue_protocol_build
from app.services.protocol_catalog import (
    is_prerelease_version,
    npm_package_catalog,
    npm_version_summary,
)
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.snowflake import new_public_id


router = APIRouter(
    prefix="/api/protocol-definitions",
    tags=["protocol-definitions"],
)


def _definition(db: DbSession, identifier: str) -> ProtocolDefinition:
    item = db.scalar(
        select(ProtocolDefinition).where(
            identifier_filter(ProtocolDefinition, identifier)
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="协议不存在")
    return item


def _runtime_info() -> dict:
    try:
        return WaGatewayClient().protocol_info()
    except GatewayError:
        return {}


def _row(
    item: ProtocolDefinition,
    *,
    node_count: int,
    upstream: dict[str, str | None],
    runtime: dict,
    latest_build: ProtocolBuildJob | None = None,
) -> dict:
    runtime_version = str(runtime.get("baileysVersion") or "")
    runtime_matches = (
        str(runtime.get("protocol") or "") == item.adapter_key
        and runtime_version == item.version
    )
    version_category = (
        "preview" if is_prerelease_version(item.version) else "stable"
    )
    return {
        "id": entity_id(item),
        "name": item.name,
        "adapterKey": item.adapter_key,
        "repositoryUrl": item.repository_url,
        "packageName": item.package_name,
        "version": item.version,
        "upstreamRef": item.upstream_ref,
        "buildStatus": item.build_status,
        "contractVersion": item.contract_version,
        "enabled": item.enabled,
        "builtin": item.is_builtin,
        "remark": item.remark,
        "nodeCount": node_count,
        "runtimeInstalled": runtime_matches or bool(
            item.build_status == "ready" and item.artifact_digest
        ),
        "runtimeActive": runtime_matches,
        "runtimeEngine": runtime.get("engine") if runtime_matches else None,
        "currentWebRevision": (
            runtime.get("currentWaWebVersion") if runtime_matches else None
        ),
        "versionCategory": version_category,
        "remoteLatestVersion": upstream.get(
            "latestPreview"
            if version_category == "preview"
            else "latestStable"
        ),
        "upstreamCheckedAt": upstream.get("checkedAt"),
        "upstreamError": upstream.get("error"),
        "artifactDigest": item.artifact_digest,
        "artifactIntegrity": item.artifact_integrity,
        "buildErrorCode": item.build_error_code,
        "buildErrorMessage": item.build_error_message,
        "buildStartedAt": (
            item.build_started_at.isoformat() if item.build_started_at else None
        ),
        "builtAt": item.built_at.isoformat() if item.built_at else None,
        "latestBuild": (
            {
                "id": entity_id(latest_build),
                "status": latest_build.status,
                "attemptNumber": latest_build.attempt_number,
                "errorCode": latest_build.error_code,
                "errorMessage": latest_build.error_message,
                "logExcerpt": latest_build.log_excerpt,
                "startedAt": (
                    latest_build.started_at.isoformat()
                    if latest_build.started_at
                    else None
                ),
                "finishedAt": (
                    latest_build.finished_at.isoformat()
                    if latest_build.finished_at
                    else None
                ),
            }
            if latest_build is not None
            else None
        ),
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


@router.get("")
def list_protocol_definitions(
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    del current_user
    items = db.scalars(
        select(ProtocolDefinition).order_by(
            ProtocolDefinition.is_builtin.desc(),
            ProtocolDefinition.id,
        )
    ).all()
    counts = dict(
        db.execute(
            select(
                ProtocolNode.protocol_definition_id,
                func.count(ProtocolNode.id),
            ).group_by(ProtocolNode.protocol_definition_id)
        ).all()
    )
    runtime = _runtime_info()
    latest_builds: dict[int, ProtocolBuildJob] = {}
    for job in db.scalars(
        select(ProtocolBuildJob).order_by(
            ProtocolBuildJob.protocol_definition_id,
            ProtocolBuildJob.id.desc(),
        )
    ).all():
        latest_builds.setdefault(job.protocol_definition_id, job)
    upstream_by_package = {
        package_name: npm_version_summary(package_name)
        for package_name in {item.package_name for item in items}
    }
    return {
        "data": {
            "rows": [
                _row(
                    item,
                    node_count=int(counts.get(item.id, 0)),
                    upstream=upstream_by_package[item.package_name],
                    runtime=runtime,
                    latest_build=latest_builds.get(item.id),
                )
                for item in items
            ],
            "total": len(items),
        }
    }


@router.get("/options")
def list_protocol_definition_options(
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    del current_user
    items = db.scalars(
        select(ProtocolDefinition).order_by(
            ProtocolDefinition.is_builtin.desc(),
            ProtocolDefinition.id,
        )
    ).all()
    return {
        "data": {
            "rows": [
                _definition_option(item)
                for item in items
                if item.enabled and item.build_status == "ready"
            ],
            "total": sum(
                item.enabled and item.build_status == "ready"
                for item in items
            ),
        }
    }


@router.get("/available-versions")
def list_available_protocol_versions(
    current_user: CurrentUser,
    package_name: str = Query(
        alias="packageName",
        min_length=1,
        max_length=160,
    ),
) -> dict:
    del current_user
    catalog = npm_package_catalog(package_name)
    tags = catalog.get("tags")
    tags = tags if isinstance(tags, dict) else {}
    stable_versions = catalog.get("stableVersions")
    stable_versions = stable_versions if isinstance(stable_versions, list) else []
    preview_versions = catalog.get("previewVersions")
    preview_versions = preview_versions if isinstance(preview_versions, list) else []
    return {
        "data": {
            "rows": [
                {
                    "version": str(version),
                    "category": category,
                    "tags": sorted(
                        str(tag)
                        for tag, tagged_version in tags.items()
                        if tagged_version == version
                    ),
                }
                for category, versions in (
                    ("stable", stable_versions),
                    ("preview", preview_versions),
                )
                for version in versions
            ],
            "latestStable": catalog.get("latestStable"),
            "latestPreview": catalog.get("latestPreview"),
            "checkedAt": catalog.get("checkedAt"),
            "error": catalog.get("error"),
        }
    }


def _definition_option(item: ProtocolDefinition) -> dict:
    return {
        "id": entity_id(item),
        "name": item.name,
        "adapterKey": item.adapter_key,
        "version": item.version,
        "buildStatus": item.build_status,
        "enabled": item.enabled,
        "builtin": item.is_builtin,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_protocol_definition(
    payload: ProtocolDefinitionCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    del current_user
    adapter = validate_protocol_source(
        adapter_key=payload.adapter_key,
        repository_url=payload.repository_url,
        package_name=payload.package_name,
    )
    catalog = npm_package_catalog(payload.package_name)
    if catalog.get("error"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="暂时无法读取 NPM 软件包版本，请稍后重试",
        )
    available_versions = catalog.get("versions")
    if (
        not isinstance(available_versions, list)
        or payload.version not in available_versions
    ):
        raise HTTPException(
            status_code=422,
            detail="所选版本不在该 NPM 软件包的远程版本列表中",
        )
    item = ProtocolDefinition(
        public_id=new_public_id("protocol-definition"),
        name=payload.name,
        adapter_key=payload.adapter_key,
        repository_url=payload.repository_url,
        package_name=payload.package_name,
        version=payload.version,
        upstream_ref=payload.upstream_ref,
        build_status="pending",
        contract_version=adapter.contract_version,
        enabled=True,
        is_builtin=False,
        remark=payload.remark,
    )
    db.add(item)
    try:
        db.flush()
        job = queue_protocol_build(db, item)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="该实现仓库和版本已经创建过协议",
        ) from None
    db.refresh(item)
    upstream = npm_version_summary(item.package_name)
    return {
        "data": {
            "protocol": _row(
                item,
                node_count=0,
                upstream=upstream,
                runtime=_runtime_info(),
                latest_build=job,
            )
        }
    }


@router.get("/{protocol_id}/builds")
def list_protocol_builds(
    protocol_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    del current_user
    item = _definition(db, protocol_id)
    jobs = db.scalars(
        select(ProtocolBuildJob)
        .where(ProtocolBuildJob.protocol_definition_id == item.id)
        .order_by(ProtocolBuildJob.id.desc())
    ).all()
    return {
        "data": {
            "rows": [
                {
                    "id": entity_id(job),
                    "status": job.status,
                    "attemptNumber": job.attempt_number,
                    "errorCode": job.error_code,
                    "errorMessage": job.error_message,
                    "logExcerpt": job.log_excerpt,
                    "artifactDigest": job.artifact_digest,
                    "artifactIntegrity": job.artifact_integrity,
                    "startedAt": job.started_at.isoformat() if job.started_at else None,
                    "finishedAt": job.finished_at.isoformat() if job.finished_at else None,
                    "createdAt": job.created_at.isoformat(),
                }
                for job in jobs
            ],
            "total": len(jobs),
        }
    }


@router.post("/{protocol_id}/builds", status_code=status.HTTP_202_ACCEPTED)
def retry_protocol_build(
    protocol_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    del current_user
    item = _definition(db, protocol_id)
    if item.is_builtin:
        raise HTTPException(status_code=409, detail="内置协议不需要重新构建")
    if item.build_status == "ready":
        raise HTTPException(status_code=409, detail="协议运行包已经构建完成")
    try:
        job = queue_protocol_build(db, item)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="协议已经在构建队列中") from exc
    db.commit()
    db.refresh(job)
    return {
        "data": {
            "build": {
                "id": entity_id(job),
                "status": job.status,
                "attemptNumber": job.attempt_number,
            }
        }
    }


@router.delete("/{protocol_id}")
def delete_protocol_definition(
    protocol_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    del current_user
    item = _definition(db, protocol_id)
    if item.is_builtin:
        raise HTTPException(status_code=409, detail="内置协议不能删除")
    if db.scalar(
        select(ProtocolNode.id).where(
            ProtocolNode.protocol_definition_id == item.id
        ).limit(1)
    ) is not None:
        raise HTTPException(status_code=409, detail="仍有节点使用该协议")
    if db.scalar(
        select(ProtocolBuildJob.id).where(
            ProtocolBuildJob.protocol_definition_id == item.id,
            ProtocolBuildJob.status.in_(("queued", "building")),
        ).limit(1)
    ) is not None:
        raise HTTPException(status_code=409, detail="协议正在构建，暂时不能删除")
    db.delete(item)
    db.commit()
    return {"data": {"deleted": True}}
