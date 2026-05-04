import {useState} from 'react';

export type FAQItem = {
  question: string;
  answer: string;
};

export function FAQAccordion({items}: {items: FAQItem[]}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <ul className="faq-accordion">
      {items.map((item, index) => {
        const isOpen = openIndex === index;
        return (
          <li
            key={item.question}
            className={`faq-accordion-item${isOpen ? ' is-open' : ''}`}
          >
            <button
              type="button"
              className="faq-accordion-trigger"
              aria-expanded={isOpen}
              onClick={() => setOpenIndex(isOpen ? null : index)}
            >
              <span className="faq-accordion-question">{item.question}</span>
              <span className="faq-accordion-icon" aria-hidden="true">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                >
                  <path d="M3 5l4 4 4-4" />
                </svg>
              </span>
            </button>
            {isOpen && (
              <div className="faq-accordion-panel">
                <p>{item.answer}</p>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
