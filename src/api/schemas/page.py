from typing import Literal

from pydantic import BaseModel, Field


class NavigateRequest(BaseModel):
    url: str
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "load"


class ClickRequest(BaseModel):
    selector: str = Field(
        description="Playwright selector: CSS, text=..., or role=button[name='...']"
    )
    timeout: int = Field(10_000, ge=100, le=120_000)


class TypeRequest(BaseModel):
    selector: str
    text: str = Field(max_length=20_000)
    submit: bool = Field(False, description="Press Enter after typing")
    clear: bool = Field(True, description="Replace the field's value instead of appending")
    timeout: int = Field(10_000, ge=100, le=120_000)


class PressRequest(BaseModel):
    key: str = Field(description="Key name such as Enter, Tab, Escape, Control+A")
    selector: str | None = None


class ClickAtRequest(BaseModel):
    x: float = Field(ge=0, description="Viewport X in CSS pixels, as on a screenshot")
    y: float = Field(ge=0, description="Viewport Y in CSS pixels, as on a screenshot")


class KeyboardTypeRequest(BaseModel):
    text: str = Field(max_length=20_000)


class WaitRequest(BaseModel):
    selector: str
    timeout: int = Field(15_000, ge=100, le=120_000)


class EvaluateRequest(BaseModel):
    script: str = Field(
        max_length=200_000,
        description="JavaScript expression or function body, e.g. document.title",
    )


class TabNewRequest(BaseModel):
    url: str | None = None


class BatchTarget(BaseModel):
    """One URL to extract text from; unset fields fall back to the batch defaults."""

    id: str = Field(min_length=1, max_length=200, description="Caller-chosen target identifier")
    url: str = Field(min_length=1, max_length=4000)
    selector: str | None = None
    timeout: int | None = Field(None, ge=100, le=120_000)
    max_chars: int | None = Field(None, ge=500, le=200_000)


class BatchExtractRequest(BaseModel):
    targets: list[BatchTarget] = Field(min_length=1, max_length=500)
    selector: str = "body"
    timeout: int = Field(15_000, ge=100, le=120_000)
    max_chars: int = Field(40_000, ge=500, le=200_000)
    skip_succeeded: bool = Field(
        False,
        description="Skip targets that already succeeded in an earlier batch of this profile",
    )
