# Company and Market Twin Requirements Package

Version 1.0 · 24 October 2026 · Status: proposed implementation baseline

This package specifies the entire intended production system. It converts the user's original request and the 18 October architecture blueprint into a PRD, SRS, detailed capability contracts, and verifiable acceptance criteria. It does not authorize implementation, installation, purchases, deployment, or external business actions by itself.

## Reading order

1. [PRD](PRD.md): product purpose, complete workflows, user requirements, scope, implementation dependencies, and unresolved owner decisions.
2. [SRS](SRS.md): numbered software requirements, architecture, data contracts, state machines, numerical specifications, APIs, and operational controls.
3. [Agent specifications](AGENT_SPECIFICATIONS.md): all 23 requested capabilities, their activation conditions, inputs, tools, outputs, interworking, limits, and failure handling.
4. [Traceability and acceptance](TRACEABILITY_AND_ACCEPTANCE.md): mappings from product requirements to software requirements, fixtures, test oracles, and release gates.
5. [AI implementation contract](AI_IMPLEMENTATION_CONTRACT.md): instructions for an implementing AI, prohibited inventions, dependency order, and evidence required to claim completion.
6. [Mega build prompt](MEGA_BUILD_PROMPT.md): copy-ready instructions for a coding AI to build the complete system, configure secrets safely, and minimize coding-process token waste without reducing quality.
7. [Architecture and data contracts](ARCHITECTURE_AND_DATA_CONTRACTS.md): complete component diagram, trust boundaries, record keys, interaction sequences, build dependencies and integration readiness. This is also incorporated in the SRS.
8. [Core contract schemas](contracts/core.schema.json): machine-checkable transport envelopes for claims, parameters, tasks, events, challenges, scenarios, results, and decisions. See [schema notes and semantic validators](contracts/README.md) and [fixture examples](contracts/examples.json).

The JSON schemas cover the core cross-component artifacts, not every API or database row. SRS semantic rules remain mandatory: a structurally valid claim can still be unsupported or unauthorized. Every implementation must add the domain schemas and semantic checks explicitly specified by the SRS.

## Authority and conflict handling

The user's current explicit instructions take precedence. Within this package, the PRD governs product intent, the SRS governs implementation behavior, and the agent catalog refines role behavior without widening permissions. Schemas define payload structure but cannot override evidence, authorization, or numerical requirements. Tests illustrate and verify requirements; they do not silently narrow them.

If documents conflict, record the conflicting IDs and ask the owner when the difference changes product meaning, permissions, cost, security, or a public contract. Do not pick whichever version is easiest to implement. Corrections must update all affected documents and tests in the same specification revision. The earlier blueprint remains background; this package resolves its informal design into explicit proposed requirements.

## What is established and what remains proposed

- **USER_REQUIRED:** the company/market twin, interconnected bounded agents, hybrid knowledge, evidence lineage, quantitative simulation, adversarial review, uncertainty-driven research, and a continuous closed loop.
- **DESIGN_BASELINE:** architecture choices made here to make the design implementable. They are the proposed baseline, not evidence that the owner has approved a provider, fee, domain, or deployment.
- **OWNER_REQUIRED:** facts or permissions that the system cannot invent, listed as OD-01 through OD-12 in the PRD.
- **FIXTURE_ONLY:** fictional companies, numbers, source events, and synthetic test outcomes. They are never presented as real market evidence.
- **DEPENDENCY_GATED:** a required full-system capability whose activation depends on completed infrastructure, configured access, or validated domain data. This status does not remove it from scope.

No specification can guarantee that a model never hallucinates. This package makes important outputs constrained, traceable, challengeable, and rejectable; it requires abstention when material support is missing. It also prevents an implementing AI from silently substituting mocks, invented integrations, or unspecified models for working features.

## Full-system scope and completion

The target is the entire system. All 23 agent capabilities, connected investigation, monitoring, experiment learning, production identity/isolation, operations, and governed execution are required. Build stages describe dependencies only; they are not smaller substitutes for the requested product. There is no MVP completion gate in this package.

A capability can be implemented yet unconfigured for a particular tenant. Its connector and failure paths still need tests against a real authorized sandbox or service before integration readiness is claimed. Data-dependent model validity is evaluated separately from software completeness. An unsupported business domain cannot be made supported by completing the software.

There is no completed software in this package. All acceptance gates are requirements to verify, not reported accomplishments. Research sources establish selected framework behavior only; the architecture and performance targets are design decisions.

## Verification and handoff

[Specification validation report](SPECIFICATION_VALIDATION.md) records document completeness, link/cross-reference checks, core schema validation and arithmetic verification. These checks validate the authored package only, not a software implementation. The detailed acceptance matrix defines the future implementation tests.

The main SRS incorporates the complete architecture and agent catalog, plus lifecycle transition guards, permissions and event contracts. [Reproduce the specification checks](validation/README.md).
