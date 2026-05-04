import type {ReactNode} from 'react';

type AttributeKey =
  | 'warranty'
  | 'utensilSafe'
  | 'nonstick'
  | 'ovenSafe'
  | 'dishwasherSafe'
  | 'inductionReady'
  | 'stayCoolHandle';

const ATTRIBUTES: Array<{key: AttributeKey; label: string; icon: ReactNode}> = [
  {key: 'warranty', label: 'Lifetime warranty', icon: <ShieldGlyph />},
  {key: 'utensilSafe', label: 'Utensil-safe', icon: <UtensilGlyph />},
  {key: 'nonstick', label: 'Nonstick', icon: <NonstickGlyph />},
  {key: 'ovenSafe', label: 'Oven-safe to 500°F', icon: <OvenGlyph />},
  {key: 'dishwasherSafe', label: 'Dishwasher-safe', icon: <DishGlyph />},
  {key: 'inductionReady', label: 'Induction-ready', icon: <InductionGlyph />},
  {key: 'stayCoolHandle', label: 'Stay-cool handle', icon: <HandleGlyph />},
];

export function AttributeStrip({active}: {active: Partial<Record<AttributeKey, boolean>>}) {
  return (
    <ul className="pdp-attribute-strip" aria-label="Product attributes">
      {ATTRIBUTES.map((attr) => {
        const isOn = active[attr.key] === true;
        return (
          <li
            key={attr.key}
            className={`pdp-attribute${isOn ? ' is-on' : ' is-off'}`}
            aria-disabled={!isOn}
          >
            <span className="pdp-attribute-icon" aria-hidden="true">
              {attr.icon}
            </span>
            <span className="pdp-attribute-label">{attr.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

function ShieldGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}
function UtensilGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 2v9a2 2 0 0 0 2 2v9" />
      <path d="M11 2v9" />
      <path d="M15 2v9" />
      <path d="M15 13v9" />
    </svg>
  );
}
function NonstickGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="14" rx="8" ry="4.5" />
      <path d="M20 14V8" />
      <path d="M4 14V8" />
      <path d="M4 8a8 4 0 0 1 16 0" />
    </svg>
  );
}
function OvenGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 8h10" />
      <circle cx="9" cy="14" r="2" />
      <circle cx="15" cy="14" r="2" />
    </svg>
  );
}
function DishGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="18" rx="8" ry="2.5" />
      <path d="M8 18l1-9h6l1 9" />
      <path d="M11 4l1 3 1-3" />
    </svg>
  );
}
function InductionGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M9 8c0 4 6 4 6 8" />
      <path d="M15 8c0 4-6 4-6 8" />
    </svg>
  );
}
function HandleGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 14h11l4-2 3 1v3l-3 1-4-2H3z" />
      <path d="M6 9c1-2 3-3 5-3" />
    </svg>
  );
}
