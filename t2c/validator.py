"""Validator — full pipeline: AST → Schema → Reference → Evidence → Claim Safety → Coverage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from t2c.claim_safety import ClaimSafetyValidator
from t2c.parser import T2CParseError, T2CParser
from t2c.schema import SchemaValidator, SchemaViolation


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class Validator:
    """Full validation pipeline: AST grammar → Schema → Reference → Evidence → Claim Safety."""

    def __init__(
        self,
        raw_text_store: dict[str, str] | None = None,
    ) -> None:
        self._parser = T2CParser()
        self._schema_validator = SchemaValidator()
        self._claim_safety_validator = ClaimSafetyValidator()
        self._raw_text_store: dict[str, str] = raw_text_store or {}

    def set_raw_text(self, doc_id: str, text: str) -> None:
        self._raw_text_store[doc_id] = text

    # -- Main validation methods -----------------------------------------

    def validate_file(self, path: Path) -> ValidationResult:
        source = path.read_text(encoding="utf-8")
        return self.validate_string(source)

    def validate_string(self, source: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # Step 1: Parse (includes AST grammar validation)
        try:
            objects = self._parser.parse_string(source)
        except T2CParseError as e:
            return ValidationResult(valid=False, errors=[str(e)])

        # Step 2: Schema validation
        schema_violations = self._schema_validator.validate(objects)
        for v in schema_violations:
            errors.append(f"Schema violation in {v.object_type} ({v.object_id}): {v.field} — {v.message}")

        # Step 3: Reference validation
        ref_errors, ref_warnings = self._validate_references(objects)
        errors.extend(ref_errors)
        warnings.extend(ref_warnings)

        # Step 4: Evidence validation
        ev_errors, ev_warnings = self._validate_evidence(objects)
        errors.extend(ev_errors)
        warnings.extend(ev_warnings)

        # Step 5: Claim Safety validation
        cs_errors, cs_warnings = self._validate_claim_safety(objects)
        errors.extend(cs_errors)
        warnings.extend(cs_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def validate_objects(self, objects: list[dict]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # Schema validation
        schema_violations = self._schema_validator.validate(objects)
        for v in schema_violations:
            errors.append(f"Schema violation in {v.object_type} ({v.object_id}): {v.field} — {v.message}")

        # Reference validation
        ref_errors, ref_warnings = self._validate_references(objects)
        errors.extend(ref_errors)
        warnings.extend(ref_warnings)

        # Evidence validation
        ev_errors, ev_warnings = self._validate_evidence(objects)
        errors.extend(ev_errors)
        warnings.extend(ev_warnings)

        # Claim Safety validation
        cs_errors, cs_warnings = self._validate_claim_safety(objects)
        errors.extend(cs_errors)
        warnings.extend(cs_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # -- Reference validation --------------------------------------------

    def _validate_references(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """Check that all cross-references resolve to existing objects."""
        errors: list[str] = []
        warnings: list[str] = []

        existing_ids: dict[str, set[str]] = {}
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id")
            if obj_id:
                existing_ids.setdefault(type_name, set()).add(str(obj_id))

        doc_ids = existing_ids.get("Document", set())
        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id", "?")

            if type_name in ("Block", "Segment"):
                doc_id = data.get("doc_id")
                if doc_id and doc_id not in doc_ids:
                    warnings.append(
                        f"Reference warning in {type_name} ({obj_id}): "
                        f"doc_id '{doc_id}' not found in current file"
                    )

        return errors, warnings

    # -- Evidence validation ---------------------------------------------

    def _validate_evidence(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """Validate evidence references against raw text when available."""
        errors: list[str] = []
        warnings: list[str] = []

        import hashlib

        for obj in objects:
            type_name = obj.get("type", "")
            data = obj.get("data", {})
            obj_id = data.get("id", "?")

            if type_name in ("Block", "Segment"):
                doc_id = data.get("doc_id")
                start = data.get("start_offset")
                end = data.get("end_offset")
                text_slice = data.get("text_slice")
                stored_hash = data.get("hash")

                if text_slice and stored_hash:
                    actual_hash = f"sha256:{hashlib.sha256(text_slice.encode('utf-8')).hexdigest()}"
                    if stored_hash != actual_hash:
                        errors.append(
                            f"Evidence error in {type_name} ({obj_id}): "
                            f"hash does not match text_slice content"
                        )

                if doc_id and doc_id in self._raw_text_store:
                    raw_text = self._raw_text_store[doc_id]
                    if start is not None and end is not None and text_slice:
                        actual_slice = raw_text[start:end]
                        if text_slice != actual_slice:
                            errors.append(
                                f"Evidence error in {type_name} ({obj_id}): "
                                f"text_slice does not match raw_text[{start}:{end}]"
                            )
                elif doc_id:
                    warnings.append(
                        f"Evidence warning in {type_name} ({obj_id}): "
                        f"raw text for doc_id '{doc_id}' not available for validation"
                    )

        return errors, warnings

    # -- Claim Safety validation -----------------------------------------

    def _validate_claim_safety(self, objects: list[dict]) -> tuple[list[str], list[str]]:
        """Validate claim safety rules."""
        errors: list[str] = []
        warnings: list[str] = []

        claims_data = [obj for obj in objects if obj.get("type") == "Claim"]
        relations_data = [obj for obj in objects if obj.get("type") == "Relation"]

        claim_models, claim_violations = self._schema_validator.validate_and_construct(claims_data)
        for v in claim_violations:
            warnings.append(
                f"Schema warning in Claim ({v.object_id}): {v.field} — {v.message}"
            )

        relation_models, rel_violations = self._schema_validator.validate_and_construct(relations_data)
        for v in rel_violations:
            warnings.append(
                f"Schema warning in Relation ({v.object_id}): {v.field} — {v.message}"
            )

        if claim_models and relation_models:
            violations = self._claim_safety_validator.validate_claims(claim_models, relation_models)
            for v in violations:
                errors.append(
                    f"Claim safety error ({v.claim_id}): {v.rule} — {v.message}"
                )

        return errors, warnings