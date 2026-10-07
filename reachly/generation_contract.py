"""Public, versioned business-only generation inputs; credentials are out-of-band."""
from typing import Literal
import json
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer
from .business_brand import palette
from .models import BusinessProfile


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colors: list[str] = Field(default_factory=list)
    theme: str = Field(default="", max_length=2000)
    logo_base64: str = Field(default="", max_length=2_800_000)

    @field_validator("colors")
    @classmethod
    def valid_colors(cls, value):
        return palette(value)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_id: str
    captured_at: str
    sources: list[dict] = Field(default_factory=list, max_length=12)
    findings: list[dict] = Field(default_factory=list, max_length=30)
    audit_id: str = ""
    website: str = ""


class CreativeBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: Literal["awareness", "trust", "enquiries", "recognition"] = "awareness"
    theme: Literal["awareness", "services", "prevention", "team", "community", "accolades", "research"] = "awareness"
    narrative: Literal["educational", "doctor_perspective", "illustrative_journey", "surprise"] = "educational"
    setting: Literal["clinic", "lab", "treatment", "abstract", "surprise"] = "clinic"
    format: Literal["image", "carousel", "video"] = "image"
    topic: str = Field(default="", max_length=200)
    instructions: str = Field(default="", max_length=2000)


class ScriptOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["saved_topic", "surprise"]
    topic: str = Field(default="", max_length=200)
    speaker: str = Field(default="", max_length=160)
    language: str = Field(default="English", min_length=1, max_length=80)
    target_seconds: Literal[60, 75, 90] = 75

    @field_validator("language")
    @classmethod
    def valid_language(cls, value):
        if not value.strip():
            raise ValueError("A script language is required")
        return value.strip()


class Performance(BaseModel):
    """Aggregate results of this business's own published posts, computed by the caller."""
    model_config = ConfigDict(extra="forbid")
    window_days: int = Field(ge=1, le=365)
    measured_posts: int = Field(ge=1, le=10000)
    metric: str = Field(default="", max_length=200)
    top: list[dict] = Field(default_factory=list, max_length=10)
    bottom: list[dict] = Field(default_factory=list, max_length=10)
    by_content_type: dict = Field(default_factory=dict)
    by_narrative: dict = Field(default_factory=dict)
    by_weekday: dict = Field(default_factory=dict)
    by_platform: dict = Field(default_factory=dict)


class Contribution(BaseModel):
    """Material the business shared itself (award, event, talk, news); text only, never files."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=2000)
    speaker: str = Field(default="", max_length=160)
    event_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    source_url: str = Field(default="", max_length=200)
    shared_at: str = Field(default="", max_length=40)
    focus: bool = False


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2, 3] = 1
    operation: Literal["posts", "ideas", "teleprompter_script"] = "posts"
    script_options: ScriptOptions | None = None
    brief: CreativeBrief | None = None
    business_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    organisation_id: str | None = Field(default=None, pattern=r"^ORG-[A-F0-9]{16}$")
    context_mode: Literal["clinic_basic", "clinic_enhanced", "business"] = "business"
    business: BusinessProfile
    public_facts: dict = Field(default_factory=dict)
    source_version: str = Field(min_length=1, max_length=128)
    brand: Brand = Field(default_factory=Brand)
    geo: Evidence | None = None
    research: Evidence | None = None
    research_requested: bool = False
    performance: Performance | None = None
    contributions: list[Contribution] | None = Field(default=None, max_length=10)
    recent_hooks: list[str] = Field(default_factory=list, max_length=40)
    count: int = Field(default=5, ge=1, le=5)
    creative_mode: Literal["distinct_posts", "daily_alternatives"] = "distinct_posts"
    content_type: str = Field(default="", max_length=40)
    topic: str = Field(default="", max_length=200)
    feedback: str = Field(default="", max_length=2000)
    revision_mode: Literal["both", "copy", "image"] = "both"
    original: dict | None = None

    @model_serializer(mode="wrap")
    def serialize_version(self, handler):
        data = handler(self)
        if self.script_options is None:
            data.pop("script_options", None)
        # Absent signals keep earlier request digests stable for in-flight replays.
        if self.performance is None:
            data.pop("performance", None)
        if self.contributions is None:
            data.pop("contributions", None)
        if self.schema_version == 1:
            data.pop("operation", None)
            data.pop("brief", None)
        return data

    def check_scope(self):
        if self.operation == "teleprompter_script":
            if (self.schema_version != 3 or self.script_options is None or self.count != 1
                    or self.original or self.brief or self.creative_mode != "distinct_posts"):
                raise ValueError("Script generation requires v3, options and one text-only result")
            if self.script_options.source == "saved_topic" and not self.script_options.topic.strip():
                raise ValueError("A saved topic is required")
        elif self.script_options is not None:
            raise ValueError("Script options are exclusive to script generation")
        if self.schema_version == 1 and (self.operation != "posts" or self.brief is not None):
            raise ValueError("New creative operations require schema version 2")
        if self.operation == "ideas" and (self.count != 3 or self.original or self.creative_mode != "distinct_posts"):
            raise ValueError("Idea generation requires three ideas and no original media")
        if self.brief and self.brief.format != "image":
            raise ValueError("This generation operation currently supports static images")
        if self.creative_mode == "daily_alternatives" and self.count > 2:
            raise ValueError("A daily post has at most two initial alternatives")
        if self.performance and len(self.performance.model_dump_json()) > 30000:
            raise ValueError("Performance summary is too large")
        if self.contributions:
            focused = [c for c in self.contributions if c.focus]
            if len(focused) > 1 or (focused and self.operation != "posts"):
                raise ValueError("Only one contribution can be the focus of a post request")
            if len({c.id for c in self.contributions}) != len(self.contributions):
                raise ValueError("Duplicate contribution")
            for item in self.contributions:
                url = urlparse(item.source_url) if item.source_url else None
                if url and (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password):
                    raise ValueError("Invalid contribution source link")
        if not self.business.name.strip() or len(self.business.model_dump_json()) > 16000 or len(json.dumps(self.public_facts)) > 60000:
            raise ValueError("Business brief is empty or too large")
        if self.business.website:
            url = urlparse(self.business.website)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                raise ValueError("Invalid business website")
        for evidence in (self.geo, self.research):
            if evidence and evidence.business_id != self.business_id:
                raise ValueError("Evidence business scope mismatch")
            if evidence:
                captured = datetime.fromisoformat(evidence.captured_at.replace("Z", "+00:00"))
                if not captured.tzinfo or not datetime.now(timezone.utc)-timedelta(days=30) <= captured <= datetime.now(timezone.utc)+timedelta(minutes=5):
                    raise ValueError("Evidence is stale or has an invalid timestamp")
                if not evidence.findings or not evidence.sources or len(evidence.model_dump_json()) > 280000:
                    raise ValueError("Evidence requires bounded findings and sources")
                if any(urlparse(str(s.get("url", ""))).scheme not in {"https", "http"} for s in evidence.sources):
                    raise ValueError("Evidence source URLs are required")
        if self.geo and urlparse(self.geo.website).hostname != urlparse(self.business.website or "").hostname:
            raise ValueError("Audit website does not match business")
        if self.context_mode == "clinic_basic" and (self.research or self.research_requested):
            raise ValueError("Basic mode cannot include online research")
        if self.context_mode.startswith("clinic") and self.business.content_preset != "business":
            raise ValueError("Clinic inputs cannot use another business preset")
        if self.original is not None and self.count != 1:
            raise ValueError("A revision generates one candidate")
        if self.original:
            if set(self.original) != {"job_id", "candidate_id"}:
                raise ValueError("Invalid original candidate reference")
            uuid.UUID(str(self.original["job_id"]))
            uuid.UUID(str(self.original["candidate_id"]))
        if self.original is None and self.revision_mode != "both":
            raise ValueError("Copy/image revision requires an original candidate")
