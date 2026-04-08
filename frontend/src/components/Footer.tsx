import { useScrollReveal } from "../hooks/useScrollReveal";
import styles from "../styles/footer.module.css";

const FOOTER_LINKS = [
  { label: "Features", href: "#features" },
  { label: "Pricing", href: "#pricing" },
  { label: "FAQ", href: "#faq" },
  { label: "GitHub", href: "https://github.com" },
] as const;

export function Footer() {
  const [ref, visible] = useScrollReveal();

  return (
    <footer className={styles.footer}>
      {/* -- CTA banner -- */}
      <div
        ref={ref}
        className={`${styles.ctaBanner} reveal${visible ? " visible" : ""}`}
      >
        <h2 className={styles.ctaHeading}>Ready to build your first graph?</h2>
        <a href="#get-started" className="btn btn-primary">
          Get Started Free
        </a>
      </div>

      {/* -- Bottom bar -- */}
      <div className={styles.bottom}>
        <span className={styles.brand}>PersonaGraph</span>

        <nav className={styles.nav} aria-label="Footer navigation">
          {FOOTER_LINKS.map(({ label, href }) => (
            <a key={href} href={href} className={styles.navLink}>
              {label}
            </a>
          ))}
        </nav>

        <span className={styles.copy}>(c) 2026 PersonaGraph</span>
      </div>
    </footer>
  );
}
