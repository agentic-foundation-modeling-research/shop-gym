import {useState} from 'react';
import {type MappedProductOptions} from '@shopify/hydrogen';
import {AddToCartButton} from './AddToCartButton';
import {useAside} from './Aside';
import {ColorSwatches} from './ColorSwatches';
import {SizeSelector} from './SizeSelector';
import {GiftPackagingDrawer} from './GiftPackagingDrawer';
import type {ProductFragment} from 'storefrontapi.generated';

const PERSONALISE_KEYWORDS = [
  'engrave',
  'engraved',
  'personalise',
  'personalised',
  'personalize',
  'personalized',
  'monogram',
  'custom',
  'birthstone',
  'name',
  'initial',
];

function isPersonalisable(handle: string, productType?: string | null): boolean {
  const haystack = `${handle} ${productType ?? ''}`.toLowerCase();
  return PERSONALISE_KEYWORDS.some((kw) => haystack.includes(kw));
}

function isColorOption(name: string): boolean {
  const lc = name.toLowerCase();
  return (
    lc.includes('color') ||
    lc.includes('colour') ||
    lc.includes('finish') ||
    lc.includes('shade')
  );
}

function isSizeOption(name: string): boolean {
  return name.toLowerCase().includes('size');
}

export function ProductForm({
  productOptions,
  selectedVariant,
  productHandle,
  productTitle,
  vendor,
}: {
  productOptions: MappedProductOptions[];
  selectedVariant: ProductFragment['selectedOrFirstAvailableVariant'];
  productHandle: string;
  productTitle: string;
  vendor?: string | null;
}) {
  const {open} = useAside();
  const [deliveryMode, setDeliveryMode] = useState<'ship' | 'pickup'>('ship');
  const [giftDrawerOpen, setGiftDrawerOpen] = useState(false);

  const personalisable = isPersonalisable(productHandle, vendor);
  const available = Boolean(selectedVariant?.availableForSale);

  const colorOptions = productOptions.find((o) => isColorOption(o.name));
  const sizeOptions = productOptions.find((o) => isSizeOption(o.name));
  const otherOptions = productOptions.filter(
    (o) =>
      !isColorOption(o.name) &&
      !isSizeOption(o.name) &&
      o.optionValues.length > 1,
  );

  const selectedColorName = colorOptions?.optionValues.find(
    (v) => v.selected,
  )?.name;

  return (
    <div className="pdp-form">
      {colorOptions && colorOptions.optionValues.length > 1 ? (
        <ColorSwatches option={colorOptions} selectedLabel={selectedColorName} />
      ) : null}

      {sizeOptions && sizeOptions.optionValues.length > 1 ? (
        <SizeSelector option={sizeOptions} />
      ) : null}

      {otherOptions.map((option) => (
        <ColorSwatches key={option.name} option={option} />
      ))}

      {personalisable ? (
        <p className="pdp-personalise-note">
          Personalisation available — engraving and bespoke options at the next
          step.
        </p>
      ) : null}

      <div className="pdp-delivery-tabs" role="tablist" aria-label="Delivery method">
        <button
          type="button"
          role="tab"
          aria-selected={deliveryMode === 'ship'}
          className={`pdp-delivery-tab${
            deliveryMode === 'ship' ? ' is-selected' : ''
          }`}
          onClick={() => setDeliveryMode('ship')}
        >
          <span className="pdp-delivery-tab-title">Ship to Me</span>
          <span className="pdp-delivery-tab-meta">
            Free over $75 · 2-4 business days
          </span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={deliveryMode === 'pickup'}
          className={`pdp-delivery-tab${
            deliveryMode === 'pickup' ? ' is-selected' : ''
          }`}
          onClick={() => setDeliveryMode('pickup')}
        >
          <span className="pdp-delivery-tab-title">Pickup in Store</span>
          <span className="pdp-delivery-tab-meta">
            Available at SoHo & Marylebone
          </span>
        </button>
      </div>

      <div className="pdp-cta-row">
        {available ? (
          <AddToCartButton
            disabled={!selectedVariant}
            onClick={() => {
              setGiftDrawerOpen(true);
              open('cart');
            }}
            lines={
              selectedVariant
                ? [
                    {
                      merchandiseId: selectedVariant.id,
                      quantity: 1,
                      selectedVariant,
                    },
                  ]
                : []
            }
          >
            <span className="pdp-cta-button-label">
              {personalisable ? 'Personalise & Add to Bag' : 'Add to Bag'}
            </span>
          </AddToCartButton>
        ) : (
          <button type="button" className="pdp-cta-notify">
            Notify Me When Available
          </button>
        )}
        <button
          type="button"
          className="pdp-icon-button"
          aria-label="Save to wishlist"
          title="Save to wishlist"
        >
          <HeartIcon />
        </button>
        <button
          type="button"
          className="pdp-icon-button"
          aria-label="Share product"
          title="Share product"
          onClick={() => {
            if (typeof navigator !== 'undefined' && navigator.share) {
              void navigator.share({
                title: productTitle,
                url: typeof window !== 'undefined' ? window.location.href : '',
              });
            }
          }}
        >
          <ShareIcon />
        </button>
      </div>

      <ul className="pdp-trust-zone-2">
        <li>
          <BadgeCheckIcon />
          <span>Tarnish-free guarantee</span>
        </li>
        <li>
          <ChatIcon />
          <span>24/7 customer support</span>
        </li>
        <li>
          <ReturnIcon />
          <span>365-day extended returns</span>
        </li>
      </ul>

      <div className="pdp-payment-row">
        <span className="pdp-payment-label">
          <LockIcon />
          Secure Checkout
        </span>
        <ul className="pdp-payment-icons" aria-label="Accepted payment methods">
          <li className="pdp-payment-icon">VISA</li>
          <li className="pdp-payment-icon">MC</li>
          <li className="pdp-payment-icon">AMEX</li>
          <li className="pdp-payment-icon">PAY</li>
          <li className="pdp-payment-icon">G PAY</li>
          <li className="pdp-payment-icon">PYPL</li>
        </ul>
      </div>

      <ul className="pdp-trust-zone-3">
        <li>
          <ShieldIcon />
          <span>Waterproof &amp; durable</span>
        </li>
        <li>
          <CertIcon />
          <span>5-year warranty</span>
        </li>
        <li>
          <SparkleIcon />
          <span>Designed in-house</span>
        </li>
        <li>
          <GiftIcon />
          <span>Luxury packaging</span>
        </li>
      </ul>

      {giftDrawerOpen ? (
        <GiftPackagingDrawer
          productTitle={productTitle}
          onClose={() => setGiftDrawerOpen(false)}
        />
      ) : null}
    </div>
  );
}

function HeartIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 21s-7.5-4.6-9.6-9.5C1 7.4 4.2 4 7.6 4c2 0 3.4 1.1 4.4 2.4C13 5.1 14.4 4 16.4 4c3.4 0 6.6 3.4 5.2 7.5C19.5 16.4 12 21 12 21z"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
      />
    </svg>
  );
}

function ShareIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 4v12M12 4l-4 4M12 4l4 4M5 14v5a1 1 0 001 1h12a1 1 0 001-1v-5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function BadgeCheckIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2l2.5 2 3.5-.5.5 3.5 2 2.5-2 2.5-.5 3.5-3.5-.5L12 18l-2.5-2-3.5.5-.5-3.5-2-2.5 2-2.5.5-3.5 3.5.5L12 2z"
        stroke="currentColor"
        strokeWidth="1.4"
        fill="none"
      />
      <path
        d="M9 12l2 2 4-4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M21 12a8 8 0 11-3.5 6.6L4 20l1.5-3.7A8 8 0 0121 12z"
        stroke="currentColor"
        strokeWidth="1.4"
        fill="none"
      />
    </svg>
  );
}

function ReturnIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 12a9 9 0 0114-7.5L20 7M21 12a9 9 0 01-14 7.5L4 17M3 7h4V3M21 17h-4v4"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="5"
        y="11"
        width="14"
        height="9"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M8 11V8a4 4 0 018 0v3"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
      />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3l8 3v6c0 4.5-3.4 8.6-8 9-4.6-.4-8-4.5-8-9V6l8-3z"
        stroke="currentColor"
        strokeWidth="1.4"
        fill="none"
      />
      <path
        d="M9 12l2 2 4-4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CertIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="9" r="5" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M9 13l-2 7 5-3 5 3-2-7"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function SparkleIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3l1.6 5L19 9.5l-5.4 1.5L12 16l-1.6-5L5 9.5 10.4 8 12 3z"
        stroke="currentColor"
        strokeWidth="1.3"
        fill="none"
      />
      <path
        d="M19 17l.7 2 2 .8-2 .7L19 22l-.7-1.5-2-.7 2-.8L19 17z"
        stroke="currentColor"
        strokeWidth="1.3"
        fill="none"
      />
    </svg>
  );
}

function GiftIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="3"
        y="9"
        width="18"
        height="11"
        rx="1.5"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path d="M3 13h18M12 9v11" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M12 9c-1.5-2.5-5-3-5-1s2 2 5 1zm0 0c1.5-2.5 5-3 5-1s-2 2-5 1z"
        stroke="currentColor"
        strokeWidth="1.4"
        fill="none"
      />
    </svg>
  );
}
