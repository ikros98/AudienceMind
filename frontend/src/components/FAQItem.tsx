import { useState } from "react";
import styles from "../styles/faq.module.css";

interface FAQItemProps {
  question: string;
  answer: string;
}

export function FAQItem({ question, answer }: FAQItemProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className={styles.item}>
      <button
        type="button"
        className={styles.question}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        {question}
        <svg
          className={open ? styles.caretOpen : styles.caret}
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 7.5L10 12.5L15 7.5" />
        </svg>
      </button>

      <div className={open ? styles.answerWrapOpen : styles.answerWrap}>
        <div className={styles.answerInner}>
          <p className={styles.answer}>{answer}</p>
        </div>
      </div>
    </div>
  );
}
