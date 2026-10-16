import React, { useCallback, useState } from "react";
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Chip,
  FormControlLabel,
  Link,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { Link as RouterLink, useParams } from "react-router-dom";
import { client } from "../api/client";
import { latestDecision } from "../api/types";
import type { ApplicationStatus } from "../api/types";
import { BusyBanner, ErrorAlert, FitBar, Section, StatusChip } from "../components/common";
import { JobSummaryDetails } from "../components/JobSummary";
import { useAsync, useResource } from "../hooks/useAsync";

// Mirrors ALLOWED_TRANSITIONS in backend/src/applications/models.py; the backend still enforces it.
const CAN_EDIT: ApplicationStatus[] = ["drafted", "approved", "prepared", "failed", "rejected"];
const CAN_REGENERATE: ApplicationStatus[] = ["drafted", "approved", "rejected", "prepared", "failed"];
const CAN_REJECT: ApplicationStatus[] = ["drafted", "approved"];
const FACT_CHECK_FAILED = "(fact check did not run)";

export const ApplicationPage: React.FC = () => {
  const { applicationId = "" } = useParams();
  const fetcher = useCallback(() => client.getApplication(applicationId), [applicationId]);
  const { data: view, error: loadError, reload } = useResource(fetcher);
  // Unsaved edits on top of the stored draft.
  const [edits, setEdits] = useState<{ subject?: string; letter?: string; pitch?: string }>({});
  const [autofill, setAutofill] = useState(true);
  const { busy, error, setError, run } = useAsync();

  if (!view) return <ErrorAlert error={loadError} />;
  const { application: app, job } = view;
  const draft = app.draft;
  const decision = latestDecision(app);
  // drafting_service reports a failed check as this placeholder claim.
  const checkFailure = draft?.unsupported_claims.find((c) => c.claim === FACT_CHECK_FAILED);
  const claims = (draft?.unsupported_claims ?? []).filter((c) => c.claim !== FACT_CHECK_FAILED);
  const subject = edits.subject ?? draft?.subject ?? "";
  const letter = edits.letter ?? draft?.cover_letter ?? "";
  const pitch = edits.pitch ?? draft?.short_pitch ?? "";
  const dirty = !!draft && (subject !== draft.subject || letter !== draft.cover_letter || pitch !== draft.short_pitch);
  const setSubject = (v: string) => setEdits({ ...edits, subject: v });
  const setLetter = (v: string) => setEdits({ ...edits, letter: v });
  const setPitch = (v: string) => setEdits({ ...edits, pitch: v });
  const action = (label: string, fn: () => Promise<unknown>) =>
    run(label, async () => { await fn(); setEdits({}); reload(); });

  return (
    <>
      <Button component={RouterLink} to={`/searches/${app.search_id}`} sx={{ mb: 1 }}>← Back to search</Button>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 0.5 }}>
        <Typography variant="h4">{job.title}</Typography>
        <StatusChip status={app.status} size="medium" />
      </Stack>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {job.company} · {job.location ?? "n/a"} · {job.work_mode} ·{" "}
        <Link href={job.url} target="_blank" rel="noreferrer">posting</Link>
        {job.apply_url && job.apply_url !== job.url && <> · <Link href={job.apply_url} target="_blank" rel="noreferrer">apply page</Link></>}
      </Typography>
      <ErrorAlert error={error ?? loadError} onClose={() => setError(null)} />
      <BusyBanner busy={busy} />

      {app.status === "prepared" && app.package && (
        <Alert severity="success" sx={{ mb: 2 }}>
          <AlertTitle>Ready to submit, by you</AlertTitle>
          {app.package.autofill
            ? "A browser window opened with the form filled in. Check every field, answer any custom questions, and click submit there."
            : "Apply on the company site using the files below."}
          <ul style={{ margin: "8px 0" }}>
            {app.package.autofill_report.map((l) => <li key={l}>{l}</li>)}
          </ul>
          <Typography variant="body2">
            Package folder: <code>{app.package.directory}</code> ·{" "}
            <Link href={client.coverLetterPdfUrl(app.id)} target="_blank" rel="noreferrer">open cover letter PDF</Link>
          </Typography>
        </Alert>
      )}

      <Stack direction={{ xs: "column", md: "row" }} spacing={3} alignItems="flex-start">
        {/* ---------------- left: draft editor ---------------- */}
        <Box sx={{ flex: 3, width: "100%" }}>
          {!draft ? (
            <Alert severity="info">No draft yet.</Alert>
          ) : (
            <Section title={<>Draft <Chip size="small" label={draft.language} sx={{ ml: 1 }} />{draft.edited_by_human && <Chip size="small" label="edited by you" sx={{ ml: 1 }} />}</>}>
              {checkFailure ? (
                <Alert severity="error" sx={{ mb: 2 }}>
                  <AlertTitle>The fact check did not run. Read the letter carefully yourself.</AlertTitle>
                  {checkFailure.why}
                </Alert>
              ) : claims.length > 0 ? (
                <Alert severity="warning" sx={{ mb: 2 }}>
                  <AlertTitle>Fact check: {claims.length} statement(s) not backed by your profile</AlertTitle>
                  <ul style={{ margin: 0 }}>
                    {claims.map((c) => (
                      <li key={c.claim}><b>{c.claim}</b>{c.why && <> ({c.why})</>}</li>
                    ))}
                  </ul>
                  Edit them out, or add the fact to your profile if it's true.
                </Alert>
              ) : (
                <Alert severity="success" sx={{ mb: 2 }}>Fact check: every statement about you is backed by your profile.</Alert>
              )}
              <Paper sx={{ p: 2 }}>
                <Stack spacing={2}>
                  <TextField label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!CAN_EDIT.includes(app.status)} fullWidth />
                  <TextField
                    label="Cover letter"
                    value={letter}
                    onChange={(e) => setLetter(e.target.value)}
                    disabled={!CAN_EDIT.includes(app.status)}
                    multiline
                    minRows={14}
                    fullWidth
                    helperText={`${letter.trim().split(/\s+/).filter(Boolean).length} words`}
                  />
                  <TextField
                    label="Short pitch (for 'anything else?' form fields)"
                    value={pitch}
                    onChange={(e) => setPitch(e.target.value)}
                    disabled={!CAN_EDIT.includes(app.status)}
                    multiline
                    minRows={2}
                    fullWidth
                  />
                </Stack>
              </Paper>
            </Section>
          )}

          {/* ---------------- actions ---------------- */}
          <Paper sx={{ p: 2, mb: 3 }}>
            {dirty && app.status !== "drafted" && (
              <Alert severity="info" sx={{ mb: 2 }}>Saving edits clears the current approval; you'll approve the new text again.</Alert>
            )}
            <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
              {draft && CAN_EDIT.includes(app.status) && (
                <Button
                  variant="outlined"
                  disabled={!dirty || busy !== null}
                  onClick={() => action("Saving edits and re-running the fact check", () =>
                    client.editDraft(app.id, { subject, cover_letter: letter, short_pitch: pitch }))}
                >
                  Save edits
                </Button>
              )}
              {dirty && <Button disabled={busy !== null} onClick={() => setEdits({})}>Discard edits</Button>}
              {(app.status === "screened_in" || CAN_REGENERATE.includes(app.status)) && (
                <Button disabled={busy !== null} onClick={() => action("Drafting cover letter", () => client.draftOne(app.id))}>
                  {draft ? "Regenerate" : "Generate draft"}
                </Button>
              )}
              <Box sx={{ flex: 1 }} />
              {CAN_REJECT.includes(app.status) && (
                <Button color="error" disabled={busy !== null} onClick={() => action("Rejecting", () => client.reject(app.id))}>
                  Don't apply
                </Button>
              )}
              {app.status === "drafted" && (
                <Button
                  variant="contained"
                  color="success"
                  disabled={dirty || busy !== null}
                  title={dirty ? "Save your edits first" : undefined}
                  onClick={() => action("Approving", () => client.approve(app.id))}
                >
                  Approve this exact text
                </Button>
              )}
              {app.status === "approved" && (
                <>
                  <FormControlLabel
                    control={<Switch checked={autofill} onChange={(e) => setAutofill(e.target.checked)} />}
                    label="Open browser autofill"
                  />
                  <Button
                    variant="contained"
                    disabled={dirty || busy !== null}
                    onClick={() => action("Building package" + (autofill ? " and opening the form" : ""), () => client.prepare(app.id, autofill))}
                  >
                    Prepare application
                  </Button>
                </>
              )}
              {app.status === "prepared" && (
                <Button variant="contained" color="success" disabled={busy !== null} onClick={() => action("Saving", () => client.markApplied(app.id))}>
                  I submitted it
                </Button>
              )}
              {app.status === "applied" && <Chip color="success" label="Applied" />}
            </Stack>
          </Paper>
        </Box>

        {/* ---------------- right: context ---------------- */}
        <Box sx={{ flex: 2, width: "100%" }}>
          <Section title="At a glance">
            <Paper sx={{ p: 2 }}>
              <JobSummaryDetails job={job} />
            </Paper>
          </Section>

          {decision && (
            <Section title="Screening">
              <Paper sx={{ p: 2 }}>
                <FitBar value={decision.fit_score} />
                <Typography variant="body2" sx={{ mt: 1 }}>{decision.reason}</Typography>
                {decision.missing_requirements.length > 0 && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    Missing: {decision.missing_requirements.join("; ")}
                  </Typography>
                )}
              </Paper>
            </Section>
          )}

          {draft && draft.requirement_matches.length > 0 && (
            <Section title="Requirement coverage">
              <Paper sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow><TableCell>Requirement</TableCell><TableCell>Evidence</TableCell></TableRow>
                  </TableHead>
                  <TableBody>
                    {draft.requirement_matches.map((m) => (
                      <TableRow key={m.requirement}>
                        <TableCell sx={{ verticalAlign: "top" }}>
                          {m.requirement}
                          <Box>{m.experience_ids.length ? m.experience_ids.map((id) => <Chip key={id} size="small" label={id} sx={{ mr: 0.5 }} />) : <Chip size="small" color="warning" label="not covered" />}</Box>
                        </TableCell>
                        <TableCell sx={{ verticalAlign: "top" }}><Typography variant="body2">{m.evidence}</Typography></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Paper>
            </Section>
          )}

          <Section title="History">
            <Paper sx={{ p: 2 }}>
              {app.history.map((h, i) => (
                <Stack key={i} direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ width: 120 }}>{new Date(h.at).toLocaleString()}</Typography>
                  <StatusChip status={h.to_status} />
                  <Typography variant="caption">by {h.actor_type}{h.note && ` – ${h.note}`}</Typography>
                </Stack>
              ))}
            </Paper>
          </Section>

          <Section title="Job description">
            <Paper sx={{ p: 2, maxHeight: 420, overflowY: "auto", whiteSpace: "pre-wrap" }}>
              <Typography variant="body2">{job.description || "(no description)"}</Typography>
            </Paper>
          </Section>
        </Box>
      </Stack>
    </>
  );
};
