import { useState, useCallback } from "react";
import styles from "../styles/capsule-nav.module.css";

const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "Pricing", href: "#pricing" },
  { label: "FAQ", href: "#faq" },
  { label: "Demo", href: "/demo" },
] as const;

const MOBILE_MENU_ID = "mobile-nav-menu";

export function CapsuleNav() {
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLinkClick = useCallback(() => {
    setMenuOpen(false);
  }, []);

  return (
    <nav className={styles.wrapper} aria-label="Main navigation">
      <div className={styles.capsule}>
        {/* -- Brand -- */}
        <a href="#" className={styles.brand}>
          <svg
            className={styles.brandIcon}
            viewBox="0 0 32 32"
            fill="none"
            aria-hidden="true"
          >
            <circle cx="16" cy="16" r="14" stroke="url(#brand-grad)" strokeWidth="1.5" />
            <circle cx="10" cy="13" r="2.5" fill="#7ee7ff" />
            <circle cx="22" cy="13" r="2.5" fill="#a78bfa" />
            <circle cx="16" cy="22" r="2.5" fill="#4a6fff" />
            <line x1="10" y1="13" x2="22" y2="13" stroke="rgba(255,255,255,0.25)" strokeWidth="1" />
            <line x1="10" y1="13" x2="16" y2="22" stroke="rgba(255,255,255,0.25)" strokeWidth="1" />
            <line x1="22" y1="13" x2="16" y2="22" stroke="rgba(255,255,255,0.25)" strokeWidth="1" />
            <defs>
              <linearGradient id="brand-grad" x1="0" y1="0" x2="32" y2="32">
                <stop offset="0%" stopColor="#4a6fff" />
                <stop offset="100%" stopColor="#7ee7ff" />
              </linearGradient>
            </defs>
          </svg>
          <span className={styles.brandName}>AudienceMind</span>
        </a>

        {/* -- Desktop nav links -- */}
        <div className={styles.navLinks}>
          {NAV_LINKS.map(({ label, href }) => (
            <a key={href} href={href} className={styles.navLink}>
              {label}
            </a>
          ))}
        </div>

        {/* -- Right actions -- */}
        <div className={styles.actions}>
          <a href="/demo" className={styles.cta}>
            Try Demo
          </a>

          {/* Hamburger (visible on mobile only via CSS) */}
          <button
            type="button"
            className={styles.hamburger}
            aria-expanded={menuOpen}
            aria-controls={MOBILE_MENU_ID}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((prev) => !prev)}
          >
            <svg
              className={styles.hamburgerIcon}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              aria-hidden="true"
            >
              {menuOpen ? (
                <>
                  <line x1="4" y1="4" x2="16" y2="16" />
                  <line x1="16" y1="4" x2="4" y2="16" />
                </>
              ) : (
                <>
                  <line x1="3" y1="5" x2="17" y2="5" />
                  <line x1="3" y1="10" x2="17" y2="10" />
                  <line x1="3" y1="15" x2="17" y2="15" />
                </>
              )}
            </svg>
          </button>
        </div>

        {/* -- Mobile dropdown -- */}
        <div
          id={MOBILE_MENU_ID}
          className={`${styles.mobileMenu} ${menuOpen ? styles.isOpen : ""}`}
          role="menu"
        >
          {NAV_LINKS.map(({ label, href }) => (
            <a
              key={href}
              href={href}
              className={styles.mobileLink}
              role="menuitem"
              onClick={handleLinkClick}
            >
              {label}
            </a>
          ))}
          <a
            href="/demo"
            className={styles.mobileCta}
            role="menuitem"
            onClick={handleLinkClick}
          >
            Try Demo
          </a>
        </div>
      </div>
    </nav>
  );
}
