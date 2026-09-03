/* Clinical Signal Atlas: calm editorial Swiss information design, evidence-first hierarchy, and humane human-in-the-loop actions. */
import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bell,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Command,
  Database,
  FileText,
  Filter,
  Gauge,
  HeartPulse,
  LayoutDashboard,
  Menu,
  MoreHorizontal,
  PackageSearch,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Stethoscope,
  Users,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

type Priority = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
type Freshness = "FRESH" | "STALE" | "UNKNOWN";

type Equipment = {
  id: string;
  name: string;
  department: string;
  score: number;
  priority: Priority;
  downtime: string;
  repairEta: string;
  procedures: number;
  urgent: number;
  alternatives: string;
  freshness: Freshness;
  summary: string;
  factors: { label: string; value: number; tone: string }[];
};

const equipment: Equipment[] = [
  {
    id: "MRI-04",
    name: "Magnetic Resonance Imaging",
    department: "Neurology",
    score: 91,
    priority: "CRITICAL",
    downtime: "5h 12m",
    repairEta: "8h",
    procedures: 7,
    urgent: 3,
    alternatives: "1 of 3 available",
    freshness: "FRESH",
    summary:
      "Seven procedures are exposed, including three high-urgency studies. Only one alternative MRI is verified for the window.",
    factors: [
      { label: "Procedure urgency", value: 94, tone: "coral" },
      { label: "Affected procedures", value: 78, tone: "coral" },
      { label: "Alternative availability", value: 86, tone: "amber" },
      { label: "Service criticality", value: 90, tone: "coral" },
      { label: "Repair delay", value: 81, tone: "coral" },
    ],
  },
  {
    id: "VENT-12",
    name: "ICU Ventilator",
    department: "Critical Care",
    score: 86,
    priority: "CRITICAL",
    downtime: "2h 08m",
    repairEta: "3h",
    procedures: 2,
    urgent: 2,
    alternatives: "0 of 5 available",
    freshness: "FRESH",
    summary:
      "No verified substitute is available in the ICU. Two critical care episodes may be exposed while the repair window remains open.",
    factors: [
      { label: "Procedure urgency", value: 100, tone: "coral" },
      { label: "Affected procedures", value: 62, tone: "amber" },
      { label: "Alternative availability", value: 100, tone: "coral" },
      { label: "Service criticality", value: 100, tone: "coral" },
      { label: "Repair delay", value: 58, tone: "amber" },
    ],
  },
  {
    id: "CT-07",
    name: "Computed Tomography",
    department: "Emergency",
    score: 68,
    priority: "HIGH",
    downtime: "3h 44m",
    repairEta: "2h",
    procedures: 5,
    urgent: 1,
    alternatives: "2 of 4 available",
    freshness: "FRESH",
    summary:
      "The emergency service has a moderate queue with one urgent study, but two alternative scanners are currently verified.",
    factors: [
      { label: "Procedure urgency", value: 64, tone: "amber" },
      { label: "Affected procedures", value: 70, tone: "amber" },
      { label: "Alternative availability", value: 48, tone: "teal" },
      { label: "Service criticality", value: 82, tone: "coral" },
      { label: "Repair delay", value: 36, tone: "teal" },
    ],
  },
  {
    id: "XR-21",
    name: "Digital X-Ray",
    department: "Outpatient Imaging",
    score: 42,
    priority: "MEDIUM",
    downtime: "10h 24m",
    repairEta: "4h",
    procedures: 3,
    urgent: 0,
    alternatives: "3 of 6 available",
    freshness: "STALE",
    summary:
      "The equipment has the longest downtime in the queue, but the affected studies are routine and alternatives are likely available.",
    factors: [
      { label: "Procedure urgency", value: 24, tone: "teal" },
      { label: "Affected procedures", value: 38, tone: "teal" },
      { label: "Alternative availability", value: 28, tone: "teal" },
      { label: "Service criticality", value: 32, tone: "teal" },
      { label: "Repair delay", value: 64, tone: "amber" },
    ],
  },
];

const navItems = [
  { label: "Overview", icon: LayoutDashboard, active: true },
  { label: "Priority queue", icon: Gauge, badge: "12" },
  { label: "Equipment", icon: PackageSearch },
  { label: "Procedure impact", icon: CalendarDays },
  { label: "Review log", icon: FileText },
];

function PriorityPill({ priority }: { priority: Priority }) {
  return <span className={`priority-pill priority-${priority.toLowerCase()}`}><span className="priority-dot" />{priority}</span>;
}

function FreshnessPill({ freshness }: { freshness: Freshness }) {
  const label = freshness === "FRESH" ? "Fresh" : freshness === "STALE" ? "Stale" : "Unknown";
  return <span className={`freshness freshness-${freshness.toLowerCase()}`}><span className="freshness-dot" />{label}</span>;
}

function AppMark() {
  return (
    <div className="app-mark" aria-label="MediPulse AI">
      <img src="/manus-storage/medipulse-mark_ce300ede.png" alt="" />
      <span>medipulse <b>AI</b></span>
    </div>
  );
}

export default function Home() {
  const [selectedId, setSelectedId] = useState("MRI-04");
  const [query, setQuery] = useState("");
  const [activeNav, setActiveNav] = useState("Overview");
  const [reviewed, setReviewed] = useState<Record<string, string>>({});
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const selected = equipment.find((item) => item.id === selectedId) ?? equipment[0];

  const filteredEquipment = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    if (!normalized) return equipment;
    return equipment.filter((item) => `${item.id} ${item.name} ${item.department} ${item.priority}`.toLowerCase().includes(normalized));
  }, [query]);

  const handleReview = (action: string) => {
    setReviewed((current) => ({ ...current, [selected.id]: action }));
    toast.success(`${selected.id} ${action.toLowerCase()}`, {
      description: "The decision was added to the review log.",
    });
  };

  const handleNav = (label: string) => {
    setActiveNav(label);
    if (label !== "Overview") toast.info(`${label} view is coming soon`, { description: "The overview keeps the current clinical signal in focus." });
    setSidebarOpen(false);
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-top">
          <AppMark />
          <button className="mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <div className="workspace-switcher">
          <div className="workspace-avatar">NC</div>
          <div><span>Northstar Clinical</span><small>Biomedical command center</small></div>
          <ChevronDown size={15} />
        </div>
        <div className="nav-label">Workspace</div>
        <nav className="nav-list" aria-label="Primary navigation">
          {navItems.map(({ label, icon: Icon, badge, active }) => (
            <button key={label} className={`nav-item ${(activeNav === label || (active && activeNav === "Overview")) ? "active" : ""}`} onClick={() => handleNav(label)}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>{badge && <em>{badge}</em>}
            </button>
          ))}
        </nav>
        <div className="nav-label nav-label-bottom">System</div>
        <nav className="nav-list">
          <button className="nav-item" onClick={() => toast.info("Data health panel is coming soon")}><Database size={17} strokeWidth={1.8} /><span>Data health</span><span className="status-check"><Check size={12} /></span></button>
          <button className="nav-item" onClick={() => toast.info("Settings are coming soon")}><Settings2 size={17} strokeWidth={1.8} /><span>Settings</span></button>
        </nav>
        <div className="sidebar-footer">
          <div className="privacy-badge"><ShieldCheck size={15} /><div><strong>Synthetic workspace</strong><span>No patient data in use</span></div></div>
          <div className="user-row"><div className="user-avatar">JR</div><div><strong>Jordan Reyes</strong><span>Biomedical engineer</span></div><MoreHorizontal size={17} /></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="breadcrumb"><span>Northstar Clinical</span><ChevronRight size={14} /><strong>Overview</strong></div>
          <div className="topbar-actions">
            <div className="sync-status"><span className="pulse-dot" />Last synced 2 min ago</div>
            <button className="icon-button" onClick={() => toast.info("No new notifications")} aria-label="Notifications"><Bell size={18} /><span className="notification-dot" /></button>
            <button className="help-button" onClick={() => toast.info("Need a hand? Contact the clinical operations lead.")}><CircleHelp size={16} />Support</button>
          </div>
        </header>

        <div className="content-wrap">
          <section className="briefing-row">
            <div>
              <div className="eyebrow"><span className="eyebrow-rule" />Monday, 14 October 2024 <span className="eyebrow-separator">/</span> Morning brief</div>
              <h1>Repair the risk,<br /><span>not just the clock.</span></h1>
              <p className="intro-copy">Clinical impact intelligence for the equipment decisions that cannot wait.</p>
            </div>
            <div className="briefing-aside">
              <div className="aside-kicker"><Sparkles size={14} /> Today’s signal</div>
              <p><strong>4 assets</strong> need attention before the next procedure window.</p>
              <button className="text-action" onClick={() => document.getElementById("queue")?.scrollIntoView({ behavior: "smooth" })}>View priority queue <ArrowUpRight size={14} /></button>
            </div>
          </section>

          <section className="metric-grid" aria-label="Current operational metrics">
            <article className="metric-card metric-primary"><div className="metric-head"><span>Equipment down</span><PackageSearch size={16} /></div><div className="metric-number">12</div><div className="metric-foot"><span className="metric-delta down"><ArrowUpRight size={13} /> 2 since 06:00</span><span>across 5 services</span></div></article>
            <article className="metric-card"><div className="metric-head"><span>Critical impact</span><AlertTriangle size={16} /></div><div className="metric-number coral-number">4</div><div className="metric-foot"><span className="metric-delta coral-text">Requires review</span><span>highest tier</span></div></article>
            <article className="metric-card"><div className="metric-head"><span>At-risk procedures</span><Activity size={16} /></div><div className="metric-number">18</div><div className="metric-foot"><span className="metric-delta amber-text">3 high urgency</span><span>next 12 hours</span></div></article>
            <article className="metric-card"><div className="metric-head"><span>Data confidence</span><ShieldCheck size={16} /></div><div className="metric-number teal-number">94<span className="number-suffix">%</span></div><div className="metric-foot"><span className="metric-delta teal-text"><Check size={13} /> within threshold</span><span>1 stale source</span></div></article>
          </section>

          <div className="section-heading" id="queue"><div><div className="eyebrow compact"><span className="eyebrow-rule" />Decision queue</div><h2>Maintenance priority</h2></div><div className="queue-controls"><button className="filter-button" onClick={() => toast.info("Showing all equipment with active downtime")}><Filter size={15} />All equipment<ChevronDown size={14} /></button><button className="more-button" onClick={() => toast.info("Export is available in the review log") }><MoreHorizontal size={18} /></button></div></div>

          <section className="workspace-grid">
            <div className="queue-panel panel">
              <div className="panel-toolbar"><div className="queue-count"><span className="live-indicator" />Live queue <b>{filteredEquipment.length}</b></div><label className="search-field"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search equipment" aria-label="Search equipment" />{query && <button onClick={() => setQuery("")} aria-label="Clear search"><X size={13} /></button>}</label></div>
              <div className="table-scroll"><table><thead><tr><th>Equipment</th><th>Impact</th><th>Priority</th><th>Downtime</th><th>Exposure</th><th>Data</th><th /></tr></thead><tbody>
                {filteredEquipment.map((item) => <tr key={item.id} className={selectedId === item.id ? "selected-row" : ""} onClick={() => setSelectedId(item.id)} tabIndex={0} onKeyDown={(event) => event.key === "Enter" && setSelectedId(item.id)}>
                  <td><div className="equipment-cell"><div className={`equipment-glyph glyph-${item.priority.toLowerCase()}`}>{item.id.split("-")[0].slice(0, 2)}</div><div><strong>{item.id}</strong><span>{item.name}</span><small>{item.department}</small></div></div></td>
                  <td><div className="impact-cell"><strong>{item.score}</strong><span>/ 100</span></div></td>
                  <td><PriorityPill priority={item.priority} /></td>
                  <td><span className="mono-cell">{item.downtime}</span><small className="table-sub">ETA {item.repairEta}</small></td>
                  <td><span className="exposure-cell">{item.procedures} <small>procedures</small></span><small className="table-sub">{item.urgent ? `${item.urgent} high urgency` : "routine only"}</small></td>
                  <td><FreshnessPill freshness={item.freshness} /></td>
                  <td><ChevronRight size={16} className="row-chevron" /></td>
                </tr>)}
              </tbody></table></div>
              <div className="queue-footer"><span>Showing {filteredEquipment.length} of 12 active equipment events</span><button onClick={() => toast.info("Priority queue view is coming soon")}>Open full queue <ArrowUpRight size={14} /></button></div>
            </div>

            <aside className="evidence-column">
              <div className="panel evidence-panel">
                <div className="evidence-topline"><div className="eyebrow compact"><span className="eyebrow-rule" />Selected signal</div><button className="panel-icon" onClick={() => toast.info("Equipment actions are recorded in the review log")} aria-label="More equipment actions"><MoreHorizontal size={17} /></button></div>
                <div className="selected-asset"><div><div className="asset-id">{selected.id}</div><h3>{selected.name}</h3><span className="asset-service"><Stethoscope size={13} /> {selected.department} service</span></div><PriorityPill priority={selected.priority} /></div>
                <div className="impact-summary"><div className="score-dial" style={{ "--score": `${selected.score * 3.6}deg` } as React.CSSProperties}><div><strong>{selected.score}</strong><span>impact</span></div></div><div className="summary-copy"><span className="summary-label">Why this matters</span><p>{selected.summary}</p></div></div>
                <div className="evidence-meta"><div><Clock3 size={14} /><span>Down for <b>{selected.downtime}</b></span></div><div><Wrench size={14} /><span>Repair ETA <b>{selected.repairEta}</b></span></div><div><CalendarDays size={14} /><span><b>{selected.procedures}</b> exposed procedures</span></div></div>
                <div className="factor-block"><div className="factor-heading"><span>Impact composition</span><button onClick={() => toast.info("Scores use the five weighted factors from the project model")}><CircleHelp size={14} /></button></div>{selected.factors.map((factor) => <div className="factor-row" key={factor.label}><div className="factor-label"><span>{factor.label}</span><b>{factor.value}</b></div><div className="factor-track"><span className={`factor-fill fill-${factor.tone}`} style={{ width: `${factor.value}%` }} /></div></div>)}</div>
                <div className="evidence-source"><div className="source-icon"><Zap size={14} /></div><div><span>Evidence is current</span><small>Equipment + schedule sources synced 2 min ago</small></div><FreshnessPill freshness={selected.freshness} /></div>
                <div className="review-actions"><span className="review-label">Human review</span>{reviewed[selected.id] ? <div className="reviewed-state"><Check size={15} /><span>{reviewed[selected.id]} by Jordan Reyes</span></div> : <div className="action-row"><button className="approve-button" onClick={() => handleReview("Priority approved")}><Check size={15} />Approve</button><button className="override-button" onClick={() => handleReview("Priority overridden")}><SlidersHorizontal size={14} />Override</button><button className="escalate-button" onClick={() => handleReview("Escalated to lead")}><ArrowUpRight size={14} />Escalate</button></div>}</div>
              </div>
              <div className="panel data-health-panel"><div className="health-header"><div><div className="eyebrow compact"><span className="eyebrow-rule" />System watch</div><h3>Data health</h3></div><button className="refresh-button" onClick={() => toast.success("Data health checked", { description: "All sources responded within the expected window." })}><RefreshCw size={15} /></button></div><div className="health-items"><div><span className="health-label"><span className="health-dot healthy" />Equipment status</span><span className="health-time">2 min ago</span></div><div><span className="health-label"><span className="health-dot healthy" />Procedure schedule</span><span className="health-time">2 min ago</span></div><div><span className="health-label"><span className="health-dot stale" />Alternatives registry</span><span className="health-time stale-text">5h ago</span></div></div><div className="health-note"><AlertTriangle size={14} /><span>One source is stale. Review before acting on substitution assumptions.</span></div></div>
              <div className="signal-image-card"><img src="/manus-storage/medipulse-signal-field_8c6b7e95.png" alt="Abstract signal field" /><div className="signal-image-copy"><span>Signal note 04</span><strong>Impact is a clinical question,<br />not a stopwatch.</strong></div></div>
            </aside>
          </section>

          <footer className="page-footer"><div><HeartPulse size={15} /><span>Decision support for clinical operations</span></div><span>Last model review · 14 Oct 2024 · v0.8.2</span></footer>
        </div>
      </main>
    </div>
  );
}
