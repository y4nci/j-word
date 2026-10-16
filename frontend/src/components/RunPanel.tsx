import React, { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  LinearProgress,
  Paper,
  Slider,
  Stack,
  Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import { client } from "../api/client";
import type { SearchRun } from "../api/types";

const POLL_MS = 2000;
const STAGE_LABEL: Record<SearchRun["stage"], string> = {
  starting: "Starting",
  discovering: "Discovering jobs",
  screening: "Screening jobs",
  drafting: "Drafting cover letters",
  done: "Done",
};
const STATUS_COLOR = { running: "info", completed: "success", failed: "error", cancelled: "default", interrupted: "warning" } as const;

/**
 * The background "full search" job: start, live progress, activity log, cancel.
 * Polls the backend, so it also picks up runs started elsewhere (e.g. right after
 * creating the search) and keeps working if you leave and come back.
 */
export const RunPanel: React.FC<{
  searchId: string;
  minFit: number;
  setMinFit: (v: number) => void;
  disabled: boolean;
  onChanged: () => void; // results changed: reload the job table
  onRunningChange: (running: boolean) => void;
}> = ({ searchId, minFit, setMinFit, disabled, onChanged, onRunningChange }) => {
  const [run, setRun] = useState<SearchRun | null>(null);
  const [draft, setDraft] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const running = run?.status === "running";

  useEffect(() => {
    let stop = false;
    let ticks = 0;
    let wasRunning = false;
    const tick = () =>
      client.getRun(searchId).then(
        (r) => {
          if (stop) return;
          const now = r?.status === "running";
          setRun(r);
          onRunningChange(now);
          ticks += 1;
          // refresh the table every ~6s while running, and once when the run ends
          if ((now && ticks % 3 === 0) || (wasRunning && !now)) onChanged();
          wasRunning = now;
        },
        (e: Error) => { if (!stop) setError(e.message); }
      );
    void tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [searchId, onChanged, onRunningChange]);

  const start = () => {
    setStarting(true);
    setError(null);
    client
      .startRun(searchId, { draft, min_fit: minFit })
      .then((r) => { setRun(r); onRunningChange(true); }, (e: Error) => setError(e.message))
      .finally(() => setStarting(false));
  };
  const cancel = () =>
    client.cancelRun(searchId).then((r) => { if (r) setRun(r); onChanged(); }, (e: Error) => setError(e.message));

  const pct = run && run.total > 0 ? (100 * run.done) / run.total : undefined;

  return (
    <Paper sx={{ p: 2 }}>
      {error && <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>{error}</Alert>}

      {running && run ? (
        <Stack spacing={1}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <Typography variant="subtitle1" fontWeight={600}>{STAGE_LABEL[run.stage]}</Typography>
            {run.total > 0 && <Typography color="text.secondary">{run.done} / {run.total}</Typography>}
            <Box sx={{ flex: 1 }} />
            <Button color="error" startIcon={<StopIcon />} onClick={() => void cancel()}>Cancel</Button>
          </Stack>
          <LinearProgress variant={pct === undefined ? "indeterminate" : "determinate"} value={pct} />
          <Typography variant="body2" color="text.secondary" noWrap>{run.message}</Typography>
          <Typography variant="caption" color="text.secondary">
            Running on the server: you can leave this page and come back. Screened jobs appear in the table as batches finish.
          </Typography>
        </Stack>
      ) : (
        <Stack spacing={1.5}>
          <Typography variant="body2">
            Searches every source (deep searches take longer), screens every job that passes your filters,
            and saves progress after each batch. Re-running continues where the last run stopped.
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
            <Button
              variant="contained"
              size="large"
              startIcon={<PlayArrowIcon />}
              disabled={disabled || starting}
              onClick={start}
            >
              {run ? "Run again" : "Run full search"}
            </Button>
            <FormControlLabel
              control={<Checkbox checked={draft} onChange={(e) => setDraft(e.target.checked)} />}
              label="Also draft cover letters for good matches"
            />
            <Box sx={{ minWidth: 200 }}>
              <Typography variant="caption">min fit for drafting: {minFit.toFixed(2)}</Typography>
              <Slider size="small" min={0} max={1} step={0.05} value={minFit} onChange={(_, v) => setMinFit(v as number)} />
            </Box>
          </Stack>
          {run && (
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="body2" color="text.secondary">Last run:</Typography>
              <Chip size="small" color={STATUS_COLOR[run.status]} label={run.status} />
              <Typography variant="body2" color="text.secondary">
                {run.finished_at ? new Date(run.finished_at).toLocaleString() : ""}
                {run.status === "interrupted" && " (the server stopped mid-run; run again to continue)"}
              </Typography>
            </Stack>
          )}
          {run?.error && <Alert severity="error">{run.error}</Alert>}
        </Stack>
      )}

      {run && run.log.length > 0 && (
        <Box
          component="details"
          open={running}
          sx={{ mt: 1.5, "& summary": { cursor: "pointer", color: "text.secondary", fontSize: 13 } }}
        >
          <summary>Activity</summary>
          <Box
            component="pre"
            sx={{ m: 0, mt: 1, p: 1.5, bgcolor: "#fafbfe", borderRadius: 2, fontSize: 12, maxHeight: 220, overflowY: "auto", whiteSpace: "pre-wrap" }}
          >
            {[...run.log].reverse().join("\n")}
          </Box>
        </Box>
      )}
    </Paper>
  );
};
