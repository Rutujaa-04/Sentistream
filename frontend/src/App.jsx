import React, { useState, useEffect, useRef } from 'react';

// ==========================================
// CUSTOM SVG CHART COMPONENT: LATENCY PERCENTILES
// ==========================================
function LatencyChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height: '220px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#4B5563', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        [ PIPELINE WARMING UP // GATHERING LATENCY TELEMETRY ]
      </div>
    );
  }

  // Prep data to ensure at least 2 points to draw line charts
  let chartData = data;
  if (data.length === 1) {
    const singlePoint = data[0];
    const prevBucket = new Date(new Date(singlePoint.bucket) - 60000).toISOString();
    chartData = [
      {
        bucket: prevBucket,
        p50_ms: 0,
        p95_ms: 0,
        p99_ms: 0,
        samples: 0
      },
      singlePoint
    ];
  }

  // Find max latency to scale Y axis dynamically
  const maxVal = Math.max(...chartData.map(d => Math.max(d.p50_ms, d.p95_ms, d.p99_ms)), 60.0);
  const yMax = Math.ceil(maxVal / 10) * 10 + 10; // Round up to nearest 10 with margin

  // SVG dimensions
  const width = 500;
  const height = 220;
  const paddingLeft = 40;
  const paddingRight = 10;
  const paddingTop = 20;
  const paddingBottom = 30;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  // Helper to map data index and value to SVG coordinates
  const getX = (index) => paddingLeft + (index / (chartData.length - 1)) * chartWidth;
  const getY = (val) => paddingTop + chartHeight - (val / yMax) * chartHeight;

  // Generate SVG path string for a key
  const generatePath = (key) => {
    return chartData.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(d[key])}`).join(' ');
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '220px' }}>
      <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
        {/* Horizontal Gridlines & Y-Axis ticks */}
        {[0, 0.25, 0.5, 0.75, 1.0].map((ratio, i) => {
          const val = Math.round(ratio * yMax);
          const y = getY(val);
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={paddingLeft} y1={y} x2={width - paddingRight} y2={y} />
              <text className="chart-label" x={paddingLeft - 8} y={y + 3} textAnchor="end">{val}ms</text>
            </g>
          );
        })}

        {/* X-Axis Ticks (Time labels) */}
        {chartData.map((d, i) => {
          // Label every 4th bucket to avoid crowding
          if (i % Math.ceil(chartData.length / 5) !== 0 && i !== chartData.length - 1) return null;
          const x = getX(i);
          const timeStr = d.bucket.split('T')[1]?.substring(0, 5) || '';
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={x} y1={paddingTop} x2={x} y2={paddingTop + chartHeight} />
              <text className="chart-label" x={x} y={paddingTop + chartHeight + 16} textAnchor="middle">{timeStr}</text>
            </g>
          );
        })}

        {/* Axis Lines */}
        <line className="chart-axis-line" x1={paddingLeft} y1={paddingTop} x2={paddingLeft} y2={paddingTop + chartHeight} />
        <line className="chart-axis-line" x1={paddingLeft} y1={paddingTop + chartHeight} x2={width - paddingRight} y2={paddingTop + chartHeight} />

        {/* Performance Percentile Paths */}
        {/* p50 Line (Blue) */}
        <path d={generatePath('p50_ms')} fill="none" stroke="var(--color-neutral)" strokeWidth="1.5" className="glow-blue" />
        {/* p95 Line (Amber) */}
        <path d={generatePath('p95_ms')} fill="none" stroke="var(--color-drift)" strokeWidth="1.5" className="glow-amber" />
        {/* p99 Line (Red) */}
        <path d={generatePath('p99_ms')} fill="none" stroke="var(--color-bearish)" strokeWidth="2" className="glow-red" />
      </svg>
    </div>
  );
}

// ==========================================
// CUSTOM SVG CHART COMPONENT: SENTIMENT TRENDS
// ==========================================
function SentimentTrendChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height: '220px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#4B5563', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        [ PIPELINE WARMING UP // ANALYZING SENTIMENT DISTRIBUTION ]
      </div>
    );
  }

  // Prep data to ensure at least 2 points to draw line charts
  let chartData = data;
  if (data.length === 1) {
    const singlePoint = data[0];
    const prevBucket = new Date(new Date(singlePoint.bucket) - 60000).toISOString();
    chartData = [
      {
        bucket: prevBucket,
        positive: 0,
        negative: 0,
        neutral: 0,
        total: 0
      },
      singlePoint
    ];
  }

  // Find max total count in a single bucket to scale Y axis
  const maxVal = Math.max(...chartData.map(d => d.total), 5);
  const yMax = Math.ceil(maxVal / 5) * 5 + 2;

  // SVG dimensions
  const width = 500;
  const height = 220;
  const paddingLeft = 30;
  const paddingRight = 10;
  const paddingTop = 20;
  const paddingBottom = 30;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const getX = (index) => paddingLeft + (index / (chartData.length - 1)) * chartWidth;
  const getY = (val) => paddingTop + chartHeight - (val / yMax) * chartHeight;

  // Generate SVG area and path strings for stacked charts
  // Stacking order: negative (bottom) -> neutral -> positive (top)
  const paths = { negArea: '', neuArea: '', posArea: '', negLine: '', neuLine: '', posLine: '' };
  
  // 1. Negative Area (Bottom)
  paths.negLine = chartData.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(d.negative)}`).join(' ');
  paths.negArea = `${paths.negLine} L ${getX(chartData.length - 1)} ${getY(0)} L ${getX(0)} ${getY(0)} Z`;

  // 2. Neutral Stacked
  paths.neuLine = chartData.map((d, i) => {
    const stackedVal = d.negative + d.neutral;
    return `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(stackedVal)}`;
  }).join(' ');
  paths.neuArea = chartData.map((d, i) => {
    const stackedVal = d.negative + d.neutral;
    return `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(stackedVal)}`;
  }).join(' ');
  // Complete the loop using the top of negative as base
  const neuBase = [...chartData].reverse().map((d, i) => {
    const idx = chartData.length - 1 - i;
    return `L ${getX(idx)} ${getY(d.negative)}`;
  }).join(' ');
  paths.neuArea = `${paths.neuArea} ${neuBase} Z`;

  // 3. Positive Stacked
  paths.posLine = chartData.map((d, i) => {
    const stackedVal = d.negative + d.neutral + d.positive;
    return `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(stackedVal)}`;
  }).join(' ');
  paths.posArea = chartData.map((d, i) => {
    const stackedVal = d.negative + d.neutral + d.positive;
    return `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(stackedVal)}`;
  }).join(' ');
  // Complete the loop using the top of neutral as base
  const posBase = [...chartData].reverse().map((d, i) => {
    const idx = chartData.length - 1 - i;
    return `L ${getX(idx)} ${getY(d.negative + d.neutral)}`;
  }).join(' ');
  paths.posArea = `${paths.posArea} ${posBase} Z`;

  return (
    <div style={{ position: 'relative', width: '100%', height: '220px' }}>
      <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
        {/* Gridlines */}
        {[0, 0.25, 0.5, 0.75, 1.0].map((ratio, i) => {
          const val = Math.round(ratio * yMax);
          const y = getY(val);
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={paddingLeft} y1={y} x2={width - paddingRight} y2={y} />
              <text className="chart-label" x={paddingLeft - 8} y={y + 3} textAnchor="end">{val}</text>
            </g>
          );
        })}

        {/* X-Axis Ticks */}
        {chartData.map((d, i) => {
          if (i % Math.ceil(chartData.length / 5) !== 0 && i !== chartData.length - 1) return null;
          const x = getX(i);
          const timeStr = d.bucket.split('T')[1]?.substring(0, 5) || '';
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={x} y1={paddingTop} x2={x} y2={paddingTop + chartHeight} />
              <text className="chart-label" x={x} y={paddingTop + chartHeight + 16} textAnchor="middle">{timeStr}</text>
            </g>
          );
        })}

        {/* Axis Lines */}
        <line className="chart-axis-line" x1={paddingLeft} y1={paddingTop} x2={paddingLeft} y2={paddingTop + chartHeight} />
        <line className="chart-axis-line" x1={paddingLeft} y1={paddingTop + chartHeight} x2={width - paddingRight} y2={paddingTop + chartHeight} />

        {/* Stacked Sentiment Areas */}
        {/* Positive Area (Green - Top) */}
        <path d={paths.posArea} fill="rgba(16, 185, 129, 0.12)" />
        <path d={paths.posLine} fill="none" stroke="var(--color-bullish)" strokeWidth="1" className="glow-green" />

        {/* Neutral Area (Blue/Gray - Middle) */}
        <path d={paths.neuArea} fill="rgba(59, 130, 246, 0.08)" />
        <path d={paths.neuLine} fill="none" stroke="var(--color-neutral)" strokeWidth="1" className="glow-blue" />

        {/* Negative Area (Red - Bottom) */}
        <path d={paths.negArea} fill="rgba(239, 68, 68, 0.12)" />
        <path d={paths.negLine} fill="none" stroke="var(--color-bearish)" strokeWidth="1" className="glow-red" />
      </svg>
    </div>
  );
}

// ==========================================
// CUSTOM SVG CHART COMPONENT: P&L HISTORY
// ==========================================
function PnLHistoryChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height: '220px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#4B5563', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        [ NO HISTORICAL TRADES FOUND // WAITING FOR STRATEGY EXECUTION ]
      </div>
    );
  }

  // Find min and max total P&L to scale Y axis dynamically
  const pnlVals = data.map(d => d.total_pnl);
  const maxVal = Math.max(...pnlVals, 1000.0);
  const minVal = Math.min(...pnlVals, -1000.0);
  
  // Scale Y axis with padding
  const yMax = Math.ceil(maxVal / 500) * 500 + 100;
  const yMin = Math.floor(minVal / 500) * 500 - 100;
  const yRange = yMax - yMin;

  // SVG dimensions
  const width = 500;
  const height = 220;
  const paddingLeft = 60;
  const paddingRight = 10;
  const paddingTop = 20;
  const paddingBottom = 30;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const getX = (index) => paddingLeft + (index / (data.length - 1)) * chartWidth;
  const getY = (val) => paddingTop + chartHeight - ((val - yMin) / yRange) * chartHeight;

  // Generate SVG path string
  const generatePath = () => {
    return data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(d.total_pnl)}`).join(' ');
  };

  const zeroY = getY(0.0);

  return (
    <div style={{ position: 'relative', width: '100%', height: '220px' }}>
      <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
        {/* Horizontal Gridlines & Y-Axis ticks */}
        {[0, 0.25, 0.5, 0.75, 1.0].map((ratio, i) => {
          const val = Math.round(yMin + ratio * yRange);
          const y = getY(val);
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={paddingLeft} y1={y} x2={width - paddingRight} y2={y} />
              <text className="chart-label" x={paddingLeft - 8} y={y + 3} textAnchor="end">
                {val >= 0 ? `+$${val}` : `-$${Math.abs(val)}`}
              </text>
            </g>
          );
        })}

        {/* Zero Line */}
        {zeroY >= paddingTop && zeroY <= paddingTop + chartHeight && (
          <line x1={paddingLeft} y1={zeroY} x2={width - paddingRight} y2={zeroY} stroke="rgba(255, 255, 255, 0.15)" strokeWidth="1.5" strokeDasharray="4 4" />
        )}

        {/* X-Axis Ticks */}
        {data.map((d, i) => {
          if (i % Math.ceil(data.length / 5) !== 0 && i !== data.length - 1) return null;
          const x = getX(i);
          const timeStr = d.timestamp.split('T')[1]?.substring(0, 5) || d.timestamp.substring(5, 10);
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={x} y1={paddingTop} x2={x} y2={paddingTop + chartHeight} />
              <text className="chart-label" x={x} y={paddingTop + chartHeight + 16} textAnchor="middle">{timeStr}</text>
            </g>
          );
        })}

        {/* Axis Lines */}
        <line className="chart-axis-line" x1={paddingLeft} y1={paddingTop} x2={paddingLeft} y2={paddingTop + chartHeight} />
        <line className="chart-axis-line" x1={paddingLeft} y1={paddingTop + chartHeight} x2={width - paddingRight} y2={paddingTop + chartHeight} />

        {/* P&L Line */}
        <path d={generatePath()} fill="none" stroke="var(--color-bullish)" strokeWidth="2" className="glow-green" />
      </svg>
    </div>
  );
}

// ==========================================
// MAIN DASHBOARD APPLICATION COMPONENT
// ==========================================
export default function App() {
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const [backendPing, setBackendPing] = useState(null);
  
  // Real-time Event States
  const [headlines, setHeadlines] = useState([]);
  const [totalHeadlinesCount, setTotalHeadlinesCount] = useState(0);
  const [driftAlerts, setDriftAlerts] = useState([]);
  
  // Historical Analytics States (from ClickHouse)
  const [latencyHistory, setLatencyHistory] = useState([]);
  const [sentimentTrends, setSentimentTrends] = useState([]);
  const [portfolio, setPortfolio] = useState(null);
  const [abStats, setAbStats] = useState([]);
  const [portfolioHistory, setPortfolioHistory] = useState([]);
  const [strategyMode, setStrategyMode] = useState('long_only');
  
  const handleStrategyChange = async (newMode) => {
    setStrategyMode(newMode);
    try {
      await fetch('http://localhost:8000/api/v1/settings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ strategy_mode: newMode })
      });
    } catch (e) {
      console.error("Failed to update strategy settings", e);
    }
  };
  
  // Real-time trading states
  const [showTradeGlow, setShowTradeGlow] = useState(false);
  const [insufficientCapitalAlert, setInsufficientCapitalAlert] = useState(null);

  // Subscriptions & Filtering state
  const [selectedTicker, setSelectedTicker] = useState('ALL');
  
  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const backoffMultiplierRef = useRef(1);

  // Dynamic system metric card counters
  const totalProcessed = totalHeadlinesCount;
  const bullishCount = headlines.filter(h => h.sentiment === 'positive').length;
  const bearishCount = headlines.filter(h => h.sentiment === 'negative').length;
  const neutralCount = headlines.filter(h => h.sentiment === 'neutral').length;
  
  const p99Latency = latencyHistory.length > 0 ? latencyHistory[latencyHistory.length - 1].p99_ms : 0;
  const averageLatency = latencyHistory.length > 0 ? (latencyHistory.reduce((sum, d) => sum + d.p50_ms, 0) / latencyHistory.length).toFixed(1) : 0;

  // 1. Fetch REST API datasets from ClickHouse and health check endpoint
  const fetchTelemetryData = async () => {
    try {
      const tickerParam = selectedTicker === 'ALL' ? '' : `&ticker=${selectedTicker}`;
      
      // Ping check
      const pingRes = await fetch('http://localhost:8000/ping');
      if (pingRes.ok) {
        const pingData = await pingRes.json();
        setBackendPing(pingData);
      }

      // Recent headlines
      const headlinesRes = await fetch(`http://localhost:8000/api/v1/headlines?limit=20${tickerParam}`);
      if (headlinesRes.ok) {
        const headlinesData = await headlinesRes.json();
        setHeadlines(headlinesData.data);
        setTotalHeadlinesCount(headlinesData.total_count || headlinesData.data.length);
      }

      // Latency Percentiles (1 hour window)
      const latRes = await fetch('http://localhost:8000/api/v1/latency-percentiles?window=1h');
      if (latRes.ok) {
        const latData = await latRes.json();
        setLatencyHistory(latData.data);
      }

      // Sentiment Trends (6 hour window)
      const trendsRes = await fetch(`http://localhost:8000/api/v1/sentiment-trends?hours=6${tickerParam}`);
      if (trendsRes.ok) {
        const trendsData = await trendsRes.json();
        setSentimentTrends(trendsData.data);
      }

      // Drift Alerts
      const driftRes = await fetch(`http://localhost:8000/api/v1/drift-alerts?limit=10${tickerParam}`);
      if (driftRes.ok) {
        const driftData = await driftRes.json();
        setDriftAlerts(driftData.alerts);
      }

      // Paper Portfolio Summary
      const portRes = await fetch('http://localhost:8000/api/v1/portfolio');
      if (portRes.ok) {
        const portData = await portRes.json();
        setPortfolio(portData);
      }

      // Model A/B Performance Stats
      const abRes = await fetch('http://localhost:8000/api/v1/ab-stats');
      if (abRes.ok) {
        const abData = await abRes.json();
        setAbStats(abData.data || []);
      }

      // Portfolio History
      const historyRes = await fetch('http://localhost:8000/api/v1/portfolio/history');
      if (historyRes.ok) {
        const historyData = await historyRes.json();
        setPortfolioHistory(historyData.data || []);
      }

      // Strategy settings
      const settingsRes = await fetch('http://localhost:8000/api/v1/settings');
      if (settingsRes.ok) {
        const settingsData = await settingsRes.json();
        setStrategyMode(settingsData.strategy_mode);
      }
    } catch (e) {
      console.error("Rest queries failed", e);
    }
  };

  // 2. Set up WebSockets Connection with robust auto-reconnection
  const connectWebSocket = () => {
    if (socketRef.current) {
      socketRef.current.close();
    }

    setConnectionStatus('connecting');
    const ws = new WebSocket('ws://localhost:8000/ws');
    socketRef.current = ws;

    ws.onopen = () => {
      logger_log("WebSocket connection established successfully.");
      setConnectionStatus('connected');
      backoffMultiplierRef.current = 1; // Reset backoff multiplier

      // Subscribe to target tickers
      const tickers = selectedTicker === 'ALL' ? [] : [selectedTicker];
      ws.send(JSON.stringify({
        type: "subscribe",
        tickers: tickers
      }));
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      const eventType = message.type;
      const eventData = message.data;

      if (eventType === "sentiment") {
        setHeadlines(prev => {
          // Keep a FIFO queue capped at 100 entries to protect memory
          const updated = [eventData, ...prev];
          if (updated.length > 100) updated.pop();
          return updated;
        });
        setTotalHeadlinesCount(prev => prev + 1);
      } else if (eventType === "drift_alert") {
        setDriftAlerts(prev => {
          const updated = [eventData, ...prev];
          if (updated.length > 20) updated.pop();
          return updated;
        });
      } else if (eventType === "paper_trade") {
        logger_log("Paper trade executed live! Refreshing portfolio stats.");
        setShowTradeGlow(true);
        setTimeout(() => {
          setShowTradeGlow(false);
        }, 1500);
        // Re-fetch portfolio data instantly to show live position updates!
        fetchTelemetryData();
      } else if (eventType === "insufficient_capital") {
        logger_log("Insufficient capital warning received!");
        setInsufficientCapitalAlert(eventData);
        setTimeout(() => {
          setInsufficientCapitalAlert(null);
        }, 5000);
      }
    };

    ws.onclose = () => {
      setConnectionStatus('disconnected');
      socketRef.current = null;
      
      // Calculate exponential backoff timer: multiplier * 2s, capped at 30 seconds
      const nextDelay = Math.min(backoffMultiplierRef.current * 2000, 30000);
      backoffMultiplierRef.current = backoffMultiplierRef.current * 1.5;
      
      logger_log(`WebSocket disconnected. Retrying in ${(nextDelay / 1000).toFixed(0)} seconds...`);
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, nextDelay);
    };

    ws.onerror = (err) => {
      console.error("WebSocket socket error:", err);
      ws.close();
    };
  };

  // Helper logging
  const logger_log = (msg) => {
    console.log(`[SENTISTREAM WS] ${msg}`);
  };

  // Trigger re-subscription when user clicks ticker buttons
  useEffect(() => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      const tickers = selectedTicker === 'ALL' ? [] : [selectedTicker];
      socketRef.current.send(JSON.stringify({
        type: "subscribe",
        tickers: tickers
      }));
    }
    // Re-fetch ClickHouse data to align filters
    fetchTelemetryData();
  }, [selectedTicker]);

  // Initial mount setup
  useEffect(() => {
    connectWebSocket();
    fetchTelemetryData();

    // Set polling loops
    const restInterval = setInterval(fetchTelemetryData, 10000); // Poll every 10s

    return () => {
      clearInterval(restInterval);
      if (socketRef.current) socketRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* ==========================================
          HEADER SYSTEM PANEL
          ========================================== */}
      <header className="card" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '16px', borderBottom: '1px solid var(--border-glow)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <h1 style={{ fontSize: '20px', letterSpacing: '0.05em', color: '#FFF', fontFamily: 'var(--font-sans)' }}>
            SENTISTREAM // <span style={{ color: 'var(--color-neutral)' }}>REAL-TIME MLOPS OBSERVABILITY</span>
          </h1>
          <p style={{ fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
            FINBERT SENTIMENT PIPELINE & QUANTITATIVE PAPER TRADING GATEWAY
          </p>
        </div>

        {/* Diagnostics Badges */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '12px' }}>
          <div className="badge badge-neutral" style={{ padding: '4px 10px' }}>
            <span className={`status-indicator ${connectionStatus === 'connected' ? 'online' : connectionStatus === 'connecting' ? 'warning' : 'offline'}`} />
            WS STREAM: {connectionStatus.toUpperCase()}
          </div>
          
          <div className={`badge ${backendPing?.clickhouse === 'warm' ? 'badge-bullish' : 'badge-bearish'}`}>
            CH STORAGE: {backendPing?.clickhouse === 'warm' ? 'WARM' : 'COLD'}
          </div>

          <div className={`badge ${backendPing?.redis === 'warm' ? 'badge-bullish' : 'badge-bearish'}`}>
            REDIS BROKER: {backendPing?.redis === 'warm' ? 'ACTIVE' : 'OFFLINE'}
          </div>

          <div className={`badge ${backendPing?.onnx_model === 'loaded' ? 'badge-bullish' : 'badge-bearish'}`}>
            ONNX Serving: {backendPing?.onnx_model === 'loaded' ? 'INT8' : 'MISSING'}
          </div>
        </div>
      </header>

      {/* ==========================================
          DYNAMIC TICKER SELECTOR BAR
          ========================================== */}
      <div className="card" style={{ padding: '12px 20px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: '600', color: 'var(--text-secondary)' }}>FILTER INSTRUMENT:</span>
          {['ALL', 'AAPL', 'TSLA', 'NVDA', 'SPY'].map(ticker => (
            <button
              key={ticker}
              onClick={() => setSelectedTicker(ticker)}
              style={{
                background: selectedTicker === ticker ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                color: selectedTicker === ticker ? 'var(--color-neutral)' : 'var(--text-secondary)',
                border: `1px solid ${selectedTicker === ticker ? 'var(--color-neutral)' : 'var(--border-light)'}`,
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                fontWeight: '600',
                padding: '4px 12px',
                borderRadius: '4px',
                cursor: 'pointer',
                transition: 'all 0.2s ease'
              }}
            >
              {ticker}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', borderLeft: '1px solid var(--border-light)', paddingLeft: '16px', marginLeft: '4px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: '600', color: 'var(--text-secondary)' }}>STRATEGY:</span>
          <select
            value={strategyMode}
            onChange={(e) => handleStrategyChange(e.target.value)}
            style={{
              background: 'rgba(17, 24, 39, 0.8)',
              color: '#FFF',
              border: '1px solid var(--border-light)',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              padding: '4px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              outline: 'none'
            }}
          >
            <option value="long_only">LONG-ONLY</option>
            <option value="long_short">LONG-SHORT</option>
          </select>
        </div>

        <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
          TOTAL HEADLINES CAPTURED: <span style={{ color: '#FFF', fontWeight: 'bold' }}>{totalProcessed}</span>
        </div>
      </div>

      {/* ==========================================
          METRIC DIAGNOSTIC CARDS
          ========================================== */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '24px' }}>
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>MEAN CPU INFERENCE</span>
          <h2 style={{ fontSize: '28px', color: 'var(--color-neutral)', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>
            {averageLatency}ms
          </h2>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>dynamic dynamic INT8 execution</p>
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>p99 LATENCY SLOWEST</span>
          <h2 style={{ fontSize: '28px', color: 'var(--color-bearish)', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>
            {p99Latency ? `${p99Latency}ms` : 'warming...'}
          </h2>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>columnar percentile read</p>
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>SENTIMENT RATIO</span>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <span style={{ color: 'var(--color-bullish)', fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: '600' }}>+{bullishCount}</span>
            <span style={{ color: 'var(--color-bearish)', fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: '600' }}>-{bearishCount}</span>
            <span style={{ color: 'var(--color-neutral)', fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: '600' }}>={neutralCount}</span>
          </div>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>live classified distribution</p>
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>PAPER PORTFOLIO P&L</span>
          <h2 style={{ fontSize: '28px', color: portfolio?.total_pnl_usd >= 0 ? 'var(--color-bullish)' : 'var(--color-bearish)', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>
            {portfolio ? `$${portfolio.total_pnl_usd.toFixed(2)}` : '$0.00'}
          </h2>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>trades executed: {portfolio?.total_trades || 0}</p>
        </div>
      </section>

      {/* ==========================================
          MAIN DASHBOARD DOUBLE GRID
          ========================================== */}
      <div className="dashboard-grid">
        
        {/* LEFT COLUMN: LIVE TICKER STREAM */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: '550px', overflow: 'hidden' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px' }}>
              <span>LIVE HEADLINE TICKER STREAM</span>
              <span className="status-indicator online" style={{ width: '6px', height: '6px', marginTop: '6px' }} />
            </h2>

            {/* Headline List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px' }}>
              {headlines.length === 0 ? (
                <div style={{ height: '300px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px', color: 'var(--text-muted)' }}>
                  <div className="status-indicator warning" style={{ width: '12px', height: '12px' }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>[ WAITING FOR LIVE FINANCIAL DATA FEED ]</span>
                </div>
              ) : (
                headlines.map((item, idx) => (
                  <div key={idx} style={{ padding: '12px', border: '1px solid var(--border-light)', borderRadius: '6px', background: 'rgba(255,255,255,0.01)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 'bold', color: '#FFF', background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px' }}>
                          {item.ticker}
                        </span>
                        <span className={`badge ${item.sentiment === 'positive' ? 'badge-bullish' : item.sentiment === 'negative' ? 'badge-bearish' : 'badge-neutral'}`}>
                          {item.sentiment} ({Math.round(item.confidence * 100)}%)
                        </span>
                        <span className="badge" style={{
                          backgroundColor: item.model_version === 'v2' ? 'rgba(245, 158, 11, 0.05)' : 'rgba(59, 130, 246, 0.05)',
                          color: item.model_version === 'v2' ? 'var(--color-drift)' : 'var(--color-neutral)',
                          border: `1px solid ${item.model_version === 'v2' ? 'rgba(245, 158, 11, 0.25)' : 'rgba(59, 130, 246, 0.25)'}`,
                          marginLeft: '4px'
                        }}>
                          {(item.model_version || 'v1').toUpperCase()}
                        </span>
                      </div>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-secondary)' }}>
                        {item.processed_at?.split('T')[1]?.substring(0, 8) || ''}
                      </span>
                    </div>

                    <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-primary)', fontWeight: '500' }}>
                      {item.headline}
                    </p>

                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      <span>SOURCE: {item.source.toUpperCase()}</span>
                      <span>INFERENCE LATENCY: {item.latency_ms}ms</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* SIMULATED PAPER TRADING PORTFOLIO COMPONENT */}
          <div className={`card ${showTradeGlow ? 'glow-trade-flash' : ''}`} style={{ display: 'flex', flexDirection: 'column', gap: '16px', transition: 'all 0.3s ease' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px', margin: 0 }}>
              QUANTITATIVE PAPER TRADING PORTFOLIO (HEXAGONAL LOG)
            </h2>

            {insufficientCapitalAlert && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: '6px',
                padding: '10px 14px',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                color: 'var(--color-bearish)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                animation: 'pulse-red 2.5s infinite ease-in-out'
              }}>
                <span className="status-indicator offline" style={{ animation: 'none' }} />
                <span>
                  WARNING: INSUFFICIENT CAPITAL TO BUY {insufficientCapitalAlert.ticker}. REQUIRED: ${insufficientCapitalAlert.required_cash.toFixed(2)} | AVAILABLE: ${insufficientCapitalAlert.available_cash.toFixed(2)}
                </span>
              </div>
            )}

            {/* Portfolio Summary Header Metrics */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
              gap: '12px',
              borderBottom: '1px solid var(--border-light)',
              paddingBottom: '16px'
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>NET VALUE</span>
                <span style={{ fontSize: '15px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: '#FFF' }}>
                  ${portfolio?.portfolio_value_usd !== undefined ? portfolio.portfolio_value_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '100,000.00'}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>CASH BALANCE</span>
                <span style={{ fontSize: '15px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: '#FFF' }}>
                  ${portfolio?.cash_usd !== undefined ? portfolio.cash_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '100,000.00'}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>REALIZED P&L</span>
                <span style={{ fontSize: '15px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: portfolio?.realized_pnl_usd >= 0 ? 'var(--color-bullish)' : 'var(--color-bearish)' }}>
                  ${portfolio?.realized_pnl_usd !== undefined ? (portfolio.realized_pnl_usd >= 0 ? '+' : '') + portfolio.realized_pnl_usd.toFixed(2) : '0.00'}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>UNREALIZED P&L</span>
                <span style={{ fontSize: '15px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: portfolio?.unrealized_pnl_usd >= 0 ? 'var(--color-bullish)' : 'var(--color-bearish)' }}>
                  ${portfolio?.unrealized_pnl_usd !== undefined ? (portfolio.unrealized_pnl_usd >= 0 ? '+' : '') + portfolio.unrealized_pnl_usd.toFixed(2) : '0.00'}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>WIN RATE</span>
                <span style={{ fontSize: '15px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: 'var(--color-neutral)' }}>
                  {portfolio?.win_rate !== undefined ? Math.round(portfolio.win_rate * 100) : 0}%
                </span>
              </div>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '12px', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-light)', color: 'var(--text-secondary)' }}>
                    <th style={{ padding: '8px 12px' }}>TICKER</th>
                    <th style={{ padding: '8px 12px' }}>POSITION</th>
                    <th style={{ padding: '8px 12px' }}>AVG PRICE</th>
                    <th style={{ padding: '8px 12px' }}>CURRENT PRICE</th>
                    <th style={{ padding: '8px 12px' }}>MARKET VALUE</th>
                    <th style={{ padding: '8px 12px' }}>UNREALIZED P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {!portfolio?.positions || portfolio.positions.length === 0 ? (
                    <tr>
                      <td colSpan="6" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                        [ PORTFOLIO IS FLAT // WAITING FOR CONFIDENT SIGNALS TO TRANSACT ]
                      </td>
                    </tr>
                  ) : (
                    portfolio.positions.map((pos, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid var(--border-light)' }}>
                        <td style={{ padding: '10px 12px', fontWeight: 'bold', color: '#FFF' }}>{pos.ticker}</td>
                        <td style={{ padding: '10px 12px', color: pos.shares < 0 ? 'var(--color-drift)' : 'var(--color-bullish)', fontWeight: 'bold' }}>
                          {pos.shares < 0 ? `${Math.abs(pos.shares)} SHORT` : `${pos.shares} SHARES`}
                        </td>
                        <td style={{ padding: '10px 12px' }}>${pos.avg_price.toFixed(2)}</td>
                        <td style={{ padding: '10px 12px' }}>${pos.current_price.toFixed(2)}</td>
                        <td style={{ padding: '10px 12px' }}>${pos.market_value.toFixed(2)}</td>
                        <td style={{ padding: '10px 12px', color: pos.unrealized_pnl >= 0 ? 'var(--color-bullish)' : 'var(--color-bearish)', fontWeight: 'bold' }}>
                          ${pos.unrealized_pnl >= 0 ? '+' : ''}{pos.unrealized_pnl.toFixed(2)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* DRIFT ALERTS */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: '350px', overflow: 'hidden' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px', display: 'flex', justifyContent: 'space-between' }}>
              <span>STATISTICAL DRIFT MONITOR ALERTS</span>
              <span className="badge badge-drift" style={{ fontSize: '9px' }}>ALERT THRESHOLD: |Z| &gt; 2.0</span>
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', paddingRight: '4px' }}>
              {driftAlerts.length === 0 ? (
                <div style={{ height: '140px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  [ DRIFT DETECTOR ACTIVE // SENTIMENT WINDOW STABLE ]
                </div>
              ) : (
                driftAlerts.map((alert, idx) => (
                  <div key={idx} style={{ padding: '10px', border: '1px solid rgba(245, 158, 11, 0.15)', borderRadius: '6px', background: 'rgba(245, 158, 11, 0.02)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="badge badge-drift" style={{ fontSize: '10px' }}>
                        {alert.ticker} DRIFT: {alert.direction.replace('_', ' ').toUpperCase()}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-secondary)' }}>
                        {alert.alerted_at?.split('T')[1]?.substring(0, 8) || ''}
                      </span>
                    </div>

                    <p style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      Rolling Z-Score: <span style={{ color: 'var(--color-drift)', fontWeight: 'bold' }}>{alert.z_score}</span> &nbsp;
                      (Threshold: {alert.triggered_threshold})
                    </p>

                    <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                      Mean: {alert.window_mean} | Std Dev: {alert.window_std}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>

        {/* RIGHT COLUMN: ANALYTICS & DRIFT LOG */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* MODEL A/B PERFORMANCE COMPARISON CARD */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px', display: 'flex', justifyContent: 'space-between', margin: 0 }}>
              <span>MODEL A/B PERFORMANCE (CLICKHOUSE OLAP)</span>
              <span className="badge badge-neutral" style={{ fontSize: '9px', borderColor: 'var(--border-glow)' }}>80/20 SPLIT ACTIVE</span>
            </h2>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {['v1', 'v2'].map(version => {
                const stats = abStats.find(s => s.model_version === version) || {
                  model_version: version,
                  total_count: 0,
                  avg_latency_ms: 0,
                  p50_ms: 0,
                  p95_ms: 0,
                  p99_ms: 0
                };
                
                const isV2 = version === 'v2';
                const accentColor = isV2 ? 'var(--color-drift)' : 'var(--color-neutral)';
                const bgLight = isV2 ? 'rgba(245, 158, 11, 0.02)' : 'rgba(59, 130, 246, 0.02)';
                const borderLightCol = isV2 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(59, 130, 246, 0.15)';
                
                return (
                  <div key={version} style={{ 
                    padding: '14px', 
                    borderRadius: '8px', 
                    background: bgLight, 
                    border: `1px solid ${borderLightCol}`,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid ${borderLightCol}`, paddingBottom: '6px' }}>
                      <span style={{ fontSize: '12px', fontWeight: 'bold', color: '#FFF', fontFamily: 'var(--font-mono)' }}>
                        MODEL {version.toUpperCase()} {isV2 ? '(CHALLENGER)' : '(CHAMPION)'}
                      </span>
                      <span className="status-indicator online" style={{ backgroundColor: accentColor }} />
                    </div>
                    
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px', fontFamily: 'var(--font-mono)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>EVALUATIONS:</span>
                        <span style={{ color: '#FFF', fontWeight: 'bold' }}>{stats.total_count}</span>
                      </div>
                      
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>AVG LATENCY:</span>
                        <span style={{ color: accentColor, fontWeight: 'bold' }}>{stats.avg_latency_ms}ms</span>
                      </div>
                      
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>p50:</span>
                        <span style={{ color: '#FFF' }}>{stats.p50_ms}ms</span>
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>p95:</span>
                        <span style={{ color: '#FFF' }}>{stats.p95_ms}ms</span>
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>p99:</span>
                        <span style={{ color: 'var(--color-bearish)' }}>{stats.p99_ms}ms</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            
            <p style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', margin: 0, textAlign: 'center' }}>
              Deterministic hash routing ensures replay consistency.
            </p>
          </div>

          {/* PORTFOLIO HISTORICAL P&L PATH CARD */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px', display: 'flex', justifyContent: 'space-between', margin: 0 }}>
              <span>PORTFOLIO HISTORICAL P&L PATH</span>
              <span className="badge badge-bullish" style={{ fontSize: '9px' }}>REAL-TIME VALUE</span>
            </h2>
            <PnLHistoryChart data={portfolioHistory} />
          </div>

          {/* LATENCY percentiles */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px', display: 'flex', justifyContent: 'space-between' }}>
              <span>SYSTEM LATENCY PROFILE percentiles</span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                <span style={{ color: 'var(--color-bearish)' }}>■ p99</span> &nbsp;
                <span style={{ color: 'var(--color-drift)' }}>■ p95</span> &nbsp;
                <span style={{ color: 'var(--color-neutral)' }}>■ p50</span>
              </span>
            </h2>
            <LatencyChart data={latencyHistory} />
          </div>

          {/* SENTIMENT TRENDS */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '14px', letterSpacing: '0.05em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '10px', display: 'flex', justifyContent: 'space-between' }}>
              <span>HISTORICAL SENTIMENT TRENDS</span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                <span style={{ color: 'var(--color-bullish)' }}>■ POS</span> &nbsp;
                <span style={{ color: 'var(--color-neutral)' }}>■ NEU</span> &nbsp;
                <span style={{ color: 'var(--color-bearish)' }}>■ NEG</span>
              </span>
            </h2>
            <SentimentTrendChart data={sentimentTrends} />
          </div>

        </section>

      </div>

    </div>
  );
}
