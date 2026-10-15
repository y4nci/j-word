import React, { useCallback, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardActionArea,
  CardContent,
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
import type { CandidateProfile, Experience } from "../api/types";
import { BusyBanner, ChipInput, ErrorAlert, Section } from "../components/common";
import { useAsync, useResource } from "../hooks/useAsync";

const KINDS: Experience["kind"][] = ["job", "project", "education", "volunteering", "other"];

export const ProfilePage: React.FC = () => {
  const { profileId = "" } = useParams();
  const navigate = useNavigate();
  const fetcher = useCallback(
    () => Promise.all([client.getProfile(profileId), client.listSearches(profileId)]),
    [profileId]
  );
  const { data, error: loadError, reload } = useResource(fetcher);
  // Unsaved edits live here; null = showing the stored profile.
  const [edited, setEdited] = useState<CandidateProfile | null>(null);
  const { busy, error, setError, run } = useAsync();

  if (!data) return <ErrorAlert error={loadError} />;
  const [stored, searches] = data;
  const profile = edited ?? stored;
  const dirty = edited !== null;

  const update = (patch: Partial<CandidateProfile>) => setEdited({ ...profile, ...patch });
  const updateExp = (i: number, patch: Partial<Experience>) =>
    update({ experiences: profile.experiences.map((e, j) => (j === i ? { ...e, ...patch } : e)) });
  const addExp = () => {
    const nextId = Math.max(0, ...profile.experiences.map((e) => Number(e.id.replace("exp-", "")) || 0)) + 1;
    update({
      experiences: [
        ...profile.experiences,
        { id: `exp-${nextId}`, kind: "project", title: "", organization: null, start: null, end: null, summary: "", skills: [], highlights: [] },
      ],
    });
  };

  return (
    <>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
        <Typography variant="h4">{profile.full_name || "Profile"}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate(`/profiles/${profile.id}/search/new`)}>
          New search
        </Button>
      </Stack>
      <ErrorAlert error={error ?? loadError} onClose={() => setError(null)} />
      <BusyBanner busy={busy} />

      {searches.length > 0 && (
        <Section title="Searches">
          <Stack gap={1}>
            {searches.map((s) => (
              <Card key={s.id}>
                <CardActionArea onClick={() => navigate(`/searches/${s.id}`)}>
                  <CardContent sx={{ py: 1.5 }}>
                    <Typography variant="body1" noWrap>{s.plan?.refined_goal ?? s.prompt}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {s.status} · {new Date(s.created_at).toLocaleString()}
                    </Typography>
                  </CardContent>
                </CardActionArea>
              </Card>
            ))}
          </Stack>
        </Section>
      )}

      <Alert severity="info" sx={{ mb: 2 }}>
        Check this once: drafts may only use facts from this profile, and the fact check compares letters against it.
      </Alert>

      <Section
        title="Profile"
        action={
          <Stack direction="row" spacing={1}>
            {dirty && <Button onClick={() => setEdited(null)}>Discard</Button>}
            <Button
              variant="contained"
              disabled={!dirty || busy !== null}
              onClick={() => run("Saving", async () => { await client.updateProfile(profile); setEdited(null); reload(); })}
            >
              Save profile
            </Button>
          </Stack>
        }
      >
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Full name" value={profile.full_name} onChange={(e) => update({ full_name: e.target.value })} fullWidth />
              <TextField label="Email" value={profile.email} onChange={(e) => update({ email: e.target.value })} fullWidth />
              <TextField label="Phone" value={profile.phone ?? ""} onChange={(e) => update({ phone: e.target.value || null })} fullWidth />
              <TextField label="City" value={profile.location ?? ""} onChange={(e) => update({ location: e.target.value || null })} fullWidth />
            </Stack>
            <TextField label="Headline" value={profile.headline} onChange={(e) => update({ headline: e.target.value })} fullWidth />
            <ChipInput label="Skills" values={profile.skills} onChange={(skills) => update({ skills })} />
            <ChipInput label="Languages" values={profile.languages} onChange={(languages) => update({ languages })} placeholder="e.g. German (C1)" />
            <ChipInput
              label="Links (name=url)"
              values={Object.entries(profile.links).map(([k, v]) => `${k}=${v}`)}
              onChange={(vals) =>
                update({ links: Object.fromEntries(vals.map((v) => v.split(/=(.*)/s)).filter((kv) => kv[1]).map(([k, v]) => [k.trim(), v.trim()])) })
              }
              placeholder="linkedin=https://..."
            />
          </Stack>
        </Paper>
      </Section>

      <Section title={`Experiences (${profile.experiences.length})`} action={<Button startIcon={<AddIcon />} onClick={addExp}>Add</Button>}>
        <Stack spacing={2}>
          {profile.experiences.map((exp, i) => (
            <Paper key={exp.id} sx={{ p: 2 }}>
              <Stack spacing={1.5}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
                  <Typography variant="caption" sx={{ minWidth: 44 }}>{exp.id}</Typography>
                  <TextField select size="small" label="Kind" value={exp.kind} onChange={(e) => updateExp(i, { kind: e.target.value as Experience["kind"] })} sx={{ minWidth: 130, flexShrink: 0 }}>
                    {KINDS.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                  </TextField>
                  <TextField size="small" label="Title" value={exp.title} onChange={(e) => updateExp(i, { title: e.target.value })} fullWidth />
                  <TextField size="small" label="Organization" value={exp.organization ?? ""} onChange={(e) => updateExp(i, { organization: e.target.value || null })} fullWidth />
                  <TextField size="small" label="Start" value={exp.start ?? ""} onChange={(e) => updateExp(i, { start: e.target.value || null })} sx={{ width: 120, flexShrink: 0 }} />
                  <TextField size="small" label="End" value={exp.end ?? ""} onChange={(e) => updateExp(i, { end: e.target.value || null })} sx={{ width: 120, flexShrink: 0 }} />
                  <IconButton aria-label="remove experience" onClick={() => update({ experiences: profile.experiences.filter((_, j) => j !== i) })}>
                    <DeleteOutlineIcon />
                  </IconButton>
                </Stack>
                <TextField size="small" label="What you did" multiline minRows={3} value={exp.summary} onChange={(e) => updateExp(i, { summary: e.target.value })} />
                <ChipInput label="Highlights (concrete, verifiable)" values={exp.highlights} onChange={(highlights) => updateExp(i, { highlights })} />
                <ChipInput label="Skills used" values={exp.skills} onChange={(skills) => updateExp(i, { skills })} />
              </Stack>
            </Paper>
          ))}
        </Stack>
      </Section>
    </>
  );
};
