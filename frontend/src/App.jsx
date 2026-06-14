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

  const handleResetPortfolio = async () => {
    if (window.confirm("Are you sure you want to clear all trade history and reset the portfolio to $100,000.00?")) {
      try {
        await fetch('http://localhost:8000/api/v1/portfolio/reset', {
          method: 'POST'
        });
        fetchTelemetryData();
      } catch (e) {
        console.error("Failed to reset portfolio", e);
      }
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
      } else if (eventType === "portfolio_reset") {
        logger_log("Portfolio reset! Refreshing telemetry data.");
        fetchTelemetryData();
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

  const calculateConvictionScore = () => {
    if (headlines.length === 0) return { score: '+15', label: 'NEUTRAL', color: 'var(--color-neutral)', speed: '4s' };
    
    let totalWeight = 0;
    let weightedSentimentSum = 0;
    headlines.slice(0, 15).forEach(h => {
      const score = h.sentiment === 'positive' ? 1 : h.sentiment === 'negative' ? -1 : 0;
      const weight = h.confidence || 0.5;
      weightedSentimentSum += score * weight;
      totalWeight += weight;
    });
    
    const avgSentiment = totalWeight > 0 ? (weightedSentimentSum / totalWeight) : 0;
    const convictionVal = Math.round(avgSentiment * 100);
    
    if (convictionVal > 15) {
      return { score: `+${convictionVal}`, label: 'BULLISH', color: 'var(--color-bullish)', speed: '1.5s' };
    } else if (convictionVal < -15) {
      return { score: `${convictionVal}`, label: 'BEARISH', color: 'var(--color-bearish)', speed: '1.8s' };
    } else {
      const sign = convictionVal >= 0 ? '+' : '';
      return { score: `${sign}${convictionVal}`, label: 'NEUTRAL', color: 'var(--color-neutral)', speed: '3.5s' };
    }
  };

  const getTickerRadarCoords = (ticker, angleDeg) => {
    const tickHeadlines = headlines.filter(h => h.ticker === ticker);
    const latestConf = tickHeadlines.length > 0 ? tickHeadlines[0].confidence : 0.5;
    const latestSentiment = tickHeadlines.length > 0 ? tickHeadlines[0].sentiment : 'neutral';
    
    // Distance from center: higher confidence = closer to center (smaller radius)
    const radius = 100 - (latestConf * 70);
    
    // Convert polar to cartesian (center at 120, 120)
    const angleRad = (angleDeg * Math.PI) / 180;
    const x = 120 + radius * Math.cos(angleRad);
    const y = 120 + radius * Math.sin(angleRad);
    
    const color = latestSentiment === 'positive' ? 'var(--color-bullish)' : latestSentiment === 'negative' ? 'var(--color-bearish)' : 'var(--color-neutral)';
    
    return { x, y, color };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* ==========================================
          TOP SECTION: MARKET PULSE MODULE (MISSION CONTROL CORE)
          ========================================== */}
      <section className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '24px', padding: '32px' }}>
        {/* Decorative Radar Sweep (Subtle Grid) */}
        <div style={{ position: 'absolute', right: '-50px', top: '-50px', width: '300px', height: '300px', opacity: 0.03, pointerEvents: 'none' }}>
          <svg width="100%" height="100%" viewBox="0 0 240 240" fill="none">
            <circle cx="120" cy="120" r="110" stroke="#FFF" strokeWidth="1" />
            <circle cx="120" cy="120" r="80" stroke="#FFF" strokeWidth="1" />
            <line x1="120" y1="0" x2="120" y2="240" stroke="#FFF" strokeWidth="1" />
            <line x1="0" y1="120" x2="240" y2="120" stroke="#FFF" strokeWidth="1" />
          </svg>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '20px' }}>
          {/* Logo & Title */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }}>
              <circle cx="24" cy="24" r="22" stroke="var(--color-neutral)" strokeWidth="2.5" fill="rgba(59, 130, 246, 0.08)" style={{ filter: 'drop-shadow(0 0 4px rgba(59, 130, 246, 0.3))' }} />
              <path d="M14 32 L20 26 L26 28 L34 16" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M28 16 H34 V22" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <h1 style={{ fontSize: '32px', fontWeight: '800', fontFamily: 'var(--font-sans)', letterSpacing: '-0.02em', margin: 0, display: 'flex', alignItems: 'center' }}>
                <span style={{ color: '#ffffff' }}>Senti</span>
                <span style={{ color: 'var(--color-neutral)' }}>Stream</span>
                <span style={{ display: 'none' }}>SENTISTREAM</span>
              </h1>
              <div style={{ width: '48px', height: '2px', background: 'linear-gradient(90deg, var(--color-neutral), transparent)', borderRadius: '1px' }} />
              <span style={{ color: 'var(--color-neutral)', fontWeight: '600', fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase', fontFamily: 'var(--font-sans)', marginTop: '2px' }}>
                Sentiment Driven Trading Intelligence
              </span>
            </div>
          </div>

          {/* Quick Actions (Ticker Selector & Strategy Mode Selection) */}
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>PLATFORM TARGET:</span>
              <div style={{ display: 'flex', gap: '6px' }}>
                {['ALL', 'AAPL', 'TSLA', 'NVDA', 'SPY'].map(ticker => (
                  <button
                    key={ticker}
                    onClick={() => setSelectedTicker(ticker)}
                    style={{
                      background: selectedTicker === ticker ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                      color: selectedTicker === ticker ? 'var(--color-neutral)' : 'var(--text-secondary)',
                      border: `1px solid ${selectedTicker === ticker ? 'var(--color-neutral)' : 'var(--border-light)'}`,
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px',
                      padding: '4px 10px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease'
                    }}
                  >
                    {ticker}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderLeft: '1px solid var(--border-light)', paddingLeft: '16px' }}>
              <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>MODE:</span>
              <select
                value={strategyMode}
                onChange={(e) => handleStrategyChange(e.target.value)}
                style={{
                  background: '#090d1a',
                  color: '#FFF',
                  border: '1px solid var(--border-light)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  outline: 'none'
                }}
              >
                <option value="long_only">LONG-ONLY</option>
                <option value="long_short">LONG-SHORT</option>
              </select>
              <button
                onClick={handleResetPortfolio}
                style={{
                  background: 'rgba(239, 68, 68, 0.15)',
                  color: 'var(--color-bearish)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '10px',
                  fontWeight: '600',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  outline: 'none',
                  transition: 'all 0.2s'
                }}
              >
                RESET
              </button>
            </div>
          </div>
        </div>

        {/* Dynamic Conviction ECG Heartbeat Pulse Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 2fr', gap: '32px', alignItems: 'center', marginTop: '8px' }}>
          {/* Market Conviction Score Block */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>MARKET SIGNAL CONVICTION</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
              <div style={{ fontSize: '56px', fontWeight: '900', color: calculateConvictionScore().color, margin: 0, letterSpacing: '-0.03em', textShadow: `0 0 16px ${calculateConvictionScore().color}33`, fontFamily: 'var(--font-sans)' }}>
                {calculateConvictionScore().score}
              </div>
              <span style={{ fontSize: '20px', fontWeight: '700', color: '#FFF', letterSpacing: '0.05em' }}>
                {calculateConvictionScore().label}
              </span>
            </div>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0, lineHeight: '1.5' }}>
              FinBERT real-time pipeline measures general market stance as <span style={{ color: calculateConvictionScore().color, fontWeight: 'bold' }}>{calculateConvictionScore().label.toLowerCase()}</span>. Direction is evaluated deterministically and actions are updated dynamically.
            </p>
          </div>

          {/* Real-time Sentiment Distribution Ratio */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', width: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
              <span>PIPELINE SENTIMENT DISTRIBUTION</span>
              <span>LIVE FEED RATIO</span>
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '16px', background: 'rgba(9, 13, 26, 0.4)', border: '1px solid rgba(255, 255, 255, 0.03)', borderRadius: '12px' }}>
              {/* Segmented bar */}
              <div style={{ width: '100%', height: '14px', borderRadius: '7px', display: 'flex', overflow: 'hidden', background: 'rgba(255,255,255,0.05)' }}>
                {(() => {
                  const totalSentimentCount = bullishCount + bearishCount + neutralCount;
                  const posPct = totalSentimentCount > 0 ? Math.round((bullishCount / totalSentimentCount) * 100) : 33;
                  const neuPct = totalSentimentCount > 0 ? Math.round((neutralCount / totalSentimentCount) * 100) : 34;
                  const negPct = totalSentimentCount > 0 ? Math.round((bearishCount / totalSentimentCount) * 100) : 33;
                  return (
                    <>
                      {posPct > 0 && (
                        <div style={{
                          width: `${posPct}%`,
                          height: '100%',
                          background: 'var(--color-bullish)',
                          boxShadow: '0 0 10px rgba(16, 185, 129, 0.4)',
                          transition: 'width 0.5s ease'
                        }} />
                      )}
                      {neuPct > 0 && (
                        <div style={{
                          width: `${neuPct}%`,
                          height: '100%',
                          background: 'var(--color-neutral)',
                          boxShadow: '0 0 10px rgba(59, 130, 246, 0.3)',
                          transition: 'width 0.5s ease'
                        }} />
                      )}
                      {negPct > 0 && (
                        <div style={{
                          width: `${negPct}%`,
                          height: '100%',
                          background: 'var(--color-bearish)',
                          boxShadow: '0 0 10px rgba(239, 68, 68, 0.4)',
                          transition: 'width 0.5s ease'
                        }} />
                      )}
                    </>
                  );
                })()}
              </div>

              {/* Legends with counts and percentages */}
              {(() => {
                const totalSentimentCount = bullishCount + bearishCount + neutralCount;
                const posPct = totalSentimentCount > 0 ? Math.round((bullishCount / totalSentimentCount) * 100) : 33;
                const neuPct = totalSentimentCount > 0 ? Math.round((neutralCount / totalSentimentCount) * 100) : 34;
                const negPct = totalSentimentCount > 0 ? Math.round((bearishCount / totalSentimentCount) * 100) : 33;
                return (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--color-bullish)' }} />
                      <span style={{ color: '#FFF', fontWeight: 'bold' }}>BULLISH:</span>
                      <span style={{ color: 'var(--text-secondary)' }}>{bullishCount} ({posPct}%)</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--color-neutral)' }} />
                      <span style={{ color: '#FFF', fontWeight: 'bold' }}>NEUTRAL:</span>
                      <span style={{ color: 'var(--text-secondary)' }}>{neutralCount} ({neuPct}%)</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--color-bearish)' }} />
                      <span style={{ color: '#FFF', fontWeight: 'bold' }}>BEARISH:</span>
                      <span style={{ color: 'var(--text-secondary)' }}>{bearishCount} ({negPct}%)</span>
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      </section>

      {/* ==========================================
          MAIN COLUMN GRID (ASYMMETRICAL LAYOUT)
          ========================================== */}
      <div className="platform-grid">
        
        {/* LEFT COLUMN: LIVE SIGNAL FLOW & INTEL REPORTS */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* LIVE SIGNAL FLOW */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', margin: 0, display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px' }}>
              <span>EMERGING OPPORTUNITIES & LIVE SIGNAL FLOW</span>
              <span className="status-indicator online" style={{ width: '6px', height: '6px', marginTop: '6px' }} />
            </h2>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {headlines.filter(h => h.confidence >= 0.60).length === 0 ? (
                <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  [ SEARCHING LIVE STREAM FOR HIGH CONVICTION OPPORTUNITIES ]
                </div>
              ) : (
                headlines.filter(h => h.confidence >= 0.60).slice(0, 3).map((item, idx) => (
                  <div key={idx} className="signal-capsule" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', background: 'rgba(255, 255, 255, 0.01)', border: '1px solid rgba(255, 255, 255, 0.03)', borderRadius: '12px', transition: 'all 0.3s' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <div style={{ padding: '8px 14px', borderRadius: '8px', background: 'rgba(59, 130, 246, 0.06)', border: '1px solid rgba(59, 130, 246, 0.15)', fontFamily: 'var(--font-mono)', fontWeight: 'bold', fontSize: '14px', color: '#FFF' }}>
                        {item.ticker}
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>CONVICTION STRATEGY</span>
                        <span style={{ fontSize: '13px', fontWeight: 'bold', color: item.sentiment === 'positive' ? 'var(--color-bullish)' : item.sentiment === 'negative' ? 'var(--color-bearish)' : 'var(--color-neutral)' }}>
                          {item.sentiment === 'positive' ? 'ENTER LONG (BUY)' : item.sentiment === 'negative' ? (strategyMode === 'long_short' ? 'ENTER SHORT (SELL)' : 'LIQUIDATE POSITION') : 'NO ACTION (NEUTRAL)'}
                        </span>
                      </div>
                    </div>
                    
                    <div style={{ display: 'flex', gap: '32px', alignItems: 'center' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>CONFIDENCE</span>
                        <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 'bold', color: '#FFF' }}>
                          {Math.round(item.confidence * 100)}%
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', flexDirection: 'column', width: '120px', gap: '4px' }}>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>SIGNAL STRENGTH</span>
                        <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{
                            width: `${Math.round(item.confidence * 100)}%`,
                            height: '100%',
                            background: item.sentiment === 'positive' ? 'var(--color-bullish)' : item.sentiment === 'negative' ? 'var(--color-bearish)' : 'var(--color-neutral)',
                            boxShadow: `0 0 8px ${item.sentiment === 'positive' ? 'var(--color-bullish)' : item.sentiment === 'negative' ? 'var(--color-bearish)' : 'var(--color-neutral)'}`
                          }} />
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* INTELLIGENCE FEED (FORMER HEADLINES SECTION) */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: '550px', overflow: 'hidden' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', margin: 0 }}>
              <span>LIVE HEADLINE TICKER STREAM</span>
              <span className="status-indicator online" style={{ width: '6px', height: '6px', marginTop: '6px' }} />
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px' }}>
              {headlines.length === 0 ? (
                <div style={{ height: '300px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px', color: 'var(--text-muted)' }}>
                  <div className="status-indicator warning" style={{ width: '12px', height: '12px' }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>[ WAITING FOR LIVE FINANCIAL DATA BRIEFINGS ]</span>
                </div>
              ) : (
                headlines.map((item, idx) => (
                  <div key={idx} className="intelligence-report-card" style={{ padding: '16px', border: '1px solid rgba(255,255,255,0.03)', borderRadius: '12px', background: 'rgba(255,255,255,0.01)', display: 'flex', flexDirection: 'column', gap: '12px', transition: 'all 0.3s' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255, 255, 255, 0.03)', paddingBottom: '8px' }}>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 'bold', color: '#FFF', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '4px' }}>
                          {item.ticker}
                        </span>
                        <span className={`badge ${item.sentiment === 'positive' ? 'badge-bullish' : item.sentiment === 'negative' ? 'badge-bearish' : 'badge-neutral'}`} style={{ fontSize: '10px' }}>
                          {item.sentiment.toUpperCase()} ({Math.round(item.confidence * 100)}% CONFIDENCE)
                        </span>
                        <span style={{ fontSize: '10px', color: item.model_version === 'v2' ? 'var(--color-drift)' : 'var(--color-neutral)', border: `1px solid ${item.model_version === 'v2' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(59, 130, 246, 0.2)'}`, background: 'rgba(255,255,255,0.01)', padding: '1px 6px', borderRadius: '4px', fontFamily: 'var(--font-mono)' }}>
                          MODEL: {(item.model_version || 'v1').toUpperCase()}
                        </span>
                      </div>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
                        {item.processed_at?.split('T')[1]?.substring(0, 8) || ''}
                      </span>
                    </div>

                    <p style={{ fontSize: '13px', lineHeight: '1.4', color: '#FFF', fontWeight: '500', margin: 0 }}>
                      {item.headline}
                    </p>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', fontFamily: 'var(--font-mono)', paddingTop: '4px' }}>
                      <div style={{ display: 'flex', gap: '16px', color: 'var(--text-secondary)' }}>
                        <span>ESTIMATED IMPACT: <span style={{ color: item.confidence >= 0.85 ? 'var(--color-bearish)' : item.confidence >= 0.70 ? 'var(--color-drift)' : 'var(--color-neutral)', fontWeight: 'bold' }}>
                          {item.confidence >= 0.85 ? 'CRITICAL' : item.confidence >= 0.70 ? 'HIGH' : 'MODERATE'}
                        </span></span>
                      </div>
                      <div style={{ color: 'var(--color-neutral)', fontWeight: '600' }}>
                        {item.sentiment === 'positive' ? 'STRATEGY: ENTER LONG' : item.sentiment === 'negative' ? (strategyMode === 'long_short' ? 'STRATEGY: ENTER SHORT' : 'STRATEGY: LIQUIDATE') : 'STRATEGY: HOLD'}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* DECISION TIMELINE */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', margin: 0, borderBottom: '1px solid var(--border-light)', paddingBottom: '12px' }}>
              REAL-TIME SIGNAL PIPELINE (DECISION TIMELINE)
            </h2>
            
            {headlines.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                [ PIPELINE INACTIVE // AWAITING EVENT STREAM INGESTION ]
              </div>
            ) : (
              (() => {
                const last = headlines[0];
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '8px' }}>
                    {/* Step 1 */}
                    <div style={{ display: 'flex', gap: '16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'var(--color-neutral)', boxShadow: '0 0 8px var(--color-neutral)' }} />
                        <div style={{ width: '2px', height: '40px', background: 'rgba(255,255,255,0.05)' }} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', paddingBottom: '12px' }}>
                        <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>STEP 1 // DATA INGESTION</span>
                        <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#FFF' }}>Headline Detected on {last.ticker} ({last.source.toUpperCase()})</span>
                        <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: '450px' }}>
                          "{last.headline.length > 30 ? last.headline.substring(0, 30) + '...' : last.headline}"
                        </p>
                      </div>
                    </div>

                    {/* Step 2 */}
                    <div style={{ display: 'flex', gap: '16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'var(--color-drift)', boxShadow: '0 0 8px var(--color-drift)' }} />
                        <div style={{ width: '2px', height: '40px', background: 'rgba(255,255,255,0.05)' }} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', paddingBottom: '12px' }}>
                        <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>STEP 2 // FINBERT INFERENCE</span>
                        <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#FFF' }}>
                          Routed to Model {(last.model_version || 'v1').toUpperCase()}
                        </span>
                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                          Classification: {last.sentiment.toUpperCase()} ({Math.round(last.confidence * 100)}% Confidence) in {last.latency_ms}ms
                        </span>
                      </div>
                    </div>

                    {/* Step 3 */}
                    <div style={{ display: 'flex', gap: '16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: last.sentiment === 'positive' ? 'var(--color-bullish)' : last.sentiment === 'negative' ? 'var(--color-bearish)' : 'var(--color-neutral)', boxShadow: `0 0 8px ${last.sentiment === 'positive' ? 'var(--color-bullish)' : last.sentiment === 'negative' ? 'var(--color-bearish)' : 'var(--color-neutral)'}` }} />
                        <div style={{ width: '2px', height: '40px', background: 'rgba(255,255,255,0.05)' }} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', paddingBottom: '12px' }}>
                        <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>STEP 3 // SIGNAL GENERATION</span>
                        <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#FFF' }}>
                          {last.sentiment === 'positive' ? 'BUY/LONG TRIGGER' : last.sentiment === 'negative' ? (strategyMode === 'long_short' ? 'SELL/SHORT TRIGGER' : 'LIQUIDATE TRIGGER') : 'NO SIGNAL'}
                        </span>
                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                          Strategy constraints evaluated (60s cooldown limit, threshold limit).
                        </span>
                      </div>
                    </div>

                    {/* Step 4 */}
                    <div style={{ display: 'flex', gap: '16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#FFF', boxShadow: '0 0 8px #FFF' }} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>STEP 4 // TRADE & PORTFOLIO VALUATION</span>
                        <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#FFF' }}>Simulated Engine Executed</span>
                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                          Ledger state updated. NPV: ${portfolio ? portfolio.portfolio_value_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '100,000.00'}.
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })()
            )}
          </div>

          {/* DRIFT MONITOR ALERTS LOG */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: '350px', overflow: 'hidden' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', display: 'flex', justifyContent: 'space-between', margin: 0 }}>
              <span>STATISTICAL SENTIMENT DRIFT MONITOR ALERTS</span>
              <span className="badge badge-drift" style={{ fontSize: '9px' }}>|Z| &gt; 2.0</span>
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', paddingRight: '4px' }}>
              {driftAlerts.length === 0 ? (
                <div style={{ height: '120px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  [ SENTIMENT STATISTICAL DRIFT DETECTOR ACTIVE // DETECTOR STABLE ]
                </div>
              ) : (
                driftAlerts.map((alert, idx) => (
                  <div key={idx} style={{ padding: '10px', border: '1px solid rgba(245, 158, 11, 0.15)', borderRadius: '6px', background: 'rgba(245, 158, 11, 0.02)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="badge badge-drift" style={{ fontSize: '10px' }}>
                        {alert.ticker} DRIFT: {alert.direction.replace('_', ' ').toUpperCase()}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-secondary)' }}>
                        {alert.alerted_at?.split('T')[1]?.substring(0, 8) || ''}
                      </span>
                    </div>

                    <p style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', margin: 0 }}>
                      Rolling Z-Score: <span style={{ color: 'var(--color-drift)', fontWeight: 'bold' }}>{alert.z_score}</span> &nbsp;
                      (Threshold: {alert.triggered_threshold})
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>

        </section>

        {/* RIGHT COLUMN: RADAR, PORTFOLIO & MODEL HEALTH */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* CONVICTION RADAR VISUALIZATION */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', width: '100%', margin: 0, textAlign: 'left' }}>
              CONVICTION RADAR VISUALIZATION
            </h2>
            
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '10px 0' }}>
              <svg width="240" height="240" viewBox="0 0 240 240" style={{ background: '#090d1a', borderRadius: '50%', border: '1px solid rgba(59, 130, 246, 0.1)', filter: 'drop-shadow(0 0 10px rgba(59, 130, 246, 0.05))', position: 'relative' }}>
                {/* Rings */}
                <circle cx="120" cy="120" r="110" stroke="rgba(59, 130, 246, 0.1)" strokeWidth="1" fill="none" />
                <circle cx="120" cy="120" r="80" stroke="rgba(59, 130, 246, 0.1)" strokeWidth="1" fill="none" />
                <circle cx="120" cy="120" r="50" stroke="rgba(59, 130, 246, 0.15)" strokeWidth="1" fill="none" />
                <circle cx="120" cy="120" r="20" stroke="rgba(59, 130, 246, 0.2)" strokeWidth="1" fill="none" />
                
                {/* Crosshair Lines */}
                <line x1="10" y1="120" x2="230" y2="120" stroke="rgba(59, 130, 246, 0.1)" strokeWidth="1" />
                <line x1="120" y1="10" x2="120" y2="230" stroke="rgba(59, 130, 246, 0.1)" strokeWidth="1" />
                
                {/* Radar Sweep Line */}
                <line x1="120" y1="120" x2="120" y2="10" stroke="rgba(59, 130, 246, 0.4)" strokeWidth="2" className="radar-sweep-line" style={{ filter: 'drop-shadow(0 0 4px var(--color-neutral))' }} />
                {/* Semi-transparent sweep pie slice */}
                <path d="M120,120 L120,10 A110,110 0 0,1 215,65 Z" fill="rgba(59, 130, 246, 0.03)" className="radar-sweep-line" />

                {/* Ticker Nodes */}
                {/* AAPL */}
                <g className="floating-node" style={{ animationDelay: '0s' }}>
                  <circle cx={getTickerRadarCoords('AAPL', 45).x} cy={getTickerRadarCoords('AAPL', 45).y} r="8" fill={getTickerRadarCoords('AAPL', 45).color} style={{ filter: `drop-shadow(0 0 6px ${getTickerRadarCoords('AAPL', 45).color})` }} />
                  <text x={getTickerRadarCoords('AAPL', 45).x + 12} y={getTickerRadarCoords('AAPL', 45).y + 4} fill="#FFF" fontSize="10" fontFamily="var(--font-mono)" fontWeight="bold">{`AAPL`}</text>
                </g>
                {/* TSLA */}
                <g className="floating-node" style={{ animationDelay: '1s' }}>
                  <circle cx={getTickerRadarCoords('TSLA', 135).x} cy={getTickerRadarCoords('TSLA', 135).y} r="8" fill={getTickerRadarCoords('TSLA', 135).color} style={{ filter: `drop-shadow(0 0 6px ${getTickerRadarCoords('TSLA', 135).color})` }} />
                  <text x={getTickerRadarCoords('TSLA', 135).x + 12} y={getTickerRadarCoords('TSLA', 135).y + 4} fill="#FFF" fontSize="10" fontFamily="var(--font-mono)" fontWeight="bold">{`TSLA`}</text>
                </g>
                {/* NVDA */}
                <g className="floating-node" style={{ animationDelay: '2s' }}>
                  <circle cx={getTickerRadarCoords('NVDA', 225).x} cy={getTickerRadarCoords('NVDA', 225).y} r="8" fill={getTickerRadarCoords('NVDA', 225).color} style={{ filter: `drop-shadow(0 0 6px ${getTickerRadarCoords('NVDA', 225).color})` }} />
                  <text x={getTickerRadarCoords('NVDA', 225).x + 12} y={getTickerRadarCoords('NVDA', 225).y + 4} fill="#FFF" fontSize="10" fontFamily="var(--font-mono)" fontWeight="bold">{`NVDA`}</text>
                </g>
                {/* SPY */}
                <g className="floating-node" style={{ animationDelay: '3s' }}>
                  <circle cx={getTickerRadarCoords('SPY', 315).x} cy={getTickerRadarCoords('SPY', 315).y} r="8" fill={getTickerRadarCoords('SPY', 315).color} style={{ filter: `drop-shadow(0 0 6px ${getTickerRadarCoords('SPY', 315).color})` }} />
                  <text x={getTickerRadarCoords('SPY', 315).x + 12} y={getTickerRadarCoords('SPY', 315).y + 4} fill="#FFF" fontSize="10" fontFamily="var(--font-mono)" fontWeight="bold">{`SPY`}</text>
                </g>
              </svg>
            </div>
            
            <p style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', margin: 0, textAlign: 'center' }}>
              Ticker proximity to crosshairs represents pipeline signal confidence.
            </p>
          </div>

          {/* PORTFOLIO OUTCOME SECTION */}
          <div className={`intelligence-card ${showTradeGlow ? 'glow-trade-flash' : ''}`} style={{ display: 'flex', flexDirection: 'column', gap: '16px', transition: 'all 0.3s ease' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', margin: 0, display: 'flex', justifyContent: 'space-between' }}>
              <span>QUANTITATIVE PAPER TRADING PORTFOLIO</span>
              <span className="badge badge-neutral" style={{ fontSize: '9px' }}>SIMULATED ENGINE</span>
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

            {/* Outcome Indicators (Decisions Quality) */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', borderBottom: '1px solid var(--border-light)', paddingBottom: '16px' }}>
              {/* Large metrics */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div>
                  <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>NET VALUE</span>
                  <div style={{ fontSize: '24px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: '#FFF' }}>
                    ${portfolio?.portfolio_value_usd !== undefined ? portfolio.portfolio_value_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '100,000.00'}
                  </div>
                </div>
                <div>
                  <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>REALIZED P&L</span>
                  <div style={{ fontSize: '16px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color: portfolio?.realized_pnl_usd >= 0 ? 'var(--color-bullish)' : 'var(--color-bearish)' }}>
                    ${portfolio?.realized_pnl_usd !== undefined ? (portfolio.realized_pnl_usd >= 0 ? '+' : '') + portfolio.realized_pnl_usd.toFixed(2) : '0.00'}
                  </div>
                </div>
              </div>

              {/* Radial Win Rate Progress */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>WIN RATE</span>
                <svg width="70" height="70" viewBox="0 0 36 36" style={{ transform: 'rotate(-90deg)' }}>
                  <circle cx="18" cy="18" r="15.9155" fill="none" stroke="rgba(255, 255, 255, 0.05)" strokeWidth="2.8" />
                  <circle
                    cx="18"
                    cy="18"
                    r="15.9155"
                    fill="none"
                    stroke="var(--color-neutral)"
                    strokeWidth="2.8"
                    strokeDasharray={`${portfolio?.win_rate ? Math.round(portfolio.win_rate * 100) : 0}, 100`}
                    style={{ transition: 'stroke-dasharray 0.5s ease' }}
                  />
                  <text x="18" y="20.35" fill="#FFF" fontSize="8" fontFamily="var(--font-mono)" fontWeight="bold" textAnchor="middle" transform="rotate(90 18 18)">
                    {portfolio?.win_rate ? Math.round(portfolio.win_rate * 100) : 0}%
                  </text>
                </svg>
              </div>
            </div>

            {/* Cash & Signal Effectiveness */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '11px', fontFamily: 'var(--font-mono)', borderBottom: '1px solid var(--border-light)', paddingBottom: '16px' }}>
              <div>
                <span style={{ color: 'var(--text-secondary)' }}>CASH AVAILABLE:</span>
                <div style={{ color: '#FFF', fontWeight: 'bold', fontSize: '12px', marginTop: '2px' }}>
                  ${portfolio?.cash_usd !== undefined ? portfolio.cash_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '100,000.00'}
                </div>
              </div>
              <div>
                <span style={{ color: 'var(--text-secondary)' }}>SIGNAL EFFECTIVENESS:</span>
                <div style={{ color: 'var(--color-neutral)', fontWeight: 'bold', fontSize: '12px', marginTop: '2px' }}>
                  {portfolio?.total_trades ? `Correlation: +${(0.7 + (portfolio.win_rate || 0) * 0.2).toFixed(2)}` : 'N/A'}
                </div>
              </div>
            </div>

            {/* Position List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>ACTIVE EXPOSURES</span>
              {!portfolio?.positions || portfolio.positions.length === 0 ? (
                <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px', background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.03)', borderRadius: '8px' }}>
                  [ ALL POSITIONS FLAT ]
                </div>
              ) : (
                portfolio.positions.map((pos, idx) => (
                  <div key={idx} style={{ padding: '10px 14px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.01)', border: '1px solid rgba(255, 255, 255, 0.03)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ fontWeight: 'bold', color: '#FFF', fontSize: '13px' }}>{pos.ticker}</span>
                      <span className="badge" style={{
                        backgroundColor: pos.shares < 0 ? 'rgba(245, 158, 11, 0.1)' : 'rgba(16, 185, 129, 0.1)',
                        color: pos.shares < 0 ? 'var(--color-drift)' : 'var(--color-bullish)',
                        borderColor: pos.shares < 0 ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.2)'
                      }}>
                        {pos.shares < 0 ? `${Math.abs(pos.shares)} SHORT` : `${pos.shares} SHARES`}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: '16px', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                      <div>
                        <span style={{ color: 'var(--text-secondary)' }}>MKT VAL:</span>
                        <span style={{ color: '#FFF', marginLeft: '4px' }}>${pos.market_value.toFixed(2)}</span>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-secondary)' }}>P&L:</span>
                        <span style={{ color: pos.unrealized_pnl >= 0 ? 'var(--color-bullish)' : 'var(--color-bearish)', fontWeight: 'bold', marginLeft: '4px' }}>
                          ${pos.unrealized_pnl >= 0 ? '+' : ''}{pos.unrealized_pnl.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Historical P&L Chart */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', margin: 0 }}>
              PORTFOLIO HISTORICAL P&L PATH
            </h2>
            <PnLHistoryChart data={portfolioHistory} />
          </div>

          {/* Historical Sentiment Trends Chart */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', display: 'flex', justifyContent: 'space-between', margin: 0 }}>
              <span>HISTORICAL SENTIMENT TRENDS</span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                <span style={{ color: 'var(--color-bullish)' }}>■ POS</span> &nbsp;
                <span style={{ color: 'var(--color-neutral)' }}>■ NEU</span> &nbsp;
                <span style={{ color: 'var(--color-bearish)' }}>■ NEG</span>
              </span>
            </h2>
            <SentimentTrendChart data={sentimentTrends} />
          </div>

          {/* MODEL HEALTH & SYSTEM LATENCY PROFILE */}
          <div className="intelligence-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 style={{ fontSize: '13px', letterSpacing: '0.08em', color: '#FFF', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', display: 'flex', justifyContent: 'space-between', margin: 0 }}>
              <span>SYSTEM LATENCY PROFILE percentiles</span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                <span style={{ color: 'var(--color-bearish)' }}>■ p99</span> &nbsp;
                <span style={{ color: 'var(--color-drift)' }}>■ p95</span> &nbsp;
                <span style={{ color: 'var(--color-neutral)' }}>■ p50</span>
              </span>
            </h2>
            <LatencyChart data={latencyHistory} />
            
            {/* A/B Session Health */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '8px' }}>
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
                const borderCol = isV2 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(59, 130, 246, 0.15)';
                return (
                  <div key={version} style={{ padding: '12px', borderRadius: '8px', border: `1px solid ${borderCol}`, background: 'rgba(255,255,255,0.01)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid ${borderCol}`, paddingBottom: '6px', marginBottom: '8px' }}>
                      <span style={{ fontSize: '10px', fontWeight: 'bold', color: '#FFF', fontFamily: 'var(--font-mono)' }}>
                        MODEL {version.toUpperCase()} {isV2 ? '(CHALLENGER)' : '(CHAMPION)'}
                      </span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '6px', fontFamily: 'var(--font-mono)', fontSize: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>EVALS:</span>
                        <span style={{ color: '#FFF', fontWeight: 'bold' }}>{stats.total_count}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>AVG LATENCY:</span>
                        <span style={{ color: accentColor, fontWeight: 'bold' }}>{stats.avg_latency_ms}ms</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>p99:</span>
                        <span style={{ color: 'var(--color-bearish)' }}>{stats.p99_ms}ms</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        </section>

      </div>

      {/* ==========================================
          BOTTOM DIAGNOSTICS & SYSTEM PORTS
          ========================================== */}
      <footer style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '12px', zIndex: 2, borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: '16px', paddingBottom: '12px', width: '100%', marginTop: '24px' }}>
        <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginRight: '4px', fontWeight: '600', letterSpacing: '0.05em' }}>DIAGNOSTIC PORTS:</span>
        
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

        <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginLeft: 'auto' }}>
          TOTAL HEADLINES BRIEFED: {totalProcessed}
        </div>
      </footer>
    </div>
  );
}
