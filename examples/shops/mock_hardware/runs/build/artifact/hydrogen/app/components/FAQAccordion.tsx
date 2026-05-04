import {useState} from 'react';

export type FAQItem = {
  question: string;
  answer: React.ReactNode;
};

export type FAQGroup = {
  label: string;
  items: FAQItem[];
};

export function FAQAccordion({groups}: {groups: FAQGroup[]}) {
  return (
    <div className="faq-accordion">
      {groups.map((group, gi) => (
        <section key={group.label} className="faq-accordion-group">
          <h5 className="faq-accordion-group-label">{group.label}</h5>
          <ul className="faq-accordion-list">
            {group.items.map((item, ii) => (
              <FAQAccordionRow
                key={item.question}
                id={`faq-${gi}-${ii}`}
                item={item}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function FAQAccordionRow({id, item}: {id: string; item: FAQItem}) {
  const [open, setOpen] = useState(false);
  return (
    <li className={`faq-accordion-item${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="faq-accordion-trigger"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        id={`${id}-trigger`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="faq-accordion-question">{item.question}</span>
        <svg
          className="faq-accordion-chevron"
          width="18"
          height="18"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="4 6 8 10 12 6" />
        </svg>
      </button>
      {open ? (
        <div
          id={`${id}-panel`}
          role="region"
          aria-labelledby={`${id}-trigger`}
          className="faq-accordion-panel"
        >
          {item.answer}
        </div>
      ) : null}
    </li>
  );
}
