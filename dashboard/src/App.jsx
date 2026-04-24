import { useState, useEffect, useCallback } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const SYMBOLS = ["BTC/USDC", "BTC/USDT", "ETH/USDC", "ETH/USDT", "SOL/USDC", "SOL/USDT"];

function fmt(n, decimals = 2) {
  if (n == null) return "—";
  return Number(n).toFixed(decimals);
}

function fmtPrice(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("nl-NL", { maximumFractionDigits: 0 });
}

function PnlBadge({ value, size = 13 }) {
  if (value == null) return <span style={{ color: "#444" }}>—</span>;
  const color = value >= 0 ? "#00ff88" : "#ff4455";
  const sign = value >= 0 ? "+" : "";
  return <span style={{ color, fontWeight: 700, fontSize: size }}>{sign}{fmt(value)} USDT</span>;
}

// ─── Phase config ─────────────────────────────────────────────────────────────
const PHASES = {
  open:      { label: "OPEN",     color: "#00ff88", bg: "#001a0d", pct: 100 },
  partial_1: { label: "TP1 ✓",    color: "#ffd166", bg: "#1a1200", pct: 75 },
  partial_2: { label: "TP2 ✓",    color: "#f4a261", bg: "#1a0d00", pct: 50 },
  partial_3: { label: "RUNNER",   color: "#e76f51", bg: "#1a0800", pct: 25 },
  closed:    { label: "CLOSED",   color: "#444",    bg: "#111",    pct: 0  },
};

function getPhase(t) {
  return PHASES[t.status] || PHASES.open;
}

function getOpenPct(t) {
  return getPhase(t).pct;
}

// ─── TP Progress Bar ──────────────────────────────────────────────────────────
function TpProgress({ trade }) {
  const tps = [
    { key: "tp1", hit: trade.tp1_hit, price: trade.tp1, label: "TP1" },
    { key: "tp2", hit: trade.tp2_hit, price: trade.tp2, label: "TP2" },
    { key: "tp3", hit: trade.tp3_hit, price: trade.tp3, label: "TP3" },
  ];

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      {tps.map(tp => (
        <div key={tp.key} style={{
          fontSize: 9,
          padding: "2px 6px",
          borderRadius: 3,
          background: tp.hit ? "#1a3a1a" : "#111",
          color: tp.hit ? "#00ff88" : "#333",
          border: `1px solid ${tp.hit ? "#00ff4422" : "#1a1a1a"}`,
          letterSpacing: 0.5,
        }}>
          {tp.hit ? "✓" : "·"} {tp.label}
        </div>
      ))}
      <div style={{
        fontSize: 9,
        padding: "2px 6px",
        borderRadius: 3,
        background: trade.status === "partial_3" ? "#2a0d00" : "#111",
        color: trade.status === "partial_3" ? "#e76f51" : "#333",
        border: `1px solid ${trade.status === "partial_3" ? "#e76f5122" : "#1a1a1a"}`,
        letterSpacing: 0.5,
      }}>
        {trade.status === "partial_3" ? "⟳" : "·"} RUN
      </div>
    </div>
  );
}

// ─── Active Trade Card ────────────────────────────────────────────────────────
function ActiveTradeCard({ trade }) {
  const phase = getPhase(trade);
  const openPct = getOpenPct(trade);
  const isLong = trade.side === "buy";

  const slLabel = trade.tp1_hit
    ? (trade.tp2_hit ? "SL (swing)" : "SL (BE)")
    : "SL";

  return (
    <div style={{
      background: "#0a0a0a",
      border: `1px solid ${phase.color}22`,
      borderLeft: `3px solid ${phase.color}`,
      borderRadius: 8,
      padding: "16px 20px",
      marginBottom: 12,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{
            fontSize: 11, fontWeight: 700, letterSpacing: 1,
            color: isLong ? "#00ff88" : "#ff4455",
          }}>{isLong ? "▲ LONG" : "▼ SHORT"}</span>
          <span style={{ fontSize: 11, color: "#555" }}>{trade.symbol}</span>
          <span style={{
            fontSize: 9, padding: "2px 7px", borderRadius: 3,
            background: "#1a1a2a", color: "#7788ff", letterSpacing: 1,
            textTransform: "uppercase",
          }}>{trade.setup_type}</span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{
            fontSize: 10, padding: "3px 10px", borderRadius: 4,
            background: phase.bg, color: phase.color,
            letterSpacing: 1, fontWeight: 700,
          }}>{phase.label}</span>
          <span style={{ fontSize: 11, color: "#444" }}>{openPct}% open</span>
        </div>
      </div>

      {/* Price levels */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 8, marginBottom: 12 }}>
        {[
          { label: "ENTRY",  value: fmtPrice(trade.entry_price), color: "#e0e0e0" },
          { label: slLabel,  value: fmtPrice(trade.stop_loss),   color: "#ff4455" },
          { label: "TP1",    value: fmtPrice(trade.tp1),         color: trade.tp1_hit ? "#00ff88" : "#555" },
          { label: "TP2",    value: fmtPrice(trade.tp2),         color: trade.tp2_hit ? "#00ff88" : "#555" },
          { label: "TP3",    value: fmtPrice(trade.tp3),         color: trade.tp3_hit ? "#00ff88" : "#555" },
          { label: "RUNNER", value: trade.tp3_hit ? "OPEN" : "—", color: trade.tp3_hit ? "#e76f51" : "#333" },
        ].map(item => (
          <div key={item.label} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 9, color: "#444", letterSpacing: 1, marginBottom: 3 }}>{item.label}</div>
            <div style={{ fontSize: 12, color: item.color, fontWeight: 600 }}>{item.value}</div>
          </div>
        ))}
      </div>

      {/* TP progress + PnL */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <TpProgress trade={trade} />
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 9, color: "#444", letterSpacing: 1, marginBottom: 2 }}>REALIZED PnL</div>
          <PnlBadge value={trade.realized_pnl} size={12} />
        </div>
      </div>

      {/* Reason */}
      {trade.reason && (
        <div style={{ marginTop: 8, fontSize: 10, color: "#333", fontStyle: "italic" }}>
          {trade.reason}
        </div>
      )}
    </div>
  );
}

// ─── Stat Card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, accent }) {
  return (
    <div style={{
      background: "#0d0d0d",
      border: `1px solid ${accent ? accent + "33" : "#1a1a1a"}`,
      borderRadius: 8,
      padding: "16px 20px",
      minWidth: 130,
      flex: 1,
    }}>
      <div style={{ color: "#444", fontSize: 10, letterSpacing: 2, textTransform: "uppercase", marginBottom: 6 }}>{label}</div>
      <div style={{ color: accent || "#e0e0e0", fontSize: 20, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ color: "#333", fontSize: 10, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export default function Dashboard() {
  const [status, setStatus] = useState(null);
  const [config, setConfig] = useState({ symbol: "BTC/USDT", risk_per_trade: 0.01 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/status`);
      const data = await res.json();
      setStatus(data);
      setError(null);
    } catch {
      setError("Kan bot API niet bereiken — draait hij?");
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 5000);
    return () => clearInterval(id);
  }, [fetchStatus]);

  async function startBot() {
    setLoading(true);
    try {
      await fetch(`${API_URL}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...config, timeframe: "15m" }),
      });
      await fetchStatus();
    } catch { setError("Start mislukt"); }
    setLoading(false);
  }

  async function stopBot() {
    setLoading(true);
    try {
      await fetch(`${API_URL}/stop`, { method: "POST" });
      await fetchStatus();
    } catch { setError("Stop mislukt"); }
    setLoading(false);
  }

  const isRunning = status?.running;
  const allTrades = status?.trades || [];
  const activeTrades = allTrades.filter(t => t.status !== "closed");
  const closedTrades = allTrades.filter(t => t.status === "closed");
  const winRate = closedTrades.length > 0
    ? Math.round((status.winning_trades / closedTrades.length) * 100)
    : null;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#060606",
      color: "#e0e0e0",
      fontFamily: "'JetBrains Mono', monospace",
      padding: "28px 36px",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@700;800&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; background: #0a0a0a; }
        ::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }
        .btn-primary {
          background: #00ff88; color: #000; border: none; border-radius: 6px;
          padding: 11px 24px; font-family: inherit; font-size: 12px; font-weight: 700;
          letter-spacing: 1.5px; cursor: pointer; text-transform: uppercase;
          transition: opacity 0.15s; width: 100%;
        }
        .btn-primary:hover { opacity: 0.85; }
        .btn-primary:disabled { opacity: 0.3; cursor: not-allowed; }
        .btn-danger {
          background: transparent; color: #ff4455; border: 1px solid #ff445544;
          border-radius: 6px; padding: 11px 24px; font-family: inherit; font-size: 12px;
          font-weight: 700; letter-spacing: 1.5px; cursor: pointer; text-transform: uppercase;
          transition: background 0.15s; width: 100%;
        }
        .btn-danger:hover { background: #ff445511; }
        select, input {
          background: #0d0d0d; border: 1px solid #1e1e1e; color: #e0e0e0;
          font-family: inherit; font-size: 12px; padding: 8px 12px;
          border-radius: 6px; outline: none; width: 100%;
        }
        select:focus, input:focus { border-color: #00ff8844; }
        .closed-row:hover { background: #0d0d0d !important; }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.2; } }
        .pulse { animation: pulse 1.6s infinite; }
      `}</style>

      {/* ── Header ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 24, fontWeight: 800, letterSpacing: -0.5 }}>
            ₿ TRADE<span style={{ color: "#00ff88" }}>BOT</span>
          </div>
          <div style={{ color: "#333", fontSize: 10, letterSpacing: 2.5, marginTop: 2 }}>OKX · DOOPIECASH METHOD · 15M/1H</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className="pulse" style={{
            width: 7, height: 7, borderRadius: "50%",
            background: isRunning ? "#00ff88" : "#2a2a2a",
          }} />
          <span style={{ fontSize: 10, color: isRunning ? "#00ff88" : "#444", letterSpacing: 2 }}>
            {isRunning ? "LIVE" : "OFFLINE"}
          </span>
        </div>
      </div>

      {error && (
        <div style={{ background: "#180808", border: "1px solid #ff445533", borderRadius: 6, padding: "9px 14px", marginBottom: 20, color: "#ff4455", fontSize: 11 }}>
          ⚠ {error}
        </div>
      )}

      {/* ── Stats ── */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 24 }}>
        <StatCard label="Balance"   value={status ? `$${fmt(status.balance, 0)}` : "—"} sub="USDT vrij" accent="#00ff88" />
        <StatCard label="Equity"    value={status ? `$${fmt(status.equity, 0)}`  : "—"} sub="USDT totaal" />
        <StatCard label="Total PnL" value={<PnlBadge value={status?.total_pnl} />} />
        <StatCard label="Win Rate"  value={winRate != null ? `${winRate}%` : "—"} sub={`${status?.winning_trades || 0}/${closedTrades.length} trades`} />
        <StatCard label="Actief"    value={activeTrades.length} sub={activeTrades.length > 0 ? activeTrades.map(t => t.setup_type).join(", ") : "geen open trades"} accent={activeTrades.length > 0 ? "#ffd166" : undefined} />
        <StatCard
          label="Last Signal"
          value={status?.last_setup?.toUpperCase() || "—"}
          sub={status?.last_signal?.toUpperCase() || ""}
          accent={status?.last_signal === "buy" ? "#00ff88" : status?.last_signal === "sell" ? "#ff4455" : undefined}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 20 }}>

        {/* ── Config ── */}
        <div>
          <div style={{ background: "#0a0a0a", border: "1px solid #161616", borderRadius: 10, padding: 20, marginBottom: 16 }}>
            <div style={{ fontSize: 10, letterSpacing: 2, color: "#444", marginBottom: 18, textTransform: "uppercase" }}>Configuratie</div>

            <label style={{ display: "block", marginBottom: 14 }}>
              <div style={{ fontSize: 10, color: "#444", marginBottom: 5, letterSpacing: 1 }}>SYMBOL</div>
              <select value={config.symbol} onChange={e => setConfig({ ...config, symbol: e.target.value })} disabled={isRunning}>
                {SYMBOLS.map(s => <option key={s}>{s}</option>)}
              </select>
            </label>

            <label style={{ display: "block", marginBottom: 20 }}>
              <div style={{ fontSize: 10, color: "#444", marginBottom: 5, letterSpacing: 1 }}>RISICO PER TRADE</div>
              <input
                type="number" min="0.001" max="0.05" step="0.001"
                value={config.risk_per_trade}
                onChange={e => setConfig({ ...config, risk_per_trade: parseFloat(e.target.value) })}
                disabled={isRunning}
              />
              <div style={{ fontSize: 10, color: "#2a2a2a", marginTop: 4 }}>
                {(config.risk_per_trade * 100).toFixed(1)}% per trade
              </div>
            </label>

            {!isRunning
              ? <button className="btn-primary" onClick={startBot} disabled={loading}>{loading ? "Starten..." : "▶ Start Bot"}</button>
              : <button className="btn-danger"  onClick={stopBot}  disabled={loading}>{loading ? "Stoppen..." : "■ Stop Bot"}</button>
            }
          </div>

          {/* Strategy legend */}
          <div style={{ background: "#0a0a0a", border: "1px solid #161616", borderRadius: 10, padding: 20 }}>
            <div style={{ fontSize: 10, letterSpacing: 2, color: "#444", marginBottom: 14, textTransform: "uppercase" }}>Setups</div>
            {[
              { name: "Breakout",     desc: "Break + retest level" },
              { name: "Range",        desc: "Long onder / short boven" },
              { name: "Continuation", desc: "Pullback naar constructie" },
              { name: "Rotation",     desc: "Structuurbreuk + bevestiging" },
            ].map(s => (
              <div key={s.name} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: "#7788ff", marginBottom: 1 }}>{s.name}</div>
                <div style={{ fontSize: 10, color: "#333" }}>{s.desc}</div>
              </div>
            ))}
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid #161616" }}>
              <div style={{ fontSize: 10, color: "#444", marginBottom: 8, letterSpacing: 1 }}>TP STRUCTUUR</div>
              {[
                { label: "TP1 (25%)", note: "SL → Breakeven" },
                { label: "TP2 (25%)", note: "SL → Swing PA" },
                { label: "TP3 (25%)", note: "SL → Nieuw swing" },
                { label: "Runner (25%)", note: "SL trailend" },
              ].map(r => (
                <div key={r.label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 10, color: "#555" }}>{r.label}</span>
                  <span style={{ fontSize: 10, color: "#333" }}>{r.note}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Right column ── */}
        <div>
          {/* Active trades */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 10, letterSpacing: 2, color: "#444", marginBottom: 14, textTransform: "uppercase" }}>
              Actieve trades {activeTrades.length > 0 && <span style={{ color: "#ffd166" }}>({activeTrades.length})</span>}
            </div>
            {activeTrades.length === 0 ? (
              <div style={{ background: "#0a0a0a", border: "1px solid #161616", borderRadius: 8, padding: "32px 20px", textAlign: "center", color: "#2a2a2a", fontSize: 12 }}>
                Geen actieve trades.<br />
                <span style={{ fontSize: 10, color: "#1a1a1a" }}>Bot zoekt naar een setup...</span>
              </div>
            ) : (
              activeTrades.map((t, i) => <ActiveTradeCard key={t.id || i} trade={t} />)
            )}
          </div>

          {/* Closed trades */}
          <div>
            <div style={{ fontSize: 10, letterSpacing: 2, color: "#444", marginBottom: 14, textTransform: "uppercase" }}>
              Gesloten trades ({closedTrades.length})
            </div>
            {closedTrades.length === 0 ? (
              <div style={{ color: "#222", fontSize: 11 }}>Nog geen gesloten trades.</div>
            ) : (
              <div style={{ background: "#0a0a0a", border: "1px solid #161616", borderRadius: 8, overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #161616" }}>
                      {["Tijd", "Setup", "Side", "Entry", "Exit", "SL gebruikt", "Fases", "PnL"].map(h => (
                        <th key={h} style={{ padding: "8px 12px", textAlign: "left", color: "#333", fontWeight: 400, fontSize: 9, letterSpacing: 1, textTransform: "uppercase" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...closedTrades].reverse().map((t, i) => (
                      <tr key={t.id || i} className="closed-row" style={{ borderBottom: "1px solid #0d0d0d" }}>
                        <td style={{ padding: "8px 12px", color: "#444" }}>{t.timestamp?.slice(11, 16)}</td>
                        <td style={{ padding: "8px 12px", color: "#7788ff", textTransform: "uppercase", fontSize: 10 }}>{t.setup_type}</td>
                        <td style={{ padding: "8px 12px", color: t.side === "buy" ? "#00ff88" : "#ff4455", fontWeight: 700, textTransform: "uppercase" }}>{t.side}</td>
                        <td style={{ padding: "8px 12px" }}>{fmtPrice(t.entry_price)}</td>
                        <td style={{ padding: "8px 12px", color: "#666" }}>{fmtPrice(t.exit_price)}</td>
                        <td style={{ padding: "8px 12px", color: "#ff4455" }}>{fmtPrice(t.stop_loss)}</td>
                        <td style={{ padding: "8px 12px" }}>
                          <div style={{ display: "flex", gap: 3 }}>
                            {["tp1_hit","tp2_hit","tp3_hit"].map((k, idx) => (
                              <span key={k} style={{
                                fontSize: 9, padding: "1px 5px", borderRadius: 2,
                                background: t[k] ? "#001a0d" : "#111",
                                color: t[k] ? "#00ff88" : "#2a2a2a",
                              }}>TP{idx+1}</span>
                            ))}
                          </div>
                        </td>
                        <td style={{ padding: "8px 12px" }}><PnlBadge value={t.realized_pnl} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 28, textAlign: "center", color: "#1a1a1a", fontSize: 10, letterSpacing: 1 }}>
        VERVERST ELKE 5S · {new Date().toLocaleTimeString("nl-NL")} · USE AT YOUR OWN RISK
      </div>
    </div>
  );
}
