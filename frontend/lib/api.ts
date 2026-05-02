export type DataOrigin = "collected" | "inferred" | "selected" | "review_required";

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
  collected_inputs: CollectedInput[];
  inferred_context: InferredContext[];
  human_review: HumanReviewField[];
  questions_asked: string[];
  dtpr_chain: DtprStep[];
}

export interface ConfirmResponse {
  report: ReportDraft;
  message: string;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createDemoDraft(): Promise<ReportDraft> {
  const response = await fetch(`${API_BASE_URL}/api/report/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario: "flooding_near_school_crossing" }),
  });

  return parseResponse<ReportDraft>(response);
}

export async function confirmDraft(reportId: string): Promise<ConfirmResponse> {
  const response = await fetch(`${API_BASE_URL}/api/report/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report_id: reportId, accepted: true }),
  });

  return parseResponse<ConfirmResponse>(response);
}
