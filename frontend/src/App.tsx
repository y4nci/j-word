import React from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProfilesPage } from "./pages/ProfilesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { NewSearchPage } from "./pages/NewSearchPage";
import { SearchPage } from "./pages/SearchPage";
import { ApplicationPage } from "./pages/ApplicationPage";

export const App: React.FC = () => (
  <BrowserRouter>
    <AppShell>
      <Routes>
        <Route path="/" element={<ProfilesPage />} />
        <Route path="/profiles/:profileId" element={<ProfilePage />} />
        <Route path="/profiles/:profileId/search/new" element={<NewSearchPage />} />
        <Route path="/searches/:searchId" element={<SearchPage />} />
        <Route path="/applications/:applicationId" element={<ApplicationPage />} />
      </Routes>
    </AppShell>
  </BrowserRouter>
);
