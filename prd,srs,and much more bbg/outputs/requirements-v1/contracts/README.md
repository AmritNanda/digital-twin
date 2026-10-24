# Machine-Readable Core Contracts

`core.schema.json` uses [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12). It defines 11 strict transport artifact shapes: ClaimProposal, ParameterProposal, TaskRequest, AgentResult, EventEnvelope, Challenge, ScenarioPatch, SimulationResult, DecisionProposal, ApprovalRecord and VerificationReport, plus shared reference/value/scope/distribution types.

`examples.json` contains one independent FIXTURE example per type. They are structural examples, not records in an actual database. UUIDs/hashes are illustrative, references are not expected to resolve, approval examples grant no real permission, and results are not evidence that a simulation application ran. Do not load this file as a connected production dataset.

Validate with a Draft 2020-12 validator and format checking enabled; parse strict JSON that rejects NaN/Infinity. Additional fields are rejected. Schema compliance does not establish evidence support, authorization, currentness, valid accounting or referential integrity. These are required application checks below.

## Mandatory semantic validators

| Check | Required behavior beyond the JSON schema |
|---|---|
| Identity and authority | Server-derived tenant/actor match authorized resource scope; client fields cannot grant privileges |
| Reference closure | Every required ref exists at the exact revision, is same-tenant, accessible and of the required semantic kind |
| Specific ref types | `snapshot_ref` resolves a snapshot, `model_ref` a model, `selected_strategy_ref` a strategy, and each other role-specific ref has its declared kind |
| Snapshot consistency | Used claims/parameters/models belong to the pinned manifest or an explicitly permitted new proposal; no mixed revisions |
| Time | Valid interval start is before end when both exist; recorded cutoff excludes future knowledge; required freshness and effective scope pass |
| Origin | FIXTURE content never becomes REAL by copying or deriving it; mixed-origin outputs expose fixture influence and cannot support real-world claims |
| Claim support | KNOWN requires inspected direct support, INFERRED a valid derivation, ASSUMED authorized assumption use; review independently checks entailment and qualifiers |
| Unknown/conflict | UNKNOWN has no selected value; CONTRADICTED retains distinct competing assertions in equivalent scope; a non-null value cannot hide a blocker |
| Parameter admissibility | Model input key/unit/support/range/uncertainty basis is valid; measured/fitted values have appropriate data and derivation; assumptions have allowed-use refs |
| Distributions | Low < high; low <= mode <= high; finite values/support; Beta/lognormal interpretation explicit; empirical dataset/weights valid; joint dependencies specified |
| Currency/tax | Monetary values have explicit compatible currency and tax basis; conversion requires dated rate/assumption; no cross-currency arithmetic without a model |
| Task admission | Capability/template/output types allowed, dependency DAG valid, fingerprint unique where required, budget/depth/deadline available |
| Task completion | Result task/instance/lease matches; required outputs satisfy completion test; terminal state/reason consistent; null reason allowed for successful task completion |
| Events | Event ID is unique; `id` equals `event_id` for this envelope; aggregate revision is valid; canonical commit/outbox and consumer receipt policies hold |
| Challenge resolution | RESOLVED requires test/resolution refs and authorized disposition; material unresolved challenges apply release policy |
| Scenario semantics | Patch keys allowed by model; base immutable; causal counterfactual requires a valid identification review/model, not merely a non-null reference |
| Simulation validity | Invalid draw count <= total; strategy/result sets align; finite metrics; actual output hashes/manifests resolve; unit/accounting checks pass |
| Metric availability | AVAILABLE requires numeric value; NOT_APPLICABLE/UNAVAILABLE require null plus reason; no NaN masquerading as unavailable |
| Decision outcome | RECOMMEND/CONDITIONAL need a selected feasible strategy; definitive recommendations pass all gates; abstention/no-feasible can have no selected strategy |
| Verification | Mandatory FAIL blocks definitive release; NOT_APPLICABLE has a justified policy reason; no agent-provided pass flag bypasses independent checks |
| Approval | Authorized reviewer/category, exact payload hash, destination/resource caps, expiry and revocation checked; an ApprovalRecord supplied by a model has no authority |
| Lineage/currentness | No dependency cycles; provenance closure resolves; release rechecks stale flags and expected case revision transactionally |
| State transitions | Prior state and actor permit the transition; setting a status field in a valid payload cannot directly change authoritative lifecycle |

A schema-valid example may intentionally fail semantic verification when used outside its fixture context. Semantic validators need real repositories/services and acceptance tests; this specification does not claim to implement them.

## Remaining required domain contracts

The core schema is a foundation, not a complete database or OpenAPI definition. Before the corresponding component is implemented, create strict schemas for the records defined by SRS-016 and the architecture annex: Organization/Case, SourceVersion/EvidenceSpan, Requirement/Constraint/Assumption, Review/Question/Answer, Snapshot/PolicyEnvelope, Budget/Reservation, ModelManifest, Strategy/Comparison/OptimizationResult, Experiment/Dataset/Observation, Watcher/Connector, Action, RetrievalPack, domain-specific role outputs and API command/error envelopes. Their fields, invariants and owners are prescribed in the SRS/catalog; ordinary serialization details must be documented and tested, never silently invented as business facts.

Version changes require compatibility/migration checks under SRS-062. Use these schemas to reject malformed transport; use the SRS and semantic validators to reject unsupported meaning.
