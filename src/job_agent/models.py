"""Shared data shapes. Every module speaks these types."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    """Reject unknown fields instead of silently dropping them.

    A typo in profile.yaml should be an error, not a field that quietly
    never gets filled in on a real job application.
    """

    model_config = ConfigDict(extra="forbid")


class Identity(Strict):
    first_name: str
    last_name: str
    email: str
    phone: str
    pronouns: str | None = None


class Location(Strict):
    city: str
    state: str
    country: str = "United States"
    postal_code: str | None = None
    willing_to_relocate: bool = False


class Links(Strict):
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None


class WorkAuthorization(Strict):
    authorized_to_work_us: bool
    requires_sponsorship_now: bool
    requires_sponsorship_future: bool
    status: str | None = None


class Education(Strict):
    school: str
    degree: str
    field: str
    start: str
    end: str
    gpa: str | None = None


class Experience(Strict):
    company: str
    title: str
    start: str
    end: str
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)


class Project(Strict):
    name: str
    stack: str | None = None
    date: str | None = None
    bullets: list[str] = Field(default_factory=list)


class Leadership(Strict):
    organization: str
    role: str
    start: str
    end: str
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)


class Documents(Strict):
    """Paths to files a form may ask you to upload. Relative to the repo root."""

    resume: str
    transcript: str | None = None
    cover_letter_template: str | None = None


class Preferences(Strict):
    desired_salary: str | None = None
    earliest_start_date: str | None = None
    notice_period: str | None = None
    remote_preference: str | None = None


class Profile(Strict):
    identity: Identity
    location: Location
    links: Links = Field(default_factory=Links)
    work_authorization: WorkAuthorization
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    leadership: list[Leadership] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    documents: Documents | None = None
    preferences: Preferences = Field(default_factory=Preferences)


# --- form extraction -------------------------------------------------------

FieldKind = Literal[
    "text",
    "textarea",
    "email",
    "tel",
    "number",
    "url",
    "select",
    "radio",
    "checkbox",
    "file",
    "date",
    "combobox",
    "attention_check",
]

CHOICE_KINDS = {"select", "radio", "combobox"}


class FormField(Strict):
    """One control on a page, described the way the model should see it.

    Deliberately no CSS selector: Rippling regenerates name/id per render, so
    the extractor keeps its own role+name handle and the model refers to
    fields only by the opaque field_id.
    """

    field_id: str
    role: str                      # ARIA role: textbox, combobox, button, ...
    accessible_name: str           # what a screen reader would announce
    kind: FieldKind
    required: bool = False
    options: list[str] | None = None
    # Whatever is already in the field — often the resume parser's guess.
    # A non-empty value is NOT evidence that the field is correct.
    current_value: str | None = None
    help_text: str | None = None

    @model_validator(mode="after")
    def choice_fields_need_options(self):
        if self.kind in CHOICE_KINDS and self.options is None:
            raise ValueError(f"options are required for kind={self.kind}")
        return self


class FormSnapshot(Strict):
    url: str
    page_title: str
    page_kind: Literal["form", "login", "review", "confirmation", "captcha", "unknown"]
    ats: str | None = None
    fields: list[FormField] = Field(default_factory=list)
    next_buttons: list[str] = Field(default_factory=list)
    submit_buttons: list[str] = Field(default_factory=list)

    @field_validator("fields")
    @classmethod
    def field_ids_must_be_unique(cls, fields: list[FormField]) -> list[FormField]:
        ids = [f.field_id for f in fields]
        if len(ids) != len(set(ids)):
            raise ValueError("field_id values must be unique within a snapshot")
        return fields
