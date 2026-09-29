from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ScreenElement(BaseModel):
    id: Optional[str] = None
    label: Optional[str] = None
    type: str = "unknown"
    actions: List[str] = Field(default_factory=list)
    bbox: Optional[Dict[str, int]] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_label(cls, values: Any) -> Any:
        if isinstance(values, dict):
            label = values.get("label")
            if isinstance(label, str):
                values["label"] = label.strip()
            if values.get("type") is None:
                values["type"] = "unknown"
            if values.get("actions") is None:
                values["actions"] = []
        return values


class ScreenSemanticModel(BaseModel):
    screen_name: Optional[str] = None
    screen_purpose: Optional[str] = None
    source: Optional[str] = None
    source_image: Optional[str] = None
    elements: List[ScreenElement] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


def json_schema() -> Dict[str, Any]:
    return ScreenSemanticModel.model_json_schema()
