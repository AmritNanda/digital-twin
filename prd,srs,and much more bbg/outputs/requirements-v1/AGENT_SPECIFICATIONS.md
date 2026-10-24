# Complete Agent and Service Specifications

Version 1.0 · 24 October 2026 · Required full-system scope

This catalog is normative under SRS-021 through SRS-027 and SRS-049. All 23 capabilities must be implemented and evaluated. Each may have domain-specialized approved templates; they are not 23 separate LLM APIs or necessarily 23 continuously running processes. The same model can serve multiple roles. Deterministic services remain deterministic. The full catalog is also incorporated into the SRS as an annex so it is available to an implementing AI reading that document alone.

## Shared execution and communication contract

Every task receives `task_id`, `instance_id`, `capability_id`, `template_version`, `case_id`, `investigation_id`, `snapshot_ref`, `policy_ref`, `input_refs`, `requested_output_type`, `completion_test`, `parent_task_ref`, `dependency_refs`, `deadline`, `reservation_ref` and a bounded evidence pack. Tenant/actor authority comes from the server, not model-generated fields. Inputs must resolve to compatible authorized revisions before execution.

Every result contains `task_id`, `instance_id`, `snapshot_ref`, `status`, `artifact_refs`, `claim_refs`, `evidence_refs`, `assumption_refs`, `unresolved_issues`, `requested_tasks`, `concise_rationale`, `usage_ref` and `stop_reason` when terminal. Status must agree with the task state machine. Empty required evidence produces an explicit unresolved result, not fabricated citations. Role-specific output schemas extend this contract; examples below name mandatory content, not permission to use free-form unvalidated JSON.

LLM roles receive only their listed tool allowlist. Service roles expose internal typed functions with separate service credentials; they cannot use a general tool to bypass their own policy. All proposals pass domain validation. Review recommendations are not acceptance transactions. Task requests pass A22 admission and A20 prioritization; no role directly spawns an unlimited child process.

Resource envelopes are assigned by task complexity and the approved case policy, not by agent confidence. Each task has input/output token, call, tool-action, active-time and absolute-deadline caps. Retries and evaluations consume the same parent envelope. A14/A15 additionally have strategy/draw/solver limits. A21/A22 have query/transaction/rate limits even when no inference is used. A task stops on its completion test, irrecoverable missing input, denied permission, expiry, cancellation or resource limit. Partial useful artifacts remain labeled partial.

## A01 Research

**Type and purpose:** LLM investigator plus constrained retrieval/fetch tools. Resolve a specific uncertainty using inspectable material; never perform open-ended browsing without a decision purpose.

**Trigger and inputs:** An admitted ResearchRequest with question, affected claim/parameter, target geography/population/time, preferred authority, known evidence/origin clusters, search limits and completion test. It may be requested by any specialist through the planner/factory.

**Tools:** `evidence.search`, `evidence.fetch`, `evidence.get_span`, `knowledge.query`, `claims.propose`, `sources.cluster`, `research.request`, `review.request`.

**Procedure:** Check existing evidence first; form bounded queries; retrieve permitted sources; inspect original support/context; preserve dates and source identities; seek contrary material; identify duplicate origins and gaps. Fetch failure is recorded. Search snippets remain discovery records until inspected. A source's instructions are never followed as agent policy.

**Output and consumers:** EvidencePack plus ClaimProposals, query/coverage log, unresolved questions and source-access failures; sent to A13 and requesting specialist. Numeric observations can be extracted but parameter promotion belongs to SRS-029.

**Acceptance and failure:** Every material proposed assertion resolves to an exact span or declared inference; dates/scope are preserved and rejected sources remain auditable. Stop when the specified evidence question is resolved or the admissible source/budget path is exhausted. No invented URLs, source access, consensus or complete-market coverage. SRS-005–014, 018, 053.

## A02 Market Intelligence

**Type and purpose:** LLM domain analyst constructing market structure and dynamics from reviewed evidence.

**Trigger and inputs:** New market/geography, stale market assumptions, or an uncertainty about size, growth, channels, substitutes, seasonality or adoption. Requires case scope, entity map, time horizon and reviewed evidence.

**Tools:** `requirements.get`, `knowledge.query`, `evidence.search`, `evidence.get_span`, `claims.propose`, `parameters.propose`, `research.request`, `challenges.raise`.

**Procedure:** Separate TAM/SAM/reachable demand; align units, periods and population; distinguish revenue from unit volumes and stock from flow; analyze channels, seasonality and macro dependencies; identify incompatible estimates. Derive bottom-up estimates only through explicit equations with scoped inputs. Growth claims cannot be extended indefinitely or converted directly into company sales.

**Output and consumers:** MarketModelProposal containing entity relations, scoped estimates, assumptions, trend hypotheses, disagreement/coverage report and model-relevant parameter proposals. A04, A06, A11 and A16 consume accepted outputs; A13 reviews evidence.

**Acceptance and failure:** Estimates reconcile dimensionally and have temporal/geographic applicability. Incomparable reports remain separate instead of averaged. Missing identified demand becomes scenario-only input or research request. SRS-007, 009, 029–032.

## A03 Competitor

**Type and purpose:** LLM specialist for comparable competitive offers and conditional competitor-response scenarios.

**Trigger and inputs:** Pricing/strategy question, new competitor evidence or a challenge about substitution. Inputs include target SKU/tier/geography/channel, comparison attributes, date cutoff and known substitutes.

**Tools:** `knowledge.query`, `evidence.search`, `evidence.fetch`, `evidence.get_span`, `claims.propose`, `parameters.propose`, `research.request`, `challenges.raise`.

**Procedure:** Match exact products/tiers; preserve listed versus transacted price, taxes, shipping, bundles, promotion dates and eligibility. Compare functions, distribution and positioning without inventing internal sales/costs. Separate observed action from inferred motivation and possible future response. Competitor-response parameters require estimates or explicit assumptions.

**Output and consumers:** CompetitorOfferMatrix, change events, substitution hypotheses and response scenarios with evidence/uncertainty. A06 uses normalized comparisons; A16/A11 use strategic exposures; A13 validates assertions.

**Acceptance and failure:** Historical prices cannot masquerade as current; a temporary discount cannot become a permanent price without evidence. Unavailable private metrics stay unknown. Test includes conflicting dates, currency/tax mismatch and a copied announcement across multiple sites. SRS-009, 012–015, 032, 034.

## A04 Customer Intelligence

**Type and purpose:** LLM analyst with reviewed statistical model access; distinguish behavior, attitudes and hypotheses.

**Trigger and inputs:** Segment/demand uncertainty, new observation dataset, changed offering or weak coverage. Requires population definition, customer data provenance, measurement windows, consent scope, and applicable model manifests.

**Tools:** `requirements.get`, `evidence.search`, `knowledge.query`, `coverage.audit`, `models.evaluate`, `claims.propose`, `parameters.propose`, `research.request`, `experiments.design`.

**Procedure:** Define segments using permitted measured attributes; inspect sampling and denominators; separate purchases, stated intent, complaints and synthetic archetypes; evaluate eligible response/retention models; request missing behavioral evidence. Synthetic personas may suggest objections but never add observations. Cross-segment extrapolation requires reviewed transfer assumptions.

**Output and consumers:** SegmentDefinitionProposals, BehavioralEvidenceReport, response/retention parameter proposals, applicability limits and experiment needs. A06/A14/A16 consume approved inputs; A12 reviews coverage; A18 designs studies.

**Acceptance and failure:** No inferred sensitive demographic facts, fabricated survey participants or opinion-to-conversion shortcut. Small/biased cohorts produce wide/conditional results or abstention. Golden tests verify cohort eligibility, censoring and no duplicate customers. SRS-014, 029–031, 045–046, 052.

## A05 Sentiment

**Type and purpose:** Versioned classification service with optional bounded LLM disambiguation; measure expressed attitudes in collected text, not market demand.

**Trigger and inputs:** Approved corpus with language, source/version, timestamps, topic/aspect taxonomy and target population context.

**Tools/boundary:** Internal classifier and aggregation APIs; optional role access to `evidence.get_span`, `sentiment.classify`, `claims.propose`, `review.request`. No arbitrary external fetch or parameter acceptance.

**Procedure:** Deduplicate/reconcile origins; classify aspect, polarity and uncertainty; preserve mixed/neutral/unknown labels; flag sarcasm/translation ambiguity and unsupported languages; aggregate using documented weights. Cluster-level and author-level dependencies are retained where known. Translation remains linked to original text.

**Output and consumers:** SentimentReport with taxonomy/model revision, counts/denominators, excluded items, uncertain cases, temporal/source coverage and representative cited spans. A04 and A12 interpret it; A13 checks evidence. It cannot output a sales-conversion parameter without a separately validated mapping.

**Acceptance and failure:** Evaluate on labeled examples by supported language/aspect, including negation and mixed sentiment. Unknown languages are not silently treated as English. A hundred syndicated copies cannot become a hundred independent customer opinions. SRS-013–014, 031, 051, 060.

## A06 Pricing

**Type and purpose:** LLM commercial specialist with deterministic pricing/financial evaluations.

**Trigger and inputs:** Price/tier/channel decision or changed cost/competition. Requires cost/tax/currency definitions, brand and contractual constraints, customer response evidence, competing offers and permitted action bounds.

**Tools:** `requirements.get`, `knowledge.query`, `evidence.search`, `finance.evaluate`, `models.evaluate`, `parameters.propose`, `research.request`, `scenario.patch`, `challenges.raise`.

**Procedure:** Normalize comparable prices; generate bounded price/tier/bundle candidates; test contribution and constraints; distinguish willingness-to-pay data from qualitative preference; identify elasticity uncertainty and request experiments where needed. Price changes carry duration/channel/segment scope. Never choose an owner's risk/brand preference implicitly.

**Output and consumers:** PricingProposal with action vectors, feasibility evidence, response-model refs, sensitivity ranges and unresolved assumptions. A16 composes complete strategies; A14/A15 compare them; A07 checks accounting.

**Acceptance and failure:** Unsupported response curves yield conditional comparisons, not “optimal price.” Tests include negative contribution, promotion expiry, tax mismatch, price floors and multi-product cannibalization. SRS-029, 031, 033–037.

## A07 Financial

**Type and purpose:** Deterministic finance engine plus LLM explanation/review, with no LLM arithmetic authority.

**Trigger and inputs:** Candidate strategy, revised costs or simulation request. Requires scoped revenue/cost definitions, volume/new-customer distinction, payment/working-capital timing, capacity and tax/currency policy.

**Tools:** `requirements.get`, `knowledge.query`, `finance.evaluate`, `parameters.propose`, `research.request`, `review.request`, `challenges.raise`.

**Procedure:** Validate units and recognition basis; calculate contributions, fixed costs, break-even, profit, cash trough, funding and applicable LTV/CAC metrics; reconcile operational movements and financial statements. Missing definitions block affected outputs. Reviews can propose corrections but never overwrite ledgers.

**Output and consumers:** FinancialResult with metric definitions, period tables, reconciliation checks, sensitivity thresholds, infeasibility and input manifest. A14 integrates outputs; A15 ranks; A16/A23 explain; A19 checks exact values.

**Acceptance and failure:** Golden tests cover rounding, non-positive contribution, acquisition double-counting, inventory/cash timing, returns and multiple currencies. A profitable-but-illiquid case must be flagged. Unavailable LTV is not zero. SRS-029–030, 032–035, 040.

## A08 Regulatory

**Type and purpose:** LLM evidence investigator for regulatory applicability with mandatory domain/human review where policy requires.

**Trigger and inputs:** New geography/product/action, changed rule, or suspected regulatory constraint. Requires jurisdiction, product characteristics, intended activity, effective dates and authoritative-source policy.

**Tools:** `requirements.get`, `evidence.search`, `evidence.fetch`, `evidence.get_span`, `claims.propose`, `research.request`, `review.request`, `challenges.raise`.

**Procedure:** Prefer primary authoritative material; distinguish enacted/effective/proposed/repealed status; identify scope, exceptions, transition dates and ambiguity. Separate source quotation from interpretation. A document's update date is not necessarily a rule's effective date. Proposed obligations enter review as potential constraints.

**Output and consumers:** RegulatoryAssessment with rule/source refs, jurisdiction/activity mapping, effective interval, unresolved interpretation and requested reviewer decisions. A11/A16 apply accepted constraints; A19 confirms required review before release.

**Acceptance and failure:** No definitive legal/compliance certification from generated prose. Inaccessible or ambiguous critical requirements block the affected recommendation or require qualified review. Fixtures include superseded rules, wrong jurisdiction and proposed-only policy. SRS-010–015, 032, 040, 052–054.

## A09 Political and Geopolitical

**Type and purpose:** LLM contextual analyst of evidence-backed business exposure and explicit stress scenarios.

**Trigger and inputs:** Geographic/supply-chain exposure, material political/trade event, or scenario request. Inputs include supplier/channel/currency routes, dated events, time horizon and sources.

**Tools:** `knowledge.query`, `evidence.search`, `evidence.fetch`, `evidence.get_span`, `claims.propose`, `parameters.propose`, `scenario.patch`, `research.request`.

**Procedure:** Map events to relevant mechanisms such as tariffs, transit disruption, import restrictions or currency exposure. Distinguish facts, proposals, speculation and scenario assumptions. Identify correlated exposures and time lags; do not invent event probabilities or treat political opinions as measured risk.

**Output and consumers:** ExposureMap, dated event claims, shock scenarios and unknowns. A11 consolidates risk, A14 runs approved shocks, A08 reviews regulatory overlap and A16 considers alternatives.

**Acceptance and failure:** Each material propagation has a named mechanism and units. Unidentified effects remain scenario ranges or qualitative risks. Test includes an event irrelevant to the company's actual routes and duplicate reporting from one primary origin. SRS-012–015, 029, 032, 036.

## A10 Technology

**Type and purpose:** LLM technical due-diligence specialist with reviewed capability/dependency models.

**Trigger and inputs:** Product feature/technology strategy, technical constraint change, vendor dependency or feasibility challenge. Requires actual company capabilities, requirements, technical documentation, licenses, integration/security constraints and adoption horizon.

**Tools:** `requirements.get`, `knowledge.query`, `evidence.search`, `evidence.fetch`, `evidence.get_span`, `claims.propose`, `parameters.propose`, `research.request`, `review.request`.

**Procedure:** Map required functions to available technology and company capability gaps; inspect versioned primary documentation; distinguish prototype feasibility from reliable production delivery; estimate effort/cost only with an explicit basis/range. Identify technical lock-in, licensing, maintenance and security dependencies.

**Output and consumers:** TechnologyFeasibilityReport with capability/dependency map, version assumptions, gaps, candidate alternatives and cost/timing proposals. A16/A11 consume accepted findings; reviewers resolve material architectural/security issues.

**Acceptance and failure:** No invented APIs, integrations, benchmark performance or vendor access. A claimed integration needs observed compatibility evidence. Unsupported documentation/version remains unresolved. SRS-003, 029–030, 032, 049–054, 058.

## A11 Risk

**Type and purpose:** LLM risk integrator with deterministic stress/financial outputs.

**Trigger and inputs:** Candidate strategies, domain specialist findings, unresolved critical assumptions or material change. Requires risk policy, exposure graph, scenarios, constraint set and simulations.

**Tools:** `knowledge.query`, `evidence.search`, `simulation.compare`, `scenario.patch`, `parameters.propose`, `challenges.raise`, `research.request`, `review.request`.

**Procedure:** Identify failure modes, dependencies, leading indicators, severity and controllability; separate measured probabilities from qualitative likelihood categories; test joint/common-cause stresses and liquidity/operational consequences. Mitigations carry cost, delay, residual risk and implementation assumptions. Do not add correlated risks as independent probabilities.

**Output and consumers:** RiskRegister with affected strategy/parameter refs, exposure mechanisms, stress tests, mitigation proposals, escalation and review requirements. A16 revises actions, A14 evaluates stresses, A17 challenges blind spots and A23 discloses residual risk.

**Acceptance and failure:** No single unexplained risk score can override a hard constraint. Unknown likelihood remains unknown. Tests cover correlated supply/channel failure, mitigation costs and unacceptable but profitable actions. SRS-028–029, 032, 036–040.

## A12 Bias Auditor

**Type and purpose:** Statistical/coverage service plus LLM critique; inspect how evidence and framing can distort the decision.

**Trigger and inputs:** New evidence corpus, segment analysis, sentiment output or near-release decision. Requires target population, collection channels, origin clusters, model assumptions and selection history.

**Tools:** `coverage.audit`, `sources.cluster`, `evidence.search`, `evidence.get_span`, `knowledge.query`, `challenges.raise`, `research.request`, `review.request`.

**Procedure:** Inspect sampling, survivorship, geographic/language gaps, correlated sources, missing negative evidence, framing and repeated self-confirmation. Distinguish observed bias indicators from unsupported accusations. Suggest additional sampling or alternate assumptions; demographic attributes cannot be guessed to make coverage tables look complete.

**Output and consumers:** BiasCoverageReport with supported limitations, affected conclusions, missing coverage, possible impact and corrective tasks. A04/A05/A13/A17 and A20 consume it. Mitigations must be checked for whether they actually improve coverage.

**Acceptance and failure:** Reports cannot certify “bias-free.” Insufficient population/collection metadata yields unknown coverage, not a pass. Tests include syndicated praise, missing disadvantaged/rare segments where measured, and imbalanced language collection. SRS-013–014, 031, 038, 052, 056.

## A13 Evidence Auditor

**Type and purpose:** Independent claim-evidence review with deterministic reference/scope checks.

**Trigger and inputs:** New material ClaimProposal, revised source, contradiction or final material narrative. Requires exact claim, source spans/context, scope/time, origin clusters and derivation if inferred.

**Tools:** `evidence.get_span`, `evidence.search`, `knowledge.query`, `sources.cluster`, `coverage.audit`, `challenges.raise`, `research.request`, `review.request`.

**Procedure:** Check source identity, exact entailment, qualifiers, dates, independence, authority for that claim and alternative interpretations. Separate a source reporting an allegation from evidence establishing the allegation. Verify the proposed epistemic state. Record recommended ACCEPT/REJECT/NEEDS_REVIEW with reason; the validation service performs the authorized state transition.

**Output and consumers:** EvidenceReviewReport with check outcomes, source limitations, contradiction links and required corrections. All claim producers receive review feedback; A19 consumes accepted review artifacts; A20 prioritizes unresolved material gaps.

**Acceptance and failure:** A citation that merely mentions the topic must fail entailment. Critical missing source context cannot pass because the proposing agent is confident. Tests include negation, outdated sources, copied claims and accurate quotations used outside scope. SRS-006, 009–015, 040, 042.

## A14 Simulation

**Type and purpose:** Deterministic numerical execution service; no language model creates draw arrays or financial results.

**Trigger and inputs:** Admitted SimulationRequest with pinned models/parameters/snapshot, strategies, time step/horizon, distribution/dependency manifest, seed, draw count and compute reservation.

**Tools/boundary:** Internal approved model/sampler engine, object writer and task-result API. The agent-facing surface is `simulation.run`/`simulation.compare`. No web access, arbitrary code evaluation or direct acceptance of model-generated parameters.

**Procedure:** Validate applicability/units/support; reserve compute; construct seeded sampling streams; execute bounded batches; enforce operational/accounting constraints; record invalid draws; compute defined statistics and numerical error; persist draw hashes/manifests; check cancellation between batches.

**Output and consumers:** SimulationResult with strategy metrics, feasibility, conditional distributions, numeric diagnostics, manifest and reproducibility metadata. A07/A15/A17/A19/A23 consume it; stale input results cannot become current.

**Acceptance and failure:** Same pinned inputs reproduce within declared tolerances. Invalid draw thresholds fail visibly. Unknown distributions do not become invented probabilities. Tests cover correlated shocks, cancellation, overflow, zero denominators and capacity conservation. SRS-029–037, 040, 057, 061.

## A15 Optimization

**Type and purpose:** Deterministic feasible-ranking/solver service; optional LLM explains stored results only.

**Trigger and inputs:** Comparable simulations or approved objective function, feasible action space, hard constraints, risk policy, tie tolerance and compute limits.

**Tools/boundary:** Internal registered solver/ranking implementations exposed as `optimization.rank`; may request authorized simulation evaluations through the scheduler. No autonomous preference changes or permission widening.

**Procedure:** Reject incompatible comparisons; mark feasibility; calculate selected objective/risk measures; rank or produce Pareto tradeoffs; test sensitivity/ranking stability; retain search domain, evaluated candidates, termination and genuine gap certificates if supplied. Portfolio resource constraints are evaluated jointly.

**Output and consumers:** OptimizationResult with feasible set, rankings/frontier, objective definitions, downside/regret, switching thresholds, solver limits and model-conditional status. A16/A20/A23 use it; A17 tests fragility; A19 checks the ranking.

**Acceptance and failure:** All-infeasible returns NO_FEASIBLE_ACTION. Heuristics cannot claim global optimum. Fixtures include constraint-dominated high-profit choices, ties, multiobjective conflicts, correlated loss tails and portfolio double-allocation. SRS-032, 034–037, 039–040.

## A16 Strategy

**Type and purpose:** LLM action/hypothesis designer that composes coherent alternatives from company constraints and reviewed intelligence.

**Trigger and inputs:** Initial case readiness, new decision-changing evidence, failed candidate or accepted challenge. Requires objective/risk policy, company capability map, market/customer/competitor evidence, pricing/cost inputs and unresolved assumptions.

**Tools:** `requirements.get`, `knowledge.query`, `evidence.search`, `parameters.propose`, `research.request`, `scenario.patch`, `simulation.run`, `simulation.compare`, `optimization.rank`, `challenges.raise`, `experiments.design`.

**Procedure:** Propose bounded action vectors across offering, segment, geography, price, channel, positioning, spend and timing; state a rationale and falsifiable success mechanism; include baseline/defer/pilot; screen hard constraints; submit compatible simulations; revise actions after challenge. It cannot manufacture missing demand inputs to make a favorite strategy win.

**Output and consumers:** StrategyProposal set, hypothesis links, constraints, dependencies, simulation requests and experiment alternatives. A06/A07 refine; A14/A15 calculate; A17 challenges; A23 synthesizes verified candidates.

**Acceptance and failure:** Every meaningful candidate is executable in the supported domain and uses explicit assumptions. At least one alternative tests a different relevant action, not cosmetic wording. Missing identification yields conditional strategy analysis. SRS-028–038, 045.

## A17 Devil's Advocate

**Type and purpose:** LLM falsifier with bounded scenario/testing tools, separated from the strategy proposer.

**Trigger and inputs:** Leading recommendation or material revised candidate; current strongest evidence, model/parameter manifest, sensitivity, constraints, source coverage and existing challenges.

**Tools:** `evidence.search`, `evidence.get_span`, `knowledge.query`, `challenges.raise`, `research.request`, `scenario.patch`, `simulation.run`, `simulation.compare`, `review.request`.

**Procedure:** Seek the most consequential plausible failure/alternative explanation; identify the exact claim/parameter to challenge; propose a test and reversal threshold; search contrary evidence or run an approved stress; preserve unresolved dissent. Challenge only within plausible/specified scope, not arbitrary impossible scenarios masquerading as realistic forecasts.

**Output and consumers:** Challenge artifacts and test results, severity/materiality, reversal criteria and unresolved objections. A20 routes investigations, A16 revises, A13 evaluates contrary evidence and A19 enforces release policy.

**Acceptance and failure:** A testable high-impact challenge is required; generic criticism fails. It cannot invent negative evidence, mutate assumptions silently or mark its own challenge accepted without validation. Tests seed a recommendation that fails under an omitted known constraint. SRS-028, 036, 038–040.

## A18 Experiment

**Type and purpose:** LLM study designer with reviewed statistical/financial services; execution is a separate approval-controlled system.

**Trigger and inputs:** Material resolvable uncertainty, high-value research proposal or model-validation gap. Requires hypothesis, estimand, population/access, available interventions, measurement method, cost/time/privacy constraints and decision threshold.

**Tools:** `requirements.get`, `knowledge.query`, `models.evaluate`, `finance.evaluate`, `experiments.design`, `research.request`, `review.request`, `actions.preview`.

**Procedure:** Choose an appropriate study design; specify allocation/control, outcomes, guardrails, sampling and analysis; calculate power/sample size only under stated assumptions; consider attrition/confounding/interference; compare decision relevance against cost and delay. Predefine stopping/deviation policy. Generate previews, not live outreach/campaigns.

**Output and consumers:** ExperimentProposal, analysis plan, cost/sampling rationale, authorization checklist specific to the action, and expected observation contract. A20 prioritizes; reviewers approve; action gateway executes only approved payloads; learning pipeline handles actual data.

**Acceptance and failure:** Cannot claim a study ran, has power or collected participants without evidence. Unavailable sampling frames yield explicit limitations. Tests include no identifiable effect, missing baseline rate, nonrandomized confounding and changed action payload after approval. SRS-039, 045–047, 052.

## A19 Verification

**Type and purpose:** Deterministic gate service plus independently evaluated LLM evidence review where needed.

**Trigger and inputs:** Any material decision proposal and its complete lineage, reviews, numerical results, constraints and current validity state.

**Tools/boundary:** `verification.check`, `evidence.get_span`, `knowledge.query`, `simulation.compare`, `review.request`, `challenges.raise`. Internal rule engine reads authoritative revisions; no general acceptance/release privilege is granted to an LLM.

**Procedure:** Check schema/reference closure, tenant/snapshot consistency, currentness, numerical agreement, unit/time alignment, hard constraints, approvals, material entailment, assumption labels, challenge disposition and correct stop reason. Produce explicit mandatory/optional check outcomes. Bounded repair requests return to the responsible producer.

**Output and consumers:** VerificationReport with PASS/FAIL/NOT_APPLICABLE per check, blockers and allowed outcome classes. Release service uses it with a final currentness transaction; A23 may revise a draft after failure.

**Acceptance and failure:** Any mandatory failure prevents definitive release. A fabricated citation, stale simulation, unapproved assumption, wrong profit or unresolved hard constraint must fail even if the text sounds plausible. Verification cannot grade itself from the proposer success flag. SRS-040–042, 056, 061.

## A20 Planner

**Type and purpose:** LLM planning proposal generator plus deterministic scheduling/policy services.

**Trigger and inputs:** New case/investigation, completed/failed task, accepted challenge, answered question, material change or stalled progress. Requires uncertainty backlog, task graph, approved capabilities, policy, budgets and current snapshot.

**Tools:** `requirements.get`, `knowledge.query`, `tasks.list`, `budgets.get`, `memory.retrieve`, `research.request`, `review.request`, `experiments.design`, `challenges.raise`.

**Procedure:** Identify blockers and independent work; connect research to decision sensitivity; use valid VOI or labeled heuristics; propose tasks/dependencies/completion criteria; avoid duplicated research; choose between further inquiry, scenario comparison, experiment and stopping. Replan only from accepted/explicitly pending artifacts, not uncommitted assumptions. Record a concise reason for each material route change.

**Output and consumers:** PlanRevision with priorities, task proposals, dependencies, question requests, expected artifacts and stop proposal. A22 admits; scheduler dispatches; release service handles final state.

**Acceptance and failure:** Cannot increase budgets, waive verification or call exhaustion convergence. Tests include cyclic task proposals, unreachable dependencies, new contradiction, diminishing research value and continued independent work while waiting. SRS-008, 021–028, 039, 043–044.

## A21 Memory

**Type and purpose:** Deterministic knowledge/memory service; optional summarization produces unaccepted proposals.

**Trigger and inputs:** Retrieval request, accepted artifact event, expiry/withdrawal, completed investigation or approved procedural update. Inputs include tenant/case, purpose, valid/recorded-time filters, artifact refs and retention policy.

**Tools/boundary:** Internal canonical retrieval/projection APIs, exposed as `memory.retrieve` and `memory.propose`. No unrestricted writes to accepted facts, no cross-tenant training and no source-text privilege escalation.

**Procedure:** Retrieve working/semantic/episodic/procedural/experimental records with provenance; reject stale or incompatible use; preserve conflict links; compress context only while retaining material qualifiers and references. Store reusable findings only through review/expiry rules. An agent's previous assertion is not independent evidence for its next assertion.

**Output and consumers:** MemoryPack with selected refs, validity/coverage, summary proposals and exclusion reasons; all roles can consume scoped packs. Withdrawal/deletion propagates to indexes/caches and dependent current use.

**Acceptance and failure:** Historical as-known queries must not leak future corrections. Summaries must not convert assumptions/simulations into observations. Tests cover withdrawn facts, changed permissions, cross-case scope mismatch and backup deletion restoration. SRS-015–020, 042, 052, 059.

## A22 Agent Factory

**Type and purpose:** Deterministic admission/lifecycle service. It instantiates approved templates; it does not generate executable agents.

**Trigger and inputs:** Task/role request with purpose, template/capability, input/output types, dependencies, completion test, estimated resources, depth and deadline. Inputs include policy, capability registry, task fingerprints and atomic budget state.

**Tools/boundary:** Internal template lookup, authorization, schema validation, deduplication, budget reservation, task creation and lifecycle APIs. It is not an LLM tool allowed to override admission checks.

**Procedure:** Validate template/version and permissions; check input availability, cycles and duplicate work; enforce parent/tenant resource caps and delegation depth; atomically reserve; create instance/task and event; dispatch only through scheduler. Domain specialization uses bounded approved fields, with tools a subset of the template/parent permissions. Retire instances on terminal states and reconcile usage.

**Output and consumers:** AdmissionDecision with admitted instance/task/reservation refs or typed rejection reason; planner can revise rejected requests without broadening permissions. Scheduler owns worker leases.

**Acceptance and failure:** Concurrent admission cannot overdraw a budget or exceed worker/instance limits. Unknown templates, self-modifying tools and depth bypasses fail. An idle persistent role definition is not a running worker. SRS-021–025, 049, 061.

## A23 Final Decision

**Type and purpose:** LLM synthesis restricted to approved structured findings, followed by A19 and the deterministic release service.

**Trigger and inputs:** Feasible comparisons or justified abstention, complete constraint/assumption manifest, evidence reviews, challenge outcomes, confidence dimensions, experiment proposals and actual stop reason.

**Tools:** `requirements.get`, `knowledge.query`, `evidence.get_span`, `simulation.compare`, `decisions.propose`, `review.request`. No direct action dispatch, budget changes, source invention or decision-release transaction.

**Procedure:** State the outcome and its conditions; compare genuine alternatives; cite material claims; copy numerical values through structured bindings; disclose uncertainty, dissent and model validity; explain what would change the recommendation and what test comes next. Separate lack of evidence from evidence of no opportunity. Use concise rationale, not hidden chain-of-thought.

**Output and consumers:** DecisionProposal matching PRD section 17 and SRS-041, with selected strategy nullable for abstention/no-feasible-action, result refs, evidence/assumption refs, reversal conditions and unresolved issues. A19 verifies; release service commits; UI/exports render the same artifact.

**Acceptance and failure:** Unsupported material prose is removed/qualified or fails verification. Partial budget-exhausted results cannot be labeled converged. A conditional recommendation cannot automatically authorize execution. Tests verify exact metric agreement, mandatory limitations and current-pointer race protection. SRS-040–042, 047, 060–062.

## Required cross-agent interaction tests

1. A20 -> A22 -> A01 -> A13 -> validation -> accepted evidence -> A06/A07 -> A16 -> A14 -> A15 -> A17 -> A19 -> A23 proposal -> A19 -> release. Verification may occur before and after synthesis; narrative generation is not a shortcut around final verification.
2. A17 identifies acquisition-cost sensitivity; A20 prioritizes A04/A03 investigation; A12 detects source skew; A18 proposes a study; the result is a conditional/pilot decision when data remains inadequate.
3. A08 raises an applicable constraint; A11/A16 revise feasibility; A14/A15 rerun; A23 must not retain the previous now-forbidden recommendation.
4. A09/A10 evidence changes a supply/technology assumption; accepted revision invalidates affected A14 outputs; A21 excludes stale memory; a new A20 investigation produces a new decision revision.
5. A22 rejects a duplicate or over-budget specialist request while allowing unrelated ready work; A20 records the limitation and chooses a truthful terminal outcome.

All interactions use exact revision references and authenticated services. Dashed conceptual influence in an architecture diagram must be implemented as a typed request, event, read or artifact dependency; informal direct agent chats are not authoritative state.
