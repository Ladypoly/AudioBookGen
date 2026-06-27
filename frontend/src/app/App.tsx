import { useCallback, useEffect, useState } from "react";
import { api, type ProjectSummary } from "../lib/api";
import { useJobs } from "../lib/useJobs";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { QueueStrip } from "./QueueStrip";
import { SetupWizard } from "./SetupWizard";
import { Dashboard } from "../screens/Dashboard";
import { Characters } from "../screens/Characters";
import { Chapters } from "../screens/Chapters";
import { Settings } from "../screens/Settings";

export type Route = "dashboard" | "characters" | "chapters" | "settings";

export interface ActiveProject {
  id: string;
  title: string;
}

export function App() {
  const [route, setRoute] = useState<Route>("dashboard");
  const [project, setProject] = useState<ActiveProject | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const jobs = useJobs();

  // Restore active project on load (the sidecar keeps it process-global).
  useEffect(() => {
    api.activeProject().then((r) => r.active && setProject(r.active)).catch(() => {});
  }, []);

  // First-run: pop the setup wizard if ComfyUI / the node isn't ready yet.
  useEffect(() => {
    api.setupStatus()
      .then((s) => { if (!s.comfy_dir_valid || !s.node_installed) setShowSetup(true); })
      .catch(() => {});
  }, []);

  const openById = useCallback(async (id: string) => {
    const active = await api.openProject(id);
    setProject(active);
    setRoute("characters");
  }, []);

  const openProject = useCallback((p: ProjectSummary) => openById(p.id), [openById]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <StatusBar project={project} />
      <div className="flex min-h-0 flex-1">
        <Sidebar
          route={route}
          setRoute={setRoute}
          hasProject={!!project}
        />
        <main className="min-w-0 flex-1 overflow-y-auto">
          {route === "dashboard" && <Dashboard onOpen={openProject} jobs={jobs} onCreated={openById} />}
          {route === "characters" && <Characters project={project} jobs={jobs} />}
          {route === "chapters" && <Chapters project={project} jobs={jobs} />}
          {route === "settings" && <Settings />}
        </main>
      </div>
      <QueueStrip jobs={jobs} />
      {showSetup && <SetupWizard jobs={jobs} onClose={() => setShowSetup(false)} />}
    </div>
  );
}
