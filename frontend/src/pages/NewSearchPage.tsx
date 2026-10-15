import React, { useState } from "react";
import {
  Button,
  Chip,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { useNavigate, useParams } from "react-router-dom";
import { client } from "../api/client";
import type { CompanyBoard, EmploymentType, JobFilters, SourceName, WorkMode } from "../api/types";
import { BusyBanner, ChipInput, ErrorAlert, Section } from "../components/common";
import { useAsync } from "../hooks/useAsync";

const WORK_MODES: WorkMode[] = ["remote", "hybrid", "onsite"];
const EMPLOYMENT: EmploymentType[] = ["full_time", "part_time", "working_student", "internship", "contract"];
const SOURCES: SourceName[] = ["arbeitnow", "bundesagentur", "adzuna", "greenhouse", "lever", "ashby"];
const BOARD_SOURCES: CompanyBoard["source"][] = ["greenhouse", "lever", "ashby"];

const DEFAULT_FILTERS: JobFilters = {
  work_modes: [],
  employment_types: [],
  locations: [],
  country: "de",
  radius_km: 50,
  max_age_days: 30,
  posting_languages: [],
  exclude_companies: [],
  exclude_keywords: [],
  max_results_per_query: 50,
  sources: [],
  company_boards: [],
};

function ToggleChips<T extends string>({ label, options, values, onChange }: {
  label: string; options: T[]; values: T[]; onChange: (v: T[]) => void;
}) {
  return (
    <Stack spacing={0.5}>
      <Typography variant="caption" color="text.secondary">{label} (none selected = any)</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap">
        {options.map((o) => {
          const on = values.includes(o);
          return (
            <Chip
              key={o}
              label={o.replace("_", " ")}
              color={on ? "primary" : "default"}
              variant={on ? "filled" : "outlined"}
              onClick={() => onChange(on ? values.filter((v) => v !== o) : [...values, o])}
            />
          );
        })}
      </Stack>
    </Stack>
  );
}

export const NewSearchPage: React.FC = () => {
  const { profileId = "" } = useParams();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [filters, setFilters] = useState<JobFilters>(DEFAULT_FILTERS);
  const { busy, error, setError, run } = useAsync();
  const set = <K extends keyof JobFilters>(k: K, v: JobFilters[K]) => setFilters({ ...filters, [k]: v });

  const setBoard = (i: number, patch: Partial<CompanyBoard>) =>
    set("company_boards", filters.company_boards.map((b, j) => (j === i ? { ...b, ...patch } : b)));

  return (
    <>
      <Typography variant="h4" sx={{ mb: 2 }}>New search</Typography>
      <ErrorAlert error={error} onClose={() => setError(null)} />
      <BusyBanner busy={busy} />

      <Section title="What are you looking for?">
        <TextField
          fullWidth
          multiline
          minRows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Working student or junior roles in ML engineering, ideally NLP / LLM products. No pure data-entry roles."
        />
      </Section>

      <Section title="Hard filters">
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2.5}>
            <ToggleChips label="Work mode" options={WORK_MODES} values={filters.work_modes} onChange={(v) => set("work_modes", v)} />
            <ToggleChips label="Employment type" options={EMPLOYMENT} values={filters.employment_types} onChange={(v) => set("employment_types", v)} />
            <ChipInput label="Locations" values={filters.locations} onChange={(v) => set("locations", v)} placeholder="e.g. Berlin" />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Radius (km)" type="number" value={filters.radius_km} onChange={(e) => set("radius_km", Number(e.target.value))} />
              <TextField
                label="Max age (days)"
                type="number"
                value={filters.max_age_days ?? ""}
                onChange={(e) => set("max_age_days", e.target.value ? Number(e.target.value) : null)}
              />
              <TextField label="Country (Adzuna)" value={filters.country} onChange={(e) => set("country", e.target.value)} />
              <TextField
                label="Max results per query"
                type="number"
                value={filters.max_results_per_query}
                onChange={(e) => set("max_results_per_query", Number(e.target.value))}
              />
            </Stack>
            <ToggleChips label="Posting languages" options={["en", "de"]} values={filters.posting_languages} onChange={(v) => set("posting_languages", v)} />
            <ChipInput label="Exclude companies" values={filters.exclude_companies} onChange={(v) => set("exclude_companies", v)} />
            <ChipInput label="Exclude title keywords" values={filters.exclude_keywords} onChange={(v) => set("exclude_keywords", v)} placeholder="e.g. senior" />
            <ToggleChips label="Sources" options={SOURCES} values={filters.sources} onChange={(v) => set("sources", v)} />
          </Stack>
        </Paper>
      </Section>

      <Section
        title="Company boards"
        action={
          <Button startIcon={<AddIcon />} onClick={() => set("company_boards", [...filters.company_boards, { source: "greenhouse", token: "" }])}>
            Add board
          </Button>
        }
      >
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Companies whose careers page runs on Greenhouse, Lever or Ashby. The token is the slug in the URL,
          e.g. job-boards.greenhouse.io/<b>n26</b>, jobs.lever.co/<b>mistral</b>, jobs.ashbyhq.com/<b>ramp</b>.
          These are also the sites the browser autofill supports.
        </Typography>
        <Stack spacing={1}>
          {filters.company_boards.map((b, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField select size="small" value={b.source} onChange={(e) => setBoard(i, { source: e.target.value as CompanyBoard["source"] })} sx={{ width: 150 }}>
                {BOARD_SOURCES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
              </TextField>
              <TextField size="small" label="Token" value={b.token} onChange={(e) => setBoard(i, { token: e.target.value.trim() })} />
              <TextField size="small" label="Company name (optional)" value={b.company_name ?? ""} onChange={(e) => setBoard(i, { company_name: e.target.value || null })} />
              {b.source === "lever" && (
                <TextField select size="small" label="Region" value={b.region ?? "us"} onChange={(e) => setBoard(i, { region: e.target.value as "us" | "eu" })} sx={{ width: 100 }}>
                  <MenuItem value="us">us</MenuItem>
                  <MenuItem value="eu">eu</MenuItem>
                </TextField>
              )}
              <IconButton aria-label="remove board" onClick={() => set("company_boards", filters.company_boards.filter((_, j) => j !== i))}>
                <DeleteOutlineIcon />
              </IconButton>
            </Stack>
          ))}
        </Stack>
      </Section>

      <Stack direction="row" justifyContent="flex-end">
        <Button
          variant="contained"
          size="large"
          disabled={!prompt.trim() || busy !== null}
          onClick={() =>
            run("Planning the search", async () => {
              const cleaned = { ...filters, company_boards: filters.company_boards.filter((b) => b.token) };
              const search = await client.createSearch(profileId, prompt, cleaned);
              navigate(`/searches/${search.id}`);
            })
          }
        >
          Plan search
        </Button>
      </Stack>
    </>
  );
};
