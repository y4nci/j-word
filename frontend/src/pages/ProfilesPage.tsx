import React, { useState } from "react";
import {
  Button,
  Card,
  Chip,
  CardActionArea,
  CardContent,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { useNavigate } from "react-router-dom";
import { client } from "../api/client";
import { BusyBanner, ErrorAlert, Section } from "../components/common";
import { useAsync, useResource } from "../hooks/useAsync";

export const ProfilesPage: React.FC = () => {
  const navigate = useNavigate();
  const { data, error: loadError } = useResource(client.listProfiles);
  const profiles = data ?? [];
  const { busy, error, setError, run } = useAsync();

  return (
    <>
      <Typography variant="h4" sx={{ mb: 1 }}>Profiles</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        A profile is your CV plus your proto cover letter, turned into structured experiences.
        Cover letters may only use facts from it.
      </Typography>
      <ErrorAlert error={error ?? loadError} onClose={() => setError(null)} />
      <BusyBanner busy={busy} />

      {profiles.length > 0 && (
        <Section title="Existing profiles">
          <Stack direction={{ xs: "column", sm: "row" }} gap={2} flexWrap="wrap">
            {profiles.map((p) => (
              <Card key={p.id} sx={{ width: { xs: "100%", sm: 320 } }}>
                <CardActionArea onClick={() => navigate(`/profiles/${p.id}`)}>
                  <CardContent>
                    <Typography variant="subtitle1" fontWeight={600}>{p.full_name || "(no name)"}</Typography>
                    <Typography variant="body2" color="text.secondary" noWrap>{p.headline}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {p.experiences.length} experiences · {p.skills.length} skills · created{" "}
                      {new Date(p.created_at).toLocaleDateString()}
                    </Typography>
                  </CardContent>
                </CardActionArea>
              </Card>
            ))}
          </Stack>
        </Section>
      )}

      <Section title="New profile">
        <NewProfileForm
          disabled={busy !== null}
          onSubmit={(input) =>
            run("Extracting your profile", async () => {
              const profile = await client.createProfile(input);
              navigate(`/profiles/${profile.id}`);
            })
          }
        />
      </Section>
    </>
  );
};

const NewProfileForm: React.FC<{
  disabled: boolean;
  onSubmit: (input: Parameters<typeof client.createProfile>[0]) => void;
}> = ({ disabled, onSubmit }) => {
  const [cv, setCv] = useState<File | null>(null);
  const [letterFiles, setLetterFiles] = useState<File[]>([]);
  const [letter, setLetter] = useState("");
  const [fields, setFields] = useState({ fullName: "", email: "", phone: "", location: "", linkedin: "", github: "", website: "" });
  const set = (k: keyof typeof fields) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFields({ ...fields, [k]: e.target.value });

  const canSubmit = cv !== null && (letter.trim() !== "" || letterFiles.length > 0) && !disabled;
  const addLetterFiles = (files: FileList | null) => {
    const known = new Set(letterFiles.map((f) => f.name));
    setLetterFiles([...letterFiles, ...Array.from(files ?? []).filter((f) => !known.has(f.name))]);
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <Button variant="outlined" component="label" startIcon={<UploadFileIcon />}>
            {cv ? cv.name : "Upload CV (PDF / TXT / MD)"}
            <input hidden type="file" accept=".pdf,.txt,.md" onChange={(e) => setCv(e.target.files?.[0] ?? null)} />
          </Button>
          <Button variant="outlined" component="label" startIcon={<UploadFileIcon />}>
            Add cover letter files (any number)
            <input
              hidden
              multiple
              type="file"
              accept=".pdf,.txt,.md"
              onChange={(e) => {
                addLetterFiles(e.target.files);
                e.target.value = ""; // allow re-adding a file after removing it
              }}
            />
          </Button>
        </Stack>
        {letterFiles.length > 0 && (
          <Stack direction="row" gap={1} flexWrap="wrap">
            {letterFiles.map((f) => (
              <Chip key={f.name} label={f.name} onDelete={() => setLetterFiles(letterFiles.filter((x) => x !== f))} />
            ))}
          </Stack>
        )}
        <TextField
          label="Proto cover letter: what you did in each job / project, in your own words"
          multiline
          minRows={8}
          value={letter}
          onChange={(e) => setLetter(e.target.value)}
          helperText="Optional if you uploaded files. Text and all files are combined; this is the main source of facts for your letters."
        />
        <Typography variant="subtitle2">Contact details (override what's extracted from the CV)</Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField label="Full name" value={fields.fullName} onChange={set("fullName")} fullWidth />
          <TextField label="Email" value={fields.email} onChange={set("email")} fullWidth />
          <TextField label="Phone" value={fields.phone} onChange={set("phone")} fullWidth />
          <TextField label="City" value={fields.location} onChange={set("location")} fullWidth />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField label="LinkedIn URL" value={fields.linkedin} onChange={set("linkedin")} fullWidth />
          <TextField label="GitHub URL" value={fields.github} onChange={set("github")} fullWidth />
          <TextField label="Website" value={fields.website} onChange={set("website")} fullWidth />
        </Stack>
        <Stack direction="row" justifyContent="flex-end">
          <Button
            variant="contained"
            disabled={!canSubmit}
            onClick={() =>
              cv &&
              onSubmit({
                cv,
                protoCoverLetter: letter,
                protoCoverLetterFiles: letterFiles,
                fullName: fields.fullName,
                email: fields.email,
                phone: fields.phone,
                location: fields.location,
                links: Object.fromEntries(
                  (["linkedin", "github", "website"] as const).filter((k) => fields[k]).map((k) => [k, fields[k]])
                ),
              })
            }
          >
            Create profile
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
};
