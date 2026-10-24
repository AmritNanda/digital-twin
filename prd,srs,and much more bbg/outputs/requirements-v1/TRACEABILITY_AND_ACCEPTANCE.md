# Full-System Traceability and Acceptance

Version 1.0 · Required future implementation tests · No software test results are claimed here

Each AT item below is a test family with positive, negative, boundary and recovery cases. Implementations must create executable tests/evaluations and retain actual results. Documentation/schema checks performed while authoring this package are not implementation acceptance tests.

## Product-to-software traceability

| Product requirement | Software requirements | Main capabilities | Acceptance families |
|---|---|---|---|
| PRD-01 Intake | SRS-005–008, 016, 048 | A01, A13, A20 | AT-001–004 |
| PRD-02 Unknowns/conflicts | SRS-007–011, 027–029 | A13, A20, A19 | AT-003–006, 018 |
| PRD-03 Living twin | SRS-015–017, 032, 042–044 | A02–04, A21 | AT-007–010, 033–035 |
| PRD-04 Retrieval/memory | SRS-018–019, 051–052, 059 | A01, A21 | AT-009–012, 040 |
| PRD-05 Investigation | SRS-012–014, 024, 043, 049 | A01–03, A08–10 | AT-011–014, 037 |
| PRD-06 Evidence/bias | SRS-011–014, 029, 040 | A05, A12, A13 | AT-005–006, 011–013, 020 |
| PRD-07 Agent network | SRS-020–022, 025–028 | A20 and all roles | AT-015–019, 044 |
| PRD-08 Factory | SRS-021–024, 049, 061 | A22 | AT-016–017, 042 |
| PRD-09 Customers/demand | SRS-029–031, 045–046 | A04–05, A18 | AT-020–022, 036 |
| PRD-10 Economics/operations | SRS-030, 032–033 | A07, A14 | AT-023–025, 046 |
| PRD-11 Strategy/pricing | SRS-028, 034, 037 | A03, A06, A16 | AT-022, 026, 029 |
| PRD-12 Simulation | SRS-030, 035, 037 | A14–15 | AT-025–027, 029 |
| PRD-13 Counterfactuals | SRS-036, 042 | A14, A17 | AT-028, 033 |
| PRD-14 Falsification | SRS-028, 038, 040 | A11–13, A17 | AT-030–032 |
| PRD-15 VOI/convergence | SRS-024, 039 | A18, A20, A22 | AT-017, 019, 031 |
| PRD-16 Verified output | SRS-040–042, 060 | A19, A23 | AT-032–034, 043 |
| PRD-17 Monitoring | SRS-020, 043–044, 061 | A01–03, A20–21 | AT-014–015, 034–035 |
| PRD-18 Experiments/learning | SRS-045–046 | A04, A18, A21 | AT-036, 045 |
| PRD-19 Safety/ownership | SRS-004, 010, 047, 052–054, 059 | A19, A22 + gateways | AT-006, 037–042, 047 |
| PRD-20 Operations/portability | SRS-048–051, 055–062 | All plus services | AT-037–050 |

## Acceptance families: inputs, action and oracle

| ID | Given / when | Required observable result |
|---|---|---|
| AT-001 | Supported text, CSV, DOCX, XLSX, PPTX, text PDF and scanned PDF/image fixtures are imported | Parsed artifacts preserve meaningful structure and exact page/slide/sheet/text anchors; OCR ambiguity is visible; original hashes resolve |
| AT-002 | Malformed, oversized, encrypted, macro-containing and partially parsed files arrive | No embedded code runs; bounded resources; actionable unsupported/failure/partial status; no invented accepted contents |
| AT-003 | Cost, revenue period, currency or objective is missing | Correct critical fields become UNKNOWN; dependent definitive calculation/recommendation is blocked; independent work proceeds |
| AT-004 | User corrects an extracted value and its effective date | New revision, actor provenance and old source/extraction retained; affected dependencies become stale |
| AT-005 | Two sources conflict, and another apparent conflict differs only by date/tax scope | True conflict persists with both refs; scope mismatch is explained; no arbitrary averaging/last-write-wins |
| AT-006 | A reviewer lacks category authority or approval payload changes after approval | Review/action rejected; exact artifact revision/hash required; no timeout/default selection becomes consent |
| AT-007 | Historical query precedes a later correction of an earlier-period fact | As-known query excludes the future correction; valid-time query and recorded-time query differ correctly |
| AT-008 | A graph projector crashes/replays events | Canonical facts remain correct; idempotent projection catches up with a visible watermark; rebuild matches expected edges |
| AT-009 | Hybrid retrieval includes relevant semantic, lexical, graph and contradictory evidence | EvidencePack resolves exact authorized spans; configured bounds hold; raw scores are not incorrectly added |
| AT-010 | Same entity has ambiguous aliases or differently scoped offers | No unsupported identity merge; separate offers/periods retained; reviewed merge preserves audit and references |
| AT-011 | Ten URLs repeat one primary report plus one independent source | Origin count is two when justified, not eleven; summaries are not new corroboration; uncertainty about origins stays explicit |
| AT-012 | A claim cites a topically related but non-entailing span, or removes a qualifier | Evidence review fails/requests revision; no accepted material statement based on mere topic overlap |
| AT-013 | Biased-language/source sample, mixed sentiment, sarcasm and unknown demographics | Coverage gaps and uncertainty reported; no fabricated demographic coverage or sentiment-to-demand mapping |
| AT-014 | Connector times out, rate-limits, denies access or returns unchanged content | Bounded retry/backoff; visible degraded freshness; no fabricated data or unauthorized collection fallback; unchanged source avoids needless LLM work |
| AT-015 | Canonical transaction commits, process crashes before event publication/ack, then replays | Accepted event survives; consumers deduplicate; no duplicate accepted revision/action; ordering respects aggregate revision |
| AT-016 | Multiple requests concurrently admit specialists with duplicates/depth/tool violations | Unique admitted work where required; atomic caps respected; unauthorized template/tool/depth rejected with reasons |
| AT-017 | Concurrent calls exhaust currency/token/call/time budgets or billing outcome is unknown | No new dispatch beyond reservation; retries count; unknown charges stay reserved; terminal reason is exhaustion, not convergence |
| AT-018 | Durable human interrupt resumes after process restart and then expires | Exact question/checkpoint binding; new answer creates/rebases snapshot; no duplicate pre-interrupt effect; expired run requires new envelope |
| AT-019 | A completed task reveals a critical new uncertainty; another task waits for input | Planner revises bounded graph and permits independent work; unmet dependencies never execute; stable/exhausted outcomes distinguished |
| AT-020 | LLM proposes conversion from a favorable quote or synthetic survey | Parameter promotion rejects measured/estimated status; only explicitly authorized scenario assumption or unresolved state allowed |
| AT-021 | Cohort data includes repeat buyers, censored observations and duplicates | Correct eligibility/denominators; no acquisition double-counting; measured versus hypothetical observations separated |
| AT-022 | Price response is unidentified or actions exceed approved domain ranges | Conditional scenario comparison or MODEL_NOT_IDENTIFIED; no empirical optimal-price claim or silent clamping |
| AT-023 | Golden unit-economics fixture below is evaluated | Exact contribution/profit/break-even and stress outputs within the declared rounding tolerance |
| AT-024 | Inventory paid before sales, returns/refunds and fixed costs create a cash shortfall | Profit/cash differ correctly; inventory balances reconcile; positive profit cannot override liquidity constraint |
| AT-025 | Pinned model/seed/environment run repeats and invalid draws are introduced | Reproducibility within tolerance; invalid draws reported/fail above threshold, never silently discarded |
| AT-026 | Candidate A maximizes profit but violates hard capacity/brand constraint | A marked infeasible and not recommended; suitable baseline/defer considered |
| AT-027 | Larger draw count, correlated inputs and alternative model structures are tested | Monte Carlo error decreases as expected on controlled fixture; no claim empirical certainty increased; dependency sampler respected |
| AT-028 | User edits acquisition cost and requests a causal conclusion without identified model | Child snapshot preserves base; correct descendants recalculate; sensitivity labeled; causal claim rejected |
| AT-029 | Multiobjective ties, all-infeasible set and heuristic solver termination occur | Explicit tradeoff/tie/no-feasible outcome; no invented utility weights/global-optimum certificate |
| AT-030 | A leading action fails under an omitted known supply/cost condition | Challenger creates concrete test/refutation; affected inputs rerun; unresolved material objection cannot vanish |
| AT-031 | Research has no coherent likelihood model or no remaining value within budget | Heuristic labeled as such; no fabricated EVSI; stop/experiment selection follows configured criterion |
| AT-032 | Draft contains invented source, wrong profit, missing assumption or fake convergence | Mandatory verification fails and definitive release is blocked; bounded repair or qualified abstention is explicit |
| AT-033 | Decision lineage includes a missing ref, incompatible snapshot or dependency cycle | Closure/currentness/acyclic checks fail; no release; valid lineage reaches original permitted sources and computations |
| AT-034 | Material accepted parameter change arrives while two release workers race | Existing decision marked stale; one current new version at most; losing stale release rejected by revision check |
| AT-035 | Duplicate, unrelated, late and burst watcher events arrive | No unnecessary unrelated reruns; causes retained; current version never regresses; tenant quotas bound work |
| AT-036 | Proposed study lacks sampling assumptions; later real/fixture observations arrive | No invented power; plans and execution separate; real analysis uses eligible actual data only; synthetic data cannot update real calibration |
| AT-037 | Provider rejects schema/changes model, MCP server returns invalid payload, or optional n8n delivery repeats | Typed adapter failure/approved bounded fallback; no permission widening; duplicate requests idempotent; native scheduler remains usable |
| AT-038 | Tenant B guesses Tenant A IDs across API/search/graph/cache/objects/SSE/export | No data or existence leakage; server scope enforced across every surface |
| AT-039 | Uploaded source instructs model to exfiltrate secrets, raise budget or accept false facts | Policy/gateways prevent effects and unauthorized state changes; contaminated lineage reviewed before release |
| AT-040 | Withdrawal/deletion affects text, vectors, graph, cache and backup restore | Current retrieval excludes removed data; lineage shows unavailable support; restore reapplies tombstones |
| AT-041 | Redirect points to internal metadata, archive traversal or malicious XML is supplied | Fetch/parser sandbox blocks access/execution; safe diagnostics and bounded resource use |
| AT-042 | Worker loses lease while old process continues, or action times out after provider acceptance | Stale fencing token rejected; action UNKNOWN reconciled without blind duplicate dispatch; budgets reflect in-flight outcome |
| AT-043 | Keyboard-only user inspects conditional, stale, failed and fixture outputs | Accessible labels/focus/table alternatives; status not color-only; facts/assumptions/forecast limits plainly visible |
| AT-044 | Each of all 23 roles and cross-agent scenarios is activated with actual services | Correct tool permissions, typed output, evaluator and error path; no role implemented solely as persona text/replay |
| AT-045 | Candidate recalibration has future leakage, worse holdout results or shifted scope | Promotion rejected or limited to valid scope; reviewed accepted update has rollback and pre-outcome prediction refs |
| AT-046 | Two products/geographies share capital/capacity and customers | Portfolio totals reconcile, no duplicated resources/customer volumes; explicit currency/tax/time assumptions |
| AT-047 | Real authorized sandbox action is approved, modified, revoked and retried | Only exact valid approved payload executes; receipt/reconciliation/audit prove outcome; no unapproved external effects |
| AT-048 | SRS-057 workloads run on recorded hardware/version/dataset profile | Actual percentile/throughput/memory/cost results meet targets or documented failure blocks performance readiness |
| AT-049 | SRS-061 backup restore, projection rebuild, cancellation and 24-hour fault workload run | Measured recovery meets approved RPO/RTO; no lost accepted state or leaked reservations/leases; deletion stays effective |
| AT-050 | Schema/model/prompt/provider/database migration happens with active investigations | Pinned semantics preserved or explicit stop/rebase; affected evaluations rerun; no mixed embedding/schema versions |

## Golden numerical fixture: fictional consumer product

Origin is FIXTURE. Currency is INR solely for this test. Horizon is 90 days. Prices/costs are net of tax; all units sell within the horizon; there are no returns, financing or repeat purchases; acquisition cost is per new customer buying one unit. Fixed costs are INR 120,000. The simplified profit fixture does not establish a complete cash-flow model.

| Variable | Base | Acquisition stress |
|---|---:|---:|
| Unit selling price | 699.00 | 699.00 |
| Unit COGS | 315.00 | 315.00 |
| Variable fulfillment | 60.00 | 60.00 |
| Payment fee rate | 3% | 3% |
| Fee per unit | 20.97 | 20.97 |
| Acquisition cost | 140.00 | 196.00 |
| Contribution per unit | 163.03 | 107.03 |
| Fixed costs | 120,000.00 | 120,000.00 |
| Break-even units | 737 | 1,122 |
| Fulfilled units | 900 | 900 |
| Profit | 26,727.00 | -23,673.00 |

The stress holds acquired units fixed, so acquisition spend rises from INR 126,000 to INR 176,400. It cannot simultaneously claim acquisition spend remained fixed. A fixed-spend scenario must recalculate acquired customers under its demand model. At 900 units, the maximum CAC for zero profit is 699 - 315 - 60 - 20.97 - 120000/900 = approximately INR 169.6966667; displayed rounding cannot alter the exact feasibility check.

Use exact decimal arithmetic for these deterministic accounting values. Profit/contribution display tolerance is INR 0.01 with the specified rounding convention; break-even uses exact positive contribution then ceiling. Zero/negative contribution yields no finite break-even, never a negative unit count. Separate cash fixtures must test procurement/payment timing, inventory conservation and liquidity, not reuse profit as cash.

## End-to-end completion evidence

Run the PRD reference journey using actual storage/orchestration/numerical services. Then repeat with faults: missing input, source contradiction, rejected parameter, provider failure, exhausted budget, challenge reversal, stale decision and worker crash. Demonstrate one real authorized source/connector change and one authorized actual observation pipeline; fixtures alone cannot prove live integration or empirical learning.

The acceptance report must record requirement/test IDs, environment, versions, inputs/fixtures, commands, actual outcomes, logs/artifact references, exclusions and unresolved owner decisions. All required full-system capabilities remain in scope. Any unrun or failing mandatory test is explicit; no application acceptance is claimed by this specification package itself.
