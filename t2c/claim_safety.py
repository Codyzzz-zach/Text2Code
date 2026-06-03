"""Claim Safety — enforce epistemic boundaries on claim modality propagation."""
from __future__ import annotations

from dataclasses import dataclass

from t2c.ontology import Claim, Relation


@dataclass
class ClaimSafetyViolation:
    claim_id: str
    rule: str
    message: str


class ClaimSafetyValidator:
    """Validate claims against epistemic safety rules.

    Rules:
    1. no_asserted_from_reported   — reported claims cannot project as asserted fact
    2. no_asserted_from_claimed    — claimed_by_source cannot project as asserted fact
    3. no_uncertain_default_fact   — uncertain/hypothetical cannot enter default fact edges
    4. no_unconditional_from_cond  — conditional claims cannot unconditionally enter fact edges
    5. no_positive_from_negative   — negative polarity claims cannot produce positive relations
    6. inferred_requires_source    — inferred claims must have derived_from
    """

    UNCERTAIN_MODALS = {"uncertain", "hypothetical"}

    def validate_claims(
        self,
        claims: list[Claim],
        relations: list[Relation],
    ) -> list[ClaimSafetyViolation]:
        violations: list[ClaimSafetyViolation] = []

        for claim in claims:
            violations.extend(self._check_inferred_requires_source(claim))
            violations.extend(self._check_reported_not_asserted(claim, relations))
            violations.extend(self._check_claimed_not_asserted(claim, relations))
            violations.extend(self._check_uncertain_not_fact(claim, relations))
            violations.extend(self._check_conditional_not_unconditional(claim, relations))
            violations.extend(self._check_negative_not_positive(claim, relations))

        return violations

    def _check_inferred_requires_source(self, claim: Claim) -> list[ClaimSafetyViolation]:
        if claim.modality == "inferred" and not claim.derived_from:
            return [ClaimSafetyViolation(
                claim_id=claim.id,
                rule="inferred_requires_source",
                message="Inferred claim must have derived_from references",
            )]
        return []

    def _check_reported_not_asserted(
        self, claim: Claim, relations: list[Relation]
    ) -> list[ClaimSafetyViolation]:
        if claim.modality == "reported" and claim.polarity == "positive":
            fact_relations = [r for r in relations if r.claim_id == claim.id]
            if fact_relations:
                return [ClaimSafetyViolation(
                    claim_id=claim.id,
                    rule="no_asserted_from_reported",
                    message=f"Reported claim projects as fact via {len(fact_relations)} relation(s)",
                )]
        return []

    def _check_claimed_not_asserted(
        self, claim: Claim, relations: list[Relation]
    ) -> list[ClaimSafetyViolation]:
        if claim.modality == "claimed_by_source" and claim.polarity == "positive":
            fact_relations = [r for r in relations if r.claim_id == claim.id]
            if fact_relations:
                return [ClaimSafetyViolation(
                    claim_id=claim.id,
                    rule="no_asserted_from_claimed",
                    message=f"claimed_by_source projects as fact via {len(fact_relations)} relation(s)",
                )]
        return []

    def _check_uncertain_not_fact(
        self, claim: Claim, relations: list[Relation]
    ) -> list[ClaimSafetyViolation]:
        if claim.modality in self.UNCERTAIN_MODALS:
            fact_relations = [r for r in relations if r.claim_id == claim.id]
            if fact_relations:
                return [ClaimSafetyViolation(
                    claim_id=claim.id,
                    rule="no_uncertain_default_fact",
                    message=f"Uncertain/hypothetical claim has {len(fact_relations)} fact-edge relation(s)",
                )]
        return []

    def _check_conditional_not_unconditional(
        self, claim: Claim, relations: list[Relation]
    ) -> list[ClaimSafetyViolation]:
        if claim.modality == "conditional":
            fact_relations = [r for r in relations if r.claim_id == claim.id]
            if fact_relations:
                return [ClaimSafetyViolation(
                    claim_id=claim.id,
                    rule="no_unconditional_from_cond",
                    message=f"Conditional claim has {len(fact_relations)} unconditional fact-edge relation(s)",
                )]
        return []

    def _check_negative_not_positive(
        self, claim: Claim, relations: list[Relation]
    ) -> list[ClaimSafetyViolation]:
        if claim.polarity == "negative":
            positive_relations = [r for r in relations if r.claim_id == claim.id]
            if positive_relations:
                return [ClaimSafetyViolation(
                    claim_id=claim.id,
                    rule="no_positive_from_negative",
                    message="Negative polarity claim cannot produce positive relations",
                )]
        return []