from datetime import datetime

from pydantic import BaseModel


class DisclosureResponse(BaseModel):
    id: int
    corp_code: str
    corp_name: str
    stock_code: str | None = None
    stock_id: int | None = None
    stock_name: str | None = None
    report_name: str
    report_type: str | None = None
    rcept_no: str
    rcept_dt: str
    url: str
    created_at: datetime

    model_config = {"from_attributes": True}
