import {useState} from 'react';

export type AccordionSection = {
  id: string;
  label: string;
  content: React.ReactNode;
};

export function ProductAccordion({sections}: {sections: AccordionSection[]}) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div className="product-accordion">
      {sections.map((section) => {
        const isOpen = openId === section.id;
        return (
          <div
            key={section.id}
            className={`product-accordion-item${isOpen ? ' is-open' : ''}`}
          >
            <button
              type="button"
              className="product-accordion-trigger"
              aria-expanded={isOpen}
              aria-controls={`accordion-panel-${section.id}`}
              id={`accordion-trigger-${section.id}`}
              onClick={() => setOpenId(isOpen ? null : section.id)}
            >
              <span>{section.label}</span>
              <svg
                className="product-accordion-chevron"
                width="16"
                height="16"
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
            {isOpen ? (
              <div
                id={`accordion-panel-${section.id}`}
                role="region"
                aria-labelledby={`accordion-trigger-${section.id}`}
                className="product-accordion-panel"
              >
                {section.content}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
