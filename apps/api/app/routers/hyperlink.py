from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    DataPackageCreate, DataPackageUpdate, HyperlinkTemplateCreate,
    HyperlinkTemplateUpdate, MaterialCreate, MaterialUpdate,
    RecipientsImport, StrategyCreate, StrategyUpdate, TaskCreate, TaskUpdate,
)
from app.deps import CurrentUser, DbSession
from app.snowflake import new_public_id

from app.models import (
    DataPackage, DataPackageRecipient, HyperlinkMaterial,
    HyperlinkStrategy, HyperlinkTask, HyperlinkTaskDelivery, HyperlinkTemplate,
    MessageDelivery, PersonalAccount, PromotionChannel,
)
from app.security import utcnow
from app.serializers import iso
from app.task_queue import enqueue_hyperlink_task


router = APIRouter(prefix="/api/hyperlink", tags=["hyperlink"])


def _one(db: DbSession, model: type, public_id: str, label: str, user):
    statement = select(model).where(model.public_id == public_id, model.archived_at.is_(None))
    if user.role != "admin": statement = statement.where(model.created_by == user.id)
    item = db.scalar(statement)
    if item is None: raise HTTPException(status_code=404, detail=f"{label}不存在")
    return item


def _base(item) -> dict: return {"id": item.public_id, "publicId": item.public_id, "createdAt": iso(item.created_at), "updatedAt": iso(item.updated_at)}
def material_row(x: HyperlinkMaterial) -> dict: return {**_base(x), "name": x.name, "type": x.material_type, "contentJson": x.content_json, "enabled": x.enabled}
def strategy_row(x: HyperlinkStrategy) -> dict: return {**_base(x), "name": x.name, "maxQps": x.max_qps, "concurrency": x.concurrency, "batchSize": x.batch_size, "retryLimit": x.retry_limit, "rulesJson": x.rules_json, "enabled": x.enabled}


def template_row(db: DbSession, x: HyperlinkTemplate) -> dict:
    material = db.get(HyperlinkMaterial, x.material_id) if x.material_id else None; channel = db.get(PromotionChannel, x.promotion_channel_id) if x.promotion_channel_id else None
    return {**_base(x), "name": x.name, "contentJson": x.content_json, "materialId": material.public_id if material else None, "promotionChannelId": channel.public_id if channel else None, "enabled": x.enabled}


def package_row(db: DbSession, x: DataPackage) -> dict:
    count = int(db.scalar(select(func.count()).select_from(DataPackageRecipient).where(DataPackageRecipient.data_package_id == x.id)) or 0)
    return {**_base(x), "name": x.name, "status": x.status, "recipientCount": count}


def recipient_row(x: DataPackageRecipient) -> dict: return {**_base(x), "phone": x.phone_e164, "countryCode": x.country_code, "variables": x.variables_json}


def _sync_task_counts(db: DbSession, task: HyperlinkTask) -> None:
    effective_status = func.coalesce(MessageDelivery.status, HyperlinkTaskDelivery.status)
    counts = {
        str(delivery_status): int(count)
        for delivery_status, count in db.execute(
            select(effective_status, func.count(HyperlinkTaskDelivery.id))
            .outerjoin(
                MessageDelivery,
                MessageDelivery.id == HyperlinkTaskDelivery.message_delivery_id,
            )
            .where(HyperlinkTaskDelivery.task_id == task.id)
            .group_by(effective_status)
        ).all()
    }
    task.total_count = sum(counts.values())
    task.queued_count = sum(counts.get(name, 0) for name in ("queued", "sending", "retry"))
    task.sent_count = counts.get("sent", 0)
    task.delivered_count = counts.get("delivered", 0)
    task.failed_count = counts.get("failed", 0)
    if task.status == "running" and task.total_count and task.queued_count == 0:
        task.status = "completed"
        task.completed_at = task.completed_at or utcnow()


def task_row(db: DbSession, x: HyperlinkTask) -> dict:
    _sync_task_counts(db, x); tpl = db.get(HyperlinkTemplate, x.template_id); strategy = db.get(HyperlinkStrategy, x.strategy_id); package = db.get(DataPackage, x.data_package_id)
    return {**_base(x), "name": x.name, "templateId": tpl.public_id if tpl else None, "strategyId": strategy.public_id if strategy else None, "dataPackageId": package.public_id if package else None, "accountIds": x.account_public_ids, "channel": x.channel, "status": x.status, "totalCount": x.total_count, "queuedCount": x.queued_count, "sentCount": x.sent_count, "deliveredCount": x.delivered_count, "failedCount": x.failed_count, "startedAt": iso(x.started_at), "completedAt": iso(x.completed_at)}


def _list(db, model, user):
    statement = select(model).where(model.archived_at.is_(None))
    if user.role != "admin": statement = statement.where(model.created_by == user.id)
    return db.scalars(statement.order_by(model.created_at.desc())).all()


@router.get("/materials")
def materials(db: DbSession, current_user: CurrentUser) -> dict:
    rows=[material_row(x) for x in _list(db, HyperlinkMaterial, current_user)]; return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/materials", status_code=201)
def create_material(p: MaterialCreate, db: DbSession, current_user: CurrentUser) -> dict:
    x=HyperlinkMaterial(public_id=new_public_id("hmat"),name=p.name,material_type=p.material_type,content_json=p.content_json,enabled=p.enabled,created_by=current_user.id);db.add(x);db.commit();return {"data":{"material":material_row(x)}}
@router.get("/materials/{pid}")
def get_material(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"material":material_row(_one(db,HyperlinkMaterial,pid,"素材",current_user))}}
@router.patch("/materials/{pid}")
def update_material(pid:str,p:MaterialUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkMaterial,pid,"素材",current_user)
    for field,attr in (("name","name"),("material_type","material_type"),("content_json","content_json"),("enabled","enabled")):
        value=getattr(p,field); setattr(x,attr,value) if value is not None else None
    db.commit();return {"data":{"material":material_row(x)}}
@router.delete("/materials/{pid}")
def delete_material(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkMaterial,pid,"素材",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTemplate).where(HyperlinkTemplate.material_id==x.id,HyperlinkTemplate.archived_at.is_(None))):raise HTTPException(409,"素材仍被模板使用")
    x.enabled=False;x.archived_at=utcnow();db.commit();return {"data":{"ok":True}}


def _template_refs(db, user, material_id, promotion_id, current=None):
    mat=current.material_id if current else None; promo=current.promotion_channel_id if current else None
    if material_id is not None:
        mat=_one(db,HyperlinkMaterial,material_id,"素材",user).id if material_id else None
    if promotion_id is not None:
        promo=_one(db,PromotionChannel,promotion_id,"推广渠道",user).id if promotion_id else None
    return mat,promo


@router.get("/templates")
def templates(db:DbSession,current_user:CurrentUser)->dict:
    rows=[template_row(db,x) for x in _list(db,HyperlinkTemplate,current_user)];return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/templates",status_code=201)
def create_template(p:HyperlinkTemplateCreate,db:DbSession,current_user:CurrentUser)->dict:
    mat,promo=_template_refs(db,current_user,p.material_id,p.promotion_channel_id);x=HyperlinkTemplate(public_id=new_public_id("htpl"),name=p.name,content_json=p.content_json,material_id=mat,promotion_channel_id=promo,enabled=p.enabled,created_by=current_user.id);db.add(x);db.commit();return {"data":{"template":template_row(db,x)}}
@router.get("/templates/{pid}")
def get_template(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"template":template_row(db,_one(db,HyperlinkTemplate,pid,"模板",current_user))}}
@router.patch("/templates/{pid}")
def update_template(pid:str,p:HyperlinkTemplateUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTemplate,pid,"模板",current_user);mat,promo=_template_refs(db,current_user,p.material_id if "material_id" in p.model_fields_set else None,p.promotion_channel_id if "promotion_channel_id" in p.model_fields_set else None,x)
    if p.name is not None:x.name=p.name
    if p.content_json is not None:x.content_json=p.content_json
    if "material_id" in p.model_fields_set:x.material_id=mat if p.material_id else None
    if "promotion_channel_id" in p.model_fields_set:x.promotion_channel_id=promo if p.promotion_channel_id else None
    if p.enabled is not None:x.enabled=p.enabled
    db.commit();return {"data":{"template":template_row(db,x)}}
@router.delete("/templates/{pid}")
def delete_template(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTemplate,pid,"模板",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.template_id==x.id,HyperlinkTask.archived_at.is_(None))):raise HTTPException(409,"模板仍被任务使用")
    x.enabled=False;x.archived_at=utcnow();db.commit();return {"data":{"ok":True}}


@router.get("/strategies")
def strategies(db:DbSession,current_user:CurrentUser)->dict:
    rows=[strategy_row(x) for x in _list(db,HyperlinkStrategy,current_user)];return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/strategies",status_code=201)
def create_strategy(p:StrategyCreate,db:DbSession,current_user:CurrentUser)->dict:
    x=HyperlinkStrategy(public_id=new_public_id("hstr"),name=p.name,max_qps=p.max_qps,concurrency=p.concurrency,batch_size=p.batch_size,retry_limit=p.retry_limit,rules_json=p.rules_json,enabled=p.enabled,created_by=current_user.id);db.add(x);db.commit();return {"data":{"strategy":strategy_row(x)}}
@router.get("/strategies/{pid}")
def get_strategy(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"strategy":strategy_row(_one(db,HyperlinkStrategy,pid,"策略",current_user))}}
@router.patch("/strategies/{pid}")
def update_strategy(pid:str,p:StrategyUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkStrategy,pid,"策略",current_user)
    for f,a in (("name","name"),("max_qps","max_qps"),("concurrency","concurrency"),("batch_size","batch_size"),("retry_limit","retry_limit"),("rules_json","rules_json"),("enabled","enabled")):
        v=getattr(p,f);setattr(x,a,v) if v is not None else None
    db.commit();return {"data":{"strategy":strategy_row(x)}}
@router.delete("/strategies/{pid}")
def delete_strategy(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkStrategy,pid,"策略",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.strategy_id==x.id,HyperlinkTask.archived_at.is_(None))):raise HTTPException(409,"策略仍被任务使用")
    x.enabled=False;x.archived_at=utcnow();db.commit();return {"data":{"ok":True}}


def _add_recipients(db, package, values):
    existing=set(db.scalars(select(DataPackageRecipient.phone_e164).where(DataPackageRecipient.data_package_id==package.id)).all());created=0
    for p in values:
        if p.phone in existing:continue
        db.add(DataPackageRecipient(public_id=new_public_id("hrcp"),data_package_id=package.id,phone_e164=p.phone,country_code=p.country_code,variables_json=p.variables));existing.add(p.phone);created+=1
    db.commit();return created


@router.get("/data-packages")
def packages(db:DbSession,current_user:CurrentUser)->dict:
    rows=[package_row(db,x) for x in _list(db,DataPackage,current_user)];return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/data-packages",status_code=201)
def create_package(p:DataPackageCreate,db:DbSession,current_user:CurrentUser)->dict:
    x=DataPackage(public_id=new_public_id("hpkg"),name=p.name,status="ready",created_by=current_user.id);db.add(x);db.flush();_add_recipients(db,x,p.recipients);return {"data":{"dataPackage":package_row(db,x)}}
@router.get("/data-packages/{pid}")
def get_package(pid:str,db:DbSession,current_user:CurrentUser)->dict:return {"data":{"dataPackage":package_row(db,_one(db,DataPackage,pid,"数据包",current_user))}}
@router.patch("/data-packages/{pid}")
def update_package(pid:str,p:DataPackageUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);x.name=p.name or x.name;db.commit();return {"data":{"dataPackage":package_row(db,x)}}
@router.delete("/data-packages/{pid}")
def delete_package(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user)
    if db.scalar(select(func.count()).select_from(HyperlinkTask).where(HyperlinkTask.data_package_id==x.id,HyperlinkTask.archived_at.is_(None))):raise HTTPException(409,"数据包仍被任务使用")
    x.status="archived";x.archived_at=utcnow();db.commit();return {"data":{"ok":True}}
@router.get("/data-packages/{pid}/recipients")
def recipients(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);rows=db.scalars(select(DataPackageRecipient).where(DataPackageRecipient.data_package_id==x.id).order_by(DataPackageRecipient.id)).all();return {"data":{"rows":[recipient_row(r) for r in rows],"total":len(rows)}}
@router.post("/data-packages/{pid}/recipients")
def import_recipients(pid:str,p:RecipientsImport,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);created=_add_recipients(db,x,p.recipients);return {"data":{"createdCount":created,"dataPackage":package_row(db,x)}}
@router.delete("/data-packages/{pid}/recipients/{rid}")
def delete_recipient(pid:str,rid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,DataPackage,pid,"数据包",current_user);r=db.scalar(select(DataPackageRecipient).where(DataPackageRecipient.public_id==rid,DataPackageRecipient.data_package_id==x.id))
    if not r:raise HTTPException(404,"收件人不存在")
    db.delete(r);db.commit();return {"data":{"ok":True}}


def _task_refs(db,p,user,current=None):
    tpl=current.template_id if current else None;strategy=current.strategy_id if current else None;package=current.data_package_id if current else None
    if getattr(p,"template_id",None):tpl=_one(db,HyperlinkTemplate,p.template_id,"模板",user).id
    if getattr(p,"strategy_id",None):strategy=_one(db,HyperlinkStrategy,p.strategy_id,"策略",user).id
    if getattr(p,"data_package_id",None):package=_one(db,DataPackage,p.data_package_id,"数据包",user).id
    ids=getattr(p,"account_ids",None) or (current.account_public_ids if current else [])
    from app.models import ProtocolNode
    account_statement=select(PersonalAccount.public_id).join(ProtocolNode,ProtocolNode.id==PersonalAccount.protocol_id).where(PersonalAccount.public_id.in_(ids),PersonalAccount.archived_at.is_(None),ProtocolNode.marketing_enabled.is_(True),ProtocolNode.online_enabled.is_(True),ProtocolNode.archived_at.is_(None))
    if user.role != "admin": account_statement=account_statement.where(PersonalAccount.created_by==user.id)
    found=set(db.scalars(account_statement).all())
    if set(ids)!=found:raise HTTPException(409,"部分账号不存在或所属协议未开启营销")
    return tpl,strategy,package,ids


@router.get("/tasks")
def tasks(db:DbSession,current_user:CurrentUser)->dict:
    items=_list(db,HyperlinkTask,current_user);rows=[task_row(db,x) for x in items];db.commit();return {"data":{"rows":rows,"total":len(rows)}}
@router.post("/tasks",status_code=201)
def create_task(p:TaskCreate,db:DbSession,current_user:CurrentUser)->dict:
    tpl,s,pkg,ids=_task_refs(db,p,current_user);x=HyperlinkTask(public_id=new_public_id("htsk"),name=p.name,template_id=tpl,strategy_id=s,data_package_id=pkg,account_public_ids=ids,channel=p.channel,status="draft",created_by=current_user.id);db.add(x);db.commit();return {"data":{"task":task_row(db,x)}}
@router.get("/tasks/{pid}")
def get_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user);row=task_row(db,x);db.commit();return {"data":{"task":row}}
@router.patch("/tasks/{pid}")
def update_task(pid:str,p:TaskUpdate,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status not in {"draft","paused"}:raise HTTPException(409,"当前任务状态不能修改")
    tpl,s,pkg,ids=_task_refs(db,p,current_user,x)
    if p.name is not None:x.name=p.name
    x.template_id=tpl;x.strategy_id=s;x.data_package_id=pkg;x.account_public_ids=ids
    if "channel" in p.model_fields_set:x.channel=p.channel
    db.commit();return {"data":{"task":task_row(db,x)}}
@router.delete("/tasks/{pid}")
def delete_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status=="running":raise HTTPException(409,"运行中的任务不能删除")
    x.archived_at=utcnow();db.commit();return {"data":{"ok":True}}


@router.post("/tasks/{pid}/start", status_code=status.HTTP_202_ACCEPTED)
def start_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    task=_one(db,HyperlinkTask,pid,"任务",current_user)
    if task.status in {"cancelled","completed"}:raise HTTPException(409,"任务已经结束")
    if task.status == "running":
        return {"data":{"task":task_row(db,task),"alreadyRunning":True}}
    from app.models import ProtocolNode
    accounts=db.scalars(select(PersonalAccount).join(ProtocolNode,ProtocolNode.id==PersonalAccount.protocol_id).where(PersonalAccount.public_id.in_(task.account_public_ids),PersonalAccount.status.in_(("online_idle","sending")),PersonalAccount.enabled.is_(True),ProtocolNode.marketing_enabled.is_(True),ProtocolNode.online_enabled.is_(True),ProtocolNode.archived_at.is_(None))).all()
    if not accounts:raise HTTPException(409,"没有在线可发送的个人账号")
    recipients=db.scalars(select(DataPackageRecipient).where(DataPackageRecipient.data_package_id==task.data_package_id).order_by(DataPackageRecipient.id)).all()
    if not recipients:raise HTTPException(409,"数据包没有收件人")
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
        account=accounts[index%len(accounts)]
        db.add(HyperlinkTaskDelivery(public_id=new_public_id("htd"),task_id=task.id,recipient_id=recipient.id,account_id=account.id,status="queued",attempt_count=0))
        if (index + 1) % 500 == 0:
            db.flush()
    task.status="running";task.started_at=task.started_at or utcnow();task.completed_at=None
    db.commit()
    try:
        enqueue_hyperlink_task(task.public_id)
    except Exception as exc:
        task.status = "paused"
        db.commit()
        raise HTTPException(status_code=503, detail="任务队列暂不可用") from exc
    return {"data":{"task":task_row(db,task),"queued":True}}
@router.post("/tasks/{pid}/pause")
def pause_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status!="running":raise HTTPException(409,"仅运行中的任务可暂停")
    x.status="paused";db.commit();return {"data":{"task":task_row(db,x)}}
@router.post("/tasks/{pid}/cancel")
def cancel_task(pid:str,db:DbSession,current_user:CurrentUser)->dict:
    x=_one(db,HyperlinkTask,pid,"任务",current_user)
    if x.status in {"completed","cancelled"}:raise HTTPException(409,"任务已经结束")
    x.status="cancelled";db.commit();return {"data":{"task":task_row(db,x)}}


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
