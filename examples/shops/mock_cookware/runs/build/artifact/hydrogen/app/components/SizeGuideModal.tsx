import {useEffect} from 'react';

const SIZE_ROWS: Array<{size: string; chest: string; waist: string; hips: string}> = [
  {size: 'XS', chest: '32–34', waist: '24–26', hips: '34–36'},
  {size: 'S', chest: '34–36', waist: '26–28', hips: '36–38'},
  {size: 'M', chest: '36–38', waist: '28–30', hips: '38–40'},
  {size: 'L', chest: '38–40', waist: '30–32', hips: '40–42'},
  {size: 'XL', chest: '40–43', waist: '32–35', hips: '42–45'},
  {size: 'XXL', chest: '43–46', waist: '35–38', hips: '45–48'},
];

export function SizeGuideModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="pdp-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="pdp-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="size-guide-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="pdp-modal-header">
          <h2 id="size-guide-title" className="pdp-modal-title">
            Size Guide
          </h2>
          <button
            type="button"
            className="pdp-modal-close"
            aria-label="Close size guide"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="pdp-modal-body">
          <p className="pdp-modal-lede">
            Measurements in inches. For the best fit, measure with snug clothing
            and round up if you’re between sizes.
          </p>
          <table className="pdp-size-table">
            <thead>
              <tr>
                <th>Size</th>
                <th>Chest</th>
                <th>Waist</th>
                <th>Hips</th>
              </tr>
            </thead>
            <tbody>
              {SIZE_ROWS.map((row) => (
                <tr key={row.size}>
                  <th scope="row">{row.size}</th>
                  <td>{row.chest}</td>
                  <td>{row.waist}</td>
                  <td>{row.hips}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
