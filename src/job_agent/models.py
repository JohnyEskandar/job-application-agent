"""Shared data shapes. Every module speaks these types."""

from pydantic import BaseModel, ConfigDict, Field


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
    skills: list[str] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
