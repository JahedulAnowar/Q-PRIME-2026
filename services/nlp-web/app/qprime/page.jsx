"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
    Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
    Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { withBasePath } from "@/lib/basePath";
import styles from "./qprime.module.css";

const TABS = ["Overview", "QoC Factors", "Decisions", "Privacy", "Configuration", "Sensitivity", "Performance"];
const COLOURS = { edge: "#32c57a", cloud: "#4f8df7", both: "#f5a623" };
const empty = { overview: {}, qoc: { timeline: [], mean_by_device: {} }, decisions: [], privacy: {}, performance: {} };

async function api(path, options) {
    const response = await fetch(withBasePath(`/api/qprime/${path}`), { cache: "no-store", ...options });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
}

function StatusBadge({ label, status }) {
    const good = ["connected", "configured", "ok"].includes(status);
    const fallback = status === "local_fallback";
    return <span className={`${styles.badge} ${good ? styles.good : fallback ? styles.warn : styles.bad}`}>{label}: {status || "checking"}</span>;
}

function Metric({ label, value, tone = "default" }) {
    return <article className={styles.metric}><span>{label}</span><strong className={styles[tone]}>{value ?? 0}</strong></article>;
}

function Panel({ title, subtitle, children }) {
    return <section className={styles.panel}><div className={styles.panelTitle}><h2>{title}</h2>{subtitle && <span>{subtitle}</span>}</div>{children}</section>;
}

function Overview({ data }) {
    const split = Object.entries(data.placement_split || {}).map(([name, value]) => ({ name, value }));
    return <>
        <div className={styles.metrics}>
            <Metric label="Records processed" value={data.records_processed} />
            <Metric label="Stored at Edge" value={data.stored_at_edge} tone="edge" />
            <Metric label="Cloud decisions" value={data.sent_to_cloud} tone="cloud" />
            <Metric label="Both tiers" value={data.both_tiers} tone="both" />
            <Metric label="Cloud retained locally" value={data.cloud_fallback_records} tone="both" />
            <Metric label="PII records" value={data.pii_records} />
        </div>
        <div className={styles.grid2}>
            <Panel title="Storage placement per device">
                <ResponsiveContainer width="100%" height={330}><BarChart data={data.placement_by_device || []}><CartesianGrid stroke="#263a59"/><XAxis dataKey="device" angle={-18} textAnchor="end" height={80}/><YAxis allowDecimals={false}/><Tooltip/><Legend/><Bar dataKey="edge" stackId="a" fill={COLOURS.edge}/><Bar dataKey="cloud" stackId="a" fill={COLOURS.cloud}/><Bar dataKey="both" stackId="a" fill={COLOURS.both}/></BarChart></ResponsiveContainer>
            </Panel>
            <Panel title="Overall placement split">
                <ResponsiveContainer width="100%" height={330}><PieChart><Pie data={split} dataKey="value" nameKey="name" innerRadius="48%" outerRadius="78%">{split.map((item) => <Cell key={item.name} fill={COLOURS[item.name] || "#8aa0c2"}/>)}</Pie><Tooltip/><Legend/></PieChart></ResponsiveContainer>
            </Panel>
        </div>
    </>;
}

function QoC({ data }) {
    const byDevice = Object.entries(data.mean_by_device || {}).map(([device, values]) => ({ device, ...values }));
    const keys = ["timeliness", "completeness", "correctness", "resolution", "significance"];
    const colours = ["#4f8df7", "#32c57a", "#f5a623", "#e84455", "#7b5cf5"];
    return <div className={styles.stack}>
        <Panel title="QoC factor scores over time" subtitle="Persistent paper evaluation results">
            <ResponsiveContainer width="100%" height={340}><LineChart data={data.timeline || []}><CartesianGrid stroke="#263a59"/><XAxis dataKey="timestamp" tickFormatter={(v) => new Date(v).toLocaleTimeString()}/><YAxis domain={[0, 1]}/><Tooltip labelFormatter={(v) => new Date(v).toLocaleString()}/><Legend/>{keys.map((key, i) => <Line key={key} type="monotone" dataKey={key} stroke={colours[i]} dot={false}/>)}</LineChart></ResponsiveContainer>
        </Panel>
        <Panel title="Current mean QoC per device">
            <ResponsiveContainer width="100%" height={360}><BarChart data={byDevice}><CartesianGrid stroke="#263a59"/><XAxis dataKey="device" angle={-16} textAnchor="end" height={75}/><YAxis domain={[0, 1]}/><Tooltip/><Legend/>{keys.map((key, i) => <Bar key={key} dataKey={key} fill={colours[i]}/>)}</BarChart></ResponsiveContainer>
        </Panel>
    </div>;
}

function Decisions({ rows }) {
    return <Panel title="Recent placement decisions" subtitle="Recommendation and actual backend are shown separately">
        <div className={styles.tableWrap}><table><thead><tr><th>Time</th><th>Device</th><th>Stream</th><th>Decision</th><th>S edge</th><th>S cloud</th><th>Profile</th><th>Actual backend</th><th>Reason</th><th>Source</th></tr></thead><tbody>{rows.map((row) => <tr key={row.record_id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.device_name || "—"}</td><td>{row.contextattribute}</td><td className={styles[row.recommended_tier]}>{row.recommended_tier}</td><td>{row.analysis?.score_edge ?? "—"}</td><td>{row.analysis?.score_cloud ?? "—"}</td><td>{row.profile_scope}:{row.profile_version}</td><td>{(row.actual_backends || []).join(", ")}</td><td>{row.analysis?.reason}</td><td>{row.source}</td></tr>)}</tbody></table></div>
    </Panel>;
}

function Privacy({ data }) {
    return <><div className={styles.metrics}><Metric label="PII records" value={data.pii_records}/><Metric label="PII sent to configured AWS" value={data.pii_leaked_to_cloud} tone={data.pii_leaked_to_cloud ? "danger" : "edge"}/><Metric label="Leak rate" value={`${data.leak_rate || 0}%`}/><Metric label="Cloud fallback is local" value="MongoDB" tone="both"/></div><Panel title="PII placement per device"><ResponsiveContainer width="100%" height={350}><BarChart data={data.by_device || []}><CartesianGrid stroke="#263a59"/><XAxis dataKey="device"/><YAxis allowDecimals={false}/><Tooltip/><Legend/><Bar dataKey="pii_records" fill="#f5a623"/><Bar dataKey="leaked_to_cloud" fill="#e84455"/></BarChart></ResponsiveContainer></Panel></>;
}

function Configuration({ config, onSaved }) {
    const activeGlobal = (config.active_profiles || []).find((item) => item.scope === "global");
    const [scope, setScope] = useState("global");
    const [selector, setSelector] = useState("");
    const [draft, setDraft] = useState("");
    const [message, setMessage] = useState("");
    useEffect(() => { if (activeGlobal) setDraft(JSON.stringify(activeGlobal.config, null, 2)); }, [activeGlobal]);
    async function save() {
        try {
            const parsed = JSON.parse(draft);
            await api("config/profiles", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope, selector, config: parsed, label: `${scope} policy from dashboard` }) });
            setMessage("Policy saved; a new immutable version is active."); onSaved();
        } catch (error) { setMessage(error.message); }
    }
    return <div className={styles.gridConfig}>
        <Panel title="Policy profile" subtitle="Resolution order: device → stream → global">
            <div className={styles.formRow}><label>Scope<select value={scope} onChange={(e) => setScope(e.target.value)}><option>global</option><option>stream</option><option>device</option></select></label><label>Selector<input value={selector} disabled={scope === "global"} onChange={(e) => setSelector(e.target.value)} placeholder="stream or device name/id"/></label></div>
            <label className={styles.editorLabel}>Complete configurable policy<textarea value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck="false"/></label>
            <div className={styles.actions}><button onClick={save}>Save new profile version</button><span>{message}</span></div>
        </Panel>
        <Panel title="Active profiles" subtitle="All changes persist in MongoDB">
            <div className={styles.profileList}>{(config.active_profiles || []).map((profile) => <article key={profile.version}><strong>{profile.scope}{profile.selector ? ` · ${profile.selector}` : ""}</strong><span>{profile.label}</span><code>{profile.version}</code><small>{new Date(profile.created_at).toLocaleString()}</small></article>)}</div>
        </Panel>
    </div>;
}

function Sensitivity() {
    const [weights, setWeights] = useState({ temporal: .33, spatial: .33, privacy: .34 });
    const [floor, setFloor] = useState(0);
    const [force, setForce] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState("");
    async function replay() { try { setResult(await api("results/sensitivity", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ weights, privacy_floor: floor, force_pii_edge: force }) })); setError(""); } catch (e) { setError(e.message); } }
    const chart = useMemo(() => ["edge", "cloud", "both"].map((tier) => ({ tier, original: result?.original?.[tier] || 0, replayed: result?.replayed?.[tier] || 0 })), [result]);
    return <Panel title="What if the criteria weights were different?" subtitle="Replays logged decisions only; it does not re-ingest or move data">
        <div className={styles.sliders}>{Object.keys(weights).map((key) => <label key={key}>{key}<input type="range" min="0" max="1" step="0.01" value={weights[key]} onChange={(e) => setWeights({ ...weights, [key]: Number(e.target.value) })}/><strong>{weights[key].toFixed(2)}</strong></label>)}<label>Privacy floor<input type="number" min="0" max="1" step="0.05" value={floor} onChange={(e) => setFloor(Number(e.target.value))}/></label><label className={styles.check}><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)}/> Force Edge for all PII</label><button onClick={replay}>Replay placements</button>{error && <span className={styles.danger}>{error}</span>}</div>
        {result && <><div className={styles.metrics}><Metric label="Replayed records" value={result.replayed_records}/><Metric label="Placements changed" value={result.placements_changed} tone="both"/><Metric label="PII cloud placements" value={result.pii_cloud_placements} tone={result.pii_cloud_placements ? "danger" : "edge"}/></div><ResponsiveContainer width="100%" height={330}><BarChart data={chart}><CartesianGrid stroke="#263a59"/><XAxis dataKey="tier"/><YAxis allowDecimals={false}/><Tooltip/><Legend/><Bar dataKey="original" fill="#93a4c3"/><Bar dataKey="replayed" fill="#4f8df7"/></BarChart></ResponsiveContainer></>}
    </Panel>;
}

function Performance({ data }) {
    return <><div className={styles.metrics}><Metric label="Placements measured" value={data.placement_count}/><Metric label="Mean placement latency" value={`${data.placement_latency_mean_ms || 0} ms`} tone="edge"/><Metric label="Queries measured" value={data.query_count}/><Metric label="Mean query latency" value={`${data.query_latency_mean_ms || 0} ms`} tone="cloud"/></div><div className={styles.grid2}><Panel title="Placement latency"><ResponsiveContainer width="100%" height={320}><AreaChart data={data.placement_timeline || []}><CartesianGrid stroke="#263a59"/><XAxis dataKey="created_at" tickFormatter={(v) => new Date(v).toLocaleTimeString()}/><YAxis/><Tooltip/><Area dataKey="placement_latency_ms" stroke={COLOURS.edge} fill="#32c57a44"/></AreaChart></ResponsiveContainer></Panel><Panel title="Query latency"><ResponsiveContainer width="100%" height={320}><AreaChart data={data.query_timeline || []}><CartesianGrid stroke="#263a59"/><XAxis dataKey="created_at" tickFormatter={(v) => new Date(v).toLocaleTimeString()}/><YAxis/><Tooltip/><Area dataKey="latency_ms" stroke={COLOURS.cloud} fill="#4f8df744"/></AreaChart></ResponsiveContainer></Panel></div></>;
}

export default function QPrimePage() {
    const [tab, setTab] = useState("Overview"); const [data, setData] = useState(empty);
    const [health, setHealth] = useState({}); const [config, setConfig] = useState({ active_profiles: [] });
    const [error, setError] = useState(""); const [loading, setLoading] = useState(true);
    const refresh = useCallback(async () => {
        try {
            const [h, o, q, d, p, perf, cfg] = await Promise.all([api("health"), api("results/overview"), api("results/qoc"), api("results/decisions?limit=250"), api("results/privacy"), api("results/performance"), api("config")]);
            setHealth(h); setData({ overview: o, qoc: q, decisions: d.decisions || [], privacy: p, performance: perf }); setConfig(cfg); setError("");
        } catch (e) { setError(e.message); } finally { setLoading(false); }
    }, []);
    useEffect(() => { refresh(); const timer = setInterval(refresh, 10000); return () => clearInterval(timer); }, [refresh]);
    return <main className={styles.shell}>
        <header className={styles.header}><div><strong>Q-PRIME</strong><span>Paper implementation — live QoC and placement analytics</span></div><div className={styles.status}><StatusBadge label="Core" status={health.status}/><StatusBadge label="EdgeX" status={health.edgex?.status}/><StatusBadge label="MongoDB" status={health.mongodb?.status}/><StatusBadge label="Cloud" status={health.cloud?.status}/><Link href={withBasePath("/")}>Open query application ↗</Link></div></header>
        <div className={styles.content}><nav>{TABS.map((name) => <button key={name} className={tab === name ? styles.active : ""} onClick={() => setTab(name)}>{name}</button>)}</nav>{error && <div className={styles.error}>{error}</div>}{loading ? <div className={styles.loading}>Loading Q-PRIME results…</div> : <>{tab === "Overview" && <Overview data={data.overview}/>} {tab === "QoC Factors" && <QoC data={data.qoc}/>} {tab === "Decisions" && <Decisions rows={data.decisions}/>} {tab === "Privacy" && <Privacy data={data.privacy}/>} {tab === "Configuration" && <Configuration config={config} onSaved={refresh}/>} {tab === "Sensitivity" && <Sensitivity/>} {tab === "Performance" && <Performance data={data.performance}/>}</>}</div>
        <footer>Q-PRIME · A Quality- and Privacy-Aware Edge–Cloud Continuum Framework for IoT Applications</footer>
    </main>;
}
