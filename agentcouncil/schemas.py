from __future__ import annotations

from enum import Enum
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ConsensusStatus",
    "ConsensusArtifact",
    "SourceRef",
    "TurnPhase",
    "TranscriptTurn",
    "TranscriptMeta",
    "Transcript",
    "DeliberationResult",
    "ReviewInput",
    "Finding",
    "ReviewArtifact",
    "DecideInput",
    "DecideOption",
    "OptionAssessment",
    "DecideArtifact",
    "ChallengeInput",
    "FailureMode",
    "ChallengeArtifact",
    "JournalEntry",
    "FindingStatus",
    "FindingIteration",
    "ConvergenceIteration",
    "ConvergenceResult",
    "ChallengeSpecialistAssessment",
    "ReviewSpecialistFinding",
    "DecideSpecialistEvaluation",
]


class ConsensusStatus(str, Enum):
    consensus = "consensus"
    consensus_with_reservations = "consensus_with_reservations"
    unresolved_disagreement = "unresolved_disagreement"
    partial_failure = "partial_failure"


class ConsensusArtifact(BaseModel):
    recommended_direction: str
    agreement_points: List[str]
    disagreement_points: List[str]
    rejected_alternatives: List[str]
    open_risks: List[str]
    next_action: str
    status: ConsensusStatus

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Common Deliberation Framework models
# ---------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)


# TN-03: Phase labels for transcript turns
TurnPhase = Literal["brief", "proposal", "exchange", "synthesis", "specialist", "convergence"]


class SourceRef(BaseModel):
    """Reference to a source document, file, or URL."""

    label: str
    path: Optional[str] = None
    url: Optional[str] = None


class TranscriptTurn(BaseModel):
    """A single turn in the deliberation transcript."""

    role: str  # "outside", "lead", "director"
    content: str
    source_refs: list[SourceRef] = Field(default_factory=list)
    # TN-02: Turn-level provenance fields (all Optional for backward compat)
    actor_id: Optional[str] = None
    actor_provider: Optional[str] = None
    actor_model: Optional[str] = None
    phase: Optional[TurnPhase] = None
    timestamp: Optional[float] = None
    parent_turn_id: Optional[str] = None


class TranscriptMeta(BaseModel):
    """Backend provenance metadata for a deliberation run.

    Deprecated: Envelope-level provenance is superseded by per-turn provenance
    fields on TranscriptTurn (TN-02). This class remains for backward
    compatibility but new code should use turn-level provenance instead.
    """

    lead_backend: Optional[str] = None
    lead_model: Optional[str] = None
    outside_backend: Optional[str] = None
    outside_model: Optional[str] = None
    outside_transport: Optional[str] = None  # "subprocess" or "session"
    independence_tier: Optional[str] = None  # "cross_backend" or "same_backend_fresh_session"
    outside_provider: Optional[str] = None  # e.g. "stub", "ollama", "openrouter"
    outside_profile: Optional[str] = None  # profile name from config
    outside_session_mode: Optional[str] = None  # "native_persistent" or "replay"
    outside_workspace_access: Optional[str] = None  # "native", "assisted", or "none"


class Transcript(BaseModel):
    """Full provenance of a deliberation run."""

    input_prompt: str
    outside_initial: Optional[str] = None
    lead_initial: Optional[str] = None
    exchanges: list[TranscriptTurn] = Field(default_factory=list)
    final_output: Optional[str] = None
    meta: Optional[TranscriptMeta] = None


class DeliberationResult(BaseModel, Generic[T]):
    """Common envelope for all deliberation functions.

    Parameterized by artifact type T (e.g. ReviewArtifact, DecideArtifact).
    """

    deliberation_status: ConsensusStatus
    artifact: T
    transcript: Transcript

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Function-specific models
# ---------------------------------------------------------------------------


class ReviewInput(BaseModel):
    """Input parameters for the review deliberation function (REV-01)."""

    artifact: str  # text or file content to review
    artifact_type: Literal["code", "design", "plan", "document", "other"] = "other"
    review_objective: Optional[str] = None
    focus_areas: list[str] = Field(default_factory=list)
    rounds: int = 1
    file_paths: list[str] = Field(default_factory=list)  # when set + workspace_access=native, agents read files directly
    prior_review_context: Optional[str] = None  # findings from a prior review cycle; used on revision retries to focus the reviewer on whether prior issues were resolved
    review_context: Optional[str] = None  # compact context pack used to avoid broad rediscovery during autopilot gates


class Finding(BaseModel):
    """A single review finding with full provenance (REV-04, REV-05, REV-06)."""

    id: str
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    impact: str
    description: str
    evidence: str
    locations: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    agreement: Literal["confirmed", "disputed"]
    origin: Literal["outside", "lead", "both"]
    source_refs: list[SourceRef] = Field(default_factory=list)
    priority: Optional[Literal["P1", "P2", "P3"]] = None


class ReviewArtifact(BaseModel):
    """Artifact for the review deliberation function (REV-02, REV-03)."""

    verdict: Literal["pass", "revise", "escalate"]
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_action: str


class DecideOption(BaseModel):
    """A single option in a decision (DEC-01)."""

    id: str
    label: str
    description: str


class DecideInput(BaseModel):
    """Input parameters for the decide deliberation function (DEC-01, DEC-12)."""

    decision: str
    options: list[DecideOption]
    criteria: Optional[str] = None
    constraints: Optional[str] = None
    rounds: int = 1

    @model_validator(mode="after")
    def check_min_options(self) -> DecideInput:
        if len(self.options) < 2:
            raise ValueError("DecideInput requires at least 2 options")
        return self


class OptionAssessment(BaseModel):
    """Assessment of a single option in a decision (DEC-04, DEC-05)."""

    option_id: str
    pros: list[str]
    cons: list[str]
    blocking_risks: list[str] = Field(default_factory=list)
    disposition: Literal["selected", "viable", "rejected", "insufficient_information"]
    confidence: Literal["high", "medium", "low"]
    source_refs: list[SourceRef] = Field(default_factory=list)


class DecideArtifact(BaseModel):
    """Artifact for the decide deliberation function (DEC-02, DEC-03)."""

    outcome: Literal["decided", "deferred", "experiment"]
    winner_option_id: Optional[str] = None
    decision_summary: str
    option_assessments: list[OptionAssessment] = Field(default_factory=list)
    defer_reason: Optional[str] = None
    experiment_plan: Optional[str] = None
    revisit_triggers: list[str] = Field(default_factory=list)
    next_action: str

    @model_validator(mode="after")
    def check_outcome_invariants(self) -> DecideArtifact:
        if self.outcome == "decided" and not self.winner_option_id:
            raise ValueError(
                "outcome='decided' requires a non-empty winner_option_id"
            )
        if self.outcome == "deferred" and not self.defer_reason:
            raise ValueError(
                "outcome='deferred' requires a non-empty defer_reason"
            )
        if self.outcome == "experiment" and not self.experiment_plan:
            raise ValueError(
                "outcome='experiment' requires a non-empty experiment_plan"
            )

        # Disposition-based invariants (DEC-06, DEC-07, DEC-08)
        selected = [
            a for a in self.option_assessments if a.disposition == "selected"
        ]
        viable = [
            a for a in self.option_assessments if a.disposition == "viable"
        ]

        if self.outcome == "decided":
            if len(selected) != 1:
                raise ValueError(
                    f"outcome='decided' requires exactly one assessment with "
                    f"disposition='selected', found {len(selected)}"
                )
            if selected[0].option_id != self.winner_option_id:
                raise ValueError(
                    f"outcome='decided': winner_option_id='{self.winner_option_id}' "
                    f"does not match selected option_id='{selected[0].option_id}'"
                )

        if self.outcome == "deferred":
            if len(selected) > 0:
                raise ValueError(
                    "outcome='deferred' must have zero assessments with "
                    "disposition='selected'"
                )

        if self.outcome == "experiment":
            if len(selected) > 0:
                raise ValueError(
                    "outcome='experiment' must have zero assessments with "
                    "disposition='selected'"
                )
            if len(viable) == 0:
                raise ValueError(
                    "outcome='experiment' requires at least one assessment with "
                    "disposition='viable'"
                )

        return self


class ChallengeInput(BaseModel):
    """Input parameters for the challenge deliberation function (CHL-01, CHL-13)."""

    artifact: str  # target plan/design/approach to challenge
    assumptions: list[str] = Field(default_factory=list)
    success_criteria: Optional[str] = None
    constraints: Optional[str] = None
    rounds: int = 2


class FailureMode(BaseModel):
    """A single failure mode identified during challenge (CHL-04, CHL-05)."""

    id: str
    assumption_ref: str
    description: str
    severity: Literal["critical", "high", "medium", "low"]
    impact: str
    confidence: Literal["high", "medium", "low"]
    disposition: Literal[
        "must_harden", "monitor", "mitigated", "accepted_risk", "invalidated"
    ]
    mitigation: Optional[str] = None
    source_refs: list[SourceRef] = Field(default_factory=list)


class ChallengeArtifact(BaseModel):
    """Artifact for the challenge deliberation function (CHL-02, CHL-03)."""

    readiness: Literal["ready", "needs_hardening", "not_ready"]
    summary: str
    failure_modes: list[FailureMode] = Field(default_factory=list)
    surviving_assumptions: list[str] = Field(default_factory=list)
    break_conditions: list[str] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    next_action: str

    @model_validator(mode="after")
    def check_readiness_invariants(self) -> ChallengeArtifact:
        has_must_harden = any(
            fm.disposition == "must_harden" for fm in self.failure_modes
        )
        if self.readiness == "ready" and has_must_harden:
            raise ValueError(
                "readiness='ready' is inconsistent with failure_modes "
                "containing disposition='must_harden'"
            )
        if (
            self.readiness in ("needs_hardening", "not_ready")
            and self.failure_modes
            and not has_must_harden
        ):
            raise ValueError(
                f"readiness='{self.readiness}' requires at least one "
                "failure_mode with disposition='must_harden'"
            )
        if (
            self.readiness in ("needs_hardening", "not_ready")
            and not self.failure_modes
        ):
            raise ValueError(
                f"readiness='{self.readiness}' requires at least one "
                "failure_mode with disposition='must_harden'"
            )
        return self


# ---------------------------------------------------------------------------
# Journal persistence models (DJ-02, DJ-04)
# ---------------------------------------------------------------------------


class JournalEntry(BaseModel):
    """A persisted record of a completed deliberation protocol run."""

    schema_version: str = "1.0"
    session_id: str
    title: Optional[str] = None
    protocol_type: Literal["brainstorm", "review", "decide", "challenge"]
    start_time: float
    end_time: float
    status: ConsensusStatus
    artifact: dict  # serialized protocol-specific artifact
    transcript: Transcript
    events: list[dict] = Field(default_factory=list)
    state: Optional[dict] = None

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Convergence Loop models (CL-03, CL-07, CL-08)
# ---------------------------------------------------------------------------


class FindingStatus(str, Enum):
    """Per-finding status in a convergence loop (CL-03)."""

    open = "open"
    fixed = "fixed"
    verified = "verified"
    reopened = "reopened"
    wont_fix = "wont_fix"


class FindingIteration(BaseModel):
    """Status of a single finding within one convergence iteration."""

    finding_id: str
    status: FindingStatus
    addressed_change: Optional[str] = None
    wont_fix_rationale: Optional[str] = None
    reviewer_notes: Optional[str] = None

    model_config = {"use_enum_values": True}


class ConvergenceIteration(BaseModel):
    """One iteration of a convergence loop (CL-07)."""

    iteration: int
    findings: list[FindingIteration] = Field(default_factory=list)
    approved: bool = False


class ConvergenceResult(BaseModel):
    """Final result of a convergence loop (CL-08)."""

    iterations: list[ConvergenceIteration] = Field(default_factory=list)
    final_findings: list[Finding] = Field(default_factory=list)
    total_iterations: int
    exit_reason: Literal[
        "all_verified",
        "max_iterations",
        "approved",
        "native_workspace_single_pass",
        "single_pass_review_depth",
    ]
    final_verdict: Literal["pass", "revise", "escalate"]
    timing: dict[str, float | str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Expert Witness specialist schemas (EW-06)
# ---------------------------------------------------------------------------


class ChallengeSpecialistAssessment(BaseModel):
    """Specialist output for challenge protocol (EW-06, EW-07)."""

    assumption: str
    validity: Literal["valid", "questionable", "invalid"]
    evidence: str
    confidence: Literal["high", "medium", "low"]


class ReviewSpecialistFinding(BaseModel):
    """Specialist output for review protocol (EW-06, EW-07)."""

    area: str
    severity: Literal["critical", "high", "medium", "low"]
    evidence: str
    affected_scope: str


class DecideSpecialistEvaluation(BaseModel):
    """Specialist output for decide protocol (EW-06, EW-07)."""

    option_id: str
    criterion: str
    score: Literal["strong", "adequate", "weak"]
    rationale: str
