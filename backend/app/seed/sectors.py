from sqlalchemy.orm import Session

from app.models.sector import Sector

DEFAULT_SECTORS = [
    "건설기계",
    "반도체",
    "2차전지",
    "자동차",
    "조선",
    "철강",
    "화학",
    "바이오/제약",
    "IT/소프트웨어",
    "금융",
    "유통/소비재",
    "에너지",
    "통신",
    "건설/부동산",
    "엔터테인먼트",
    "방산/항공",
    "음식료",
    "섬유/의류",
    "운송/물류",
    "기계/장비",
]


def seed_sectors(db: Session) -> None:
    existing = db.query(Sector).count()
    if existing > 0:
        return

    for name in DEFAULT_SECTORS:
        db.add(Sector(name=name, is_custom=False))
    db.commit()
