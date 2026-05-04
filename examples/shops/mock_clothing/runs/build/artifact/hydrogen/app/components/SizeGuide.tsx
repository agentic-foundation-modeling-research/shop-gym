import {useMemo, useState} from 'react';

type Unit = 'cm' | 'in';
type Gender = 'women' | 'men';
type Category =
  | 'tops'
  | 'outerwear'
  | 'bottoms'
  | 'footwear'
  | 'accessories';

interface SizeRow {
  size: string;
  bust: number;
  waist: number;
  hips: number;
  inseam: number;
  uk: string;
  eu: string;
  us: string;
}

const WOMENS_SIZES_CM: SizeRow[] = [
  {size: 'XXS', bust: 78, waist: 60, hips: 86, inseam: 76, uk: '4', eu: '32', us: '0'},
  {size: 'XS', bust: 82, waist: 64, hips: 90, inseam: 76, uk: '6', eu: '34', us: '2'},
  {size: 'S', bust: 86, waist: 68, hips: 94, inseam: 78, uk: '8', eu: '36', us: '4'},
  {size: 'M', bust: 92, waist: 74, hips: 100, inseam: 78, uk: '10', eu: '38', us: '6'},
  {size: 'L', bust: 98, waist: 80, hips: 106, inseam: 80, uk: '12', eu: '40', us: '8'},
  {size: 'XL', bust: 106, waist: 88, hips: 114, inseam: 80, uk: '14', eu: '42', us: '10'},
  {size: '2XL', bust: 114, waist: 96, hips: 122, inseam: 80, uk: '16', eu: '44', us: '12'},
];

const MENS_SIZES_CM: SizeRow[] = [
  {size: 'XS', bust: 88, waist: 74, hips: 90, inseam: 80, uk: '34', eu: '44', us: 'XS'},
  {size: 'S', bust: 94, waist: 80, hips: 96, inseam: 81, uk: '36', eu: '46', us: 'S'},
  {size: 'M', bust: 100, waist: 86, hips: 102, inseam: 82, uk: '38', eu: '48', us: 'M'},
  {size: 'L', bust: 106, waist: 92, hips: 108, inseam: 83, uk: '40', eu: '50', us: 'L'},
  {size: 'XL', bust: 112, waist: 98, hips: 114, inseam: 84, uk: '42', eu: '52', us: 'XL'},
  {size: '2XL', bust: 120, waist: 106, hips: 122, inseam: 85, uk: '44', eu: '54', us: '2XL'},
];

const NECKLACE_LENGTHS = [
  {length: '14"', name: 'Collar', sits: 'Snug at the base of the neck'},
  {length: '16"', name: 'Choker', sits: 'Just above the collarbone'},
  {length: '18"', name: 'Princess', sits: 'At the collarbone — most popular'},
  {length: '20"', name: 'Matinée', sits: 'Just below the collarbone'},
  {length: '24"', name: 'Opera', sits: 'Mid-chest — layers beautifully'},
];

const RING_SIZES = [
  {us: '5', uk: 'J½', eu: '49', mm: 15.7},
  {us: '6', uk: 'L½', eu: '52', mm: 16.5},
  {us: '7', uk: 'N½', eu: '54', mm: 17.3},
  {us: '8', uk: 'P½', eu: '57', mm: 18.1},
  {us: '9', uk: 'R½', eu: '59', mm: 19.0},
  {us: '10', uk: 'T½', eu: '62', mm: 19.8},
];

const MEASUREMENT_INSTRUCTIONS = [
  {
    label: 'Bust / Chest',
    description:
      'Measure around the fullest part, keeping the tape level under the arms.',
  },
  {
    label: 'Waist',
    description:
      'Measure around the narrowest part of your natural waistline, just above the navel.',
  },
  {
    label: 'Hips',
    description:
      'Stand with feet together. Measure around the fullest part of your hips and seat.',
  },
  {
    label: 'Inseam',
    description:
      'Measure from the inside of the leg, from the crotch seam down to the ankle bone.',
  },
];

function cmToIn(cm: number) {
  return Math.round((cm / 2.54) * 10) / 10;
}

export function SizeGuide() {
  const [gender, setGender] = useState<Gender>('women');
  const [category, setCategory] = useState<Category>('tops');
  const [unit, setUnit] = useState<Unit>('cm');

  const apparelRows = useMemo(() => {
    const source = gender === 'women' ? WOMENS_SIZES_CM : MENS_SIZES_CM;
    if (unit === 'cm') return source;
    return source.map((row) => ({
      ...row,
      bust: cmToIn(row.bust),
      waist: cmToIn(row.waist),
      hips: cmToIn(row.hips),
      inseam: cmToIn(row.inseam),
    }));
  }, [gender, unit]);

  const showApparel = category !== 'accessories';

  return (
    <div className="size-guide">
      <div className="size-guide-tabs" role="tablist" aria-label="Gender">
        {([
          {key: 'women', label: 'Women'},
          {key: 'men', label: 'Men'},
        ] as const).map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={gender === tab.key}
            className={`size-guide-tab${gender === tab.key ? ' is-active' : ''}`}
            onClick={() => setGender(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="size-guide-subtabs" role="tablist" aria-label="Category">
        {([
          {key: 'tops', label: 'Tops & Bras'},
          {key: 'outerwear', label: 'Outerwear'},
          {key: 'bottoms', label: 'Bottoms'},
          {key: 'footwear', label: 'Footwear'},
          {key: 'accessories', label: 'Accessories'},
        ] as const).map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={category === tab.key}
            className={`size-guide-subtab${category === tab.key ? ' is-active' : ''}`}
            onClick={() => setCategory(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {showApparel ? (
        <div className="size-guide-table-wrap">
          <div className="size-guide-unit-toggle" role="group" aria-label="Units">
            <button
              type="button"
              className={`size-guide-unit${unit === 'cm' ? ' is-active' : ''}`}
              onClick={() => setUnit('cm')}
            >
              cm
            </button>
            <button
              type="button"
              className={`size-guide-unit${unit === 'in' ? ' is-active' : ''}`}
              onClick={() => setUnit('in')}
            >
              in
            </button>
          </div>

          <div className="size-guide-table-scroll">
            <table className="size-guide-table">
              <thead>
                <tr>
                  <th scope="col">Size</th>
                  <th scope="col">Bust / Chest</th>
                  <th scope="col">Waist</th>
                  <th scope="col">Hips</th>
                  <th scope="col">Inseam</th>
                  <th scope="col">UK</th>
                  <th scope="col">EU</th>
                  <th scope="col">US</th>
                </tr>
              </thead>
              <tbody>
                {apparelRows.map((row) => (
                  <tr key={row.size}>
                    <th scope="row">{row.size}</th>
                    <td>{row.bust}</td>
                    <td>{row.waist}</td>
                    <td>{row.hips}</td>
                    <td>{row.inseam}</td>
                    <td>{row.uk}</td>
                    <td>{row.eu}</td>
                    <td>{row.us}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <AccessoriesGuide />
      )}

      <div className="size-guide-howto">
        <h3 className="size-guide-howto-heading">How to Measure</h3>
        <div className="size-guide-howto-grid">
          {MEASUREMENT_INSTRUCTIONS.map((m) => (
            <div key={m.label} className="size-guide-howto-card">
              <div className="size-guide-howto-icon" aria-hidden="true">
                <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
                  <rect
                    x="4"
                    y="14"
                    width="32"
                    height="12"
                    rx="2"
                    stroke="currentColor"
                    strokeWidth="1.4"
                  />
                  <path
                    d="M10 14v4M16 14v4M22 14v4M28 14v4"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                  />
                </svg>
              </div>
              <h4 className="size-guide-howto-label">{m.label}</h4>
              <p className="size-guide-howto-text">{m.description}</p>
            </div>
          ))}
        </div>
      </div>

      <p className="size-guide-not-sure">
        Not sure which size is right for you?{' '}
        <a href="/pages/contact" className="size-guide-help-link">
          Chat with our concierge team
        </a>{' '}
        for personalised fit advice.
      </p>
    </div>
  );
}

function AccessoriesGuide() {
  return (
    <div className="size-guide-accessories">
      <section className="size-guide-section">
        <h3 className="size-guide-section-heading">Necklace Length Guide</h3>
        <p className="size-guide-section-sub">
          Lengths reflect where the chain sits on an average adult. Layer two
          contrasting lengths for a curated look.
        </p>
        <div className="size-guide-table-scroll">
          <table className="size-guide-table">
            <thead>
              <tr>
                <th scope="col">Length</th>
                <th scope="col">Style Name</th>
                <th scope="col">Where it sits</th>
              </tr>
            </thead>
            <tbody>
              {NECKLACE_LENGTHS.map((row) => (
                <tr key={row.length}>
                  <th scope="row">{row.length}</th>
                  <td>{row.name}</td>
                  <td>{row.sits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="size-guide-section">
        <h3 className="size-guide-section-heading">Ring Size Guide</h3>
        <p className="size-guide-section-sub">
          Use a ring you already own to compare against the inner-circle
          measurements below, or order a complimentary printed ring sizer.
        </p>
        <div className="size-guide-table-scroll">
          <table className="size-guide-table">
            <thead>
              <tr>
                <th scope="col">US</th>
                <th scope="col">UK</th>
                <th scope="col">EU</th>
                <th scope="col">Inner Diameter (mm)</th>
              </tr>
            </thead>
            <tbody>
              {RING_SIZES.map((row) => (
                <tr key={row.us}>
                  <th scope="row">{row.us}</th>
                  <td>{row.uk}</td>
                  <td>{row.eu}</td>
                  <td>{row.mm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="size-guide-resource-row">
          <a
            href="/pages/contact"
            className="size-guide-resource"
            download
          >
            Download printable ring sizer
          </a>
          <a href="/pages/contact" className="size-guide-resource">
            Order a physical ring sizer
          </a>
        </div>
      </section>
    </div>
  );
}
