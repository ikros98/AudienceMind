import type { ReactNode } from "react";
import { useScrollReveal } from "../hooks/useScrollReveal";
import styles from "../styles/features.module.css";

interface FeatureCardProps {
  label: string;
  title: string;
  description: string;
  visual: ReactNode;
  reverse?: boolean;
}

export function FeatureCard({
  label,
  title,
  description,
  visual,
  reverse,
}: FeatureCardProps) {
  const [ref, visible] = useScrollReveal();

  return (
    <div
      ref={ref}
      className={`${styles.row} ${reverse ? styles.reverse : ""} reveal ${visible ? "visible" : ""}`}
    >
      <div className={styles.copy}>
        <span className={styles.label}>{label}</span>
        <h2 className={styles.heading}>{title}</h2>
        <p className={styles.description}>{description}</p>
      </div>
      <div className={styles.visual}>
        <div className={styles.imageFrame}>{visual}</div>
      </div>
    </div>
  );
}
