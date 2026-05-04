export function QuantitySelector({
  value,
  onChange,
  min = 1,
  max = 99,
}: {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
}) {
  const decrement = () => onChange(Math.max(min, value - 1));
  const increment = () => onChange(Math.min(max, value + 1));
  return (
    <div className="qty-selector" role="group" aria-label="Quantity">
      <button
        type="button"
        className="qty-btn"
        onClick={decrement}
        disabled={value <= min}
        aria-label="Decrease quantity"
      >
        <span aria-hidden="true">−</span>
      </button>
      <input
        type="number"
        className="qty-input"
        role="spinbutton"
        value={value}
        min={min}
        max={max}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isFinite(next)) {
            onChange(Math.min(max, Math.max(min, Math.floor(next))));
          }
        }}
        aria-label="Quantity"
      />
      <button
        type="button"
        className="qty-btn"
        onClick={increment}
        disabled={value >= max}
        aria-label="Increase quantity"
      >
        <span aria-hidden="true">+</span>
      </button>
    </div>
  );
}
