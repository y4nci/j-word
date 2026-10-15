import React from "react";
import { Alert, Box, Chip, CircularProgress, LinearProgress, Stack, Typography } from "@mui/material";
import type { ChipProps } from "@mui/material";
import type { ApplicationStatus } from "../api/types";

const STATUS_COLOR: Record<ApplicationStatus, ChipProps["color"]> = {
  discovered: "default",
  filtered_out: "default",
  screened_in: "primary",
  screened_out: "default",
  unsure: "warning",
  drafted: "info",
  approved: "success",
  rejected: "default",
  prepared: "secondary",
  applied: "success",
  failed: "error",
};

export const StatusChip: React.FC<{ status: ApplicationStatus; size?: ChipProps["size"] }> = ({ status, size = "small" }) => (
  <Chip
    size={size}
    label={status.replace("_", " ")}
    color={STATUS_COLOR[status]}
    variant={status === "applied" || status === "approved" ? "filled" : "outlined"}
  />
);

export const FitBar: React.FC<{ value?: number }> = ({ value }) =>
  value === undefined ? (
    <Typography variant="caption" color="text.secondary">–</Typography>
  ) : (
    <Stack direction="row" alignItems="center" spacing={1} sx={{ minWidth: 110 }}>
      <LinearProgress
        variant="determinate"
        value={value * 100}
        color={value >= 0.7 ? "success" : value >= 0.4 ? "warning" : "error"}
        sx={{ flex: 1, height: 6, borderRadius: 3 }}
      />
      <Typography variant="caption" sx={{ width: 28 }}>{value.toFixed(2)}</Typography>
    </Stack>
  );

export const ErrorAlert: React.FC<{ error: string | null; onClose?: () => void }> = ({ error, onClose }) =>
  error ? (
    <Alert severity="error" onClose={onClose} sx={{ mb: 2 }}>
      {error}
    </Alert>
  ) : null;

/** Shown while a long LLM step runs. */
export const BusyBanner: React.FC<{ busy: string | null }> = ({ busy }) =>
  busy ? (
    <Alert icon={<CircularProgress size={18} />} severity="info" sx={{ mb: 2 }}>
      {busy}… LLM steps can take a minute or two, keep this tab open.
    </Alert>
  ) : null;

export const Section: React.FC<{ title: React.ReactNode; action?: React.ReactNode; children: React.ReactNode }> = ({
  title,
  action,
  children,
}) => (
  <Box sx={{ mb: 3 }}>
    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
      <Typography variant="h6">{title}</Typography>
      {action}
    </Stack>
    {children}
  </Box>
);

/** Free-text chip input: type and press Enter to add. */
export const ChipInput: React.FC<{
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}> = ({ label, values, onChange, placeholder }) => {
  const [text, setText] = React.useState("");
  const add = () => {
    const v = text.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setText("");
  };
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mb: 0.5 }}>
        {values.map((v) => (
          <Chip key={v} label={v} size="small" onDelete={() => onChange(values.filter((x) => x !== v))} />
        ))}
      </Stack>
      <input
        value={text}
        placeholder={placeholder ?? "type and press Enter"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        style={{ width: "100%", padding: "8px 10px", border: "1px solid #ccd", borderRadius: 8, font: "inherit" }}
      />
    </Box>
  );
};
