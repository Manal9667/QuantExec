import React, { useState } from "react";
import Dashboard from "./components/dashboard.jsx";
import NewExperiment from "./components/newexperiment.jsx";
import ExperimentDetail from "./components/experimentdetail.jsx";
import Compare from "./components/compare.jsx";

// Four views, switched by plain state - react-router would be one more
// dependency for a four-screen internal tool (Rule 9, spec section 40).
export default function App() {
  const [view, setView] = useState("dashboard"); // dashboard | new | detail | compare
  const [activeExperimentId, setActiveExperimentId] = useState(null);

  function openExperiment(id) {
    setActiveExperimentId(id);
    setView("detail");
  }

  return (
    <div className="app">
      <div className="nav">
        <button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>
          Dashboard
        </button>
        <button className={view === "new" ? "active" : ""} onClick={() => setView("new")}>
          New experiment
        </button>
        <button className={view === "compare" ? "active" : ""} onClick={() => setView("compare")}>
          Strategy comparison
        </button>
      </div>

      {view === "dashboard" && (
        <Dashboard onOpenExperiment={openExperiment} onNewExperiment={() => setView("new")} />
      )}
      {view === "new" && <NewExperiment onCreated={openExperiment} />}
      {view === "detail" && activeExperimentId != null && (
        <ExperimentDetail experimentId={activeExperimentId} onBack={() => setView("dashboard")} />
      )}
      {view === "compare" && <Compare onOpenExperiment={openExperiment} />}
    </div>
  );
}