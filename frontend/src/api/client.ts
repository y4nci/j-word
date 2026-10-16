import axios, { AxiosError } from "axios";
import type {
  Application,
  ApplicationView,
  CandidateProfile,
  CompanyBoard,
  RunOptions,
  SearchRun,
  JobFilters,
  JobSearch,
  ScreeningOutcome,
  SearchSummary,
} from "./types";

// Vite proxies /api -> backend (see vite.config.ts).
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

const api = axios.create({ baseURL: API_BASE });

// Turn FastAPI's {"detail": ...} into a readable Error message.
api.interceptors.response.use(
  (r) => r,
  (err: AxiosError<{ detail?: unknown }>) => {
    const detail = err.response?.data?.detail;
    let message = err.message;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail))
      message = detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`).join("; ");
    if (!err.response) message = "Backend not reachable. Is uvicorn running on :8000?";
    return Promise.reject(new Error(message));
  }
);

export interface NewProfileInput {
  cv: File;
  protoCoverLetter: string;
  protoCoverLetterFiles: File[];
  fullName: string;
  email: string;
  phone: string;
  location: string;
  links: Record<string, string>;
}

export const client = {
  // ---------------- profiles ---------------- //
  listProfiles: async () => (await api.get<CandidateProfile[]>("/profiles")).data,
  getProfile: async (id: string) => (await api.get<CandidateProfile>(`/profiles/${id}`)).data,
  updateProfile: async (profile: CandidateProfile) =>
    (await api.put<CandidateProfile>(`/profiles/${profile.id}`, profile)).data,
  createProfile: async (input: NewProfileInput) => {
    const form = new FormData();
    form.append("cv", input.cv);
    form.append("proto_cover_letter", input.protoCoverLetter);
    input.protoCoverLetterFiles.forEach((f) => form.append("proto_cover_letter_files", f));
    form.append("full_name", input.fullName);
    form.append("email", input.email);
    form.append("phone", input.phone);
    form.append("location", input.location);
    form.append("links", JSON.stringify(input.links));
    return (await api.post<CandidateProfile>("/profiles", form)).data;
  },
  listSearches: async (profileId: string) =>
    (await api.get<JobSearch[]>(`/profiles/${profileId}/searches`)).data,

  // ---------------- searches ---------------- //
  createSearch: async (profileId: string, prompt: string, filters: JobFilters) =>
    (await api.post<JobSearch>("/searches", { profile_id: profileId, prompt, filters })).data,
  getSearch: async (id: string) => (await api.get<JobSearch>(`/searches/${id}`)).data,
  listApplications: async (searchId: string) =>
    (await api.get<SearchSummary>(`/searches/${searchId}/applications`)).data,
  discover: async (searchId: string) => (await api.post<SearchSummary>(`/searches/${searchId}/discover`)).data,
  screen: async (searchId: string) => (await api.post<SearchSummary>(`/searches/${searchId}/screen`)).data,
  draftAll: async (searchId: string, minFit: number) =>
    (await api.post<Application[]>(`/searches/${searchId}/draft`, { min_fit: minFit })).data,

  // ---------------- background full-search runs ---------------- //
  startRun: async (searchId: string, options: RunOptions) =>
    (await api.post<SearchRun>(`/searches/${searchId}/run`, options)).data,
  getRun: async (searchId: string) => (await api.get<SearchRun | null>(`/searches/${searchId}/run`)).data,
  cancelRun: async (searchId: string) => (await api.post<SearchRun | null>(`/searches/${searchId}/run/cancel`)).data,
  defaultBoards: async () => (await api.get<CompanyBoard[]>("/meta/default-boards")).data,

  // ---------------- applications ---------------- //
  getApplication: async (id: string) => (await api.get<ApplicationView>(`/applications/${id}`)).data,
  overrideScreening: async (id: string, outcome: ScreeningOutcome, reason = "") =>
    (await api.post<Application>(`/applications/${id}/screening`, { outcome, reason })).data,
  draftOne: async (id: string) => (await api.post<Application>(`/applications/${id}/draft`)).data,
  editDraft: async (id: string, edit: { subject?: string; cover_letter?: string; short_pitch?: string }) =>
    (await api.patch<Application>(`/applications/${id}/draft`, edit)).data,
  approve: async (id: string, note = "") =>
    (await api.post<Application>(`/applications/${id}/approve`, { note })).data,
  reject: async (id: string, note = "") =>
    (await api.post<Application>(`/applications/${id}/reject`, { note })).data,
  prepare: async (id: string, autofill: boolean) =>
    (await api.post<Application>(`/applications/${id}/prepare`, { autofill })).data,
  markApplied: async (id: string, note = "") =>
    (await api.post<Application>(`/applications/${id}/mark-applied`, { note })).data,
  coverLetterPdfUrl: (id: string) => `${API_BASE}/applications/${id}/cover-letter.pdf`,
};
