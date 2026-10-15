import React from "react";
import { AppBar, Box, Button, Container, Toolbar, Typography } from "@mui/material";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import { Link as RouterLink } from "react-router-dom";

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
    <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: "1px solid #e6e8f0" }}>
      <Toolbar>
        <WorkOutlineIcon color="primary" sx={{ mr: 1 }} />
        <Typography variant="h6" component={RouterLink} to="/" sx={{ color: "inherit", textDecoration: "none", flex: 1 }}>
          jword
        </Typography>
        <Button component={RouterLink} to="/">Profiles</Button>
      </Toolbar>
    </AppBar>
    <Container maxWidth="lg" sx={{ py: 3 }}>
      {children}
    </Container>
  </Box>
);
