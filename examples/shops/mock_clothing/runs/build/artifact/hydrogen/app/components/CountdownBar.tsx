import {useEffect, useState} from 'react';

const SALE_DURATION_MS = 1000 * 60 * 60 * 47 + 1000 * 60 * 32 + 1000 * 18;

function pad(value: number) {
  return value.toString().padStart(2, '0');
}

export function CountdownBar() {
  const [target, setTarget] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(SALE_DURATION_MS);

  useEffect(() => {
    const stored = window.localStorage.getItem('mock-apparel:sale-target');
    let endsAt: number;
    if (stored && Number(stored) > Date.now()) {
      endsAt = Number(stored);
    } else {
      endsAt = Date.now() + SALE_DURATION_MS;
      window.localStorage.setItem('mock-apparel:sale-target', String(endsAt));
    }
    setTarget(endsAt);

    const tick = () => setRemaining(Math.max(0, endsAt - Date.now()));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);

  const days = Math.floor(remaining / (1000 * 60 * 60 * 24));
  const hours = Math.floor((remaining / (1000 * 60 * 60)) % 24);
  const minutes = Math.floor((remaining / (1000 * 60)) % 60);
  const seconds = Math.floor((remaining / 1000) % 60);

  if (target === null) {
    return (
      <div
        className="countdown-bar"
        role="region"
        aria-label="Sale countdown"
        aria-hidden="true"
      >
        <span className="countdown-bar-label">Spring Edit ends in</span>
        <span className="countdown-bar-clock">— : — : — : —</span>
      </div>
    );
  }

  if (remaining <= 0) {
    return (
      <div className="countdown-bar countdown-bar-live" role="region">
        <span className="countdown-bar-label">Sale is live — shop now</span>
      </div>
    );
  }

  return (
    <div className="countdown-bar" role="region" aria-label="Sale countdown">
      <span className="countdown-bar-label">Spring Edit ends in</span>
      <span className="countdown-bar-clock">
        <span className="countdown-bar-cell">
          <span className="countdown-bar-num">{pad(days)}</span>
          <span className="countdown-bar-unit">Days</span>
        </span>
        <span className="countdown-bar-sep">:</span>
        <span className="countdown-bar-cell">
          <span className="countdown-bar-num">{pad(hours)}</span>
          <span className="countdown-bar-unit">Hrs</span>
        </span>
        <span className="countdown-bar-sep">:</span>
        <span className="countdown-bar-cell">
          <span className="countdown-bar-num">{pad(minutes)}</span>
          <span className="countdown-bar-unit">Min</span>
        </span>
        <span className="countdown-bar-sep">:</span>
        <span className="countdown-bar-cell">
          <span className="countdown-bar-num">{pad(seconds)}</span>
          <span className="countdown-bar-unit">Sec</span>
        </span>
      </span>
    </div>
  );
}
