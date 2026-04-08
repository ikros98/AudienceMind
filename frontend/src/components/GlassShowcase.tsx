import { useRef } from "react";
import styles from "../styles/showcase.module.css";

export function GlassShowcase() {
  const sectionRef = useRef<HTMLElement>(null);

  return (
    <section id="showcase" className={styles.section} ref={sectionRef}>
      <div className={styles.inner}>
        <span className={styles.label}>Workbench Preview</span>
        <h2 className={styles.heading}>A cleaner landing view.</h2>
        <p className={styles.description}>
          The landing page now stays focused on the product story. The
          workbench itself still carries the interactive graph and simulation
          visuals once you enter the app.
        </p>

        <div className={styles.fallback} />
      </div>
    </section>
  );
}
