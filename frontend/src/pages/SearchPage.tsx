import React, { useCallback, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Collapse,
  IconButton,
  Link,
  Paper,
  Slider,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import { useNavigate, useParams } from "react-router-dom";
import { client } from "../api/client";
import { latestDecision } from "../api/types";
import type { ApplicationStatus, ApplicationView } from "../api/types";
import { BusyBanner, ErrorAlert, FitBar, Section, StatusChip } from "../components/common";
import { useAsync, useResource } from "../hooks/useAsync";

const SCREENABLE: ApplicationStatus[] = ["discovered", "filtered_out", "screened_in", "screened_out", "unsure"];
const REVIEWABLE: ApplicationStatus[] = ["drafted", "approved", "rejected", "prepared", "applied", "failed"];
const STATUS_ORDER: ApplicationStatus[] = [
  "drafted", "approved", "prepared", "applied", "screened_in", "unsure", "discovered",
  "screened_out", "filtered_out", "rejected", "failed",
];

export const SearchPage: React.FC = () => {
  const { searchId = "" } = useParams();
  const fetcher = useCallback(
    () => Promise.all([client.getSearch(searchId), client.listApplications(searchId)]),
    [searchId]
  );
  const { data, error: loadError, reload } = useResource(fetcher);
  const [search, summary] = data ?? [null, null];
  const [filter, setFilter] = useState<ApplicationStatus | null>(null);
  const [minFit, setMinFit] = useState(0.6);
  const { busy, error, setError, run } = useAsync();

  const counts = summary?.counts ?? {};
  const rows = useMemo(
    () => (summary?.applications ?? []).filter((r) => !filter || r.application.status === filter),
    [summary, filter]
  );

  if (!search) return <ErrorAlert error={loadError} />;

  const step = (label: string, fn: () => Promise<unknown>) => run(label, async () => { await fn(); reload(); });
  const discovered = summary?.applications.length ?? 0;

  return (
    <>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Search</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>{search.prompt}</Typography>
      <ErrorAlert error={error ?? loadError} onClose={() => setError(null)} />
      <BusyBanner busy={busy} />

      {search.plan && (
        <Section title="Plan">
          <Paper sx={{ p: 2 }}>
            <Typography sx={{ mb: 1 }}><b>Goal:</b> {search.plan.refined_goal}</Typography>
            <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{ mb: 1 }}>
              {search.plan.target_titles.map((t) => <Chip key={t} size="small" label={t} />)}
            </Stack>
            <Typography variant="body2" sx={{ mb: 1 }}>
              <b>Keywords:</b> {search.plan.keywords.join(", ")} · <b>{search.plan.queries.length}</b> queries over{" "}
              {[...new Set(search.plan.queries.map((q) => q.source))].join(", ") || "no sources"}
            </Typography>
            <Typography variant="body2"><b>Screening criteria:</b></Typography>
            <ul style={{ margin: 0 }}>
              {search.plan.screening_criteria.map((c) => <li key={c}><Typography variant="body2">{c}</Typography></li>)}
            </ul>
          </Paper>
        </Section>
      )}

      <Section title="Steps">
        <Paper sx={{ p: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
            <Button variant="contained" disabled={busy !== null} onClick={() => step("Discovering jobs", () => client.discover(searchId))}>
              1 · Discover {discovered > 0 && "more"}
            </Button>
            <Button
              variant="contained"
              disabled={busy !== null || !counts.discovered}
              onClick={() => step("Screening jobs", () => client.screen(searchId))}
            >
              2 · Screen {counts.discovered ? `(${counts.discovered})` : ""}
            </Button>
            <Stack direction="row" spacing={2} alignItems="center" sx={{ minWidth: 260 }}>
              <Button
                variant="contained"
                disabled={busy !== null || !counts.screened_in}
                onClick={() => step("Drafting cover letters", () => client.draftAll(searchId, minFit))}
              >
                3 · Draft {counts.screened_in ? `(${counts.screened_in})` : ""}
              </Button>
              <Tooltip title="Only draft jobs with at least this fit score. Jobs you included manually are always drafted.">
                <Box sx={{ flex: 1 }}>
                  <Typography variant="caption">min fit {minFit.toFixed(2)}</Typography>
                  <Slider size="small" min={0} max={1} step={0.05} value={minFit} onChange={(_, v) => setMinFit(v as number)} />
                </Box>
              </Tooltip>
            </Stack>
            <Typography variant="body2" color="text.secondary">4 · Review each draft and approve it ↓</Typography>
          </Stack>
        </Paper>
      </Section>

      <Section title={`Jobs (${discovered})`}>
        <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mb: 1 }}>
          <Chip label={`all ${discovered}`} color={filter === null ? "primary" : "default"} onClick={() => setFilter(null)} />
          {STATUS_ORDER.filter((s) => counts[s]).map((s) => (
            <Chip
              key={s}
              label={`${s.replace("_", " ")} ${counts[s]}`}
              color={filter === s ? "primary" : "default"}
              variant={filter === s ? "filled" : "outlined"}
              onClick={() => setFilter(filter === s ? null : s)}
            />
          ))}
        </Stack>
        <Paper sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell />
                <TableCell>Job</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Fit</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <JobRow key={r.application.id} row={r} disabled={busy !== null} onAction={step} />
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Typography color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
                      {discovered === 0 ? "No jobs yet. Run Discover." : "No jobs with this status."}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Paper>
      </Section>
    </>
  );
};

const JobRow: React.FC<{
  row: ApplicationView;
  disabled: boolean;
  onAction: (label: string, fn: () => Promise<unknown>) => void;
}> = ({ row, disabled, onAction }) => {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { application: app, job } = row;
  const d = latestDecision(app);

  return (
    <>
      <TableRow hover>
        <TableCell padding="checkbox">
          <IconButton size="small" onClick={() => setOpen(!open)} aria-label="details">
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell sx={{ maxWidth: 320 }}>
          <Link href={job.url} target="_blank" rel="noreferrer" underline="hover" fontWeight={600}>{job.title}</Link>
          <Typography variant="body2" color="text.secondary">
            {job.company} · {job.location ?? "n/a"} · {job.work_mode}
            {job.employment_types.length > 0 && ` · ${job.employment_types.join(", ").replaceAll("_", " ")}`}
          </Typography>
          <Typography variant="caption" color="text.secondary">{job.source}</Typography>
        </TableCell>
        <TableCell><StatusChip status={app.status} /></TableCell>
        <TableCell><FitBar value={d?.fit_score} /></TableCell>
        <TableCell sx={{ maxWidth: 340 }}>
          <Typography variant="body2" sx={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
            {app.filter_reason && app.status === "filtered_out" ? `Filter: ${app.filter_reason}` : d?.reason}
            {d?.actor_type === "human" && " (you)"}
          </Typography>
        </TableCell>
        <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
          {SCREENABLE.includes(app.status) && (
            <>
              <Tooltip title="Include">
                <span>
                  <IconButton
                    aria-label="Include"
                    size="small"
                    color="success"
                    disabled={disabled || app.status === "screened_in"}
                    onClick={() => onAction("Saving decision", () => client.overrideScreening(app.id, "include"))}
                  >
                    <CheckIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="Exclude">
                <span>
                  <IconButton
                    aria-label="Exclude"
                    size="small"
                    color="error"
                    disabled={disabled || app.status === "screened_out"}
                    onClick={() => onAction("Saving decision", () => client.overrideScreening(app.id, "exclude"))}
                  >
                    <CloseIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            </>
          )}
          {app.status === "screened_in" && (
            <Button size="small" disabled={disabled} onClick={() => onAction("Drafting cover letter", () => client.draftOne(app.id))}>
              Draft
            </Button>
          )}
          {REVIEWABLE.includes(app.status) && (
            <Button size="small" variant={app.status === "drafted" ? "contained" : "outlined"} onClick={() => navigate(`/applications/${app.id}`)}>
              {app.status === "drafted" ? "Review" : "Open"}
            </Button>
          )}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={6} sx={{ py: 0, borderBottom: open ? undefined : "none" }}>
          <Collapse in={open} unmountOnExit>
            <Stack direction={{ xs: "column", md: "row" }} spacing={3} sx={{ py: 2 }}>
              <Box sx={{ flex: 1 }}>
                {d && (
                  <>
                    <Typography variant="subtitle2">Matched</Typography>
                    <ul style={{ marginTop: 0 }}>{d.matched_requirements.map((m) => <li key={m}><Typography variant="body2">{m}</Typography></li>)}</ul>
                    <Typography variant="subtitle2">Missing</Typography>
                    <ul style={{ marginTop: 0 }}>{d.missing_requirements.map((m) => <li key={m}><Typography variant="body2">{m}</Typography></li>)}</ul>
                    {d.dealbreakers.length > 0 && (
                      <Typography variant="body2" color="error">Dealbreakers: {d.dealbreakers.join("; ")}</Typography>
                    )}
                  </>
                )}
                {job.salary && <Typography variant="body2">Salary: {job.salary}</Typography>}
                {job.posted_at && <Typography variant="body2">Posted: {new Date(job.posted_at).toLocaleDateString()}</Typography>}
              </Box>
              <Box sx={{ flex: 2, maxHeight: 300, overflowY: "auto", whiteSpace: "pre-wrap", bgcolor: "#fafbfe", p: 1.5, borderRadius: 2 }}>
                <Typography variant="body2">{job.description || "(no description)"}</Typography>
              </Box>
            </Stack>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
};
