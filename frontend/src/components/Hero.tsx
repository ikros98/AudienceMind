import styles from "../styles/hero.module.css";

export function Hero() {
  return (
    <section className={styles.hero}>
      <div className={styles.fallback} />

      <div className={styles.content}>
        <span className={styles.eyebrow}>AudienceMind</span>

        <h1 className={styles.heading}>
          Build the graph. Stress the narrative. Inspect the outcome.
        </h1>

        <p className={styles.subheading}>
          AI-powered graph analytics and persona simulation. Upload evidence,
          construct knowledge graphs, simulate audience reactions, and generate
          grounded analysis reports.
        </p>

        <div className={styles.buttons}>
          <a className="btn btn-primary" href="/demo">
            Try Demo
          </a>
          <a className="btn btn-secondary" href="#features">
            Learn More
          </a>
        </div>
      </div>
    </section>
  );
}
