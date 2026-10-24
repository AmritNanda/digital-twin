# Product Requirements Document

## 1 Document control

Product: Agentic Company and Market Decision Twin. Version: 1.0. Date: 24 October 2026. Status: proposed implementation baseline. Product owner: user, identity/name not specified. Implementation owner: to be assigned. This document covers the entire intended system. All specified capabilities are in the required target; build order does not narrow that scope.

Source of product intent: the user's original project brief, subsequent architecture discussion, and request for a detailed PRD/SRS. The earlier assistant blueprint is a design input, not independently confirmed business data. The hackathon submission template has not been used to infer requirements or judging criteria in this package.

Terms `must`, `shall`, and `required` describe obligations once this specification is selected for implementation. `Proposed` marks a design choice. `May` denotes a genuine optional capability. Unknown business facts remain unknown regardless of specification detail.

## 2 Product definition and outcome

The product helps an organization decide whether to launch, change, expand, defer, or test an offering. It combines the company's actual constraints with external intelligence, explicit behavioral/economic models, and a bounded network of agents. It records why a decision was recommended and revises it when material inputs change.

The primary question is: “Should we launch this offering, where, for whom, at what price, through which channel, with what positioning, under which constraints, and what could make that strategy fail?” The product must support no-launch, pilot, defer, and insufficient-evidence outcomes.

The primary unit of work is a **DecisionCase**, not a chat transcript. A case owns its objective, horizon, constraints, evidence scope, investigation budget, permitted actions, assumptions, strategies, and decision history. Multiple cases can reuse accepted company knowledge while retaining distinct snapshots and permissions.

The primary artifact is a **DecisionPackage** containing a recommendation or abstention, alternatives, conditional outcome ranges, evidence lineage, assumptions, unresolved contradictions, confidence dimensions, risks, change conditions, and an actionable experiment proposal.

## 3 Users and responsibilities

| Persona | Jobs | Authority |
|---|---|---|
| Company owner or product lead | Specify goals, budgets, product constraints, and intended action | Approve case scope and business commitments |
| Analyst or consultant | Review evidence, propose models, investigate alternatives | Submit corrections and analyses within assigned access |
| Domain reviewer | Validate accounting, regulatory applicability, model assumptions, or research methods | Approve only assigned review categories |
| Research operator | Configure permitted sources and connector access | Manage ingestion, not business approvals |
| Platform administrator | Manage identities, quotas, configuration, operations | No automatic right to approve business decisions |
| Decision reader | Inspect approved results and evidence | Read only |

The complete system requires production identity, tenant isolation, and server-side role enforcement. A single-owner local development profile is permitted for testing but cannot satisfy production acceptance; hiding buttons is insufficient.

## 4 Product boundaries

The full twin represents company products/services, customer segments, competitors and substitutes, suppliers, channels, finances, brand promises, capabilities, technical dependencies, operations, portfolio interactions, geography, regulation, macroeconomics, political exposure, social/cultural patterns, and relevant environmental factors.

Domain relevance determines which factors require investigation. A “complete” twin does not require scraping every source or activating every specialist on every case. Unsupported domain models must be declared unsupported. A marketing claim about sustainability requires a defined impact model and evidence; it cannot arise from the product being described as reusable.

The product is decision support with controlled investigations and approved execution paths. It does not promise a perfect human/market simulator, autonomous legal judgment, causal identification from text, or guaranteed commercial returns. It does not turn synthetic responses into observed customers.

## 5 Product requirements

### PRD-01 Organization intake and requirements

The user shall upload company materials and obtain a structured, reviewable requirements specification. It must capture industry, geography, products/services, current/target customers, competitors, revenue with period, cost definitions, COGS, cash, budgets, capacities, time horizon, desired margin definition, allowable CAC, objectives, risk tolerance, pricing/brand/distribution/technical/regulatory constraints, and forbidden strategies. Each value must preserve source locations, units, scope, and status.

### PRD-02 Explicit unknowns and contradictions

The system shall distinguish KNOWN, INFERRED, ASSUMED, UNKNOWN, and CONTRADICTED. It must ask for critical missing internal facts, allow explicit scenario assumptions, preserve competing values, and avoid silently filling gaps. The user must be able to correct extraction without editing the source file.

### PRD-03 Living company and market model

The system shall preserve accepted knowledge over time, with effective dates, recorded dates, immutable revisions, and historical snapshots. It must represent company/market relationships, evidence, assumptions, models, experiments, and decisions. A later correction must not rewrite the basis of an earlier recommendation.

### PRD-04 Hybrid retrieval and institutional memory

Agents and users shall retrieve exact facts, semantic evidence, lexical matches, and graph context. Retrieval must include relevant contradiction paths and source provenance. Accepted findings and experiment lessons may be reused; stale or withdrawn evidence must not silently remain authoritative.

### PRD-05 Bounded external investigation

The system shall investigate the uncertainties relevant to the case using available, permitted sources. It must distinguish discovery snippets from inspected evidence, record queries and coverage limits, and remain useful when a connector is unavailable. It must not imply access to X, Reddit, paid reports, private systems, or other services without configured access.

### PRD-06 Evidence credibility and bias review

The system shall assess source authority for the specific claim, recency/applicability, entailment, origin independence, geographic/language/population coverage, contradiction, and manipulation signals. It must reveal evidence limitations rather than issuing an unsupported universal trust score or bias-free certification.

### PRD-07 Interconnected autonomous work

Agents shall communicate using shared typed artifacts and task/event references, request other capabilities, challenge findings, replan, and rerun affected analyses. The system must support conditional cycles and concurrent independent work. A sequence of fixed persona prompts without adaptive work selection does not satisfy this requirement.

### PRD-08 Governed specialist creation

The system shall instantiate an appropriate specialist when a decision-relevant uncertainty justifies it, subject to capabilities, permissions, budget, time, depth, deduplication, and evaluation rules. It must terminate completed/inconclusive specialists and prevent uncontrolled spawning or runtime permission escalation.

### PRD-09 Grounded customer and demand scenarios

The system shall model segment responses using measured observations or declared assumptions, with uncertainty and applicability limits. It must distinguish measured behavior, expressed intentions, qualitative attitudes, and synthetic hypotheses. It must not report a demand forecast when the available data only supports a conditional scenario.

### PRD-10 Financial and operational consequences

The system shall compute demand, fulfilled sales, revenue, margin, acquisition economics, cash, capital exposure, and relevant repeat/retention measures using executable models. It must account for capacity, inventory, lead times, channels, and cost definitions. Metrics that do not apply to the business must be labeled not applicable.

### PRD-11 Strategy generation and pricing

The system shall propose coherent combinations of price, product/features, segment, geography, channel, positioning, spend, and timing within constraints. It must include a suitable status quo, defer, or pilot alternative. It must distinguish multi-variable strategy comparisons from experiments that isolate one variable's effect.

### PRD-12 Simulation and strategy comparison

The system shall evaluate strategies reproducibly under explicit uncertainty, report distributions or scenario ranges, and compare feasibility, value, downside, and ranking stability. Simulation volume and model agreement must not be presented as empirical validation.

### PRD-13 Counterfactual and stress exploration

The user shall change competitor prices, acquisition cost, demand, supply, regulation, budget, features, segments, and geography and inspect affected results. The interface must distinguish sensitivity analysis, structural intervention scenarios, and justified causal counterfactuals.

### PRD-14 Active falsification

The system shall attempt to disprove its leading recommendation through specific, falsifiable challenges. It must investigate contrary evidence and alternative explanations, revise relevant assumptions/models when warranted, and retain unresolved dissent in the final result.

### PRD-15 Information value and convergence

The system shall prioritize research and experiments that can change a decision, taking effort and cost into account. It must stop on configured convergence or resource limits and label the actual reason. “Budget exhausted” must not be described as “converged.”

### PRD-16 Verifiable decision output

Each material recommendation shall be traceable through concise rationale, simulation, parameter/model revisions, assumptions, evidence spans, and original sources. The system must release only verified results and abstain when a hard constraint or critical model input is unresolved. Traceability means reviewable evidence and calculations, not disclosure of private model chain-of-thought.

### PRD-17 Monitoring and revision

The system shall watch configured sources and actual business data, detect material changes, mark dependent results stale, and initiate bounded re-evaluation. It must suppress duplicate/no-op updates, preserve history, and enforce organization-wide budgets as well as case budgets.

### PRD-18 Experiments and learning

The system shall propose real-world experiments to resolve material uncertainty, collect approved actual observations, and evaluate/update appropriate models. It must separate planning from authorized execution and distinguish empirical learning from repeated computation on the same assumptions.

### PRD-19 Safety, access, and human ownership

The system shall enforce data isolation, tool permissions, secrets handling, source/data retention, and scoped approvals. Research permission must not implicitly authorize sending messages, buying services, publishing prices, launching campaigns, or placing orders. Untrusted content cannot change instruction priority or permissions.

### PRD-20 Operational transparency and portability

The system shall expose task progress, meaningful events, cost, latency, failures, stop reasons, and provider/model versions. It must support provider adapters and predominantly free/open-source infrastructure where suitable, without claiming that inference or external data is free. Switching providers must preserve contracts and require re-evaluation.

## 6 Complete user workflow

| Stage | User experience | Required outcome | Failure or alternate path |
|---|---|---|---|
| WF-01 Define | Enter decision question and organization | Case with horizon and objective | Ambiguous action/population becomes a clarification |
| WF-02 Import | Upload documents, costs, and available customer data | Immutable source versions and parsed evidence | Invalid/unsupported file yields a visible error; no invented contents |
| WF-03 Review | Inspect structured requirements and disagreements | Accepted facts or explicit assumption ranges | Critical unknown creates NEEDS_INPUT |
| WF-04 Bound | Set permitted sources/actions, spend, deadline, and risk policy | Approved investigation envelope | No paid/live calls without configured authorization |
| WF-05 Observe | View company graph and evidence inventory | Snapshot with traceable assertions | Ambiguous identity remains separate pending review |
| WF-06 Investigate | Watch relevant tasks and specialists | Accepted evidence or explicit unresolved gaps | Source outage/redundancy stops that research path |
| WF-07 Model | Review behavioral/financial assumptions | Approved model and parameter manifest | Unidentified response model becomes a conditional scenario or abstention |
| WF-08 Compare | Inspect candidate strategies and uncertainty | Feasible comparison against baseline | No feasible strategy produces no-launch/defer outcome |
| WF-09 Challenge | Inspect adversarial objections and responses | Resolved tests or disclosed material dissent | Accepted challenge triggers a new revision and rerun |
| WF-10 Decide | Read verified decision and why it could change | Released decision package or qualified abstention | Unsupported material statements fail verification |
| WF-11 Authorize | Approve a specific pilot/action if desired | Scoped, expiring approval record | Changed artifact requires new approval |
| WF-12 Learn | Import observed results | Dataset revision and reviewed calibration | Synthetic observations cannot update a real dataset |
| WF-13 Reopen | See changed evidence and affected decision | New bounded investigation and decision version | Unchanged inputs remain idle; exhausted organization budget prevents dispatch |

WF-06 through WF-09 form a network of revisitable work. A regulatory issue can interrupt strategy feasibility before simulation, while pricing can request competitor research and the challenger can trigger customer investigation. The workflow is not a mandatory single pass through every role.

## 7 Information and output standards

Every material value must reveal its source or assumption status, scope, period, unit, and validity. Monetary values require currency and tax basis. Sources require original locations and retrieval dates. A source's publication date must not be invented from its retrieval date.

The final decision must separate evidence quality, parameter uncertainty, model-validation status, numerical precision, and strategy robustness. A single confidence percentage is prohibited unless its meaning and empirical calibration are defined. Conditional probability from a simulator is labeled conditional on its model and assumptions.

A user must be able to inspect a result without reading every agent trace. The default screen shows action, relevant outcome range, hard constraints, material assumptions, main challenge, and what could change the conclusion. Detailed evidence and execution traces remain accessible through drill-down.

## 8 Product screens and interactions

| Screen | Required content and actions |
|---|---|
| Case setup | Organization, question, horizon, objective, geography/population, model domain, policy envelope |
| Requirements review | Field values, source anchors, epistemic/review states, corrections, unresolved blockers |
| Company and market model | Entity relationships, scope/time filters, accepted/disputed claims, source drill-down |
| Investigation workspace | Ready/running/waiting tasks, specialist purpose, budget, findings, errors, cancel/resume |
| Evidence explorer | Exact spans, original source, dates, source-origin clusters, contradiction and coverage |
| Strategy laboratory | Comparable actions, financial definitions, distributions, constraint failures, stress patches |
| Decision history | Current and previous versions, stale/superseded status, meaningful diffs, lineage |
| Experiments | Proposed study, population, outcome, cost, approval state, observed results |
| Administration | Source/provider access, approved templates/models, quotas, retention, audit configuration |

Every screen must visibly distinguish LIVE, CACHED, and FIXTURE modes where applicable. A saved simulation is not a new live result. Failure/loading states must not display stale values as fresh success.

## 9 Full-system scope and dependency stages

Every capability below is required for the complete system. Stages describe the order in which dependencies become usable; none is an acceptable substitute for the entire requested product.

| Stage | Required capability group | Exit evidence |
|---|---|---|
| Foundation | Production identity, organization/case model, source intake, evidence review, temporal canonical storage, audit and budgets | Isolation, parsing, provenance and transaction tests |
| Knowledge and execution | Knowledge graph, semantic/lexical retrieval, memory, task/event infrastructure, LangGraph orchestration, all 23 role contracts, governed specialist factory | Real concurrent tasks, durable interruption/recovery, bounded recursive requests |
| Decision intelligence | Domain packages, behavioral/operational/financial models, pricing, simulation, optimization, counterfactuals, adversarial testing and verification | Numerical oracles, model applicability checks, reproducible comparisons and abstentions |
| Connected continuous loop | Configured external intelligence, source watches, actual business observations, invalidation, experiments, calibration, information value and adaptive replanning | A real authorized source change and measured outcome produce a reviewed decision revision |
| Production operation | Multi-tenant deployment, access administration, monitoring, backup/restore, deletion, accessibility, approved external actions and connector operations | Security, resilience, connector and end-to-end acceptance evidence |

Multiple products, portfolios, segments, channels, geographies, organizations, and simultaneous decision cases must be represented. Every supported domain needs its own validated model package. A general framework plus one validated domain is not evidence that all other industries have calibrated predictive models.

All 23 capabilities must have executable implementations and role-specific acceptance evidence. Some roles are deterministic services rather than separate LLM calls; that choice preserves their function while avoiding waste. Role activation depends on case relevance rather than running every role on every case.

Testing uses small fictional fixtures as well as larger production-scale profiles. A fixture of one company, two segments, two channels and a 90-day horizon is only a numerical test case, never a product limit. Unfinished features remain explicitly unavailable; decorative interfaces and replayed agent traces do not count as implementation.

## 10 Success metrics and release decisions

The primary metric is correct, traceable revision after a material evidence change. Supporting metrics are critical-unknown recall, supported material claim rate, source-origin handling, constraint compliance, numerical correctness, elapsed time/cost, recovery behavior, and user comprehension of assumptions.

Full-system gates: all material seeded unknowns/contradictions detected; every released material claim supported or explicitly assumed; zero hard-constraint violations; all golden numerical cases within declared tolerance; zero unauthorized side effects or budget overruns in the control suite; and every seeded material change invalidating the correct affected artifacts. Report counts and failure cases, not only percentages.

Software completeness alone cannot establish real-world predictive accuracy. Model validation requires actual held-out or prospective outcomes with a justified evaluation method. Improvements must be compared with a spreadsheet/analyst baseline and a simpler research system using comparable source access and budgets.

## 11 Non-goals and excluded shortcuts

- No claim that a single unvalidated model predicts every industry; the complete platform supports explicit domain packages and their validation.
- No arbitrary self-authored executable agents or permission changes.
- No broad collection of social/personal data without suitable source access and purpose.
- No synthetic panel responses counted as actual customers or empirical sample size.
- No market probabilities or feature uplift invented by a language model.
- No silent success fallback from a failed connector to a fabricated result.
- No implicit autonomous real-world spending or communications.
- No requirement to deploy every named technology; contracts and demonstrated need determine adoption.

These exclusions do not remove the required agent network, evidence graph, simulation, or continuous feedback loop.

## 12 Owner decisions and blocking behavior

| ID | Required decision | Proposed default for planning | Blocks |
|---|---|---|---|
| OD-01 | Initial validated business domain and decision question | Consumer-product launch fixture | Live domain-specific model selection |
| OD-02 | Actual organization/product, geography, and population | Fictional example only | Real recommendation |
| OD-03 | Real company data and permission to process it | Synthetic records | Real evidence/calibration claims |
| OD-04 | Model provider access or local inference hardware | Provider adapter with no configured credentials | Live LLM execution |
| OD-05 | Currency spend ceiling and allowed paid services | Paid/live external calls disabled | Any billable calls |
| OD-06 | Permitted external/private sources and credentials | Local fixtures and public-source designs | Connector access beyond declared policy |
| OD-07 | Development repository and deployment target | Local project; no deployment assumed | Changes to other repositories or external deployment |
| OD-08 | Team, deadline, and hackathon prebuild rules | No eligibility assumptions | Delivery promise or event eligibility claim |
| OD-09 | Decision objective, risk limits, and forbidden strategies | Required per real case | Definitive action recommendation |
| OD-10 | Approved model/data reviewers | Local owner in fixture mode | Material real-world model/applicability approval |
| OD-11 | Data retention, region, and confidentiality constraints | Local synthetic data only | Production personal/confidential data use |
| OD-12 | External actions, recipients, and approval policy | All external business mutations disabled | Real outreach, campaigns, orders, or price changes |

An implementing AI can construct interfaces, deterministic models, fixtures, and tests without inventing these answers. It must not use an empty field or elapsed time as approval. Secrets should be configured through appropriate local/secret-management mechanisms, not embedded in documents, code, or shared logs.

## 13 Product risks and mitigations

The principal risks are weak demand identification, unsupported evidence-to-parameter inference, source correlation, changing market conditions, model overfitting, stale decisions, and overconfidence from polished presentation. Mitigations are explicit assumptions, valid observation models, source-origin review, as-known snapshots, bounded optimization, dependency invalidation, independent verification, and experiments that measure actual behavior.

Operational risks include provider/network outages, uncontrolled research spend, prompt injection, cross-tenant leakage, replayed mutations, and missing data rights. The SRS specifies hard enforcement and failure paths rather than relying on agent prompts alone.

## 14 Product acceptance

The owner can accept the complete system only when its full required scope, functional behavior, remaining limitations, and test evidence are reviewable. A claimed working capability must have a demonstrated path from user input through actual storage/tools/computation to the displayed result. An architecture diagram, schema, or prompt definition alone is not implementation evidence.

The complete product is successful when a user can reliably inspect what the system knows, what it assumes, what it calculated, what challenged the conclusion, and which new evidence or experiment could change the recommended action.

## 15 Detailed functional inventory and user stories

The following stories are mandatory parts of the full product. A capability is not complete if only its happy path works. These stories refine PRD-01 through PRD-20 rather than creating a smaller delivery scope.

| Area / story | User goal and required interaction | Completion condition and exceptions |
|---|---|---|
| US-01 Organization workspace | As an owner, create organizations, offerings, geographies and business units; assign case participants | Shared knowledge is scoped and reusable; one tenant cannot inspect another tenant's entities |
| US-02 Decision definition | Define an action/question, objective, time horizon, risk tolerance, capital ceiling and forbidden choices | Ambiguous objectives remain unresolved; the system never chooses profit versus growth preferences on the owner's behalf |
| US-03 Document intake | Import business plans, decks, financial tables, customer observations and source documents | Supported text, PDF/OCR, DOCX, XLSX, PPTX and CSV retain inspectable anchors; unsupported/encrypted variants fail visibly |
| US-04 Extraction review | Inspect each extracted requirement alongside its original passage/table and correct errors | Corrections preserve the prior extraction; currency, units and time remain explicit |
| US-05 Missing facts | Answer prioritized questions or authorize limited assumption ranges | Independent investigation can continue; a critical unanswered fact blocks definitive dependent conclusions |
| US-06 Conflicting evidence | Compare alternative statements and their scopes, dates and original sources | Different contexts can resolve a conflict; unresolved material contradictions remain visible and can block release |
| US-07 Knowledge navigation | Explore company, customer, competitor, supplier and channel relationships over time | Business relations, assumed causal mechanisms and artifact dependencies have distinct meanings |
| US-08 Research control | Select permitted sources, languages, time windows and research budgets | Source failures and limited coverage are disclosed; inaccessible private/paid data is never implied available |
| US-09 Agent work inspection | See why each specialist exists, what it needs, what it found and what it requested next | Actual tasks and artifacts explain activity; animation or persona text alone is insufficient |
| US-10 Specialist requests | Let relevant agents request a narrowly scoped expert investigation | Factory checks relevance, duplication, permissions and remaining resources before dispatch |
| US-11 Customer interpretation | Compare observed behavior, expressed preferences, inferred segments and hypothetical archetypes | Synthetic customers remain hypothetical; qualitative opinions do not become sales probabilities |
| US-12 Commercial design | Compare prices, features, segments, geography, positioning and channels | Coherent strategy vectors respect hard constraints and include a meaningful baseline/defer/pilot option |
| US-13 Numerical inspection | Inspect demand, fulfilled sales, margins, profit, cash and applicable retention/LTV | Each number links to an executable model and its inputs; unsupported metrics display unavailable or not applicable |
| US-14 Portfolio allocation | Allocate shared capital/capacity across products and markets | Shared resources, overlap, cannibalization and currency assumptions reconcile across the portfolio |
| US-15 Scenario exploration | Change costs, acquisition, competitor moves, supply or market conditions | Child scenarios preserve the factual baseline and state sensitivity/intervention/causal limits |
| US-16 Downside review | Inspect loss ranges, liquidity breaches, stress scenarios and ranking changes | Uncertainty and model limitations remain visible; “best” cannot hide infeasible cases |
| US-17 Challenge | Review strongest objections and evidence that could overturn the leading action | Material challenges have test outcomes or explicit unresolved status; dissent is not silently deleted |
| US-18 Decision release | Read the recommendation, conditions, alternatives, evidence, risks and next experiment | Verification gates pass or the result is a qualified abstention; drafts cannot appear current/approved |
| US-19 Ongoing observation | Configure change watches for market and internal business data | Unchanged observations do not trigger unnecessary reasoning; material changes mark the decision stale |
| US-20 Revision explanation | Compare the old and new recommendation after a change | Changed evidence, parameters, results and action are traceable without rewriting historical context |
| US-21 Experiment design | See the smallest justified test that could resolve decision-critical uncertainty | Population, estimand, controls, costs, analysis and stop rules are explicit; execution is separately authorized |
| US-22 Empirical learning | Import real outcomes and inspect calibration/model updates | Only appropriate measured data supports empirical updates; promotion and rollback are reviewed |
| US-23 External action | Preview and approve a specific supported action through configured connectors | Exact payload/recipient/spend is bound to approval; timeout/duplicate delivery cannot silently repeat effects |
| US-24 Operations and governance | Manage access, source/provider permissions, retention, exports and recovery | Auditable configuration and tested isolation/recovery/deletion work across all stores |

## 16 Full agentic capability model

All 23 capabilities are required. “Agentic” describes bounded goal-directed investigation and coordination; it does not require every capability to consume an LLM call. Arithmetic, admission, memory writes and optimization remain controlled services. The SRS and [agent specifications](AGENT_SPECIFICATIONS.md) define exact inputs, permitted tools, output contracts and evaluation rules.

| ID | Capability | Product responsibility | Primary collaborators |
|---|---|---|---|
| A01 | Research | Acquire inspectable evidence for a specific uncertainty | Planner, market/domain specialists, evidence auditor |
| A02 | Market intelligence | Market structure, trends, segments, size definitions and dynamics | Research, customer, competitor, strategy |
| A03 | Competitor | Offers, prices, substitutes, channels and conditional reactions | Pricing, market, risk, challenger |
| A04 | Customer intelligence | Behavior, needs, constraints, segmentation and evidence gaps | Sentiment, bias, pricing, experiments |
| A05 | Sentiment | Aspect-specific, language-aware opinion evidence | Customer, bias, evidence auditor |
| A06 | Pricing | Feasible price/tier/bundle alternatives and response assumptions | Competitor, customer, financial, optimization |
| A07 | Financial | Accounting, contribution, cash and capital implications | Pricing, simulation, strategy, verification |
| A08 | Regulatory | Applicable obligations, effective dates and unresolved interpretation | Research, risk, domain reviewer |
| A09 | Political/geopolitical | Geographic exposure, policy/trade scenarios and dated events | Market, suppliers/operations model, risk |
| A10 | Technology | Feasibility, maturity, dependencies, costs and adoption constraints | Company capability model, risk, strategy |
| A11 | Risk | Cross-domain failure modes, correlation and mitigations | All domain specialists, simulation, challenger |
| A12 | Bias auditor | Coverage, origin dependence, framing and selection limitations | Research, customer, sentiment, verification |
| A13 | Evidence auditor | Source entailment, authority, context and contradiction | All claim producers, validation service |
| A14 | Simulation | Execute pinned numerical scenarios and uncertainty models | Financial, customer, optimizer, challenger |
| A15 | Optimization | Feasible ranking, tradeoffs, downside and robustness | Strategy, simulation, planner |
| A16 | Strategy | Coherent action portfolios and hypotheses | Pricing, market, risk, optimization |
| A17 | Devil's advocate | Falsify leading recommendations with concrete tests | Evidence, research, simulation, strategy |
| A18 | Experiment | Design real tests and measurement/analysis plans | Customer, planner, financial, learning pipeline |
| A19 | Verification | Enforce evidence, numerical and decision-release checks | All output producers, release service |
| A20 | Planner | Uncertainty backlog, task selection, adaptive routing and stopping | Every specialist, factory, budgets |
| A21 | Memory | Retrieve/reuse accepted knowledge with scope and expiry | Knowledge services, all investigators |
| A22 | Agent factory | Admit bounded approved specialist instances and enforce lifecycle | Planner, scheduler, policy/budget services |
| A23 | Final decision | Synthesize verified structured conclusions and alternatives | Strategy, optimizer, challenger, verification |

The required interworking is a task/artifact network. For example, pricing can ask competitor and customer specialists for evidence; the customer specialist can ask the bias auditor whether the evidence covers the target population; the challenger can force a new supply or acquisition-cost scenario; the planner can select an experiment instead of further web research. All requests pass the same admission and budget controls.

No agent may silently widen its data access, change the objective, increase the budget or convert its own proposal into approved truth. A proposed specialist is useful only when it can produce a defined artifact/test that affects the decision. Persistent knowledge belongs to the system, not a persona's private unreviewed memory.

## 17 Decision package: required user-facing contents

Every released package must contain the following, with explicit unavailable/not-applicable values rather than invented completeness:

1. **Case identity and interpretation:** organization, question, scope, horizon, objective, risk policy, snapshot, creation time, current/stale status and LIVE/CACHED/FIXTURE origin.
2. **Outcome:** recommend, conditional, defer, no feasible action or abstain; selected action and conditions stated directly.
3. **Alternatives:** comparable strategy vectors, baseline, feasibility, objective values, downside and why an option was rejected.
4. **Economics and operations:** measured/scenario demand, fulfilled sales, unit economics, profit, cash trough, funding/capacity constraints and domain-applicable repeat metrics.
5. **Uncertainty:** evidence coverage, assumptions, parameter uncertainty, model-validation scope, numerical error and ranking stability as separate concepts.
6. **Provenance:** material claims, exact source locations, calculations, model/parameter versions and significant review decisions.
7. **Adversarial review:** strongest challenge, test result, remaining dissent and failure scenarios.
8. **Decision boundaries:** parameter thresholds/events that would change the recommendation; unavailable causal interpretation identified.
9. **Next information or experiment:** expected decision relevance, cost/time, data needed, study plan and approval status.
10. **Execution and monitoring:** permitted next actions, exact pending approvals, watcher coverage, expiry/freshness and last successful check.
11. **Run transparency:** work completed, unresolved tasks, actual stop reason, resource use and connector/provider failures.

Narrative and charts are derived from the same verified structured results. A readable summary is mandatory; users should not have to audit raw tool traces to learn the conclusion. Detailed calculations and evidence remain available for review/export.

## 18 Complete reference journey and alternate paths

This is a fictional acceptance journey, not a market recommendation. A company is evaluating a new product across two segments and two channels. The owner imports a deck, cost spreadsheet and customer observations, then defines a 90-day objective and liquidity limit. Intake discovers that two documents quote different fulfillment costs. It preserves both, asks for the applicable scope/date, and continues independent competitor research.

After the owner resolves the cost scope, the system accepts the requirement revision and builds a snapshot. The planner identifies price response and acquisition cost as the important uncertainties. Research fetches permitted evidence; the evidence auditor rejects an unsupported quote, while the bias auditor notes that one segment has weak coverage. Pricing proposes alternatives; numerical services calculate scenario demand, contribution, cash and capacity. These are labeled conditional because real demand calibration is insufficient.

The challenger tests whether higher acquisition cost or a supply delay reverses the ranking. An affected strategy becomes unprofitable or cash-infeasible. Strategy proposes a smaller pilot; optimization compares it against launch and defer using the owner's objective. Verification rejects an uncited assertion in the draft and checks the recalculated results. The final package gives a conditional pilot recommendation or abstention with the unresolved response model plainly visible.

The owner may approve a precisely scoped experiment. The system records observations only after the approved study produces real data. A reviewed analysis updates a parameter and triggers a new snapshot. Separately, a configured competitor/source watcher detects a material change; the old decision is marked stale before recomputation. A new bounded investigation produces a versioned decision diff. The prior recommendation remains inspectable as it was known at the time.

Alternate paths are required: missing budget means no billable dispatch; unavailable sources yield coverage limits; contradictory critical facts can yield NEEDS_INPUT; all actions infeasible yields no feasible action; expired budget yields partial results with exhaustion; repeated uncertainty can justify an experiment; failed verification yields no definitive release; a timed-out external mutation yields UNKNOWN pending reconciliation. None becomes fabricated success.

## 19 Business metrics and evaluation definitions

| Metric | Definition and interpretation | Required gate |
|---|---|---|
| Material support coverage | Released material factual assertions with resolved support / all released material factual assertions | 100% in the release suite; assumptions separately labeled and counted |
| Critical unknown detection | Seeded decision-blocking missing inputs correctly blocked / all seeded blockers | All seeded critical blockers found; report misses by severity |
| Contradiction handling | Scoped conflicts preserved/resolved correctly / seeded conflicts | No critical conflict silently overwritten |
| Numerical integrity | Golden outputs within declared tolerance and reconciliations satisfied | Every mandatory golden case passes |
| Feasibility integrity | Released definitive actions satisfying all applicable hard constraints | Zero violations in acceptance suite |
| Revision correctness | Material changes that invalidate all and only applicable descendants | All seeded dependency cases pass, including no-op and unrelated changes |
| Budget/action integrity | Unauthorized charges/actions or duplicated effects under fault injection | Zero control-suite violations; unknown outcomes explicitly reconciled |
| Evidence diversity | Independent-origin/coverage diagnostics for material claims | Correct counts/limitations, not a universal diversity quota |
| Predictive quality | Appropriate error/calibration against actual held-out/prospective outcomes | Domain-specific threshold set before evaluation; no universal claim |
| Decision usefulness | Human assessment of understanding, actionability and stated uncertainty | Predefined review rubric and recorded failures; not self-scoring only |
| Efficiency | Cost, tokens, latency and accepted useful artifacts per case | Report against simpler baselines under comparable scope/access |

Counts of agents, sources, simulations or tokens are not product success metrics by themselves. A system that correctly stops for insufficient evidence can outperform one that produces an unsupported confident recommendation.

## 20 Product quality and service expectations

The full system must support simultaneous tenants/cases, production authentication and permissions, durable work/recovery, understandable stale/degraded states, reproducible calculations, data export/deletion, accessible interaction and operational diagnostics. The SRS defines proposed capacity and recovery test profiles. These are acceptance targets to measure, not promises of present performance.

The product must remain useful when one source or provider fails: preserve accepted evidence, show coverage/freshness limits, permit unrelated work and avoid unsupported definitive conclusions. It must never hide failure behind a newly generated narrative. Changing a model/provider must preserve contracts and trigger affected evaluations.

Operating costs include inference, embeddings, data/source access, storage, compute and monitoring. Free/open-source infrastructure is preferred where appropriate, but a framework license does not make hosted execution free. The user supplies access/authorized spend; the implementation supplies configuration interfaces, adapters and workflow definitions. Manual construction of n8n flows by the user is not a prerequisite.

## 21 Activation dependencies and owner responsibilities

The owner must resolve OD-01 through OD-12 before the affected real-world uses can be activated. These decisions do not shrink the requested system. Implementation can proceed on contracts, deterministic models, fixtures, integration adapters and production controls while live data/credentials are pending. Completion reporting must distinguish software implementation, real integration verification and empirical domain validation.

The product shall guide configuration of a business domain, actual organization data, permitted sources, an LLM/embedding route or local runtime, spend limits, deployment identity/data-region policy, reviewers and allowed external actions. It must validate configuration and display capability state. It cannot silently choose a paid provider, grant source access, assume a lawful collection basis or invent the owner's commercial objective.

## 22 Explicit acceptance of the entire system

Full-system acceptance requires the entire SRS, all 23 executable capabilities, all user stories, complete lifecycle/error paths, production controls and the traceability suite. No “MVP complete” label substitutes for this gate. Build milestones are useful for verification but do not waive the remaining requirements.

The acceptance report shall list implemented capabilities, disabled/unconfigured integrations, unsupported domains, actual test commands/results, measured capacity/recovery, model-validation status and unresolved owner decisions. A requirement cannot be marked complete solely because a schema, prompt, UI mock or architecture diagram exists. Configured integration behavior needs real authorized integration evidence; numerical accuracy needs executable oracles; model predictive validity needs actual outcome evaluation.

## 23 Requirement map and specification boundary

The PRD owns user value, full scope, user journeys and acceptance meaning. SRS-001 through SRS-062 own enforceable behavior. The SRS annexes specify record relationships, component sequences, architecture and all agent contracts. The traceability document maps product requirements to software obligations and acceptance tests. The implementation contract tells an AI how to work without inventing missing evidence, endpoints, permissions or completed features.

This package intentionally leaves business facts, credentials, paid-service choices, legal determinations and empirical model quality dependent on actual owner input/evidence. They are visible unresolved inputs, not gaps that an implementation AI may fill through plausible prose.
