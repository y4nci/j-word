import React from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import PaymentsOutlinedIcon from "@mui/icons-material/PaymentsOutlined";
import ScheduleIcon from "@mui/icons-material/Schedule";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import HomeWorkOutlinedIcon from "@mui/icons-material/HomeWorkOutlined";
import PlaceOutlinedIcon from "@mui/icons-material/PlaceOutlined";
import EventOutlinedIcon from "@mui/icons-material/EventOutlined";
import TimelapseIcon from "@mui/icons-material/Timelapse";
import TranslateIcon from "@mui/icons-material/Translate";
import type { JobPosting } from "../api/types";

interface Fact {
  key: string;
  label: string; // used in the bullet list
  value: string;
  icon: React.ReactElement;
}

/**
 * Facts for a job: the LLM summary when screening produced one, otherwise
 * the structured fields the source reported (filtered-out jobs never reach the LLM).
 */
function jobFacts(job: JobPosting): Fact[] {
  const s = job.summary;
  const employment =
    s?.employment ?? (job.employment_types.length ? job.employment_types.join(", ").replaceAll("_", " ") : null);
  const workMode = s?.work_mode ?? (job.work_mode !== "unknown" ? job.work_mode : null);
  const facts: (Fact | null)[] = [
    pick("pay", "Pay", s?.pay ?? job.salary, <PaymentsOutlinedIcon />),
    pick("hours", "Hours", s?.hours, <ScheduleIcon />),
    pick("employment", "Type", employment, <WorkOutlineIcon />),
    pick("work_mode", "Work mode", workMode, <HomeWorkOutlinedIcon />),
    pick("location", "Location", s?.location ?? job.location, <PlaceOutlinedIcon />),
    pick("start", "Start", s?.start, <EventOutlinedIcon />),
    pick("duration", "Duration", s?.duration, <TimelapseIcon />),
    pick("languages", "Languages", s?.languages.join(", "), <TranslateIcon />),
  ];
  return facts.filter((f): f is Fact => f !== null);
}

function pick(key: string, label: string, value: string | null | undefined, icon: React.ReactElement): Fact | null {
  return value ? { key, label, value, icon } : null;
}

/** Compact chips + one-line description, for table rows. */
export const JobFactChips: React.FC<{ job: JobPosting; exclude?: string[] }> = ({ job, exclude = [] }) => {
  const facts = jobFacts(job).filter((f) => !exclude.includes(f.key));
  return (
    <>
      {job.summary?.short_description && (
        <Typography
          variant="body2"
          sx={{ mt: 0.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
        >
          {job.summary.short_description}
        </Typography>
      )}
      {facts.length > 0 && (
        <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{ mt: 0.75 }}>
          {facts.map((f) => (
            <Chip
              key={f.key}
              size="small"
              variant="outlined"
              icon={React.cloneElement(f.icon, { fontSize: "small" } as object)}
              label={f.value}
              title={f.label}
              color={f.key === "pay" ? "success" : "default"}
              sx={{ maxWidth: 260 }}
            />
          ))}
        </Stack>
      )}
    </>
  );
};

/** Description + bullet list, for detail views. */
export const JobSummaryDetails: React.FC<{ job: JobPosting }> = ({ job }) => {
  const facts = jobFacts(job);
  const s = job.summary;
  return (
    <Box>
      {s?.short_description && <Typography variant="body2" sx={{ mb: 1 }}>{s.short_description}</Typography>}
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        {facts.map((f) => (
          <li key={f.key}>
            <Typography variant="body2"><b>{f.label}:</b> {f.value}</Typography>
          </li>
        ))}
        {!facts.some((f) => f.key === "pay") && (
          <li><Typography variant="body2" color="text.secondary"><b>Pay:</b> not stated</Typography></li>
        )}
      </ul>
      {s && s.key_requirements.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>Key requirements</Typography>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {s.key_requirements.map((r) => <li key={r}><Typography variant="body2">{r}</Typography></li>)}
          </ul>
        </>
      )}
      {!s && (
        <Typography variant="caption" color="text.secondary">
          No summary yet: jobs that pass the hard filters are summarised during screening.
        </Typography>
      )}
    </Box>
  );
};
