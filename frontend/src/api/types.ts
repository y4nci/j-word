// TypeScript mirrors of the backend Pydantic models (backend/src/**/models.py).

export type SearchStatus = "created" | "planned" | "discovered" | "screened" | "drafted" | "failed";

export type ApplicationStatus =
  | "discovered"
  | "filtered_out"
  | "screened_in"
  | "screened_out"
  | "unsure"
  | "drafted"
  | "approved"
  | "rejected"
  | "prepared"
  | "applied"
  | "failed";

export type SourceName = "arbeitnow" | "bundesagentur" | "adzuna" | "greenhouse" | "lever" | "ashby";
export type WorkMode = "remote" | "hybrid" | "onsite" | "unknown";
export type EmploymentType =
  | "full_time"
  | "part_time"
  | "working_student"
  | "internship"
  | "contract"
  | "unknown";
export type ScreeningOutcome = "include" | "exclude" | "unsure";
export type ActorType = "human" | "agent" | "system";

export interface Experience {
  id: string;
  kind: "job" | "project" | "education" | "volunteering" | "other";
  title: string;
  organization: string | null;
  start: string | null;
  end: string | null;
  summary: string;
  skills: string[];
  highlights: string[];
}

export interface CandidateProfile {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  location: string | null;
  links: Record<string, string>;
  headline: string;
  skills: string[];
  languages: string[];
  experiences: Experience[];
  cv_text: string;
  cv_path: string | null;
  proto_cover_letter: string;
  created_at: string;
}

export interface CompanyBoard {
  source: SourceName;
  token: string;
  company_name?: string | null;
  region?: "us" | "eu" | null;
}

export interface JobFilters {
  work_modes: WorkMode[];
  employment_types: EmploymentType[];
  locations: string[];
  country: string;
  radius_km: number;
  max_age_days: number | null;
  posting_languages: string[];
  exclude_companies: string[];
  exclude_keywords: string[];
  max_results_per_query: number;
  sources: SourceName[];
  company_boards: CompanyBoard[];
}

export interface SearchQuery {
  source: SourceName;
  keywords: string;
  location: string | null;
  max_results: number;
}

export interface SearchPlan {
  refined_goal: string;
  target_titles: string[];
  keywords: string[];
  screening_criteria: string[];
  queries: SearchQuery[];
}

export interface JobSearch {
  id: string;
  profile_id: string;
  prompt: string;
  filters: JobFilters;
  plan: SearchPlan | null;
  status: SearchStatus;
  created_at: string;
}

export interface JobPosting {
  id: string;
  source: SourceName;
  external_id: string;
  title: string;
  company: string;
  location: string | null;
  work_mode: WorkMode;
  employment_types: EmploymentType[];
  description: string;
  url: string;
  apply_url: string | null;
  posted_at: string | null;
  salary: string | null;
  language: string | null;
  tags: string[];
  board_token: string | null;
}

export interface ScreeningDecision {
  outcome: ScreeningOutcome;
  fit_score: number;
  confidence: number;
  reason: string;
  matched_requirements: string[];
  missing_requirements: string[];
  dealbreakers: string[];
  actor_type: ActorType;
  model_name: string | null;
  created_at: string;
}

export interface RequirementMatch {
  requirement: string;
  experience_ids: string[];
  evidence: string;
}

export interface UnsupportedClaim {
  claim: string;
  why: string;
}

export interface ApplicationDraft {
  language: string;
  subject: string;
  cover_letter: string;
  short_pitch: string;
  requirement_matches: RequirementMatch[];
  used_experience_ids: string[];
  unsupported_claims: UnsupportedClaim[];
  model_name: string | null;
  edited_by_human: boolean;
  created_at: string;
}

export interface ApplicationPackage {
  directory: string;
  cover_letter_pdf: string;
  cover_letter_txt: string;
  cv_file: string | null;
  summary_md: string;
  autofill: string | null;
  autofill_report: string[];
}

export interface StatusEvent {
  from_status: ApplicationStatus | null;
  to_status: ApplicationStatus;
  actor_type: ActorType;
  note: string;
  at: string;
}

export interface Application {
  id: string;
  search_id: string;
  job_id: string;
  status: ApplicationStatus;
  filter_reason: string | null;
  decisions: ScreeningDecision[];
  draft: ApplicationDraft | null;
  approved_draft_hash: string | null;
  package: ApplicationPackage | null;
  history: StatusEvent[];
  updated_at: string;
}

export interface ApplicationView {
  application: Application;
  job: JobPosting;
}

export interface SearchSummary {
  search_id: string;
  counts: Partial<Record<ApplicationStatus, number>>;
  applications: ApplicationView[];
}

export const latestDecision = (app: Application): ScreeningDecision | undefined =>
  app.decisions[app.decisions.length - 1];
