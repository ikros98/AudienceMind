import { PricingCard } from "./PricingCard";
import styles from "../styles/pricing.module.css";

const FREE_FEATURES = [
  "Up to 3 projects",
  "Basic graph construction",
  "5 simulation runs / month",
  "Standard reports",
  "Community support",
] as const;

const PRO_FEATURES = [
  "Unlimited projects",
  "Advanced graph with ontology tuning",
  "Unlimited simulation runs",
  "Deep interaction & chat",
  "Priority support",
  "Custom cohort sizes",
  "Export & API access",
] as const;

export function Pricing() {
  return (
    <section id="pricing" className={styles.section}>
      <div className={styles.inner}>
        <div className={styles.heading}>
          <span className="section-label">Pricing</span>
          <h2>Simple, transparent pricing.</h2>
          <p className={styles.subtitle}>
            Start free, upgrade when you need more power.
          </p>
        </div>

        <div className={styles.grid}>
          <PricingCard
            badge="Free"
            price="$0"
            term="forever"
            features={[...FREE_FEATURES]}
            cta="Get Started Free"
          />
          <PricingCard
            badge="Pro"
            price="$49"
            term="/ month"
            features={[...PRO_FEATURES]}
            cta="Start Pro Trial"
            featured
          />
        </div>
      </div>
    </section>
  );
}
