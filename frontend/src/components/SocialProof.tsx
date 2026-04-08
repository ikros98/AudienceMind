import { useScrollReveal } from "../hooks/useScrollReveal";
import styles from "../styles/social-proof.module.css";

const TECH_BADGES = [
  { name: "React", icon: "R" },
  { name: "Three.js", icon: "3D" },
  { name: "FastAPI", icon: "API" },
  { name: "PostgreSQL", icon: "DB" },
  { name: "Ollama", icon: "AI" },
  { name: "Docker", icon: "CT" },
] as const;

export function SocialProof() {
  const [ref, visible] = useScrollReveal();

  return (
    <section
      ref={ref}
      className={`${styles.section} reveal${visible ? " visible" : ""}`}
    >
      <div className={styles.inner}>
        {TECH_BADGES.map(({ name, icon }) => (
          <div key={name} className={styles.badge}>
            <span className={styles.icon} aria-hidden="true">
              {icon}
            </span>
            <span className={styles.label}>{name}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
