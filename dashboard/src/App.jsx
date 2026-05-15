import { useState, useEffect, useCallback } from "react";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Cell, ReferenceLine, Tooltip,
} from "recharts";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const SYMBOLS = ["BTC/USDC", "BTC/USDT", "ETH/USDC", "ETH/USDT", "SOL/USDC", "SOL/USDT"];

// ─── Theme ────────────────────────────────────────────────────────────────────

const C = {
  bg:     "#060606",
  card:   "#0a0a0a",
  card2:  "#0d0d0d",
  border: "#161616",
  green:  "#00ff88",
  red:    "#ff4455",
  yellow: "#ffd166",
  orange: "#f4a261",
  blue:   "#7788ff",
  text:   "#e0e0e0",
  muted:  "#444",
  dim:    "#222",
  dimmer: "#1a1a1a",
};

const PHASES = {
  open:      { label: "OPEN",    color: C.green,   bg: "#001a0d", pct: 100 },
  partial_1: { label: "TP1 ✓",  color: C.yellow,  bg: "#1a1200", pct: 75  },
  partial_2: { label: "TP2 ✓",  color: C.orange,  bg: "#1a0d00", pct: 50  },
  partial_3: { label: "RUNNER", color: "#e76f51",  bg: "#1a0800", pct: 25  },
  closed:    { label: "CLOSED", color: C.muted,    bg: "#111",    pct: 0   },
};

const SETUP_META = [
  { key: "breakout",     label: "Breakout",     desc: "Break + retest" },
  { key: "range",        label: "Range",        desc: "Long/short extreme" },
  { key: "continuation", label: "Continuation", desc: "Pullback constructie" },
  { key: "rotation",     label: "Rotation",     desc: "Structuurbreuk" },
];

// ─── Utilities ────────────────────────────────────────────────────────────────

const fmt     = (n, d = 2) => n == null ? "—" : Number(n).toFixed(d);
const fmtP    = (n) => n == null ? "—" : Number(n).toLocaleString("nl-NL", { maximumFractionDigits: 0 });
const fmtSign = (n, d = 2) => n == null ? "—" : `${n >= 0 ? "+" : ""}$${fmt(n, d)}`;
const getPhase = (t) => PHASES[t.status] || PHASES.open;

// ─── Base atoms ───────────────────────────────────────────────────────────────

function PnlBadge({ value, size = 13 }) {
  if (value == null) return <span style={{ color: C.muted }}>—</span>;
  return (
    <span style={{ color: value >= 0 ? C.green : C.red, fontWeight: 700, fontSize: size }}>
      {value >= 0 ? "+" : ""}{fmt(value)} USDT
    </span>
  );
}

function Metric({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: C.dimmer, letterSpacing: 1, marginBottom: 3, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 700, color: color || C.text }}>{value ?? "—"}</div>
    </div>
  );
}

function StatCard({ label, value, sub, accent }) {
  return (
    <div style={{
      background: C.card2,
      border: `1px solid ${accent ? accent + "22" : C.border}`,
      borderRadius: 8, padding: "14px 18px", minWidth: 120, flex: 1,
    }}>
      <div style={{ color: C.muted, fontSize: 9, letterSpacing: 2, textTransform: "uppercase", marginBottom: 6 }}>{label}</div>
      <div style={{ color: accent || C.text, fontSize: 18, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ color: C.dimmer, fontSize: 10, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

function SectionLabel({ children, badge }) {
  return (
    <div style={{
      fontSize: 9, letterSpacing: 2, color: C.muted, marginBottom: 12,
      textTransform: "uppercase", display: "flex", alignItems: "center", gap: 8,
    }}>
      {children}
      {badge != null && badge > 0 && (
        <span style={{ color: C.yellow }}>{badge > 0 ? `(${badge})` : ""}</span>
      )}
    </div>
  );
}

function EmptyState({ icon, text, sub, height = 130 }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", height, gap: 6, color: C.dim,
    }}>
      <div style={{ fontSize: 22, opacity: 0.2 }}>{icon}</div>
      <div style={{ fontSize: 11 }}>{text}</div>
      {sub && <div style={{ fontSize: 10, color: C.dimmer }}>{sub}</div>}
    </div>
  );
}

// ─── Circuit Breaker Banner ───────────────────────────────────────────────────

function CircuitBreakerBanner({ status }) {
  if (!status?.circuit_breaker_active) return null;
  const until = status.circuit_breaker_until
    ? new Date(status.circuit_breaker_until * 1000).toLocaleString("nl-NL")
    : "—";
  return (
    <div style={{
      background: "#180808", border: `1px solid ${C.red}44`,
      borderRadius: 8, padding: "12px 18px", marginBottom: 16,
      display: "flex", alignItems: "center", gap: 12,
    }}>
      <span style={{ fontSize: 18 }}>🚨</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, color: C.red, fontWeight: 700, letterSpacing: 0.5 }}>
          CIRCUIT BREAKER ACTIEF — 5 stops op rij
        </div>
        <div style={{ fontSize: 10, color: C.red + "66", marginTop: 2 }}>
          Bot gepauzeerd tot {until}
        </div>
      </div>
      <div style={{ fontSize: 11, color: C.red + "88", fontWeight: 700 }}>
        {status.consecutive_stops} STOPS
      </div>
    </div>
  );
}

// ─── Price Ladder ─────────────────────────────────────────────────────────────

function PriceLadder({ trade }) {
  const isLong = trade.side === "buy";
  const prices = [trade.stop_loss, trade.entry_price, trade.tp1, trade.tp2, trade.tp3];
  const minP = Math.min(...prices) * 0.9985;
  const maxP = Math.max(...prices) * 1.0015;
  const span = maxP - minP;
  const pct  = (p) => (p - minP) / span * 100;

  const zones = isLong ? [
    { from: trade.stop_loss,   to: trade.entry_price, color: "#ff445520" },
    { from: trade.entry_price, to: trade.tp1,          color: "#00ff8818" },
    { from: trade.tp1,         to: trade.tp2,          color: "#00ff8828" },
    { from: trade.tp2,         to: trade.tp3,          color: "#00ff8840" },
  ] : [
    { from: trade.entry_price, to: trade.stop_loss,   color: "#ff445520" },
    { from: trade.tp1,         to: trade.entry_price, color: "#00ff8818" },
    { from: trade.tp2,         to: trade.tp1,         color: "#00ff8828" },
    { from: trade.tp3,         to: trade.tp2,         color: "#00ff8840" },
  ];

  const markers = [
    { price: trade.stop_loss,   label: "SL",    color: C.red,   hit: true },
    { price: trade.entry_price, label: "ENTRY", color: C.text,  hit: true },
    { price: trade.tp1,         label: "TP1",   color: C.green, hit: trade.tp1_hit },
    { price: trade.tp2,         label: "TP2",   color: C.green, hit: trade.tp2_hit },
    { price: trade.tp3,         label: "TP3",   color: C.green, hit: trade.tp3_hit },
  ];

  return (
    <div style={{ position: "relative", height: 54, marginTop: 10, userSelect: "none" }}>
      {/* Track */}
      <div style={{ position: "absolute", top: 22, left: 0, right: 0, height: 3, background: "#0f0f0f", borderRadius: 2 }} />

      {/* Zones */}
      {zones.map((z, i) => {
        const l = Math.min(pct(z.from), pct(z.to));
        const w = Math.abs(pct(z.to) - pct(z.from));
        return (
          <div key={i} style={{
            position: "absolute", top: 22, height: 3,
            left: `${l}%`, width: `${w}%`,
            background: z.color,
          }} />
        );
      })}

      {/* Markers */}
      {markers.map((m) => (
        <div key={m.label} style={{
          position: "absolute", left: `${pct(m.price)}%`,
          transform: "translateX(-50%)",
          display: "flex", flexDirection: "column", alignItems: "center", top: 0,
        }}>
          <div style={{ fontSize: 8, color: m.hit ? m.color : "#2a2a2a", whiteSpace: "nowrap", marginBottom: 1, letterSpacing: 0.3 }}>
            {m.label}
          </div>
          <div style={{ width: 1, height: 9, background: m.hit ? m.color : "#222" }} />
          <div style={{
            width: 5, height: 5, borderRadius: "50%",
            background: m.hit ? m.color + "33" : "#111",
            border: `1px solid ${m.hit ? m.color : "#333"}`,
          }} />
          <div style={{ fontSize: 8, color: "#2a2a2a", whiteSpace: "nowrap", marginTop: 2 }}>
            {fmtP(m.price)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── TP Progress ──────────────────────────────────────────────────────────────

function TpProgress({ trade }) {
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      {[
        { key: "tp1_hit", label: "TP1" },
        { key: "tp2_hit", label: "TP2" },
        { key: "tp3_hit", label: "TP3" },
      ].map(tp => (
        <div key={tp.key} style={{
          fontSize: 9, padding: "2px 6px", borderRadius: 3, letterSpacing: 0.5,
          background: trade[tp.key] ? "#1a3a1a" : "#111",
          color:      trade[tp.key] ? C.green   : "#333",
          border: `1px solid ${trade[tp.key] ? "#00ff4422" : C.dimmer}`,
        }}>
          {trade[tp.key] ? "✓" : "·"} {tp.label}
        </div>
      ))}
      <div style={{
        fontSize: 9, padding: "2px 6px", borderRadius: 3, letterSpacing: 0.5,
        background: trade.status === "partial_3" ? "#2a0d00" : "#111",
        color:      trade.status === "partial_3" ? "#e76f51" : "#333",
        border: `1px solid ${trade.status === "partial_3" ? "#e76f5122" : C.dimmer}`,
      }}>
        {trade.status === "partial_3" ? "⟳" : "·"} RUN
      </div>
    </div>
  );
}

// ─── Active Trade Card ────────────────────────────────────────────────────────

function ActiveTradeCard({ trade }) {
  const phase  = getPhase(trade);
  const isLong = trade.side === "buy";
  const slLabel = trade.tp1_hit ? (trade.tp2_hit ? "SL (swing)" : "SL (BE)") : "SL";

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${phase.color}22`,
      borderLeft: `3px solid ${phase.color}`,
      borderRadius: 8, padding: "14px 18px", marginBottom: 10,
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: isLong ? C.green : C.red }}>
            {isLong ? "▲ LONG" : "▼ SHORT"}
          </span>
          <span style={{ fontSize: 10, color: C.muted }}>{trade.symbol}</span>
          <span style={{
            fontSize: 9, padding: "2px 7px", borderRadius: 3,
            background: "#1a1a2a", color: C.blue, letterSpacing: 1, textTransform: "uppercase",
          }}>{trade.setup_type}</span>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{
            fontSize: 9, padding: "2px 8px", borderRadius: 4, letterSpacing: 1, fontWeight: 700,
            background: phase.bg, color: phase.color,
          }}>{phase.label}</span>
          <span style={{ fontSize: 10, color: "#333" }}>{phase.pct}% open</span>
        </div>
      </div>

      {/* Price grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 6, marginBottom: 6 }}>
        {[
          { label: "ENTRY",  value: fmtP(trade.entry_price), color: C.text },
          { label: slLabel,  value: fmtP(trade.stop_loss),   color: C.red },
          { label: "TP1",    value: fmtP(trade.tp1), color: trade.tp1_hit ? C.green : C.muted },
          { label: "TP2",    value: fmtP(trade.tp2), color: trade.tp2_hit ? C.green : C.muted },
          { label: "TP3",    value: fmtP(trade.tp3), color: trade.tp3_hit ? C.green : C.muted },
          { label: "RUNNER", value: trade.tp3_hit ? "OPEN" : "—", color: trade.tp3_hit ? "#e76f51" : "#333" },
        ].map(item => (
          <div key={item.label} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 9, color: C.muted, letterSpacing: 1, marginBottom: 3 }}>{item.label}</div>
            <div style={{ fontSize: 11, color: item.color, fontWeight: 600 }}>{item.value}</div>
          </div>
        ))}
      </div>

      {/* Price Ladder */}
      <PriceLadder trade={trade} />

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
        <TpProgress trade={trade} />
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 9, color: C.muted, letterSpacing: 1, marginBottom: 2 }}>REALIZED PNL</div>
          <PnlBadge value={trade.realized_pnl} size={12} />
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
        {trade.session && trade.session !== 'unknown' && (
          <span style={{ fontSize: 9, color: C.blue, letterSpacing: 1, textTransform: "uppercase" }}>
            ⏱ {trade.session.replace('_', ' ')}
          </span>
        )}
        {trade.valid_until && (
          <span style={{ fontSize: 9, color: C.muted }}>
            geldig tot {trade.valid_until?.slice(11, 16)} UTC
          </span>
        )}
      </div>
      {trade.reason && (
        <div style={{ marginTop: 4, fontSize: 10, color: "#2a2a2a", fontStyle: "italic" }}>{trade.reason}</div>
      )}
    </div>
  );
}

// ─── Chart tooltips ───────────────────────────────────────────────────────────

function EquityTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "#0d0d0d", border: "1px solid #222", borderRadius: 6, padding: "6px 10px", fontSize: 11 }}>
      <div style={{ color: C.muted, fontSize: 9, marginBottom: 3 }}>{label}</div>
      <div style={{ color: C.green, fontWeight: 700 }}>${fmt(payload[0].value, 0)}</div>
    </div>
  );
}

function PnlTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const v = payload[0].value;
  return (
    <div style={{ background: "#0d0d0d", border: "1px solid #222", borderRadius: 6, padding: "6px 10px", fontSize: 11 }}>
      <div style={{ color: C.muted, fontSize: 9, marginBottom: 3 }}>{label}</div>
      <div style={{ color: v >= 0 ? C.green : C.red, fontWeight: 700 }}>{fmtSign(v)}</div>
    </div>
  );
}

// ─── Equity Curve ─────────────────────────────────────────────────────────────

function EquityCurve({ history }) {
  if (!history?.length) {
    return <EmptyState icon="📈" text="Nog geen equity data" sub="Verschijnt na de eerste gesloten trade" height={155} />;
  }
  return (
    <ResponsiveContainer width="100%" height={155}>
      <LineChart data={history} margin={{ top: 4, right: 6, left: -28, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#0f0f0f" vertical={false} />
        <XAxis dataKey="ts" stroke="transparent" tick={{ fill: "#2a2a2a", fontSize: 9 }} tickLine={false} interval="preserveStartEnd" />
        <YAxis stroke="transparent" tick={{ fill: "#2a2a2a", fontSize: 9 }} tickLine={false} axisLine={false}
          tickFormatter={v => `$${(v / 1000).toFixed(1)}k`} />
        <Tooltip content={<EquityTooltip />} />
        <ReferenceLine y={history[0]?.equity} stroke="#1a1a1a" strokeDasharray="4 4" />
        <Line type="monotone" dataKey="equity" stroke={C.green} dot={false} strokeWidth={1.5} animationDuration={400} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ─── Daily PnL Chart ──────────────────────────────────────────────────────────

function DailyPnlChart({ data }) {
  if (!data?.length) {
    return <EmptyState icon="📊" text="Nog geen dagdata" sub="Verschijnt na de eerste handelsdag" height={130} />;
  }
  return (
    <ResponsiveContainer width="100%" height={130}>
      <BarChart data={data} margin={{ top: 4, right: 6, left: -28, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#0f0f0f" vertical={false} />
        <XAxis dataKey="date" stroke="transparent" tick={{ fill: "#2a2a2a", fontSize: 9 }} tickLine={false} />
        <YAxis stroke="transparent" tick={{ fill: "#2a2a2a", fontSize: 9 }} tickLine={false} axisLine={false}
          tickFormatter={v => `$${v}`} />
        <Tooltip content={<PnlTooltip />} />
        <ReferenceLine y={0} stroke="#1a1a1a" />
        <Bar dataKey="pnl" radius={[2, 2, 0, 0]} maxBarSize={44} animationDuration={400}>
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.pnl >= 0 ? C.green : C.red} fillOpacity={0.75} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ─── Setup Stats ──────────────────────────────────────────────────────────────

function SetupStatsGrid({ stats }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      {SETUP_META.map(s => {
        const d = stats?.[s.key];
        return (
          <div key={s.key} style={{ background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: C.blue, letterSpacing: 1, textTransform: "uppercase" }}>{s.label}</div>
                <div style={{ fontSize: 9, color: "#2a2a2a", marginTop: 1 }}>{s.desc}</div>
              </div>
              {d?.count > 0 && (
                <div style={{ fontSize: 11, fontWeight: 700, color: d.win_rate >= 50 ? C.green : C.red }}>
                  {d.win_rate}%
                </div>
              )}
            </div>
            {!d || d.count === 0 ? (
              <div style={{ fontSize: 10, color: C.dimmer, fontStyle: "italic" }}>geen trades</div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <Metric label="Trades"       value={d.count} />
                <Metric label="Gem. PnL"     value={fmtSign(d.avg_pnl)} color={d.avg_pnl >= 0 ? C.green : C.red} />
                <Metric label="Winst"        value={`${d.wins}/${d.count}`} />
                <Metric label="Prof. factor" value={d.profit_factor ?? "—"}
                  color={d.profit_factor > 1 ? C.green : d.profit_factor != null ? C.red : C.muted} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Config Panel ─────────────────────────────────────────────────────────────

function ConfigPanel({ config, setConfig, isRunning, loading, onStart, onStop }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 18, marginBottom: 12 }}>
      <SectionLabel>Configuratie</SectionLabel>
      <label style={{ display: "block", marginBottom: 12 }}>
        <div style={{ fontSize: 9, color: C.muted, marginBottom: 4, letterSpacing: 1 }}>SYMBOL</div>
        <select value={config.symbol} onChange={e => setConfig({ ...config, symbol: e.target.value })} disabled={isRunning}>
          {SYMBOLS.map(s => <option key={s}>{s}</option>)}
        </select>
      </label>
      <label style={{ display: "block", marginBottom: 18 }}>
        <div style={{ fontSize: 9, color: C.muted, marginBottom: 4, letterSpacing: 1 }}>RISICO PER TRADE</div>
        <input
          type="number" min="0.001" max="0.05" step="0.001"
          value={config.risk_per_trade}
          onChange={e => setConfig({ ...config, risk_per_trade: parseFloat(e.target.value) })}
          disabled={isRunning}
        />
        <div style={{ fontSize: 10, color: "#2a2a2a", marginTop: 3 }}>
          {(config.risk_per_trade * 100).toFixed(1)}% per trade
        </div>
      </label>
      {!isRunning
        ? <button className="btn-primary" onClick={onStart} disabled={loading}>{loading ? "Starten..." : "▶ Start Bot"}</button>
        : <button className="btn-danger"  onClick={onStop}  disabled={loading}>{loading ? "Stoppen..." : "■ Stop Bot"}</button>
      }
    </div>
  );
}

// ─── Strategy Legend ──────────────────────────────────────────────────────────

function StrategyLegend() {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 18 }}>
      <SectionLabel>Setups</SectionLabel>
      {SETUP_META.map(s => (
        <div key={s.key} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, color: C.blue }}>{s.label}</div>
          <div style={{ fontSize: 10, color: "#2a2a2a", marginTop: 1 }}>{s.desc}</div>
        </div>
      ))}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 9, color: C.muted, letterSpacing: 1, marginBottom: 8 }}>TP STRUCTUUR</div>
        {[
          { label: "TP1 (25%)",    note: "SL → Breakeven" },
          { label: "TP2 (25%)",    note: "SL → Swing PA" },
          { label: "TP3 (25%)",    note: "SL → Nieuw swing" },
          { label: "Runner (25%)", note: "SL trailend" },
        ].map(r => (
          <div key={r.label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
            <span style={{ fontSize: 10, color: C.muted }}>{r.label}</span>
            <span style={{ fontSize: 10, color: C.dim }}>{r.note}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Closed Trades Table ──────────────────────────────────────────────────────

function ClosedTradesTable({ trades }) {
  if (!trades.length) {
    return (
      <div style={{
        background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
        padding: "28px 0", textAlign: "center", color: C.dim, fontSize: 11,
      }}>
        Nog geen gesloten trades.
      </div>
    );
  }
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.border}` }}>
            {["Tijd", "Setup", "Side", "Entry", "Exit", "Fases", "PnL"].map(h => (
              <th key={h} style={{ padding: "8px 12px", textAlign: "left", color: "#333", fontWeight: 400, fontSize: 9, letterSpacing: 1, textTransform: "uppercase" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...trades].reverse().map((t, i) => (
            <tr key={t.id || i} className="closed-row" style={{ borderBottom: `1px solid #0d0d0d` }}>
              <td style={{ padding: "8px 12px", color: C.muted }}>{t.timestamp?.slice(11, 16)}</td>
              <td style={{ padding: "8px 12px", color: C.blue, textTransform: "uppercase", fontSize: 10 }}>{t.setup_type}</td>
              <td style={{ padding: "8px 12px", color: t.side === "buy" ? C.green : C.red, fontWeight: 700, textTransform: "uppercase" }}>{t.side}</td>
              <td style={{ padding: "8px 12px" }}>{fmtP(t.entry_price)}</td>
              <td style={{ padding: "8px 12px", color: "#555" }}>{fmtP(t.exit_price)}</td>
              <td style={{ padding: "8px 12px" }}>
                <div style={{ display: "flex", gap: 3 }}>
                  {["tp1_hit", "tp2_hit", "tp3_hit"].map((k, idx) => (
                    <span key={k} style={{
                      fontSize: 9, padding: "1px 5px", borderRadius: 2,
                      background: t[k] ? "#001a0d" : "#111",
                      color: t[k] ? C.green : "#2a2a2a",
                    }}>TP{idx + 1}</span>
                  ))}
                </div>
              </td>
              <td style={{ padding: "8px 12px" }}><PnlBadge value={t.realized_pnl} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function Dashboard() {
  const [status, setStatus] = useState(null);
  const [stats,  setStats]  = useState(null);
  const [config, setConfig] = useState({ symbol: "BTC/USDT", risk_per_trade: 0.01 });
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const fetchAll = useCallback(async () => {
    try {
      const [sRes, stRes] = await Promise.all([
        fetch(`${API_URL}/status`),
        fetch(`${API_URL}/stats`),
      ]);
      setStatus(await sRes.json());
      setStats(await stRes.json());
      setError(null);
    } catch {
      setError("Kan bot API niet bereiken — draait hij?");
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => clearInterval(id);
  }, [fetchAll]);

  async function startBot() {
    setLoading(true);
    try {
      await fetch(`${API_URL}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...config, timeframe: "15m" }),
      });
      await fetchAll();
    } catch { setError("Start mislukt"); }
    setLoading(false);
  }

  async function stopBot() {
    setLoading(true);
    try {
      await fetch(`${API_URL}/stop`, { method: "POST" });
      await fetchAll();
    } catch { setError("Stop mislukt"); }
    setLoading(false);
  }

  const isRunning    = status?.running;
  const allTrades    = status?.trades || [];
  const activeTrades = allTrades.filter(t => t.status !== "closed");
  const closedTrades = allTrades.filter(t => t.status === "closed");
  const winRate      = closedTrades.length > 0
    ? Math.round((status.winning_trades / closedTrades.length) * 100)
    : null;

  return (
    <div style={{
      minHeight: "100vh", background: C.bg, color: C.text,
      fontFamily: "'JetBrains Mono', monospace",
      padding: "24px 28px", maxWidth: 1400, margin: "0 auto",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@700;800&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; background: #0a0a0a; }
        ::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }
        .btn-primary {
          background: ${C.green}; color: #000; border: none; border-radius: 6px;
          padding: 10px 20px; font-family: inherit; font-size: 11px; font-weight: 700;
          letter-spacing: 1.5px; cursor: pointer; text-transform: uppercase;
          transition: opacity 0.15s; width: 100%;
        }
        .btn-primary:hover { opacity: 0.85; }
        .btn-primary:disabled { opacity: 0.3; cursor: not-allowed; }
        .btn-danger {
          background: transparent; color: ${C.red}; border: 1px solid ${C.red}44;
          border-radius: 6px; padding: 10px 20px; font-family: inherit; font-size: 11px;
          font-weight: 700; letter-spacing: 1.5px; cursor: pointer; text-transform: uppercase;
          transition: background 0.15s; width: 100%;
        }
        .btn-danger:hover { background: ${C.red}11; }
        select, input {
          background: #0d0d0d; border: 1px solid #1e1e1e; color: ${C.text};
          font-family: inherit; font-size: 11px; padding: 7px 10px;
          border-radius: 6px; outline: none; width: 100%;
        }
        select:focus, input:focus { border-color: ${C.green}44; }
        .closed-row:hover { background: #0d0d0d !important; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.2} }
        .pulse { animation: pulse 1.6s infinite; }
        @media (max-width: 900px) {
          .main-grid    { grid-template-columns: 1fr !important; }
          .analytics-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 600px) {
          .stats-row > div { min-width: 45% !important; }
        }
      `}</style>

      {/* Circuit Breaker Banner */}
      <CircuitBreakerBanner status={status} />

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 22, fontWeight: 800, letterSpacing: -0.5 }}>
            ₿ TRADE<span style={{ color: C.green }}>BOT</span>
          </div>
          <div style={{ color: "#2a2a2a", fontSize: 9, letterSpacing: 2.5, marginTop: 2 }}>
            OKX · DOOPIECASH METHOD · 15M/1H
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {status?.consecutive_stops > 0 && (
            <span style={{ fontSize: 9, color: C.red + "88", letterSpacing: 1 }}>
              {status.consecutive_stops} STOP{status.consecutive_stops !== 1 ? "S" : ""} OP RIJ
            </span>
          )}
          {status?.daily_loss_pct < -1 && (
            <span style={{ fontSize: 9, color: C.yellow + "99", letterSpacing: 1 }}>
              DAY {fmt(status.daily_loss_pct, 1)}%
            </span>
          )}
          <div className="pulse" style={{
            width: 6, height: 6, borderRadius: "50%",
            background: isRunning ? C.green : "#2a2a2a",
          }} />
          <span style={{ fontSize: 9, color: isRunning ? C.green : "#333", letterSpacing: 2 }}>
            {isRunning ? "LIVE" : "OFFLINE"}
          </span>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          background: "#180808", border: `1px solid ${C.red}33`, borderRadius: 6,
          padding: "8px 14px", marginBottom: 18, color: C.red, fontSize: 11,
        }}>⚠ {error}</div>
      )}

      {/* Stats row */}
      <div className="stats-row" style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
        <StatCard label="Balance"     value={status ? `$${fmt(status.balance, 0)}` : "—"}  sub="USDT vrij"   accent={C.green} />
        <StatCard label="Equity"      value={status ? `$${fmt(status.equity,  0)}` : "—"}  sub="USDT totaal" />
        <StatCard label="Total PnL"   value={<PnlBadge value={status?.total_pnl} />} />
        <StatCard label="Win Rate"    value={winRate != null ? `${winRate}%` : "—"}
          sub={`${status?.winning_trades || 0}/${closedTrades.length} trades`} />
        <StatCard label="Actief"      value={activeTrades.length}
          sub={activeTrades.length > 0 ? activeTrades.map(t => t.setup_type).join(", ") : "geen open trades"}
          accent={activeTrades.length > 0 ? C.yellow : undefined} />
        <StatCard label="Last Signal" value={status?.last_setup?.toUpperCase() || "—"}
          sub={status?.last_signal?.toUpperCase() || ""}
          accent={status?.last_signal === "buy" ? C.green : status?.last_signal === "sell" ? C.red : undefined} />
      </div>

      {/* Main grid: Config | Active trades + Equity curve */}
      <div className="main-grid" style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16, marginBottom: 16 }}>
        <div>
          <ConfigPanel
            config={config} setConfig={setConfig}
            isRunning={isRunning} loading={loading}
            onStart={startBot} onStop={stopBot}
          />
          <StrategyLegend />
        </div>

        <div>
          {/* Active trades */}
          <div style={{ marginBottom: 16 }}>
            <SectionLabel badge={activeTrades.length}>Actieve trades</SectionLabel>
            {activeTrades.length === 0 ? (
              <div style={{
                background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
                padding: "28px 20px", textAlign: "center",
              }}>
                <div style={{ fontSize: 11, color: C.dim }}>Geen actieve trades</div>
                <div style={{ fontSize: 10, color: C.dimmer, marginTop: 4 }}>Bot zoekt naar een setup...</div>
              </div>
            ) : (
              activeTrades.map((t, i) => <ActiveTradeCard key={t.id || i} trade={t} />)
            )}
          </div>

          {/* Equity curve */}
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
            <SectionLabel>Equity curve</SectionLabel>
            <EquityCurve history={stats?.equity_history} />
          </div>
        </div>
      </div>

      {/* Analytics: Daily PnL + Setup stats */}
      <div className="analytics-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
          <SectionLabel>Dagelijks PnL</SectionLabel>
          <DailyPnlChart data={stats?.daily_pnl} />
        </div>
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
          <SectionLabel>Setup statistieken</SectionLabel>
          <SetupStatsGrid stats={stats?.setup_stats} />
        </div>
      </div>

      {/* Closed trades */}
      <SectionLabel badge={closedTrades.length}>Gesloten trades</SectionLabel>
      <ClosedTradesTable trades={closedTrades} />

      <div style={{ marginTop: 24, textAlign: "center", color: C.dimmer, fontSize: 9, letterSpacing: 1 }}>
        VERVERST ELKE 5S · {new Date().toLocaleTimeString("nl-NL")} · USE AT YOUR OWN RISK
      </div>
    </div>
  );
}
