import {useEffect, useState} from 'react';

type Tab = 'tools' | 'report';

export function AccessibilityToolbar() {
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('tools');
  const [largeText, setLargeText] = useState(false);
  const [highContrast, setHighContrast] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [reportSent, setReportSent] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const root = document.documentElement;
    root.classList.toggle('a11y-large-text', largeText);
    root.classList.toggle('a11y-high-contrast', highContrast);
    root.classList.toggle('a11y-reduce-motion', reduceMotion);
  }, [largeText, highContrast, reduceMotion, mounted]);

  if (!mounted) return null;

  return (
    <>
      <button
        type="button"
        className="a11y-trigger"
        aria-label="Accessibility menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg
          viewBox="0 0 24 24"
          width="22"
          height="22"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="7" r="1.4" fill="currentColor" stroke="none" />
          <path d="M8 11h8M10 11l-1 7M14 11l1 7M12 11v3" />
        </svg>
      </button>
      {open && (
        <div
          className="a11y-dialog"
          role="dialog"
          aria-label="Accessibility tools"
        >
          <div className="a11y-dialog-header">
            <h2 className="a11y-dialog-title">Accessibility</h2>
            <button
              type="button"
              className="a11y-dialog-close"
              onClick={() => setOpen(false)}
              aria-label="Close accessibility menu"
            >
              ×
            </button>
          </div>
          <div className="a11y-dialog-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'tools'}
              className={`a11y-dialog-tab${tab === 'tools' ? ' is-active' : ''}`}
              onClick={() => setTab('tools')}
            >
              Personalization
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'report'}
              className={`a11y-dialog-tab${tab === 'report' ? ' is-active' : ''}`}
              onClick={() => setTab('report')}
            >
              Report an issue
            </button>
          </div>
          {tab === 'tools' ? (
            <div className="a11y-dialog-body">
              <ToggleRow
                label="Larger text"
                value={largeText}
                onChange={setLargeText}
              />
              <ToggleRow
                label="High contrast"
                value={highContrast}
                onChange={setHighContrast}
              />
              <ToggleRow
                label="Reduce motion"
                value={reduceMotion}
                onChange={setReduceMotion}
              />
            </div>
          ) : (
            <form
              className="a11y-dialog-body"
              onSubmit={(e) => {
                e.preventDefault();
                setReportSent(true);
              }}
            >
              {reportSent ? (
                <p className="a11y-success">Thanks — our team will review.</p>
              ) : (
                <>
                  <label className="a11y-field">
                    <span>Email</span>
                    <input
                      type="email"
                      required
                      className="a11y-input"
                      placeholder="contact@mock-shop.example"
                    />
                  </label>
                  <label className="a11y-field">
                    <span>What happened?</span>
                    <textarea
                      required
                      className="a11y-textarea"
                      rows={4}
                      placeholder="Describe the issue you ran into."
                    />
                  </label>
                  <button type="submit" className="a11y-submit">
                    Send report
                  </button>
                </>
              )}
            </form>
          )}
        </div>
      )}
    </>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="a11y-toggle-row">
      <span>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        className={`a11y-switch${value ? ' is-on' : ''}`}
        onClick={() => onChange(!value)}
      >
        <span className="a11y-switch-thumb" aria-hidden="true" />
      </button>
    </label>
  );
}
