export type DataOrigin = "collected" | "inferred" | "selected" | "review_required";
export type DemoVariant =
  | "baseline"
  | "confirmed_location"
  | "blocked_crosswalk"
  | "visible_drain_obstruction";

export interface Location {
  label: string | null;
  latitude: number | null;
  longitude: number | null;
  confirmed: boolean;
}

export interface RoutingTarget {
  department: string;
  service: string;
  agency: string | null;
  source: string;
  confidence: number;
}

export interface CivicContext {
  source: string;
  dataset: string;
  query_summary: string;
  matched_count: number;
  likely_agencies: string[];
  likely_problem_types: string[];
  likely_problem_details: string[];
  evidence_summary: string;
  confidence: number;
  used_live_data: boolean;
  fallback_reason: string | null;
}

export interface CollectedInput {
  kind: "text" | "audio" | "image" | "location";
  value: string;
  origin: DataOrigin;
}

export interface InferredContext {
  label: string;
  value: string;
  confidence: number;
  origin: DataOrigin;
}

export interface HumanReviewField {
  field: string;
  reason: string;
  current_value: string | null;
  origin: DataOrigin;
}

export interface DtprStep {
  id: string;
  label: string;
  data_type: string;
  purpose: string;
  processor: string;
  destination: string;
  retention: string;
  control_point: string;
  origin: DataOrigin;
}

export interface EvidenceItem {
  kind: "text" | "audio" | "image" | "location";
  summary: string;
  captured_at: string | null;
}

export interface UncertaintyItem {
  field: string;
  reason: string;
  confidence: number;
}

export interface ReportDraft {
  id: string;
  status: "draft" | "confirmed";
  category: string;
  subcategory: string | null;
  title: string;
  description: string;
  narrative: string;
  location: Location;
  observed_at: string | null;
  priority: "low" | "medium" | "high" | "unknown";
  routing: RoutingTarget | null;
  civic_context: CivicContext | null;
  collected_inputs: CollectedInput[];
  inferred_context: InferredContext[];
  human_review: HumanReviewField[];
  evidence: EvidenceItem[];
  questions_asked: string[];
  uncertainty: UncertaintyItem[];
  dtpr_chain: DtprStep[];
}

export interface ReportUpdateRequest {
  title?: string;
  description?: string;
  category?: string;
  subcategory?: string | null;
  priority?: ReportDraft["priority"];
  location?: Location;
}

export interface ConfirmResponse {
  report: ReportDraft;
  message: string;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

function apiUrl(path: string) {
  return API_BASE_URL ? `${API_BASE_URL}${path}` : `/api/backend${path}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createDemoDraft(
  demoVariant: DemoVariant = "baseline",
  location?: Location,
): Promise<ReportDraft> {
  const response = await fetch(apiUrl("/api/report/draft"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario: "flooding_near_school_crossing",
      demo_variant: demoVariant,
      location,
    }),
  });

  return parseResponse<ReportDraft>(response);
}

export async function confirmDraft(reportId: string): Promise<ConfirmResponse> {
  const response = await fetch(apiUrl("/api/report/confirm"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report_id: reportId, accepted: true }),
  });

  return parseResponse<ConfirmResponse>(response);
}

export async function updateDraft(
  reportId: string,
  updates: ReportUpdateRequest,
): Promise<ReportDraft> {
  const response = await fetch(apiUrl(`/api/report/${reportId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });

  return parseResponse<ReportDraft>(response);
}
