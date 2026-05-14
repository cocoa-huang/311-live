export type DataOrigin = "collected" | "inferred" | "selected" | "review_required";
export type DemoVariant =
  | "baseline"
  | "confirmed_location"
  | "blocked_crosswalk"
  | "visible_drain_obstruction"
  | "street_trash_bags";
export type ReportScenario =
  | "flooding_near_school_crossing"
  | "trash_bags_on_street";

export interface Location {
  label: string | null;
  latitude: number | null;
  longitude: number | null;
  accuracy_meters: number | null;
  street_address: string | null;
  intersection: string | null;
  neighborhood: string | null;
  borough: string | null;
  source: string | null;
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

export interface IntakeState {
  frame_status: "not_available" | "available" | "not_required";
  camera_lifecycle:
    | "unavailable"
    | "camera_streaming"
    | "evidence_captured"
    | "camera_closed_by_user";
  candidate_provenance:
    | "camera_observed"
    | "resident_reported_only"
    | "visual_unclear";
  resident_confirmed_intent: boolean;
  location_confirmed: boolean;
  draft_ready: boolean;
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
  location?: Location;
}

export interface ConfirmResponse {
  report: ReportDraft;
  message: string;
}

export interface LiveClassifyResponse {
  scenario: ReportScenario;
  demo_variant: DemoVariant;
  candidate: string;
  confirmation: string;
  followup: string;
  model_source: string;
  fallback_reason: string | null;
  intake_state: IntakeState;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_BASE_URL ?? "";
const LIVE_ACCESS_CODE_STORAGE_KEY = "311-live-access-code";

function apiUrl(path: string) {
  return API_BASE_URL ? `${API_BASE_URL}${path}` : `/api/backend${path}`;
}

export function getStoredLiveAccessCode() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(LIVE_ACCESS_CODE_STORAGE_KEY) ?? "";
}

export function storeLiveAccessCode(code: string) {
  if (typeof window === "undefined") return;
  const trimmed = code.trim();
  if (trimmed) {
    window.sessionStorage.setItem(LIVE_ACCESS_CODE_STORAGE_KEY, trimmed);
  } else {
    window.sessionStorage.removeItem(LIVE_ACCESS_CODE_STORAGE_KEY);
  }
}

export function liveWebSocketUrl(accessCode = getStoredLiveAccessCode()) {
  if (WS_BASE_URL) {
    const suffix = accessCode ? `?access_code=${encodeURIComponent(accessCode)}` : "";
    return `${WS_BASE_URL}/ws/live${suffix}`;
  }
  return null;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createDemoDraft(
  scenario: ReportScenario = "flooding_near_school_crossing",
  demoVariant: DemoVariant = "baseline",
  location?: Location,
  transcript?: string,
): Promise<ReportDraft> {
  const response = await fetch(apiUrl("/api/report/draft"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario,
      demo_variant: demoVariant,
      location,
      transcript,
    }),
  });

  return parseResponse<ReportDraft>(response);
}

export async function classifyLiveObservation(
  transcript: string,
  imageSummary?: string,
  imageFrame?: string,
  location?: Location,
  accessCode = getStoredLiveAccessCode(),
): Promise<LiveClassifyResponse> {
  const response = await fetch(apiUrl("/api/live/classify"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessCode ? { "x-live-access-code": accessCode } : {}),
    },
    body: JSON.stringify({
      transcript,
      image_summary: imageSummary,
      image_frame: imageFrame,
      location,
    }),
  });

  return parseResponse<LiveClassifyResponse>(response);
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
