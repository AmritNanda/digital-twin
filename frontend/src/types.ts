export type EventRecord = {
  id: number;
  created_at: string;
  run_id?: string;
  type: string;
  stage?: string;
  status?: string;
  message?: string;
  [key: string]: unknown;
};

export type DocumentRecord = {
  id: string;
  filename: string;
  size: number;
  chunks: number;
  preview: string;
};

export type Simulation = {
  id?: string;
  hypothesis_id: string;
  avg_profit: number;
  p10_profit: number;
  p50_profit: number;
  p90_profit: number;
  prob_positive: number;
  avg_monthly_demand?: number;
  price?: number;
  channel?: string;
};

export type DecisionResult = {
  recommendation?: string;
  rationale?: string;
  confidence?: number;
  selected_hypothesis?: string;
  simulations?: Simulation[];
  hypotheses?: { id: string; title: string; channel?: string; price?: number; status?: string }[];
  sensitivity?: { elasticity: number; cac_inr: number; leader_hypothesis_id: string; leader_avg_profit: number }[];
  evidence?: { id: string; source: string; source_type: string; excerpt: string }[];
  challenges?: { id: string; severity: string; weakness: string }[];
  supporting_evidence_ids?: string[];
  counter_evidence_ids?: string[];
  open_questions?: string[];
  what_would_change?: string[];
  uncertainty_statement?: string;
  pilot?: { duration_weeks: number; budget_cap_inr: number; measure: string[]; stop_condition: string; human_action_required: boolean };
  fixture_data_present?: boolean;
  source_version?: number;
};

export type RunRecord = {
  id: string;
  version: number;
  status: string;
  result: DecisionResult;
  twin: Record<string, unknown>;
  assumptions: Record<string, number>;
  created_at: string;
};

export type CaseRecord = {
  id: string;
  question: string;
  status: string;
  source_snapshot: {
    version?: number;
    status?: string;
    suggested_questions?: string[];
    entities?: { id: string; type: string; name: string; attributes: Record<string, unknown> }[];
    facts?: { entity_id: string; field: string; value: unknown; epistemic: string }[];
    unknowns?: string[];
    used_passages?: { doc_id: string; document_id?: string; source: string; excerpt: string }[];
    corrections?: { entity_name: string; field: string; before: unknown; value: unknown; reason: string }[];
  };
  approval: { type?: string; values?: Record<string, number>; changes?: Record<string, unknown> };
  documents: DocumentRecord[];
  runs: RunRecord[];
  events: EventRecord[];
  messages: { id: number; run_id: string; role: string; content: string; created_at: string }[];
};

export type User = { id: string; email: string };
