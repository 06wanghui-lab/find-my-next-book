export type VerificationStatus = "official" | "corroborated" | "unverified";

export interface EvidenceSource {
  source_id: string;
  title: string;
  url: string;
  excerpt: string;
}

export interface Recommendation {
  rank: number;
  title: string;
  author: string | null;
  platform: string | null;
  publication_status: "completed" | "ongoing" | "unknown";
  relevance_score: number;
  match_reasons: string[];
  uncertainties: string[];
  sources: EvidenceSource[];
  official_url: string | null;
  verification_status: VerificationStatus;
  genre_tags: string[];
  reasons?: Array<{
    text: string;
    kind: "verified_metadata" | "attributed_reader_opinion" | "preference_inference";
    source_ids: string[];
  }>;
}

export interface TasteProfile {
  genres: string[];
  desired_traits: string[];
  positive_aspects: string[];
  hard_exclusions: string[];
  publication_status: "completed" | "ongoing" | "any";
}

export interface RecommendationResponse {
  profile: TasteProfile;
  recommendations: Recommendation[];
  warnings: string[];
  providers: { model: string; search: string };
}

export class RecommendationApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "RecommendationApiError";
  }
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(
  /\/$/,
  "",
);

export async function requestRecommendations(
  request: string,
  signal?: AbortSignal,
): Promise<RecommendationResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request }),
      signal,
    });
  } catch {
    throw new RecommendationApiError(
      "无法连接推荐服务。请确认后端已经启动，然后再试一次。",
      0,
      "network_error",
    );
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail?.message === "string"
        ? detail.message
        : "推荐服务暂时不可用，请稍后再试。";
    const code = typeof detail?.code === "string" ? detail.code : "request_failed";
    throw new RecommendationApiError(message, response.status, code);
  }

  return (await response.json()) as RecommendationResponse;
}
