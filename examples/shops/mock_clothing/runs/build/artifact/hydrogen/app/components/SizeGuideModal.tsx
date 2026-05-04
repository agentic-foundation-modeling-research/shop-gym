import {useEffect} from 'react';

const SIZE_CHART: Record<
  string,
  {bust: string; waist: string; hip: string; range: string}
> = {
  XS: {bust: '32"', waist: '24"', hip: '34"', range: 'US 0-2'},
  S: {bust: '34"', waist: '26"', hip: '36"', range: 'US 4-6'},
  M: {bust: '36"', waist: '28"', hip: '38"', range: 'US 8-10'},
  L: {bust: '38"', waist: '30"', hip: '40"', range: 'US 12-14'},
  XL: {bust: '41"', waist: '33"', hip: '43"', range: 'US 16-18'},
  XXL: {bust: '44"', waist: '36"', hip: '46"', range: 'US 20-22'},
};

export function SizeGuideModal({
  optionName,
  values,
  onClose,
}: {
  optionName: string;
  values: string[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  const sizesToShow = values.filter((v) => SIZE_CHART[v.toUpperCase()]);
  const fallbackSizes = sizesToShow.length === 0 ? values : sizesToShow;

  return (
    <div
      className="pdp-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`${optionName} guide`}
      onClick={onClose}
    >
      <div
        className="pdp-modal-card"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <div className="pdp-modal-head">
          <h2 className="pdp-modal-title">{optionName} Guide</h2>
          <button
            type="button"
            className="pdp-modal-close"
            onClick={onClose}
            aria-label="Close size guide"
          >
            ×
          </button>
        </div>
        <div className="pdp-modal-body">
          <p className="pdp-modal-intro">
            Measurements are taken with the body relaxed. For the closest fit,
            measure over light clothing and refer to the range below.
          </p>
          {sizesToShow.length > 0 ? (
            <table className="pdp-size-table">
              <thead>
                <tr>
                  <th scope="col">Size</th>
                  <th scope="col">Bust</th>
                  <th scope="col">Waist</th>
                  <th scope="col">Hip</th>
                  <th scope="col">US</th>
                </tr>
              </thead>
              <tbody>
                {fallbackSizes.map((s) => {
                  const row = SIZE_CHART[s.toUpperCase()];
                  if (!row) return null;
                  return (
                    <tr key={s}>
                      <th scope="row">{s}</th>
                      <td>{row.bust}</td>
                      <td>{row.waist}</td>
                      <td>{row.hip}</td>
                      <td>{row.range}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <p className="pdp-modal-intro">
              Available sizes: {values.join(', ')}. Contact our concierge team
              for help selecting the right fit.
            </p>
          )}
          <div className="pdp-size-fit-block">
            <h3 className="pdp-size-fit-heading">Fit Notes</h3>
            <ul>
              <li>True to size — order your usual.</li>
              <li>Between sizes? Size up for a relaxed fit.</li>
              <li>Engineered four-way stretch for support and movement.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
