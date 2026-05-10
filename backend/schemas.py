from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class ReportStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class DataOrigin(str, Enum):
    COLLECTED = "collected"
    INFERRED = "inferred"
    SELECTED = "selected"
    REVIEW_REQUIRED = "review_required"


class Location(BaseModel):
    label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = Field(default=None, ge=0.0)
    street_address: Optional[str] = None
    intersection: Optional[str] = None
    neighborhood: Optional[str] = None
    borough: Optional[str] = None
    source: Optional[str] = None
    confirmed: bool = False


class RoutingTarget(BaseModel):
    department: str
    service: str
    agency: Optional[str] = None
    source: str = "fallback"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CivicContext(BaseModel):
    source: str
    dataset: str
    query_summary: str
    matched_count: int = Field(default=0, ge=0)
    likely_agencies: List[str] = Field(default_factory=list)
    likely_problem_types: List[str] = Field(default_factory=list)
    likely_problem_details: List[str] = Field(default_factory=list)
    evidence_summary: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    used_live_data: bool = False
    fallback_reason: Optional[str] = None


class EvidenceItem(BaseModel):
    kind: Literal["text", "audio", "image", "location"]
    summary: str
    captured_at: Optional[datetime] = None


class UncertaintyItem(BaseModel):
    field: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


class DtprStep(BaseModel):
    id: str
    label: str
    data_type: str
    purpose: str
    processor: str
    destination: str
    retention: str
    control_point: str
    origin: DataOrigin


class CollectedInput(BaseModel):
    kind: Literal["text", "audio", "image", "location"]
    value: str
    origin: DataOrigin = DataOrigin.COLLECTED


class InferredContext(BaseModel):
    label: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    origin: DataOrigin = DataOrigin.INFERRED


class HumanReviewField(BaseModel):
    field: str
    reason: str
    current_value: Optional[str] = None
    origin: DataOrigin = DataOrigin.REVIEW_REQUIRED


class ReportDraftRequest(BaseModel):
    scenario: Optional[
        Literal["flooding_near_school_crossing", "trash_bags_on_street"]
    ] = None
    demo_variant: Optional[
        Literal[
            "baseline",
            "confirmed_location",
            "blocked_crosswalk",
            "visible_drain_obstruction",
            "street_trash_bags",
        ]
    ] = None
    transcript: Optional[str] = None
    image_summary: Optional[str] = None
    location: Optional[Location] = None
    resident_claim_summary: Optional[str] = None
    visual_evidence_summary: Optional[str] = None
    accessibility_impact: Optional[str] = None
    recurrence: Optional[str] = None
    recommended_category: Optional[str] = None
    recommended_agency: Optional[str] = None
    slot_quality_summary: Optional[str] = None
    remaining_uncertainty: Optional[str] = None


class LiveClassifyRequest(BaseModel):
    transcript: str = Field(min_length=1)
    image_summary: Optional[str] = None
    image_frame: Optional[str] = None
    location: Optional[Location] = None


class LiveClassifyResponse(BaseModel):
    scenario: Literal["flooding_near_school_crossing", "trash_bags_on_street"]
    demo_variant: Literal[
        "baseline",
        "blocked_crosswalk",
        "visible_drain_obstruction",
        "street_trash_bags",
    ]
    candidate: str
    confirmation: str
    followup: str
    model_source: str
    fallback_reason: Optional[str] = None


class ReportConfirmRequest(BaseModel):
    report_id: str
    accepted: bool = True
    correction: Optional[str] = None


class ReportUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = Field(default=None, min_length=1)
    category: Optional[str] = Field(default=None, min_length=1)
    subcategory: Optional[str] = None
    priority: Optional[Priority] = None
    location: Optional[Location] = None


class ReportDraft(BaseModel):
    id: str
    status: ReportStatus = ReportStatus.DRAFT
    category: str
    subcategory: Optional[str] = None
    title: str
    description: str
    narrative: str
    location: Location
    observed_at: Optional[datetime] = None
    priority: Priority = Priority.UNKNOWN
    routing: Optional[RoutingTarget] = None
    civic_context: Optional[CivicContext] = None
    collected_inputs: List[CollectedInput] = Field(default_factory=list)
    inferred_context: List[InferredContext] = Field(default_factory=list)
    human_review: List[HumanReviewField] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    questions_asked: List[str] = Field(default_factory=list)
    uncertainty: List[UncertaintyItem] = Field(default_factory=list)
    dtpr_chain: List[DtprStep] = Field(default_factory=list)


class ReportConfirmResponse(BaseModel):
    report: ReportDraft
    message: str


class ModelContextPacket(BaseModel):
    report_id: str
    task: Literal["draft_311_service_request"]
    model_role: str
    prompt_goal: str
    observed_inputs: List[str] = Field(default_factory=list)
    inferred_context: List[str] = Field(default_factory=list)
    civic_evidence: Optional[CivicContext] = None
    routing_context: Optional[RoutingTarget] = None
    uncertainty: List[UncertaintyItem] = Field(default_factory=list)
    required_human_confirmations: List[HumanReviewField] = Field(default_factory=list)
    output_requirements: List[str] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)
    dtpr_disclosures: List[str] = Field(default_factory=list)
