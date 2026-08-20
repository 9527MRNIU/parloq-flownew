from __future__ import annotations

from functools import lru_cache
from pathlib import Path


CONTENT_ROOT = Path(__file__).with_name("content")

DOC_SECTIONS = (
    {
        "id": "getting-started",
        "title": "开始使用",
        "pages": (
            {
                "slug": "overview",
                "title": "文档总览",
                "summary": "了解这套文档的范围、阅读方式和功能边界标记。",
                "keywords": ("总览", "范围", "权限", "登录"),
            },
            {
                "slug": "conventions",
                "title": "系统通用约定",
                "summary": "系统 ID、手机号、权限和删除行为等跨菜单通用规则。",
                "keywords": ("Snowflake", "ID", "手机号", "权限", "删除"),
            },
        ),
    },
    {
        "id": "workspace",
        "title": "工作台",
        "pages": (
            {
                "slug": "menu-home",
                "title": "首页",
                "summary": "查看系统概况、账号状态和营销任务进度。",
                "menuPath": "工作台 / 首页",
                "routePath": "/",
                "keywords": ("概况", "账号", "任务"),
            },
        ),
    },
    {
        "id": "promotion",
        "title": "推广",
        "pages": (
            {
                "slug": "menu-promotion-templates",
                "title": "模板管理",
                "summary": "导入、预览、升级和停用推广落地页模板。",
                "menuPath": "推广 / 推广管理 / 模板管理",
                "routePath": "/promotion/templates",
                "keywords": ("ZIP", "模板", "版本", "预览"),
            },
            {
                "slug": "menu-promotion-channels",
                "title": "渠道管理",
                "summary": "组合模板、域名、账号分组和协议路由并发布渠道。",
                "menuPath": "推广 / 推广管理 / 渠道管理",
                "routePath": "/promotion/channels",
                "keywords": ("渠道", "落地页", "Meta", "协议"),
            },
            {
                "slug": "menu-promotion-domains",
                "title": "域名管理",
                "summary": "接入或购买域名并完成 DNS、TLS 就绪验证。",
                "menuPath": "推广 / 推广管理 / 域名管理",
                "routePath": "/promotion/domains",
                "keywords": ("DNS", "TLS", "域名", "购买"),
            },
            {
                "slug": "menu-promotion-statistics",
                "title": "渠道统计",
                "summary": "按渠道查看请求、成功、转化率和获号成本。",
                "menuPath": "推广 / 数据中心 / 渠道统计",
                "routePath": "/promotion/statistics",
                "keywords": ("转化", "获号成本", "裂变", "导出"),
            },
            {
                "slug": "menu-promotion-trends",
                "title": "趋势图",
                "summary": "查看访问、号码提交和配对成功的每日趋势。",
                "menuPath": "推广 / 数据中心 / 趋势图",
                "routePath": "/promotion/trends",
                "keywords": ("漏斗", "趋势", "UV", "转化"),
            },
        ),
    },
    {
        "id": "marketing",
        "title": "营销",
        "pages": (
            {
                "slug": "menu-hyperlink-tasks",
                "title": "超链任务",
                "summary": "创建、执行并跟踪超链群发任务。",
                "menuPath": "营销 / 超链营销 / 超链任务",
                "routePath": "/hyperlink/tasks",
                "keywords": ("群发", "任务", "单勾", "双勾"),
            },
            {
                "slug": "menu-hyperlink-packages",
                "title": "数据包",
                "summary": "维护超链任务使用的目标号码数据。",
                "menuPath": "营销 / 超链营销 / 数据包",
                "routePath": "/hyperlink/data-packages",
                "keywords": ("号码", "CSV", "导入", "版本"),
            },
            {
                "slug": "menu-hyperlink-templates",
                "title": "超链模板",
                "summary": "配置可复用的消息正文、素材和交互按钮。",
                "menuPath": "营销 / 超链营销 / 超链模板",
                "routePath": "/hyperlink/templates",
                "keywords": ("消息", "素材", "按钮", "变量"),
            },
            {
                "slug": "menu-hyperlink-strategies",
                "title": "超链策略",
                "summary": "设置并发、发送节奏、重试和账号换号策略。",
                "menuPath": "营销 / 超链营销 / 超链策略",
                "routePath": "/hyperlink/strategies",
                "keywords": ("QPS", "并发", "重试", "冷却"),
            },
            {
                "slug": "menu-hyperlink-insights",
                "title": "超链市场透视",
                "summary": "按来源国和目标国分析送达及账号风险。",
                "menuPath": "营销 / 超链营销 / 超链市场透视",
                "routePath": "/hyperlink/market-insights",
                "keywords": ("国家", "送达", "封禁", "风险"),
            },
            {
                "slug": "menu-direct-short-links",
                "title": "直接短链",
                "summary": "通过 Bitly 账号创建和管理直接短链接。",
                "menuPath": "营销 / 直接短链",
                "routePath": "/direct-short-links",
                "keywords": ("Bitly", "短链", "点击"),
            },
        ),
    },
    {
        "id": "resources",
        "title": "资源",
        "pages": (
            {
                "slug": "menu-account-statistics",
                "title": "账号统计",
                "summary": "查看账号池规模、在线率、国家分布和质量指标。",
                "menuPath": "资源 / 账号中心 / 账号统计",
                "routePath": "/resources/accounts/statistics",
                "keywords": ("账号池", "在线", "质量", "国家"),
            },
            {
                "slug": "menu-account-groups",
                "title": "账号分组",
                "summary": "按业务用途组织统一账号池。",
                "menuPath": "资源 / 账号中心 / 账号分组",
                "routePath": "/resources/accounts/groups",
                "keywords": ("分组", "账号池", "调度"),
            },
            {
                "slug": "menu-account-management",
                "title": "账号管理",
                "summary": "管理账号连接、资料同步、分组和隔离代理。",
                "menuPath": "资源 / 账号中心 / 账号管理",
                "routePath": "/resources/accounts/manage",
                "keywords": ("连接", "同步", "代理", "导入"),
            },
            {
                "slug": "menu-account-intake",
                "title": "接入记录",
                "summary": "审计首次绑定和重新认证的接入过程。",
                "menuPath": "资源 / 账号中心 / 接入记录",
                "routePath": "/resources/accounts/intake",
                "keywords": ("接入", "绑定", "重新认证", "资料同步"),
            },
            {
                "slug": "menu-account-export",
                "title": "账号导出",
                "summary": "导出可迁移账号的兼容凭据或完整备份。",
                "menuPath": "资源 / 账号中心 / 账号导出",
                "routePath": "/resources/accounts/export",
                "keywords": ("备份", "JSON", "凭据", "导出"),
            },
            {
                "slug": "menu-materials",
                "title": "素材库",
                "summary": "统一管理文本、图片、视频、文件和联系人素材。",
                "menuPath": "资源 / 素材库",
                "routePath": "/resources/materials",
                "keywords": ("文本", "图片", "视频", "文件", "联系人"),
            },
            {
                "slug": "menu-protocols",
                "title": "协议管理",
                "summary": "维护协议节点、容量开关和回退协议池。",
                "menuPath": "资源 / 运营管理 / 协议管理",
                "routePath": "/resources/operations/protocol",
                "keywords": ("协议节点", "协议池", "容量", "配对"),
            },
            {
                "slug": "menu-ip-management",
                "title": "IP 管理",
                "summary": "维护代理资源、健康状态、账号绑定和分配策略。",
                "menuPath": "资源 / 运营管理 / IP 管理",
                "routePath": "/resources/operations/ip",
                "keywords": ("代理", "IP", "绑定", "健康检测"),
            },
        ),
    },
    {
        "id": "system",
        "title": "系统",
        "pages": (
            {
                "slug": "menu-system-users",
                "title": "用户管理",
                "summary": "创建、编辑和停用后台登录用户。",
                "menuPath": "系统 / 系统管理 / 用户管理",
                "routePath": "/system/users",
                "keywords": ("用户", "登录", "密码", "停用"),
            },
            {
                "slug": "menu-system-roles",
                "title": "角色管理",
                "summary": "按角色配置菜单范围和操作权限。",
                "menuPath": "系统 / 系统管理 / 角色管理",
                "routePath": "/system/roles",
                "keywords": ("角色", "菜单权限", "操作权限"),
            },
            {
                "slug": "menu-system-menus",
                "title": "菜单管理",
                "summary": "调整内置菜单名称、排序、启用和显示状态。",
                "menuPath": "系统 / 系统管理 / 菜单管理",
                "routePath": "/system/menus",
                "keywords": ("菜单", "路由", "权限标识", "排序"),
            },
        ),
    },
    {
        "id": "template-development",
        "title": "模板开发",
        "pages": (
            {
                "slug": "template-overview",
                "title": "开发流程",
                "summary": "从能力主题开始开发、校验、预览和发布 v2 模板。",
                "keywords": ("v2", "流程", "白标主题", "发布"),
            },
            {
                "slug": "template-package",
                "title": "ZIP 与 manifest",
                "summary": "模板包目录、文件限制和 manifest v2 字段约定。",
                "keywords": ("ZIP", "manifest", "static-bundle", "locale"),
            },
            {
                "slug": "template-runtime",
                "title": "运行时与配对接口",
                "summary": "PromotionBridge v2 的开始、查询和取消契约。",
                "keywords": ("PromotionBridge", "submitPhone", "status", "cancel"),
            },
            {
                "slug": "template-components",
                "title": "白标组件与多语言",
                "summary": "使用 account-link-elements v1 和运行时多语言资源。",
                "keywords": ("Web Components", "i18n", "无障碍", "主题"),
            },
            {
                "slug": "template-acceptance",
                "title": "验收与安全边界",
                "summary": "导入前自检、浏览器验收和安全限制。",
                "keywords": ("验收", "安全", "预览", "检查清单"),
            },
        ),
    },
)


def catalog() -> list[dict]:
    return [
        {
            "id": section["id"],
            "title": section["title"],
            "pages": [
                {key: list(value) if key == "keywords" else value for key, value in page.items()}
                for page in section["pages"]
            ],
        }
        for section in DOC_SECTIONS
    ]


def page_metadata(slug: str) -> dict | None:
    for section in DOC_SECTIONS:
        for page in section["pages"]:
            if page["slug"] == slug:
                return {
                    **page,
                    "keywords": list(page["keywords"]),
                    "sectionId": section["id"],
                    "sectionTitle": section["title"],
                }
    return None


@lru_cache(maxsize=64)
def page_content(slug: str) -> str | None:
    if page_metadata(slug) is None:
        return None
    path = CONTENT_ROOT / f"{slug}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
