"""Tests for t2c/claim_safety.py — claim safety rules."""
import pytest

from t2c.claim_safety import ClaimSafetyValidator, ClaimSafetyViolation
from t2c.ontology import Claim, Relation


@pytest.fixture
def validator():
    return ClaimSafetyValidator()


def _make_claim(claim_id="c1", modality="asserted", polarity="positive", derived_from=None, **kw):
    return Claim(
        id=claim_id,
        subject="Alice",
        predicate="knows",
        object="Bob",
        modality=modality,
        polarity=polarity,
        derived_from=derived_from or [],
        **kw,
    )


def _make_relation(claim_id="c1", rel_id="r1"):
    return Relation(
        id=rel_id,
        subject="Alice",
        predicate="knows",
        object="Bob",
        claim_id=claim_id,
    )


class TestInferredRequiresSource:
    def test_inferred_without_derived_from(self, validator):
        claim = _make_claim(modality="inferred", derived_from=[])
        violations = validator.validate_claims([claim], [])
        assert len(violations) == 1
        assert violations[0].rule == "inferred_requires_source"

    def test_inferred_with_derived_from_ok(self, validator):
        claim = _make_claim(modality="inferred", derived_from=["c0"])
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "inferred_requires_source" for v in violations)


class TestReportedNotAsserted:
    def test_reported_positive_with_relation_violation(self, validator):
        claim = _make_claim(claim_id="c1", modality="reported", polarity="positive")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert any(v.rule == "no_asserted_from_reported" for v in violations)

    def test_reported_positive_no_relation_ok(self, validator):
        claim = _make_claim(modality="reported", polarity="positive")
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "no_asserted_from_reported" for v in violations)

    def test_reported_negative_ok(self, validator):
        claim = _make_claim(modality="reported", polarity="negative")
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "no_asserted_from_reported" for v in violations)


class TestClaimedNotAsserted:
    def test_claimed_by_source_positive_with_relation_violation(self, validator):
        claim = _make_claim(claim_id="c1", modality="claimed_by_source", polarity="positive")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert any(v.rule == "no_asserted_from_claimed" for v in violations)

    def test_claimed_by_source_positive_no_relation_ok(self, validator):
        claim = _make_claim(modality="claimed_by_source", polarity="positive")
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "no_asserted_from_claimed" for v in violations)

    def test_claimed_by_source_negative_ok(self, validator):
        claim = _make_claim(modality="claimed_by_source", polarity="negative")
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "no_asserted_from_claimed" for v in violations)


class TestUncertainNotFact:
    def test_uncertain_with_relation_violation(self, validator):
        claim = _make_claim(claim_id="c1", modality="uncertain")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert any(v.rule == "no_uncertain_default_fact" for v in violations)

    def test_uncertain_no_relation_ok(self, validator):
        claim = _make_claim(modality="uncertain")
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "no_uncertain_default_fact" for v in violations)

    def test_hypothetical_with_relation_violation(self, validator):
        claim = _make_claim(claim_id="c1", modality="hypothetical")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert any(v.rule == "no_uncertain_default_fact" for v in violations)


class TestConditionalNotUnconditional:
    def test_conditional_with_relation_violation(self, validator):
        claim = _make_claim(claim_id="c1", modality="conditional")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert any(v.rule == "no_unconditional_from_cond" for v in violations)

    def test_conditional_no_relation_ok(self, validator):
        claim = _make_claim(modality="conditional")
        violations = validator.validate_claims([claim], [])
        assert not any(v.rule == "no_unconditional_from_cond" for v in violations)


class TestNegativeNotPositive:
    def test_negative_polarity_with_relation_violation(self, validator):
        claim = _make_claim(claim_id="c1", modality="asserted", polarity="negative")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert any(v.rule == "no_positive_from_negative" for v in violations)

    def test_positive_polarity_ok(self, validator):
        claim = _make_claim(claim_id="c1", modality="asserted", polarity="positive")
        rel = _make_relation(claim_id="c1")
        violations = validator.validate_claims([claim], [rel])
        assert not any(v.rule == "no_positive_from_negative" for v in violations)


class TestValidClaims:
    def test_asserted_positive_no_violations(self, validator):
        claim = _make_claim(modality="asserted", polarity="positive")
        violations = validator.validate_claims([claim], [])
        assert len(violations) == 0

    def test_multiple_valid_claims(self, validator):
        claims = [
            _make_claim(claim_id="c1", modality="asserted"),
            _make_claim(claim_id="c2", modality="reported", polarity="negative"),
            _make_claim(claim_id="c3", modality="inferred", derived_from=["c1", "c2"]),
        ]
        violations = validator.validate_claims(claims, [])
        assert len(violations) == 0
