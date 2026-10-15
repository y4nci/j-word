// src/theme/theme.ts — same look as autoreview
import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    primary: { main: "#646CFF" },
    secondary: { main: "#ff6b6b" },
    background: { default: "#f5f7fb" },
  },
  shape: { borderRadius: 16 },
  components: {
    MuiButton: { styleOverrides: { root: { textTransform: "none", borderRadius: 999 } } },
    MuiChip: { styleOverrides: { root: { borderRadius: 999 } } },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: "1px solid #e6e8f0" } } },
  },
});
