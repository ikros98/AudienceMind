import { useScrollReveal } from "../hooks/useScrollReveal";
import styles from "../styles/pricing.module.css";

interface PricingCardProps {
  badge: string;
  price: string;
  term: string;
  features: string[];
  cta: string;
  featured?: boolean;
}

export function PricingCard({
  badge,
  price,
  term,
  features,
  cta,
  featured = false,
}: PricingCardProps) {
  const [ref, visible] = useScrollReveal();

  return (
    <div
      ref={ref}
      className={`${featured ? styles.cardFeatured : styles.card} reveal${visible ? " visible" : ""}`}
    >
      <span className={featured ? styles.badgeFeatured : styles.badge}>
        {badge}
      </span>

      <div className={styles.priceRow}>
        <span className={styles.price}>{price}</span>
        <span className={styles.term}>{term}</span>
      </div>

      <ul className={styles.features}>
        {features.map((f) => (
          <li key={f} className={styles.featureItem}>
            {f}
          </li>
        ))}
      </ul>

      <a
        href="#get-started"
        className={`${styles.cta} btn ${featured ? "btn-primary" : "btn-secondary"}`}
      >
        {cta}
      </a>
    </div>
  );
}
