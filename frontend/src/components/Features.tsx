import { FeatureCard } from "./FeatureCard";
import styles from "../styles/features.module.css";

/* -- Mock visuals -- */

function GraphMock() {
  const nodes = [
    { x: "18%", y: "22%", size: 42, color: "var(--accent-cyan)" },
    { x: "58%", y: "14%", size: 30, color: "var(--accent-violet)" },
    { x: "78%", y: "52%", size: 36, color: "var(--accent-blue)" },
    { x: "42%", y: "58%", size: 48, color: "var(--accent-cyan)" },
    { x: "22%", y: "72%", size: 26, color: "var(--accent-violet)" },
    { x: "68%", y: "80%", size: 32, color: "var(--accent-blue)" },
  ] as const;

  const edges = [
    { x1: 18, y1: 22, x2: 58, y2: 14 },
    { x1: 58, y1: 14, x2: 78, y2: 52 },
    { x1: 18, y1: 22, x2: 42, y2: 58 },
    { x1: 42, y1: 58, x2: 78, y2: 52 },
    { x1: 42, y1: 58, x2: 22, y2: 72 },
    { x1: 22, y1: 72, x2: 68, y2: 80 },
    { x1: 78, y1: 52, x2: 68, y2: 80 },
  ];

  return (
    <div className={styles.mockPanel}>
      <div className={styles.graphCanvas}>
        {edges.map((e, i) => {
          const dx = e.x2 - e.x1;
          const dy = e.y2 - e.y1;
          const len = Math.sqrt(dx * dx + dy * dy);
          const angle = Math.atan2(dy, dx) * (180 / Math.PI);
          return (
            <div
              key={i}
              className={styles.graphEdge}
              style={{
                left: `${e.x1}%`,
                top: `${e.y1}%`,
                width: `${len}%`,
                transform: `rotate(${angle}deg)`,
                background: "var(--accent-cyan)",
              }}
            />
          );
        })}
        {nodes.map((n, i) => (
          <div
            key={i}
            className={styles.graphNode}
            style={{
              left: n.x,
              top: n.y,
              width: n.size,
              height: n.size,
              background: `${n.color}22`,
              borderColor: `${n.color}44`,
              boxShadow: `0 0 20px ${n.color}18`,
            }}
          />
        ))}
      </div>
    </div>
  );
}

function TimelineMock() {
  const personas = [
    { color: "var(--accent-cyan)", lines: [1, 0.7] },
    { color: "var(--accent-violet)", lines: [1, 0.5] },
    { color: "var(--accent-blue)", lines: [0.8] },
    { color: "var(--accent-cyan)", lines: [1, 0.6] },
  ] as const;

  return (
    <div className={styles.mockPanel}>
      <div className={styles.timeline}>
        {personas.map((p, i) => (
          <div key={i} className={styles.timelineRow}>
            <div
              className={styles.avatar}
              style={{
                background: `${p.color}22`,
                border: `2px solid ${p.color}44`,
              }}
            />
            <div className={styles.bubble}>
              {p.lines.map((w, j) => (
                <div
                  key={j}
                  className={`${styles.bubbleLine} ${w < 1 ? styles.short : ""}`}
                  style={{ width: `${w * 100}%`, marginBottom: j < p.lines.length - 1 ? 6 : 0 }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReportMock() {
  const stats = [
    { value: "147", label: "Entities", color: "var(--accent-cyan)" },
    { value: "89", label: "Relations", color: "var(--accent-violet)" },
    { value: "24", label: "Citations", color: "var(--accent-blue)" },
  ] as const;

  const bars = [
    { width: "92%", color: "var(--accent-cyan)" },
    { width: "78%", color: "var(--accent-violet)" },
    { width: "65%", color: "var(--accent-blue)" },
    { width: "84%", color: "var(--accent-cyan)" },
    { width: "50%", color: "var(--accent-violet)" },
  ] as const;

  return (
    <div className={styles.mockPanel}>
      <div className={styles.report}>
        <div className={styles.reportHeader}>
          {stats.map((s, i) => (
            <div key={i} className={styles.stat}>
              <span className={styles.statNumber} style={{ color: s.color }}>
                {s.value}
              </span>
              <span className={styles.statLabel}>{s.label}</span>
            </div>
          ))}
        </div>
        <div className={styles.highlightBars}>
          {bars.map((b, i) => (
            <div
              key={i}
              className={styles.highlightBar}
              style={{ width: b.width, background: b.color }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function ChatMock() {
  return (
    <div className={styles.mockPanel}>
      <div className={styles.chat}>
        <div className={`${styles.chatMsg} ${styles.user}`}>
          <div className={styles.chatLine} style={{ width: "90%" }} />
          <div className={`${styles.chatLine} ${styles.short}`} />
        </div>
        <div className={`${styles.chatMsg} ${styles.agent}`}>
          <div className={styles.chatLine} />
          <div className={styles.chatLine} style={{ width: "85%" }} />
          <div className={`${styles.chatLine} ${styles.short}`} />
        </div>
        <div className={`${styles.chatMsg} ${styles.user}`}>
          <div className={styles.chatLine} style={{ width: "70%" }} />
        </div>
        <div className={`${styles.chatMsg} ${styles.agent}`}>
          <div className={styles.chatLine} />
          <div className={styles.chatLine} style={{ width: "75%" }} />
        </div>
        <div className={styles.chatInput}>
          <div className={styles.chatInputLine} />
        </div>
      </div>
    </div>
  );
}

/* -- Feature data -- */

const features = [
  {
    label: "Graph Construction",
    title: "Build knowledge graphs from raw evidence.",
    description:
      "Upload PDFs, markdown, or plain text. PersonaGraph extracts entities, relationships, and narrative threads - then constructs an interactive knowledge graph you can inspect and refine.",
    visual: <GraphMock />,
    reverse: false,
  },
  {
    label: "Persona Simulation",
    title: "Simulate audiences reacting to your narrative.",
    description:
      "Define cohorts, set tension parameters, and watch synthetic personas interact with your content in real time. Every response is grounded in the evidence graph.",
    visual: <TimelineMock />,
    reverse: true,
  },
  {
    label: "Live Analysis Reports",
    title: "Generate grounded reports with full citations.",
    description:
      "Automated analysis reports with evidence trails, highlight extraction, and exportable findings. Every claim links back to source material.",
    visual: <ReportMock />,
    reverse: false,
  },
  {
    label: "Deep Interaction",
    title: "Ask questions. Get answers backed by evidence.",
    description:
      "Chat with the report agent to drill deeper. Ask follow-ups, challenge conclusions, and explore alternative interpretations - all grounded in your original sources.",
    visual: <ChatMock />,
    reverse: true,
  },
];

/* -- Section -- */

export function Features() {
  return (
    <section id="features" className={styles.section}>
      {features.map((f) => (
        <FeatureCard
          key={f.label}
          label={f.label}
          title={f.title}
          description={f.description}
          visual={f.visual}
          reverse={f.reverse}
        />
      ))}
    </section>
  );
}
