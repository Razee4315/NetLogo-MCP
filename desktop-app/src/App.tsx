import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Activity,
  BarChart3,
  BellDot,
  Bot,
  CirclePlay,
  Clock3,
  Code2,
  Database,
  FileChartColumnIncreasing,
  FolderKanban,
  Grid2x2,
  Play,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  TerminalSquare,
  Workflow,
} from "lucide-react";
import "./App.css";

type PageId = "dashboard" | "editor" | "runs" | "results" | "settings";

type ShellState = {
  mode: string;
  workspaceLabel: string;
  backendStatus: string;
  storageMode: string;
};

type NavItem = {
  id: PageId;
  label: string;
  icon: typeof Grid2x2;
  description: string;
};

const navItems: NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: Grid2x2,
    description: "Overview, recent projects, and quick launch actions.",
  },
  {
    id: "editor",
    label: "Model Editor",
    icon: Code2,
    description: "Code, parameters, and world preview in one workspace.",
  },
  {
    id: "runs",
    label: "Simulation Runs",
    icon: CirclePlay,
    description: "Run controls, live metrics, and execution timeline.",
  },
  {
    id: "results",
    label: "Results",
    icon: FileChartColumnIncreasing,
    description: "Charts, comparisons, and saved experiment outputs.",
  },
  {
    id: "settings",
    label: "Local Settings",
    icon: Settings,
    description: "Workspace, files, and desktop preferences only.",
  },
];

const runRows = [
  {
    name: "Predator-Prey Baseline",
    updated: "2 min ago",
    status: "Ready",
    output: "Wolves stabilize after tick 220",
  },
  {
    name: "Urban Traffic Flow",
    updated: "18 min ago",
    status: "Running",
    output: "Density spike detected on west corridor",
  },
  {
    name: "Disease Spread Sandbox",
    updated: "Yesterday",
    status: "Complete",
    output: "Peak infection at day 16",
  },
];

const logEntries = [
  "Loaded `wolf-sheep-predation.nlogo` from local workspace.",
  "Applied parameters: sheep=120, wolves=24, grass-regrowth=30.",
  "Setup complete. World dimensions: 101 x 101.",
  "Run active. Metrics update every 10 ticks.",
];

const resultsRows = [
  ["Baseline", "312", "0.71", "Stable"],
  ["High Grass", "401", "0.82", "Stable"],
  ["Low Wolves", "522", "0.64", "Oscillating"],
  ["Dense Start", "188", "0.49", "Collapsed"],
];

function StatusBadge({ label }: { label: string }) {
  return <span className="status-badge">{label}</span>;
}

function SectionHeading({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="section-heading">
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
  );
}

function DashboardPage({ shellState }: { shellState: ShellState | null }) {
  return (
    <div className="page-grid">
      <section className="hero-card">
        <div className="hero-copy">
          <SectionHeading
            eyebrow="Local Research Workspace"
            title="Build, run, and study agent-based models from one calm desktop flow."
            subtitle="This first boilerplate is focused on the product shell: clean navigation, strong hierarchy, and a local-only structure we can grow into a real NetLogo desktop app."
          />

          <div className="hero-actions">
            <button className="primary-button" type="button">
              <CirclePlay size={16} />
              Continue Last Project
            </button>
            <button className="ghost-button" type="button">
              <Workflow size={16} />
              New Local Workspace
            </button>
          </div>
        </div>

        <div className="hero-panel">
          <div className="hero-panel-header">
            <span>Shell Status</span>
            <StatusBadge label={shellState?.mode ?? "Loading"} />
          </div>

          <div className="metric-stack">
            <article className="metric-card accent-teal">
              <span>Backend</span>
              <strong>{shellState?.backendStatus ?? "Preparing..."}</strong>
              <p>Python bridge will plug into this shell next.</p>
            </article>
            <article className="metric-card accent-blue">
              <span>Storage</span>
              <strong>{shellState?.storageMode ?? "Local files"}</strong>
              <p>Runs, exports, and settings remain on this machine.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="stats-grid">
        <article className="glass-card stat-card">
          <span>Active Projects</span>
          <strong>08</strong>
          <p>Three models edited this week.</p>
        </article>
        <article className="glass-card stat-card">
          <span>Queued Runs</span>
          <strong>14</strong>
          <p>Two are ready to replay with new parameters.</p>
        </article>
        <article className="glass-card stat-card">
          <span>Exports Saved</span>
          <strong>126</strong>
          <p>Charts, PNG snapshots, and run summaries.</p>
        </article>
      </section>

      <section className="glass-card full-width">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Recent Work</span>
            <h3>Projects and latest outcomes</h3>
          </div>
          <button className="ghost-button small" type="button">
            View All
          </button>
        </div>

        <div className="table-list">
          {runRows.map((row) => (
            <article className="table-row" key={row.name}>
              <div>
                <strong>{row.name}</strong>
                <span>{row.updated}</span>
              </div>
              <div>
                <StatusBadge label={row.status} />
              </div>
              <p>{row.output}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="two-col-grid full-width">
        <article className="glass-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Quick Launch</span>
              <h3>Start from a familiar workflow</h3>
            </div>
          </div>
          <div className="shortcut-grid">
            <button className="shortcut-card" type="button">
              <Code2 size={18} />
              <strong>Open Model Editor</strong>
              <span>Resume coding and tune parameters.</span>
            </button>
            <button className="shortcut-card" type="button">
              <Activity size={18} />
              <strong>Launch Baseline Run</strong>
              <span>Replay the most recent scenario locally.</span>
            </button>
            <button className="shortcut-card" type="button">
              <BarChart3 size={18} />
              <strong>Review Results</strong>
              <span>Inspect charts, trends, and saved exports.</span>
            </button>
          </div>
        </article>

        <article className="glass-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Today</span>
              <h3>What the app will optimize for</h3>
            </div>
          </div>
          <ul className="bullet-list">
            <li>Keep every workflow local-first and beginner-friendly.</li>
            <li>Make simulation state readable without opening raw files.</li>
            <li>Treat AI assistance as optional, not required.</li>
          </ul>
        </article>
      </section>
    </div>
  );
}

function EditorPage() {
  return (
    <div className="editor-layout">
      <section className="glass-card editor-sidebar">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Project Files</span>
            <h3>Predator-Prey Study</h3>
          </div>
        </div>
        <div className="file-tree">
          {[
            "models/wolf-sheep-predation.nlogo",
            "exports/views/view_0008.png",
            "exports/worlds/baseline.csv",
            "notes/experiment-plan.md",
          ].map((item) => (
            <button className="file-item" key={item} type="button">
              <TerminalSquare size={16} />
              <span>{item}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="glass-card editor-main">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Editor</span>
            <h3>setup / go procedures</h3>
          </div>
          <div className="tab-row">
            <button className="tab active" type="button">
              Code
            </button>
            <button className="tab" type="button">
              Blocks
            </button>
            <button className="tab" type="button">
              Notes
            </button>
          </div>
        </div>

        <div className="code-surface">
          <div className="code-line">
            <span>globals [ grass-regrowth ]</span>
          </div>
          <div className="code-line">
            <span>to setup</span>
          </div>
          <div className="code-line indent">
            <span>clear-all</span>
          </div>
          <div className="code-line indent">
            <span>setup-patches</span>
          </div>
          <div className="code-line indent">
            <span>create-sheep initial-sheep [ wander ]</span>
          </div>
          <div className="code-line indent">
            <span>reset-ticks</span>
          </div>
          <div className="code-line">
            <span>end</span>
          </div>
          <div className="code-line">
            <span>to go</span>
          </div>
          <div className="code-line indent">
            <span>ask turtles [ move eat reproduce ]</span>
          </div>
          <div className="code-line indent">
            <span>tick</span>
          </div>
          <div className="code-line">
            <span>end</span>
          </div>
        </div>
      </section>

      <section className="glass-card editor-inspector">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Inspector</span>
            <h3>Parameters & Preview</h3>
          </div>
        </div>

        <div className="inspector-stack">
          <div className="control-card">
            <label>Initial sheep</label>
            <input type="range" min="20" max="200" value="120" readOnly />
          </div>
          <div className="control-card">
            <label>Initial wolves</label>
            <input type="range" min="5" max="50" value="24" readOnly />
          </div>
          <div className="preview-card">
            <span>World Preview</span>
            <div className="mini-world" />
          </div>
        </div>
      </section>
    </div>
  );
}

function RunsPage() {
  return (
    <div className="page-grid">
      <section className="glass-card run-stage">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Live Simulation</span>
            <h3>Predator-Prey Baseline</h3>
          </div>
          <StatusBadge label="Running" />
        </div>

        <div className="world-stage">
          <div className="world-grid" />
        </div>

        <div className="control-strip">
          <button className="primary-button" type="button">
            <Play size={16} />
            Pause
          </button>
          <button className="ghost-button" type="button">
            <Clock3 size={16} />
            Tick 245 / 500
          </button>
          <button className="ghost-button" type="button">
            <SlidersHorizontal size={16} />
            Scenario Controls
          </button>
        </div>
      </section>

      <section className="stats-grid">
        <article className="glass-card stat-card">
          <span>Sheep</span>
          <strong>182</strong>
          <p>Up 12% over the last 40 ticks.</p>
        </article>
        <article className="glass-card stat-card">
          <span>Wolves</span>
          <strong>27</strong>
          <p>Holding near baseline range.</p>
        </article>
        <article className="glass-card stat-card">
          <span>Grass Cover</span>
          <strong>63%</strong>
          <p>Healthy recovery after early dip.</p>
        </article>
      </section>

      <section className="two-col-grid full-width">
        <article className="glass-card chart-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Trend</span>
              <h3>Population dynamics</h3>
            </div>
          </div>
          <div className="chart-placeholder line-chart" />
        </article>

        <article className="glass-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Run Log</span>
              <h3>Execution events</h3>
            </div>
          </div>
          <div className="log-list">
            {logEntries.map((entry) => (
              <div className="log-item" key={entry}>
                <span className="log-dot" />
                <p>{entry}</p>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}

function ResultsPage() {
  return (
    <div className="page-grid">
      <section className="stats-grid">
        <article className="glass-card stat-card">
          <span>Best Stability Score</span>
          <strong>0.82</strong>
          <p>Recorded in the High Grass scenario.</p>
        </article>
        <article className="glass-card stat-card">
          <span>Average Runtime</span>
          <strong>48s</strong>
          <p>Across the four latest local runs.</p>
        </article>
        <article className="glass-card stat-card">
          <span>Saved Comparisons</span>
          <strong>12</strong>
          <p>Reusable experiment snapshots.</p>
        </article>
      </section>

      <section className="two-col-grid full-width">
        <article className="glass-card chart-card large">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Analytics</span>
              <h3>Scenario comparison</h3>
            </div>
          </div>
          <div className="chart-placeholder bar-chart" />
        </article>

        <article className="glass-card chart-card large">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Spatial View</span>
              <h3>Patch distribution heatmap</h3>
            </div>
          </div>
          <div className="chart-placeholder heatmap-chart" />
        </article>
      </section>

      <section className="glass-card full-width">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Saved Results</span>
            <h3>Latest experiment table</h3>
          </div>
          <button className="ghost-button small" type="button">
            Export CSV
          </button>
        </div>
        <div className="results-table">
          <div className="results-head">
            <span>Scenario</span>
            <span>Ticks</span>
            <span>Stability</span>
            <span>Outcome</span>
          </div>
          {resultsRows.map((row) => (
            <div className="results-row" key={row[0]}>
              {row.map((cell) => (
                <span key={cell}>{cell}</span>
              ))}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SettingsPage({ shellState }: { shellState: ShellState | null }) {
  return (
    <div className="two-col-grid settings-grid">
      <section className="glass-card">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Local Preferences</span>
            <h3>Desktop behavior</h3>
          </div>
        </div>
        <div className="settings-list">
          <div className="setting-row">
            <div>
              <strong>Workspace Mode</strong>
              <span>{shellState?.mode ?? "Local workspace"}</span>
            </div>
            <StatusBadge label="Enabled" />
          </div>
          <div className="setting-row">
            <div>
              <strong>Run History</strong>
              <span>Save experiment metadata locally</span>
            </div>
            <StatusBadge label="On" />
          </div>
          <div className="setting-row">
            <div>
              <strong>Export Snapshots</strong>
              <span>Write PNG and CSV outputs to project folders</span>
            </div>
            <StatusBadge label="Auto" />
          </div>
        </div>
      </section>

      <section className="glass-card">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Folders</span>
            <h3>Current local paths</h3>
          </div>
        </div>
        <div className="path-stack">
          <div className="path-card">
            <Database size={18} />
            <div>
              <strong>Models Directory</strong>
              <span>./models</span>
            </div>
          </div>
          <div className="path-card">
            <BarChart3 size={18} />
            <div>
              <strong>Exports Directory</strong>
              <span>./exports</span>
            </div>
          </div>
          <div className="path-card">
            <Workflow size={18} />
            <div>
              <strong>Future Local DB</strong>
              <span>./desktop-app/data/app.sqlite</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function App() {
  const [activePage, setActivePage] = useState<PageId>("dashboard");
  const [shellState, setShellState] = useState<ShellState | null>(null);

  useEffect(() => {
    invoke<ShellState>("get_shell_state")
      .then(setShellState)
      .catch(() => {
        setShellState({
          mode: "Local workspace",
          workspaceLabel: "MCP_NetLogo",
          backendStatus: "Backend bridge pending",
          storageMode: "SQLite + files",
        });
      });
  }, []);

  const activeItem =
    navItems.find((item) => item.id === activePage) ?? navItems[0];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <div className="brand-mark">
            <Bot size={18} />
          </div>
          <div>
            <p className="brand-name">MCP NetLogo</p>
            <span className="brand-subtitle">Desktop Studio</span>
          </div>
        </div>

        <div className="sidebar-group">
          <span className="sidebar-label">Workspace</span>
          <button className="workspace-chip" type="button">
            <FolderKanban size={16} />
            <span>{shellState?.workspaceLabel ?? "Loading workspace..."}</span>
          </button>
        </div>

        <nav className="nav-list" aria-label="Primary">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = item.id === activePage;

            return (
              <button
                key={item.id}
                className={`nav-item${isActive ? " active" : ""}`}
                type="button"
                onClick={() => setActivePage(item.id)}
              >
                <Icon size={18} />
                <div>
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </div>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="assistant-card">
            <div className="assistant-icon">
              <Sparkles size={18} />
            </div>
            <div>
              <strong>Local-first mode</strong>
              <p>UI now, AI bridge next. No API setup needed for v1.</p>
            </div>
          </div>
        </div>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div>
            <p className="page-kicker">Product Preview</p>
            <h1>{activeItem.label}</h1>
          </div>

          <div className="topbar-actions">
            <label className="search-pill">
              <Search size={16} />
              <input
                aria-label="Search"
                placeholder="Search projects, runs, or models"
              />
            </label>
            <button className="ghost-button" type="button">
              <BellDot size={16} />
              Activity
            </button>
            <button className="primary-button" type="button">
              <Play size={16} />
              Run Simulation
            </button>
          </div>
        </header>

        <div className="page-content">
          {activePage === "dashboard" && <DashboardPage shellState={shellState} />}
          {activePage === "editor" && <EditorPage />}
          {activePage === "runs" && <RunsPage />}
          {activePage === "results" && <ResultsPage />}
          {activePage === "settings" && <SettingsPage shellState={shellState} />}
        </div>
      </section>
    </main>
  );
}

export default App;
