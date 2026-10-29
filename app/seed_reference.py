from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.commercial import Plan, StreamingPlatform, PlanEntitlement

PLANS = [
    {"code": "starter", "name": "Starter", "price_minor": 10000},
    {"code": "plus", "name": "Plus", "price_minor": 15000},
    {"code": "ultimate", "name": "Ultimate", "price_minor": 18000},
]
PLATFORMS = [
    ("netflix","Netflix","streaming"), ("disney-plus","Disney+","streaming"),
    ("apple-tv-plus","Apple TV+","streaming"), ("prime-video","Prime Video","streaming"),
    ("paramount-plus","Paramount+","streaming"), ("hulu","Hulu","streaming"),
    ("comedy-central","Comedy Central","channel"), ("syfy","SYFY","channel"),
    ("showtime","Showtime","streaming"), ("peacock","Peacock","streaming"),
    ("hbo-max","HBO Max","streaming"), ("bbc-iplayer","BBC iPlayer","catch_up"),
    ("britbox","BritBox","streaming"), ("discovery-plus","Discovery+","streaming"),
    ("mtv","MTV","channel"), ("youtube-tv","YouTube TV","live_tv"),
    ("starz","STARZ","streaming"), ("fox","FOX","channel"),
    ("cbs-television","CBS Television","channel"), ("abc-original","ABC Original","channel"),
    ("itv","ITV","channel"), ("crave-tv","Crave TV","streaming"), ("nbc","NBC","channel"),
    ("amc-studio","AMC Studio","streaming"), ("bet-star","BET Star","channel"),
    ("sundance-now","Sundance Now","streaming"), ("channel-4","Channel 4","catch_up"),
    ("channel-5","Channel 5","catch_up"), ("sky","SKY","channel"), ("a-and-e","A&E","channel"),
    ("tlc","TLC","channel"), ("hgtv","HGTV","channel"), ("food-network","Food Network","channel"),
    ("dc-universe","DC Universe","streaming"), ("tnt","TNT","channel"),
    ("cartoon-network","Cartoon Network","channel"), ("dreamworks","DreamWorks","streaming"),
    ("nickelodeon","Nickelodeon","channel"), ("sabc-1","SABC 1","live_tv"),
    ("sabc-2","SABC 2","live_tv"), ("sabc-3","SABC 3","live_tv"),
    ("sabc-news","SABC News","live_tv"), ("sabc-sport","SABC Sport","live_tv"),
    ("sabc-education","SABC Education","live_tv"), ("sabc-encore","SABC Encore","catch_up"),
]
STARTER = {"netflix", "apple-tv-plus", "comedy-central"}
PLUS_EXTRA = {"disney-plus", "paramount-plus", "prime-video"}
LOCAL = {"sabc-1","sabc-2","sabc-3","sabc-news","sabc-sport","sabc-education","sabc-encore"}

def seed():
    with SessionLocal() as db:
        plans = {}
        for data in PLANS:
            plan = db.scalar(select(Plan).where(Plan.code == data["code"]))
            if not plan:
                plan = Plan(**data, currency="ZAR", billing_interval="month")
                db.add(plan)
                db.flush()
            plans[plan.code] = plan
        platforms = {}
        for slug, name, kind in PLATFORMS:
            platform = db.scalar(select(StreamingPlatform).where(StreamingPlatform.slug == slug))
            if not platform:
                platform = StreamingPlatform(slug=slug, name=name, platform_type=kind)
                db.add(platform)
                db.flush()
            platforms[slug] = platform
        access = {"starter": STARTER, "plus": STARTER | PLUS_EXTRA | LOCAL, "ultimate": set(platforms)}
        for code, slugs in access.items():
            for slug in slugs:
                key = (plans[code].id, platforms[slug].id)
                if not db.get(PlanEntitlement, key):
                    db.add(PlanEntitlement(plan_id=key[0], platform_id=key[1]))
        db.commit()
        print("Seeded plans, platform rows and entitlements. Add verified TMDB provider/company IDs and slider definitions separately.")

if __name__ == "__main__":
    seed()
