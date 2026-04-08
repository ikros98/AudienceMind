import { FAQItem } from "./FAQItem";
import { useScrollReveal } from "../hooks/useScrollReveal";
import styles from "../styles/faq.module.css";

const FAQ_DATA = [
  {
    q: "What is PersonaGraph?",
    a: "PersonaGraph is an AI-powered platform that builds knowledge graphs from your evidence documents, simulates audience personas interacting with narratives, and generates grounded analysis reports with full citation trails.",
  },
  {
    q: "What file formats can I upload?",
    a: "PersonaGraph accepts PDF, Markdown (.md), and plain text (.txt) files. The graph construction engine extracts entities, relationships, and narrative threads automatically.",
  },
  {
    q: "How does the persona simulation work?",
    a: "You define a cohort of synthetic personas with demographic and psychographic parameters. The simulation engine runs these personas through your narrative content, generating realistic interactions grounded in the knowledge graph.",
  },
  {
    q: "Is my data private?",
    a: "Yes. PersonaGraph runs locally with your own LLM backend (Ollama-compatible). Your documents, graphs, and simulation results never leave your infrastructure.",
  },
  {
    q: "Can I self-host PersonaGraph?",
    a: "Absolutely. PersonaGraph ships as Docker containers - a FastAPI backend, a PostgreSQL database, and this frontend. Run it anywhere Docker is supported.",
  },
  {
    q: "What LLM backends are supported?",
    a: "PersonaGraph works with any Ollama-compatible model. You can use local models or tunnel to remote Ollama instances. The architecture is model-agnostic.",
  },
] as const;

export function FAQ() {
  const [ref, visible] = useScrollReveal();

  return (
    <section id="faq" className={styles.section}>
      <div ref={ref} className={`${styles.inner} reveal${visible ? " visible" : ""}`}>
        <div className={styles.heading}>
          <span className="section-label">FAQ</span>
          <h2>Common questions.</h2>
        </div>

        <div className={styles.list}>
          {FAQ_DATA.map(({ q, a }) => (
            <FAQItem key={q} question={q} answer={a} />
          ))}
        </div>
      </div>
    </section>
  );
}
