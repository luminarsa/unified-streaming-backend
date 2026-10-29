from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.commercial import Plan, PlanEntitlement, StreamingPlatform, Subscription
from app.models.identity import Profile

@dataclass
class AccessDecision:
    allowed: bool
    reason_code: str
    plan_code: str | None = None
    upgrade_plan_code: str | None = None

class EntitlementService:
    EFFECTIVE_STATUSES = {"active", "trialing", "grace_period"}

    def check(self, db: Session, account_id, profile_id, platform_slug: str) -> AccessDecision:
        profile = db.scalar(select(Profile).where(Profile.id == profile_id, Profile.account_id == account_id))
        if not profile:
            return AccessDecision(False, "PROFILE_NOT_FOUND")
        platform = db.scalar(select(StreamingPlatform).where(
            StreamingPlatform.slug == platform_slug, StreamingPlatform.is_active.is_(True)))
        if not platform:
            return AccessDecision(False, "PLATFORM_NOT_FOUND")

        now = datetime.now(timezone.utc)
        pairs = db.execute(select(Subscription, Plan).join(Plan, Plan.id == Subscription.plan_id)
                           .where(Subscription.account_id == account_id)
                           .order_by(Subscription.created_at.desc())).all()
        eligible = []
        for sub, plan in pairs:
            if sub.status not in self.EFFECTIVE_STATUSES:
                continue
            if sub.current_period_end and sub.current_period_end < now:
                continue
            eligible.append((sub, plan))

        for sub, plan in eligible:
            has_entitlement = db.scalar(select(PlanEntitlement.plan_id).where(
                PlanEntitlement.plan_id == plan.id, PlanEntitlement.platform_id == platform.id))
            if has_entitlement:
                return AccessDecision(True, "PLAN_ENTITLEMENT_GRANTED", plan.code)

        upgrade = db.execute(select(Plan).join(PlanEntitlement, PlanEntitlement.plan_id == Plan.id)
                             .where(PlanEntitlement.platform_id == platform.id, Plan.is_active.is_(True))
                             .order_by(Plan.price_minor.asc())).scalars().first()
        return AccessDecision(False, "PLATFORM_NOT_INCLUDED",
                              eligible[0][1].code if eligible else None,
                              upgrade.code if upgrade else None)
