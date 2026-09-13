"""
Schemas
=======
What the offer service accepts and returns: one sentence in, and everything the graph made
of it out — the offers side by side, the answer, and the working behind both.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from services.data_service.delivery import Store


class OfferRequest(BaseModel):
    """One request, as the salesperson raises it."""

    request: str = Field(..., min_length=1, description="What the salesperson wrote down")
    store: Store = Field(default=Store.ATHENS, description="The branch the order is raised from")
    before_cut_off: bool = Field(
        default=True, description="Whether the order is confirmed by 13:00, which same-day needs"
    )


class ComparedOffer(BaseModel):
    """One offer as a row of the comparison table."""

    strategies: list[str]
    skus: list[str]
    description: str
    quantity: int
    net: float
    discount: float
    needs_approval: bool
    shipping: float
    total: float
    fit: float
    days: int | None = Field(default=None, description="Working days, 0 being the same day")
    availability: str
    risk: str
    notes: list[str]


class CheckResult(BaseModel):
    """One question the validator asked, and the answer."""

    name: str
    severity: str
    passed: bool
    said: str


class Checked(BaseModel):
    """What the validator made of one scenario. A scenario that fails a fatal check is withheld."""

    sku: str
    offerable: bool
    failed: list[CheckResult]


class OfferAnswer(BaseModel):
    """Everything the request produced, whether or not it produced an offer."""

    requirements: dict = Field(..., description="What the request came down to")
    offers: list[ComparedOffer] = Field(..., description="Only what the check let through")
    recommendation: dict | None = Field(
        default=None, description="The offer picked and the words to send it with"
    )
    refused: str | None = Field(
        default=None, description="Why there is no offer, when there is none"
    )
    checked: list[Checked] = Field(..., description="Every scenario built, withheld ones included")
    trace: dict = Field(..., description="What each step of the graph did")


class AskRequest(BaseModel):
    """One question to the assistant, in the conversation it belongs to."""

    question: str = Field(..., min_length=1, description="What the salesperson wants to know")
    conversation_id: int | None = Field(
        default=None, description="The conversation to continue. Leave empty to start one"
    )

    model_config = {"json_schema_extra": {"example": {"question": "Τι εγγύηση έχει το PSU-1018;"}}}


class AskAnswer(BaseModel):
    conversation_id: int
    answer: str = Field(
        ..., description="In Greek — or the refusal, when nothing could be supported"
    )
    refused: bool
    tools: list[dict] = Field(default_factory=list, description="The tool calls behind the answer")
    rounds: int


class Turn(BaseModel):
    role: str
    content: str
    tools: list[dict] | None = None
    created_at: datetime


class Thread(BaseModel):
    id: int
    started_at: datetime


class ThreadDetail(Thread):
    messages: list[Turn]
