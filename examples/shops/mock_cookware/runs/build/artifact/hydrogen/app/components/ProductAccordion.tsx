import {useState} from 'react';

export type AccordionSection = {
  id: string;
  label: string;
  type?: 'html' | 'list';
  html?: string;
  items?: string[];
};

export function ProductAccordion({sections}: {sections: AccordionSection[]}) {
  const visible = sections.filter(
    (s) =>
      (s.html && s.html.trim().length > 0) ||
      (s.items && s.items.length > 0),
  );
  const [activeId, setActiveId] = useState(visible[0]?.id ?? '');

  if (!visible.length) return null;

  const active = visible.find((s) => s.id === activeId) ?? visible[0];

  return (
    <div className="pdp-accordion">
      <div role="tablist" className="pdp-accordion-tabs" aria-label="Product details">
        {visible.map((section) => {
          const isActive = section.id === active.id;
          return (
            <button
              key={section.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`pdp-accordion-tab${isActive ? ' is-active' : ''}`}
              onClick={() => setActiveId(section.id)}
            >
              {section.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="pdp-accordion-panel">
        {active.type === 'list' && active.items ? (
          <ul className="pdp-accordion-list">
            {active.items.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        ) : active.html ? (
          <div
            className="pdp-accordion-prose"
            dangerouslySetInnerHTML={{__html: active.html}}
          />
        ) : null}
      </div>
    </div>
  );
}
