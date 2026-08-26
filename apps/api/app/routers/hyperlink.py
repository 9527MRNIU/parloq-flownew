from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    DataPackageCreate, DataPackageUpdate, HyperlinkTemplateCreate,
    HyperlinkTemplateUpdate,
    RecipientsImport, StrategyCreate, StrategyUpdate, TaskCreate, TaskUpdate,
)
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.hyperlink_strategy import (
    merge_strategy_rules,
    normalize_strategy_rules,
    strategy_policy,
)
from app.snowflake import new_public_id, parse_snowflake_id

from app.models import (
    AccountGroup, DataPackage, DataPackageRecipient, Material,
    HyperlinkStrategy, HyperlinkTask, HyperlinkTaskAccountSlot,
    HyperlinkTaskDelivery, HyperlinkTemplate,
    MessageDelivery, PersonalAccount, PromotionChannel,
)
from app.material_files import BINARY_MATERIAL_TYPES
from app.security import utcnow
from app.serializers import iso
from app.task_queue import enqueue_hyperlink_task
from app.validation import phone_country_code


router = APIRouter(prefix="/api/hyperlink", tags=["hyperlink"])


def _one(db: DbSession, model: type, identifier: str, label: str, user):
    statement = select(model).where(identifier_filter(model, identifier))
    if user.role != "admin": statement = statement.where(model.created_by == user.id)
    item = db.scalar(statement)
    if item is None: raise HTTPException(status_code=404, detail=f"{label}不存在")
    return item


def _base(item) -> dict: return {"id": entity_id(item), "createdAt": iso(item.created_at), "updatedAt": iso(item.updated_at)}
def strategy_row(x: HyperlinkStrategy) -> dict:
    rules = normalize_strategy_rules(x.rules_json)
    return {
        **_base(x),
        "name": x.name,
        "maxQps": x.max_qps,
        "concurrency": x.concurrency,
        "retryLimit": x.retry_limit,
        **rules,
        "enabled": x.enabled,
    }


def template_row(db: DbSession, x: HyperlinkTemplate) -> dict:
    material = db.get(Material, x.material_id) if x.material_id else None; channel = db.get(PromotionChannel, x.promotion_channel_id) if x.promotion_channel_id else None
    return {**_base(x), "name": x.name, "contentJson": x.content_json, "materialId": entity_id(material) if material else None, "promotionChannelId": entity_id(channel) if channel else None, "enabled": x.enabled}


def package_row(db: DbSession, x: DataPackage) -> dict:
    count = int(db.scalar(select(func.count()).select_from(DataPackageRecipient).where(DataPackageRecipient.data_package_id == x.id, DataPackageRecipient.removed_revision.is_(None))) or 0)
    task_count = int(db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.data_package_id == x.id)) or 0)
    return {**_base(x), "name": x.name, "status": x.status, "revision": x.revision, "sealedAt": iso(x.sealed_at), "recipientCount": count, "taskCount": task_count}


def recipient_row(x: DataPackageRecipient) -> dict: return {**_base(x), "phone": x.phone_e164, "countryCode": x.country_code, "variables": x.variables_json, "packageRevision": x.package_revision, "removedRevision": x.removed_revision, "validationStatus": x.validation_status, "lastError": x.last_error}


def _freeze_task_template(db: DbSession, task: HyperlinkTask) -> None:
    if task.template_snapshot_json:
        return
    template = db.get(HyperlinkTemplate, task.template_id)
    if template is None:
        raise HTTPException(status_code=409, detail="任务模板不存在")
    material = db.get(Material, template.material_id) if template.material_id else None
    task.template_name_snapshot = template.name
    task.template_snapshot_json = {
        "templateId": entity_id(template),
        "name": template.name,
        "contentJson": deepcopy(template.content_json or {}),
        "material": (
            {
                "id": entity_id(material),
                "name": material.name,
                "type": material.material_type,
                "fileName": material.file_name,
                "contentType": material.content_type,
                "fileSize": material.file_size,
                "sha256": material.file_sha256,
            }
            if material is not None
            else None
        ),
    }


def _sync_task_counts(db: DbSession, task: HyperlinkTask) -> None:
    submission_counts = {
        str(submission_status): int(count)
        for submission_status, count in db.execute(
            select(
                HyperlinkTaskDelivery.submission_status,
                func.count(HyperlinkTaskDelivery.id),
            )
            .where(HyperlinkTaskDelivery.task_id == task.id)
            .group_by(HyperlinkTaskDelivery.submission_status)
        ).all()
    }
    message_counts = {
        str(message_status): int(count)
        for message_status, count in db.execute(
            select(MessageDelivery.status, func.count(HyperlinkTaskDelivery.id))
            .join(
                MessageDelivery,
                MessageDelivery.id == HyperlinkTaskDelivery.message_delivery_id,
            )
            .where(
                HyperlinkTaskDelivery.task_id == task.id,
                HyperlinkTaskDelivery.submission_status == "accepted",
            )
            .group_by(MessageDelivery.status)
        ).all()
    }
    task.total_count = sum(submission_counts.values())
    task.queued_count = sum(
        submission_counts.get(name, 0)
        for name in ("pending", "retry", "leased")
    )
    task.submitting_count = submission_counts.get("submitting", 0)
    task.accepted_count = submission_counts.get("accepted", 0)
    task.submission_failed_count = submission_counts.get("failed", 0)
    task.reconciling_count = submission_counts.get("reconciling", 0)
    task.cancelled_count = submission_counts.get("cancelled", 0)
    task.skipped_count = submission_counts.get("skipped", 0)
    task.sent_count = message_counts.get("sent", 0)
    task.delivered_count = message_counts.get("delivered", 0)
    task.failed_count = message_counts.get("failed", 0)
    accepted_pending = message_counts.get("queued", 0)
    if (
        task.status in {"running", "waiting_accounts"}
        and task.total_count
        and task.queued_count == 0
        and task.submitting_count == 0
        and task.reconciling_count == 0
        and accepted_pending == 0
    ):
        task.status = "completed"
        task.completed_at = task.completed_at or utcnow()
        now = utcnow()
        for slot in db.scalars(
            select(HyperlinkTaskAccountSlot).where(
                HyperlinkTaskAccountSlot.task_id == task.id,
                HyperlinkTaskAccountSlot.account_id.is_not(None),
            )
        ).all():
            slot.status = "released"
            slot.account_id = None
            slot.lease_token = None
            slot.lease_expires_at = None
            slot.released_at = now
            slot.last_switch_reason = "task_completed"


def task_row(db: DbSession, x: HyperlinkTask) -> dict:
    _sync_task_counts(db, x); tpl = db.get(HyperlinkTemplate, x.template_id); strategy = db.get(HyperlinkStrategy, x.strategy_id); package = db.get(DataPackage, x.data_package_id)
    account_group = db.get(AccountGroup, x.account_group_id) if x.account_group_id else None
    snapshot = x.template_snapshot_json if isinstance(x.template_snapshot_json, dict) else None
    template_name = x.template_name_snapshot or (tpl.name if tpl else "")
    template_content = (
        snapshot.get("contentJson")
        if snapshot and isinstance(snapshot.get("contentJson"), dict)
        else (deepcopy(tpl.content_json or {}) if tpl else {})
    )
    slot_counts = {
        str(slot_status): int(count)
        for slot_status, count in db.execute(
            select(
                HyperlinkTaskAccountSlot.status,
                func.count(HyperlinkTaskAccountSlot.id),
            )
            .where(HyperlinkTaskAccountSlot.task_id == x.id)
            .group_by(HyperlinkTaskAccountSlot.status)
        ).all()
    }
    active_slot_count = int(
        db.scalar(
            select(func.count())
            .select_from(HyperlinkTaskAccountSlot)
            .where(
                HyperlinkTaskAccountSlot.task_id == x.id,
                HyperlinkTaskAccountSlot.account_id.is_not(None),
                HyperlinkTaskAccountSlot.status == "active",
            )
        )
        or 0
    )
    row = {
        **_base(x),
        "name": x.name,
        "templateId": entity_id(tpl) if tpl else None,
        "templateName": template_name,
        "templateContent": template_content,
        "templateSnapshot": snapshot,
        "strategyId": entity_id(strategy) if strategy else None,
        "dataPackageId": entity_id(package) if package else None,
        "dataPackageName": package.name if package else None,
        "dataPackageRevision": x.data_package_revision,
        "accountGroupId": entity_id(account_group) if account_group else None,
        "accountGroupName": account_group.name if account_group else None,
        "senderMode": x.sender_mode,
        "channel": x.channel,
        "status": x.status,
        "totalCount": x.total_count,
        "queuedCount": x.queued_count,
        "submittingCount": x.submitting_count,
        "acceptedCount": x.accepted_count,
        "submissionFailedCount": x.submission_failed_count,
        "reconcilingCount": x.reconciling_count,
        "cancelledCount": x.cancelled_count,
        "skippedCount": x.skipped_count,
        "sentCount": x.sent_count,
        "deliveredCount": x.delivered_count,
        "failedCount": x.failed_count,
        "submissionStats": {
            "total": x.total_count,
            "waiting": x.queued_count,
            "submitting": x.submitting_count,
            "accepted": x.accepted_count,
            "failed": x.submission_failed_count,
            "reconciling": x.reconciling_count,
            "cancelled": x.cancelled_count,
            "skipped": x.skipped_count,
        },
        "sendStats": {
            "sent": x.sent_count + x.delivered_count,
            "delivered": x.delivered_count,
            "failed": x.failed_count,
        },
        "accountSlotStats": {
            "total": sum(slot_counts.values()),
            "active": active_slot_count,
            "vacant": slot_counts.get("vacant", 0),
            "replacing": slot_counts.get("replacing", 0),
            "released": slot_counts.get("released", 0),
        },
        "startedAt": iso(x.started_at),
        "pausedAt": iso(x.paused_at),
        "cancelledAt": iso(x.cancelled_at),
        "completedAt": iso(x.completed_at),
    }
    if x.sender_mode == "legacy_fixed":
        row["accountIds"] = x.account_public_ids
    return row


def _list(db, model, user):
    statement = select(model)
    if user.role != "admin": statement = statement.where(model.created_by == user.id)
    return db.scalars(statement.order_by(model.created_at.desc())).all()


def _paged_list(
    db: DbSession,
    model: type,
    user,
    *,
    keyword: str,
    page: int,
    page_size: int,
    search_columns: tuple,
    extra_predicates: tuple = (),
) -> tuple[list, int]:
    statement = select(model)
    if user.role != "admin":
        statement = statement.where(model.created_by == user.id)
    search = keyword.strip()
    if search:
        pattern = f"%{search}%"
        statement = statement.where(
            or_(
                cast(model.id, String).ilike(pattern),
                model.public_id.ilike(pattern),
                *(column.ilike(pattern) for column in search_columns),
            )
        )
    if extra_predicates:
        statement = statement.where(*extra_predicates)
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = list(
        db.scalars(
            statement.order_by(model.created_at.desc(), model.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def _template_refs(db, user, material_id, promotion_id, current=None):
    mat=current.material_id if current else None; promo=current.promotion_channel_id if current else None
    if material_id is not None:
        mat=_one(db,Material,material_id,"素材",user).id if material_id else None
    if promotion_id is not None:
        promo=_one(db,PromotionChannel,promotion_id,"推广渠道",user).id if promotion_id else None
    return mat,promo


def _ensure_template_media(
    db: DbSession, content: dict, material_id: int | None
) -> None:
    header = content.get("header") if isinstance(content, dict) else None
    header = header if isinstance(header, dict) else {}
    header_type = str(header.get("type") or "none")
    if header_type not in {"image", "video", "document"}:
        return
    material = db.get(Material, material_id) if material_id else None
    if material is None:
        raise HTTPException(status_code=422, detail="媒体页头需要选择已上传的关联素材")
    if material.material_type != header_type:
        raise HTTPException(status_code=422, detail="关联素材类型与模板页头类型不一致")
    if (
        material.material_type not in BINARY_MATERIAL_TYPES
        or not material.file_sha256
        or not material.file_size
        or not material.content_type
    ):
        raise HTTPException(status_code=422, detail="关联素材尚未完成文件上传")
    if not material.enabled:
        raise HTTPException(status_code=422, detail="关联素材已停用")


@router.get("/templates")
def templates(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str = Query(default="", max_length=200),
    enabled: bool | None = None,
    header_type: str | None = Query(default=None, alias="headerType"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    predicates = []
    if enabled is not None:
        predicates.append(HyperlinkTemplate.enabled.is_(enabled))
    if header_type and header_type != "all":
        predicates.append(
            HyperlinkTemplate.content_json["header"]["type"].as_string()
            == header_type
        )
    items, total = _paged_list(
        db,
        HyperlinkTemplate,
        current_user,
        keyword=keyword,
        page=page,
        page_size=page_size,
        search_columns=(HyperlinkTemplate.name, cast(HyperlinkTemplate.content_json, String)),
        extra_predicates=tuple(predicates),
    )
    return {"data":{"rows":[template_row(db,x) for x in items],"total":total,"page":page,"pageSize":page_size}}
@router.get("/templates/options")
def template_options(db:DbSession,current_user:CurrentUser)->dict:
    items=_list(db,HyperlinkTemplate,current_user);rows=[template_row(db,x) for x in items];return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/templates",status_code=201)
def create_template(p:HyperlinkTemplateCreate,db:DbSession,current_user:CurrentUser)->dict:
    mat,promo=_template_refs(db,current_user,p.material_id,p.promotion_channel_id)
    _ensure_template_media(db,p.content_json,mat)
    x=HyperlinkTemplate(public_id=new_public_id("htpl"),name=p.name,content_json=p.content_json,material_id=mat,promotion_channel_id=promo,enabled=p.enabled,created_by=current_user.id)
    db.add(x);db.commit();return {"data":{"template":template_row(db,x)}}
@router.get("/templates/{pid}")
def get_template(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"template":template_row(db,_one(db,HyperlinkTemplate,pid,"模板",current_user))}}
@router.patch("/templates/{pid}")
def update_template(pid:str,p:HyperlinkTemplateUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTemplate,pid,"模板",current_user)
    mat=x.material_id
    promo=x.promotion_channel_id
    if "material_id" in p.model_fields_set:
        mat=_one(db,Material,p.material_id,"素材",current_user).id if p.material_id else None
    if "promotion_channel_id" in p.model_fields_set:
        promo=_one(db,PromotionChannel,p.promotion_channel_id,"推广渠道",current_user).id if p.promotion_channel_id else None
    _ensure_template_media(db,p.content_json if p.content_json is not None else x.content_json,mat)
    if p.name is not None:x.name=p.name
    if p.content_json is not None:x.content_json=p.content_json
    if "material_id" in p.model_fields_set:x.material_id=mat if p.material_id else None
    if "promotion_channel_id" in p.model_fields_set:x.promotion_channel_id=promo if p.promotion_channel_id else None
    if p.enabled is not None:x.enabled=p.enabled
    db.commit();return {"data":{"template":template_row(db,x)}}
@router.delete("/templates/{pid}")
def delete_template(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTemplate,pid,"模板",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.template_id==x.id)):raise HTTPException(409,"模板仍被任务使用")
    db.delete(x);db.commit();return {"data":{"ok":True}}


@router.get("/strategies")
def strategies(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    items,total=_paged_list(db,HyperlinkStrategy,current_user,keyword=keyword,page=page,page_size=page_size,search_columns=(HyperlinkStrategy.name,));return {"data":{"rows":[strategy_row(x) for x in items],"total":total,"page":page,"pageSize":page_size}}
@router.get("/strategies/options")
def strategy_options(db:DbSession,current_user:CurrentUser)->dict:
    items=_list(db,HyperlinkStrategy,current_user);rows=[strategy_row(x) for x in items];return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/strategies",status_code=201)
def create_strategy(p:StrategyCreate,db:DbSession,current_user:CurrentUser)->dict:
    rules = merge_strategy_rules(
        p.rules_json,
        retry_backoff_seconds=p.retry_backoff_seconds if "retry_backoff_seconds" in p.model_fields_set else None,
        no_account_action=p.no_account_action if "no_account_action" in p.model_fields_set else None,
        send_jitter_ms=p.send_jitter_ms if "send_jitter_ms" in p.model_fields_set else None,
        account_failure_threshold=p.account_failure_threshold if "account_failure_threshold" in p.model_fields_set else None,
        account_cooldown_seconds=p.account_cooldown_seconds if "account_cooldown_seconds" in p.model_fields_set else None,
    )
    x=HyperlinkStrategy(public_id=new_public_id("hstr"),name=p.name,max_qps=p.max_qps,concurrency=p.concurrency,batch_size=2000,retry_limit=p.retry_limit,rules_json=rules,enabled=p.enabled,created_by=current_user.id);db.add(x);db.commit();return {"data":{"strategy":strategy_row(x)}}
@router.get("/strategies/{pid}")
def get_strategy(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"strategy":strategy_row(_one(db,HyperlinkStrategy,pid,"策略",current_user))}}
@router.patch("/strategies/{pid}")
def update_strategy(pid:str,p:StrategyUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkStrategy,pid,"策略",current_user)
    for f,a in (("name","name"),("max_qps","max_qps"),("concurrency","concurrency"),("retry_limit","retry_limit"),("enabled","enabled")):
        v=getattr(p,f);setattr(x,a,v) if v is not None else None
    rules_source = p.rules_json if "rules_json" in p.model_fields_set else x.rules_json
    x.rules_json = merge_strategy_rules(
        rules_source,
        retry_backoff_seconds=p.retry_backoff_seconds if "retry_backoff_seconds" in p.model_fields_set else None,
        no_account_action=p.no_account_action if "no_account_action" in p.model_fields_set else None,
        send_jitter_ms=p.send_jitter_ms if "send_jitter_ms" in p.model_fields_set else None,
        account_failure_threshold=p.account_failure_threshold if "account_failure_threshold" in p.model_fields_set else None,
        account_cooldown_seconds=p.account_cooldown_seconds if "account_cooldown_seconds" in p.model_fields_set else None,
    )
    db.commit();return {"data":{"strategy":strategy_row(x)}}
@router.delete("/strategies/{pid}")
def delete_strategy(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkStrategy,pid,"策略",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.strategy_id==x.id)):raise HTTPException(409,"策略仍被任务使用")
    db.delete(x);db.commit();return {"data":{"ok":True}}


def _add_recipients(db, package, values, *, bump_revision: bool = True):
    existing = {
        recipient.phone_e164: recipient
        for recipient in db.scalars(
            select(DataPackageRecipient).where(
                DataPackageRecipient.data_package_id == package.id
            )
        ).all()
    }
    requested = []
    seen: set[str] = set()
    for value in values:
        if value.phone in seen:
            continue
        seen.add(value.phone)
        current = existing.get(value.phone)
        if current is None or current.removed_revision is not None:
            requested.append((value, current))
    if not requested:
        return 0
    target_revision = max(int(package.revision or 1), 1)
    if bump_revision:
        target_revision += 1
        package.revision = target_revision
    for value, current in requested:
        if current is None:
            db.add(
                DataPackageRecipient(
                    public_id=new_public_id("hrcp"),
                    data_package_id=package.id,
                    phone_e164=value.phone,
                    country_code=phone_country_code(value.phone),
                    variables_json=value.variables,
                    package_revision=target_revision,
                    removed_revision=None,
                )
            )
        else:
            current.country_code = phone_country_code(value.phone)
            current.variables_json = value.variables
            current.package_revision = target_revision
            current.removed_revision = None
            current.validation_status = "valid"
            current.last_error = None
    db.commit()
    return len(requested)


@router.get("/data-packages")
def packages(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    items,total=_paged_list(db,DataPackage,current_user,keyword=keyword,page=page,page_size=page_size,search_columns=(DataPackage.name,DataPackage.status));return {"data":{"rows":[package_row(db,x) for x in items],"total":total,"page":page,"pageSize":page_size}}
@router.get("/data-packages/options")
def package_options(db:DbSession,current_user:CurrentUser)->dict:
    items=_list(db,DataPackage,current_user);rows=[package_row(db,x) for x in items];return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/data-packages",status_code=201)
def create_package(p:DataPackageCreate,db:DbSession,current_user:CurrentUser)->dict:
    x=DataPackage(public_id=new_public_id("hpkg"),name=p.name,status="ready",revision=1,created_by=current_user.id);db.add(x);db.flush();_add_recipients(db,x,p.recipients,bump_revision=False);return {"data":{"dataPackage":package_row(db,x)}}
@router.get("/data-packages/{pid}")
def get_package(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"dataPackage":package_row(db,_one(db,DataPackage,pid,"数据包",current_user))}}
@router.patch("/data-packages/{pid}")
def update_package(pid:str,p:DataPackageUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);x.name=p.name or x.name;db.commit();return {"data":{"dataPackage":package_row(db,x)}}
@router.delete("/data-packages/{pid}")
def delete_package(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.data_package_id==x.id)):raise HTTPException(409,"数据包仍被任务使用")
    db.delete(x);db.commit();return {"data":{"ok":True}}
@router.get("/data-packages/{pid}/recipients")
def recipients(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);rows=db.scalars(select(DataPackageRecipient).where(DataPackageRecipient.data_package_id==x.id,DataPackageRecipient.removed_revision.is_(None)).order_by(DataPackageRecipient.id)).all();return {"data":{"rows":[recipient_row(r) for r in rows],"total":len(rows)}}
@router.post("/data-packages/{pid}/recipients")
def import_recipients(pid:str,p:RecipientsImport,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);created=_add_recipients(db,x,p.recipients);return {"data":{"createdCount":created,"dataPackage":package_row(db,x)}}
@router.delete("/data-packages/{pid}/recipients/{rid}")
def delete_recipient(pid:str,rid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);r=db.scalar(select(DataPackageRecipient).where(identifier_filter(DataPackageRecipient,rid),DataPackageRecipient.data_package_id==x.id,DataPackageRecipient.removed_revision.is_(None)))
    if not r:raise HTTPException(404,"收件人不存在")
    if db.scalar(select(func.count()).select_from(HyperlinkTaskDelivery).where(HyperlinkTaskDelivery.recipient_id==r.id)):raise HTTPException(409,"收件人仍被任务明细使用")
    db.delete(r);x.revision=max(int(x.revision or 1),1)+1;db.commit();return {"data":{"ok":True,"dataPackage":package_row(db,x)}}


def _task_group(db: DbSession, group_id: str, user) -> AccountGroup:
    try:
        database_id = parse_snowflake_id(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="账号分组不存在") from None
    group = db.scalar(
        select(AccountGroup).where(
            AccountGroup.id == database_id,
            AccountGroup.created_by == user.id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="账号分组不存在")
    return group


def _task_refs(db,p,user,current=None):
    tpl=current.template_id if current else None;strategy=current.strategy_id if current else None;package=current.data_package_id if current else None
    if getattr(p,"template_id",None):tpl=_one(db,HyperlinkTemplate,p.template_id,"模板",user).id
    if getattr(p,"strategy_id",None):
        strategy_item=_one(db,HyperlinkStrategy,p.strategy_id,"策略",user)
        if not strategy_item.enabled:raise HTTPException(409,"发送策略已停用")
        strategy=strategy_item.id
    if getattr(p,"data_package_id",None):package=_one(db,DataPackage,p.data_package_id,"数据包",user).id
    group_id = current.account_group_id if current else None
    if "account_group_id" in p.model_fields_set:
        if current is not None and current.sender_mode == "legacy_fixed":
            raise HTTPException(409,"历史固定账号任务不支持变更账号分组")
        if p.account_group_id is None:
            raise HTTPException(422,"账号分组不能为空")
        group_id = _task_group(db, p.account_group_id, user).id
    return tpl,strategy,package,group_id


@router.get("/tasks")
def tasks(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str = Query(default="", max_length=200),
    task_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    predicates=(HyperlinkTask.status==task_status,) if task_status and task_status!="all" else ()
    items,total=_paged_list(db,HyperlinkTask,current_user,keyword=keyword,page=page,page_size=page_size,search_columns=(HyperlinkTask.name,HyperlinkTask.status,HyperlinkTask.channel),extra_predicates=predicates);rows=[task_row(db,x) for x in items];db.commit();return {"data":{"rows":rows,"total":total,"page":page,"pageSize":page_size}}


@router.get("/tasks/summary")
def task_summary(db: DbSession, current_user: CurrentUser) -> dict:
    filters = () if current_user.role == "admin" else (
        HyperlinkTask.created_by == current_user.id,
    )
    summary_rows = db.execute(
        select(
            HyperlinkTask.status,
            func.count(HyperlinkTask.id),
            func.sum(HyperlinkTask.queued_count),
        )
        .where(*filters)
        .group_by(HyperlinkTask.status)
    ).all()
    recent = db.scalars(
        select(HyperlinkTask)
        .where(*filters)
        .order_by(HyperlinkTask.created_at.desc(), HyperlinkTask.id.desc())
        .limit(5)
    ).all()
    rows = [task_row(db, item) for item in recent]
    db.commit()
    return {
        "data": {
            "rows": rows,
            "statusCounts": {
                str(status_value): int(count)
                for status_value, count, _ in summary_rows
            },
            "queuedTotal": sum(int(queued or 0) for _, _, queued in summary_rows),
        }
    }
@router.post("/tasks",status_code=201)
def create_task(p:TaskCreate,db:DbSession,current_user:CurrentUser)->dict:
    tpl,s,pkg,group_id=_task_refs(db,p,current_user);x=HyperlinkTask(public_id=new_public_id("htsk"),name=p.name,template_id=tpl,strategy_id=s,data_package_id=pkg,account_group_id=group_id,sender_mode="dynamic_group",account_public_ids=[],channel=p.channel,status="draft",created_by=current_user.id);db.add(x);db.commit();return {"data":{"task":task_row(db,x)}}
@router.get("/tasks/{pid}")
def get_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user);row=task_row(db,x);db.commit();return {"data":{"task":row}}
@router.get("/tasks/{pid}/recipients")
def task_recipients(
    pid: str,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=200),
) -> dict:
    task=_one(db,HyperlinkTask,pid,"任务",current_user)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(HyperlinkTaskDelivery)
            .where(HyperlinkTaskDelivery.task_id == task.id)
        )
        or 0
    )
    rows=db.execute(
        select(
            HyperlinkTaskDelivery,
            DataPackageRecipient,
            MessageDelivery,
            PersonalAccount,
        )
        .join(
            DataPackageRecipient,
            DataPackageRecipient.id==HyperlinkTaskDelivery.recipient_id,
        )
        .outerjoin(
            MessageDelivery,
            MessageDelivery.id==HyperlinkTaskDelivery.message_delivery_id,
        )
        .outerjoin(
            PersonalAccount,
            PersonalAccount.id==HyperlinkTaskDelivery.account_id,
        )
        .where(HyperlinkTaskDelivery.task_id==task.id)
        .order_by(HyperlinkTaskDelivery.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [
                {
                    "id": entity_id(delivery),
                    "recipientId": entity_id(recipient),
                    "phone": recipient.phone_e164,
                    "countryCode": recipient.country_code,
                    "variables": recipient.variables_json,
                    "validationStatus": recipient.validation_status,
                    "executionStatus": delivery.submission_status,
                    "messageStatus": message.status if message else None,
                    "accountId": entity_id(account) if account else None,
                    "attemptCount": delivery.attempt_count,
                    "lastError": delivery.last_error,
                    "leasedAt": iso(delivery.leased_at),
                    "submittedAt": iso(delivery.submitted_at),
                    "updatedAt": iso(delivery.updated_at),
                }
                for delivery,recipient,message,account in rows
            ],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }
@router.patch("/tasks/{pid}")
def update_task(pid:str,p:TaskUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status not in {"draft","paused"}:raise HTTPException(409,"当前任务状态不能修改")
    has_deliveries = bool(db.scalar(select(func.count()).select_from(HyperlinkTaskDelivery).where(HyperlinkTaskDelivery.task_id == x.id)))
    if has_deliveries and ({"template_id", "data_package_id"} & p.model_fields_set):
        raise HTTPException(409,"已经开始过的任务不能更换模板或数据包")
    tpl,s,pkg,group_id=_task_refs(db,p,current_user,x)
    if p.name is not None:x.name=p.name
    x.template_id=tpl;x.strategy_id=s;x.data_package_id=pkg;x.account_group_id=group_id
    if "channel" in p.model_fields_set:x.channel=p.channel
    db.commit();return {"data":{"task":task_row(db,x)}}
@router.delete("/tasks/{pid}")
def delete_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status in {"running","waiting_accounts"}:raise HTTPException(409,"运行中的任务不能删除")
    db.delete(x);db.commit();return {"data":{"ok":True}}


def _dynamic_eligible_accounts(db: DbSession, task: HyperlinkTask) -> list[PersonalAccount]:
    from app.models import ProtocolNode

    if task.account_group_id is None:
        return []
    return list(
        db.scalars(
            select(PersonalAccount)
            .join(ProtocolNode, ProtocolNode.id == PersonalAccount.protocol_id)
            .where(
                PersonalAccount.group_id == task.account_group_id,
                PersonalAccount.created_by == task.created_by,
                PersonalAccount.enabled.is_(True),
                PersonalAccount.deleted_at.is_(None),
                PersonalAccount.admission_status == "active",
                PersonalAccount.validation_status == "ready",
                PersonalAccount.status.in_(("online_idle", "sending")),
                or_(
                    PersonalAccount.sending_cooldown_until.is_(None),
                    PersonalAccount.sending_cooldown_until <= utcnow(),
                ),
                ProtocolNode.marketing_enabled.is_(True),
                ProtocolNode.online_enabled.is_(True),
            )
            .order_by(PersonalAccount.id)
        ).all()
    )


@router.post("/tasks/{pid}/start", status_code=status.HTTP_202_ACCEPTED)
def start_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    task=_one(db,HyperlinkTask,pid,"任务",current_user)
    if task.status in {"cancelled","completed"}:raise HTTPException(409,"任务已经结束")
    if task.status in {"running", "waiting_accounts"}:
        return {"data":{"task":task_row(db,task),"alreadyRunning":True}}
    strategy = db.get(HyperlinkStrategy, task.strategy_id)
    if strategy is None:
        raise HTTPException(409,"任务发送策略不存在")
    if not strategy.enabled:
        raise HTTPException(409,"任务发送策略已停用")
    policy = strategy_policy(strategy)
    from app.models import ProtocolNode
    accounts: list[PersonalAccount] = []
    if task.sender_mode == "legacy_fixed":
        account_ids=[]
        for value in task.account_public_ids:
            try:account_ids.append(parse_snowflake_id(value))
            except ValueError:pass
        accounts=list(db.scalars(select(PersonalAccount).join(ProtocolNode,ProtocolNode.id==PersonalAccount.protocol_id).where(PersonalAccount.id.in_(account_ids),PersonalAccount.created_by==task.created_by,PersonalAccount.status.in_(("online_idle","sending")),PersonalAccount.enabled.is_(True),PersonalAccount.deleted_at.is_(None),PersonalAccount.admission_status=="active",ProtocolNode.marketing_enabled.is_(True),ProtocolNode.online_enabled.is_(True))).all())
        if not accounts:raise HTTPException(409,"没有在线可发送的个人账号")
    else:
        if task.account_group_id is None:
            raise HTTPException(409,"任务没有配置账号分组")
        group = db.scalar(select(AccountGroup.id).where(AccountGroup.id==task.account_group_id,AccountGroup.created_by==task.created_by))
        if group is None:raise HTTPException(409,"任务账号分组不存在")
        accounts=_dynamic_eligible_accounts(db,task)
    package = db.get(DataPackage, task.data_package_id)
    if package is None:
        raise HTTPException(409,"任务数据包不存在")
    if task.data_package_revision is None:
        task.data_package_revision = max(int(package.revision or 1), 1)
        package.sealed_at = package.sealed_at or utcnow()
    recipients=db.scalars(select(DataPackageRecipient).where(DataPackageRecipient.data_package_id==task.data_package_id,DataPackageRecipient.package_revision<=task.data_package_revision,or_(DataPackageRecipient.removed_revision.is_(None),DataPackageRecipient.removed_revision>task.data_package_revision)).order_by(DataPackageRecipient.id)).all()
    if not recipients:raise HTTPException(409,"数据包没有收件人")
    _freeze_task_template(db, task)
    existing = {
        recipient_id
        for recipient_id in db.scalars(
            select(HyperlinkTaskDelivery.recipient_id).where(
                HyperlinkTaskDelivery.task_id == task.id
            )
        ).all()
    }
    for index,recipient in enumerate(recipients):
        if recipient.id in existing:continue
        account_id=(accounts[index%len(accounts)].id if task.sender_mode=="legacy_fixed" else None)
        valid = recipient.validation_status == "valid"
        db.add(HyperlinkTaskDelivery(public_id=new_public_id("htd"),task_id=task.id,recipient_id=recipient.id,account_id=account_id,status="queued" if valid else "skipped",submission_status="pending" if valid else "skipped",attempt_count=0,last_error=None if valid else (recipient.last_error or "号码校验未通过")))
        if (index + 1) % 500 == 0:
            db.flush()
    if task.sender_mode == "dynamic_group":
        existing_slot_indexes = set(
            db.scalars(
                select(HyperlinkTaskAccountSlot.slot_index).where(
                    HyperlinkTaskAccountSlot.task_id == task.id
                )
            ).all()
        )
        for slot_index in range(policy.concurrency):
            if slot_index not in existing_slot_indexes:
                db.add(
                    HyperlinkTaskAccountSlot(
                        task_id=task.id,
                        slot_index=slot_index,
                        status="vacant",
                    )
                )
    task.status=(
        "running"
        if task.sender_mode=="legacy_fixed" or accounts
        else ("waiting_accounts" if policy.no_account_action == "wait" else "paused")
    );task.started_at=task.started_at or utcnow();task.paused_at=None;task.completed_at=None
    db.commit()
    if task.status == "running":
        try:
            enqueue_hyperlink_task(entity_id(task))
        except Exception as exc:
            task.status = "paused"
            db.commit()
            raise HTTPException(status_code=503, detail="任务队列暂不可用") from exc
    return {"data":{"task":task_row(db,task),"queued":task.status=="running"}}
@router.post("/tasks/{pid}/pause")
def pause_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status not in {"running","waiting_accounts"}:raise HTTPException(409,"仅运行中的任务可暂停")
    now=utcnow();x.status="paused";x.paused_at=now
    # Rows that have only been leased are safe to return immediately. Rows
    # already submitting remain reconciling until their gateway result arrives.
    leased=list(db.scalars(select(HyperlinkTaskDelivery).where(HyperlinkTaskDelivery.task_id==x.id,HyperlinkTaskDelivery.submission_status=="leased")).all())
    for delivery in leased:
        delivery.submission_status="pending";delivery.slot_id=None;delivery.account_id=None;delivery.lease_token=None;delivery.leased_at=None;delivery.lease_expires_at=None
    submitting=list(db.scalars(select(HyperlinkTaskDelivery).where(HyperlinkTaskDelivery.task_id==x.id,HyperlinkTaskDelivery.submission_status=="submitting")).all())
    for delivery in submitting:
        delivery.submission_status="reconciling";delivery.lease_token=None;delivery.lease_expires_at=None;delivery.last_error="任务暂停时消息已进入网关，等待状态核对"
    slots=list(db.scalars(select(HyperlinkTaskAccountSlot).where(HyperlinkTaskAccountSlot.task_id==x.id)).all())
    for slot in slots:
        slot.status="released";slot.account_id=None;slot.lease_token=None;slot.lease_expires_at=None;slot.released_at=now;slot.last_switch_reason="task_paused"
    db.commit();return {"data":{"task":task_row(db,x)}}
@router.post("/tasks/{pid}/cancel")
def cancel_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status in {"completed","cancelled"}:raise HTTPException(409,"任务已经结束")
    now=utcnow();x.status="cancelled";x.cancelled_at=now
    cancellable=list(db.scalars(select(HyperlinkTaskDelivery).where(HyperlinkTaskDelivery.task_id==x.id,HyperlinkTaskDelivery.submission_status.in_(("pending","retry","leased")))).all())
    for delivery in cancellable:
        delivery.submission_status="cancelled";delivery.status="cancelled";delivery.slot_id=None;delivery.account_id=None;delivery.lease_token=None;delivery.leased_at=None;delivery.lease_expires_at=None
    submitting=list(db.scalars(select(HyperlinkTaskDelivery).where(HyperlinkTaskDelivery.task_id==x.id,HyperlinkTaskDelivery.submission_status=="submitting")).all())
    for delivery in submitting:
        delivery.submission_status="reconciling";delivery.lease_token=None;delivery.lease_expires_at=None;delivery.last_error="任务取消时消息已进入网关，等待状态核对"
    slots=list(db.scalars(select(HyperlinkTaskAccountSlot).where(HyperlinkTaskAccountSlot.task_id==x.id)).all())
    for slot in slots:
        slot.status="released";slot.account_id=None;slot.lease_token=None;slot.lease_expires_at=None;slot.released_at=now;slot.last_switch_reason="task_cancelled"
    db.commit();return {"data":{"task":task_row(db,x)}}


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


@router.get("/market-insights")
def market_insights(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    source_country: str | None = Query(default=None, alias="sourceCountry"),
    target_country: str | None = Query(default=None, alias="targetCountry"),
) -> dict:
    """Aggregate sending quality by account country x recipient country.

    This is intentionally independent of Facebook spend and promotion-channel
    acquisition metrics.  A restricted account is considered banned; an
    account requiring re-authentication is abnormal but not proven banned.
    """
    source_filter = source_country.upper() if source_country else None
    target_filter = target_country.upper() if target_country else None
    result = db.execute(
        select(
            HyperlinkTaskDelivery,
            MessageDelivery,
            PersonalAccount,
            DataPackageRecipient,
        )
        .join(
            MessageDelivery,
            MessageDelivery.id == HyperlinkTaskDelivery.message_delivery_id,
        )
        .join(PersonalAccount, PersonalAccount.id == HyperlinkTaskDelivery.account_id)
        .join(
            DataPackageRecipient,
            DataPackageRecipient.id == HyperlinkTaskDelivery.recipient_id,
        )
        .where(
            (PersonalAccount.created_by == current_user.id)
            if current_user.role != "admin"
            else PersonalAccount.id.is_not(None)
        )
    ).all()
    groups: dict[tuple[str, str], dict] = {}
    all_accounts: dict[int, str] = {}
    for _, message, account, recipient in result:
        event_date = message.created_at.date()
        if date_from and event_date < date_from:
            continue
        if date_to and event_date > date_to:
            continue
        source = account.country_code or "ZZ"
        target = recipient.country_code or "ZZ"
        if source_filter and source != source_filter:
            continue
        if target_filter and target != target_filter:
            continue
        all_accounts[account.id] = account.status
        key = (source, target)
        group = groups.setdefault(
            key,
            {
                "sourceCountry": source,
                "targetCountry": target,
                "accountIds": set(),
                "sent": 0,
                "delivered": 0,
                "failed": 0,
                "abnormalIds": set(),
                "bannedIds": set(),
            },
        )
        group["accountIds"].add(account.id)
        if account.status in {"reauth_required", "restricted"}:
            group["abnormalIds"].add(account.id)
        if account.status == "restricted":
            group["bannedIds"].add(account.id)
        group["sent"] += message.status in {"sent", "delivered"}
        group["delivered"] += message.status == "delivered"
        group["failed"] += message.status == "failed"

    rows = []
    for group in groups.values():
        account_count = len(group.pop("accountIds"))
        abnormal_count = len(group.pop("abnormalIds"))
        banned_count = len(group.pop("bannedIds"))
        rows.append(
            {
                **group,
                "accountCount": account_count,
                "abnormalAccounts": abnormal_count,
                "bannedAccounts": banned_count,
                "banRate": _rate(banned_count, account_count),
                # Compatibility aliases use the proven-banned definition.
                "blockedAccountCount": banned_count,
                "blockRate": _rate(banned_count, account_count),
                "deliveryRate": _rate(group["delivered"], group["sent"]),
            }
        )
    rows.sort(key=lambda row: (-row["delivered"], row["sourceCountry"], row["targetCountry"]))
    ranking_map: dict[str, dict] = {}
    for row in rows:
        rank = ranking_map.setdefault(
            row["targetCountry"],
            {"targetCountry": row["targetCountry"], "sent": 0, "delivered": 0, "failed": 0},
        )
        for field in ("sent", "delivered", "failed"):
            rank[field] += row[field]
    ranking = sorted(ranking_map.values(), key=lambda row: (-row["delivered"], row["targetCountry"]))
    for rank in ranking:
        rank["deliveryRate"] = _rate(rank["delivered"], rank["sent"])
    abnormal_accounts = sum(
        state in {"reauth_required", "restricted"} for state in all_accounts.values()
    )
    banned_accounts = sum(state == "restricted" for state in all_accounts.values())
    totals = {
        "sent": sum(row["sent"] for row in rows),
        "delivered": sum(row["delivered"] for row in rows),
        "failed": sum(row["failed"] for row in rows),
        "accountCount": len(all_accounts),
        "abnormalAccounts": abnormal_accounts,
        "bannedAccounts": banned_accounts,
        "banRate": _rate(banned_accounts, len(all_accounts)),
        "deliveryRate": _rate(
            sum(row["delivered"] for row in rows), sum(row["sent"] for row in rows)
        ),
    }
    return {
        "data": {
            "rows": rows,
            "matrix": {
                "sourceCountries": sorted({row["sourceCountry"] for row in rows}),
                "targetCountries": sorted({row["targetCountry"] for row in rows}),
                "cells": rows,
            },
            "ranking": ranking,
            "totals": totals,
        }
    }
