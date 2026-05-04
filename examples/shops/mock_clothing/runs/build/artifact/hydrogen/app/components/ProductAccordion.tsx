import {useState} from 'react';
import type {ProductFragment} from 'storefrontapi.generated';

type Panel = {
  id: string;
  title: string;
  body: React.ReactNode;
};

export function ProductAccordion({
  product,
}: {
  product: Pick<ProductFragment, 'descriptionHtml' | 'description' | 'title'>;
}) {
  const [openId, setOpenId] = useState<string>('details');

  const panels = buildPanels(product);

  return (
    <div className="pdp-accordion">
      {panels.map((panel) => {
        const isOpen = openId === panel.id;
        return (
          <div
            key={panel.id}
            className={`pdp-accordion-panel${isOpen ? ' is-open' : ''}`}
          >
            <button
              type="button"
              className="pdp-accordion-trigger"
              aria-expanded={isOpen}
              aria-controls={`pdp-accordion-${panel.id}`}
              onClick={() => setOpenId(isOpen ? '' : panel.id)}
            >
              <span>{panel.title}</span>
              <span aria-hidden="true" className="pdp-accordion-icon">
                {isOpen ? '−' : '+'}
              </span>
            </button>
            {isOpen ? (
              <div
                id={`pdp-accordion-${panel.id}`}
                className="pdp-accordion-body"
              >
                {panel.body}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function buildPanels(
  product: Pick<ProductFragment, 'descriptionHtml' | 'description' | 'title'>,
): Panel[] {
  const descriptionHtml = product.descriptionHtml || '';
  return [
    {
      id: 'details',
      title: 'Details & Specifications',
      body: (
        <>
          {descriptionHtml ? (
            <div
              className="pdp-accordion-prose"
              dangerouslySetInnerHTML={{__html: descriptionHtml}}
            />
          ) : null}
          <ul className="pdp-accordion-list">
            <li>Buttery-soft technical fabric with four-way stretch.</li>
            <li>Mid-rise relaxed silhouette, designed in-house.</li>
            <li>OEKO-TEX certified materials, ethically sourced.</li>
            <li>Hidden seamless construction for a sculpted finish.</li>
          </ul>
        </>
      ),
    },
    {
      id: 'delivery',
      title: 'Delivery & Returns',
      body: (
        <p>
          Standard tracked shipping in 2-4 business days, free over $75.
          Express same-day available in select cities. Easy 365-day returns —
          unworn pieces in their original packaging are eligible for a full
          refund or exchange.
        </p>
      ),
    },
    {
      id: 'quality',
      title: 'Quality & Materials',
      body: (
        <p>
          Each piece is finished by hand and tested against our wear-and-tear
          standards before it leaves our atelier — colour-fastness, seam
          integrity, and surface durability are all checked. Backed by our
          5-year guarantee.
        </p>
      ),
    },
    {
      id: 'care',
      title: 'Care Instructions',
      body: (
        <ul className="pdp-accordion-list">
          <li>Cold machine wash with similar colours.</li>
          <li>Use a mild, fragrance-free detergent.</li>
          <li>Lay flat to dry — do not tumble dry.</li>
          <li>Avoid direct sunlight when storing.</li>
          <li>Do not bleach or dry clean.</li>
          <li>Iron on low if needed, inside out.</li>
        </ul>
      ),
    },
    {
      id: 'gifting',
      title: 'Gifting & Packaging',
      body: (
        <p>
          All orders ship in our signature box with tissue and a thank-you
          note. Add a gift bag, hard-shell gift box, or hand-finished card at
          checkout — and include a personal message free of charge. Gift
          orders ship without pricing receipts.
        </p>
      ),
    },
  ];
}
