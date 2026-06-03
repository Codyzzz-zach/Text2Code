"""Schema Validator — validate parsed objects against Pydantic model schemas."""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from t2c.ontology import ONTOLOGY_CLASSES


@dataclass
class SchemaViolation:
    """A single schema validation error."""
    object_type: str
    object_id: str
    field: str
    message: str


class SchemaValidator:
    """Validate parsed {type, data} dicts against ontology Pydantic models."""

    def validate(self, objects: list[dict]) -> list[SchemaViolation]:
        """Validate all objects, return list of violations."""
        violations: list[SchemaViolation] = []
        for obj in objects:
            violations.extend(self._validate_object(obj))
        return violations

    @staticmethod
    def _flatten_nested(data: dict) -> dict:
        """Replace {type, data} nested constructor dicts with just the data dict."""
        flat: dict = {}
        for key, value in data.items():
            if isinstance(value, dict) and "type" in value and "data" in value:
                flat[key] = value["data"]
            elif isinstance(value, list):
                flat[key] = [
                    item["data"] if isinstance(item, dict) and "type" in item and "data" in item else item
                    for item in value
                ]
            else:
                flat[key] = value
        return flat

    def _validate_object(self, obj: dict) -> list[SchemaViolation]:
        """Validate a single {type, data} dict against its Pydantic model."""
        type_name = obj.get("type", "")
        data = obj.get("data", {})
        model_cls = ONTOLOGY_CLASSES.get(type_name)

        if model_cls is None:
            return [SchemaViolation(
                object_type=type_name, object_id=data.get("id", "?"),
                field="", message=f"Unknown type: {type_name}",
            )]

        obj_id = data.get("id", "?")
        try:
            model_cls.model_validate(self._flatten_nested(data))
        except ValidationError as e:
            violations: list[SchemaViolation] = []
            for error in e.errors():
                loc = ".".join(str(l) for l in error.get("loc", []))
                violations.append(SchemaViolation(
                    object_type=type_name,
                    object_id=str(obj_id),
                    field=loc,
                    message=error.get("msg", str(error)),
                ))
            return violations

        return []

    def validate_and_construct(self, objects: list[dict]) -> tuple[list, list[SchemaViolation]]:
        """Validate and construct Pydantic models. Returns (models, violations)."""
        models: list = []
        violations: list[SchemaViolation] = []
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            model_cls = ONTOLOGY_CLASSES.get(type_name)
            if model_cls is None:
                violations.append(SchemaViolation(
                    object_type=type_name, object_id=data.get("id", "?"),
                    field="", message=f"Unknown type: {type_name}",
                ))
                continue
            try:
                model = model_cls.model_validate(self._flatten_nested(data))
                models.append(model)
            except ValidationError as e:
                for error in e.errors():
                    loc = ".".join(str(l) for l in error.get("loc", []))
                    violations.append(SchemaViolation(
                        object_type=type_name,
                        object_id=str(data.get("id", "?")),
                        field=loc,
                        message=error.get("msg", str(error)),
                    ))
        return models, violations