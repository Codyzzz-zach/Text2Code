"""Schema Validator — validate parsed objects against Pydantic model schemas.

v3.3: handles __symbol__ markers from parser symbol refs, mapping
codegen keyword names to ontology _symbol fields.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from t2c.ontology import ONTOLOGY_CLASSES


# Mapping: (constructor_type, keyword_name) → ontology_field_name for symbol refs.
# The parser resolves symbol refs to IDs but preserves the keyword name from
# the .t2c.py source. This table tells the schema validator how to rename
# v3.3 codegen keywords to ontology field names.
#
# Example: EvidenceRef(segment=seg_0009, ...) → parser outputs data["segment"] = "seg1"
# Schema maps "segment" → "segment_id" so Pydantic sees segment_id="seg1".
# The __symbol_refs__ metadata is used to set segment_symbol="seg_0009".
KEYWORD_TO_FIELD: dict[str, dict[str, str]] = {
    "EvidenceRef": {"segment": "segment_id"},
    "Claim": {},
    "Event": {},
    "Relation": {"claim": "claim_id"},
}

# Fields that should be propagated from __symbol_refs__ metadata
SYMBOL_REF_TO_FIELD: dict[str, dict[str, str]] = {
    "EvidenceRef": {"segment": "segment_symbol"},
    "Claim": {"subject": "subject_symbol", "object": "object_symbol"},
    "Event": {"participants": "participant_symbols"},
    "Relation": {"subject": "subject_symbol", "object": "object_symbol", "claim": "claim_symbol"},
}


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
    def _flatten_nested(data: dict, type_name: str = "") -> dict:
        """Replace {type, data} nested constructor dicts with just the data dict.

        v3.3: maps v3.3 codegen keywords to ontology field names so Pydantic
        validation sees the correct field names. E.g., EvidenceRef's 'segment'
        keyword → 'segment_id' field.
        """
        kw_map = KEYWORD_TO_FIELD.get(type_name, {})
        flat: dict = {}
        for key, value in data.items():
            # Map v3.3 keyword to ontology field name
            mapped_key = kw_map.get(key, key)

            if isinstance(value, dict) and "type" in value and "data" in value:
                nested_type = value["type"]
                flat[mapped_key] = SchemaValidator._flatten_nested(value["data"], nested_type)
            elif isinstance(value, list):
                flat_list = []
                for item in value:
                    if isinstance(item, dict) and "type" in item and "data" in item:
                        nested_type = item["type"]
                        flat_list.append(SchemaValidator._flatten_nested(item["data"], nested_type))
                    else:
                        flat_list.append(item)
                flat[mapped_key] = flat_list
            else:
                flat[mapped_key] = value
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
            model_cls.model_validate(self._flatten_nested(data, type_name))
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
        """Validate and construct Pydantic models. Returns (models, violations).

        v4.1: populates _symbol fields from __symbol_refs__ metadata so
        parsed models carry symbol information for downstream use.
        """
        models: list = []
        violations: list[SchemaViolation] = []
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            symbol_refs: dict[str, str] = obj.get("__symbol_refs__", {})
            model_cls = ONTOLOGY_CLASSES.get(type_name)
            if model_cls is None:
                violations.append(SchemaViolation(
                    object_type=type_name, object_id=data.get("id", "?"),
                    field="", message=f"Unknown type: {type_name}",
                ))
                continue
            try:
                flat_data = self._flatten_nested(data, type_name)
                # Populate _symbol fields from __symbol_refs__ metadata
                if symbol_refs:
                    sym_map = SYMBOL_REF_TO_FIELD.get(type_name, {})
                    for ref_key, symbol_name in symbol_refs.items():
                        # Strip array indexing: "participants[0]" → "participants"
                        base_field = ref_key.split("[")[0]
                        target_field = sym_map.get(base_field)
                        if target_field and target_field not in flat_data:
                            # List fields (e.g., participants → participant_symbols)
                            if base_field == "participants":
                                # Collect all participant symbol refs
                                participant_syms = []
                                for key, sym_val in sorted(symbol_refs.items()):
                                    if key.startswith("participants["):
                                        participant_syms.append(sym_val)
                                if participant_syms:
                                    flat_data[target_field] = participant_syms
                            else:
                                flat_data[target_field] = symbol_name
                model = model_cls.model_validate(flat_data)
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
