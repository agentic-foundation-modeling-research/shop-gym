import {useState} from 'react';

export interface FAQItem {
  id: string;
  question: string;
  answer: React.ReactNode;
}

export function FAQAccordion({
  items,
  defaultOpenId,
  idPrefix = 'faq',
}: {
  items: FAQItem[];
  defaultOpenId?: string;
  idPrefix?: string;
}) {
  const [openId, setOpenId] = useState<string>(defaultOpenId ?? '');

  return (
    <div className="info-accordion">
      {items.map((item) => {
        const isOpen = openId === item.id;
        return (
          <div
            key={item.id}
            className={`info-accordion-item${isOpen ? ' is-open' : ''}`}
          >
            <button
              type="button"
              className="info-accordion-trigger"
              aria-expanded={isOpen}
              aria-controls={`${idPrefix}-${item.id}`}
              onClick={() => setOpenId(isOpen ? '' : item.id)}
            >
              <span className="info-accordion-question">{item.question}</span>
              <span aria-hidden="true" className="info-accordion-icon">
                {isOpen ? '−' : '+'}
              </span>
            </button>
            {isOpen ? (
              <div
                id={`${idPrefix}-${item.id}`}
                className="info-accordion-body"
              >
                {item.answer}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
