import {Link, useLoaderData} from 'react-router';
import {Image} from '@shopify/hydrogen';
import type {Route} from './+types/pages.$handle';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {ContactForm} from '~/components/ContactForm';
import {FAQAccordion, type FAQGroup} from '~/components/FAQAccordion';
import {ProductAccordion} from '~/components/ProductAccordion';
import {InfoPageFooter} from '~/components/InfoPageFooter';

export const meta: Route.MetaFunction = ({data}) => {
  return [{title: `Mock Hardware | ${data?.page.title ?? ''}`}];
};

export async function loader(args: Route.LoaderArgs) {
  const deferredData = loadDeferredData(args);
  const criticalData = await loadCriticalData(args);
  return {...deferredData, ...criticalData};
}

async function loadCriticalData({context, request, params}: Route.LoaderArgs) {
  if (!params.handle) {
    throw new Error('Missing page handle');
  }

  const [{page}] = await Promise.all([
    context.storefront.query(PAGE_QUERY, {
      variables: {handle: params.handle},
    }),
  ]);

  if (!page) {
    throw new Response('Not Found', {status: 404});
  }

  redirectIfHandleIsLocalized(request, {handle: params.handle, data: page});

  const compatProducts =
    params.handle === 'pos-compatibility'
      ? await loadCompatProducts(context.storefront)
      : null;

  return {page, compatProducts};
}

async function loadCompatProducts(
  storefront: Route.LoaderArgs['context']['storefront'],
) {
  const handles = COMPAT_CATEGORIES.flatMap((c) =>
    c.products.map((p) => p.handle),
  );
  const aliasFields = handles
    .map(
      (h, i) =>
        `p${i}: product(handle: "${h}") { handle featuredImage { id url altText width height } }`,
    )
    .join('\n');
  const query = `#graphql
    query CompatProducts($country: CountryCode, $language: LanguageCode)
      @inContext(country: $country, language: $language) {
      ${aliasFields}
    }
  `;
  const data = (await storefront.query(query)) as Record<
    string,
    {handle: string; featuredImage: CompatProductImage['featuredImage']} | null
  >;
  const map: Record<string, CompatProductImage> = {};
  for (const node of Object.values(data ?? {})) {
    if (node?.handle) {
      map[node.handle] = {featuredImage: node.featuredImage ?? null};
    }
  }
  return map;
}

type CompatProductImage = {
  featuredImage: {
    id?: string | null;
    url: string;
    altText?: string | null;
    width?: number | null;
    height?: number | null;
  } | null;
};

function loadDeferredData(_: Route.LoaderArgs) {
  return {};
}

export default function Page() {
  const {page, compatProducts} = useLoaderData<typeof loader>();

  return (
    <article className="info-page">
      {renderPageBody(page, compatProducts)}
      <InfoPageFooter />
    </article>
  );
}

function renderPageBody(
  page: {handle: string; title: string; body: string},
  compatProducts: Record<string, CompatProductImage> | null,
) {
  switch (page.handle) {
    case 'faq':
      return <FAQPage />;
    case 'return-policy':
      return <ReturnPolicyPage />;
    case 'shopify-products-warranty':
      return <WarrantyPage />;
    case 'hardware-rental-program':
      return <RentalProgramPage />;
    case 'gift-cards':
      return <GiftCardsPage />;
    case 'pos-compatibility':
      return <CompatibilityPage products={compatProducts} />;
    case 'contact':
      return <ContactPage page={page} />;
    case 'order-support-request':
      return <OrderSupportRequestPage page={page} />;
    default:
      return <GenericPage page={page} />;
  }
}

/* ---------- FAQ ---------- */

const FAQ_GROUPS: FAQGroup[] = [
  {
    label: 'Order Processing',
    items: [
      {
        question: 'How long does it take to process my order?',
        answer: (
          <p>
            Illustrative orders are processed within 1–3 business days,
            Monday–Friday. You will receive a confirmation email with tracking
            once the order ships from the (mock) warehouse.
          </p>
        ),
      },
      {
        question: 'Can I change or cancel my order after I place it?',
        answer: (
          <p>
            Once an order has entered the (illustrative) fulfillment queue, we
            cannot modify the contents. You can request a return after the
            order arrives following the steps on the Returns page.
          </p>
        ),
      },
      {
        question: 'What payment methods are accepted?',
        answer: (
          <p>
            The mock storefront illustrates major card brands (Visa,
            Mastercard, American Express). No real payments are processed.
          </p>
        ),
      },
      {
        question: 'Do you charge sales tax?',
        answer: (
          <p>
            Tax is illustratively calculated at checkout based on the
            destination address. Tax-exempt purchasers can submit
            documentation to support after placing an order.
          </p>
        ),
      },
      {
        question: 'Will I receive an order confirmation?',
        answer: (
          <p>
            A confirmation email is illustratively sent immediately after an
            order is placed, followed by a shipping notification with tracking
            once the package leaves the warehouse.
          </p>
        ),
      },
    ],
  },
  {
    label: 'Shipping & Delivery',
    items: [
      {
        question: 'How much does shipping cost?',
        answer: (
          <p>
            Standard ground shipping is shown as a flat rate at checkout. Free
            standard shipping is illustrated for qualifying hardware bundles
            above an order threshold.
          </p>
        ),
      },
      {
        question: 'How long does delivery take?',
        answer: (
          <p>
            Domestic ground orders illustrate 3–7 business days after dispatch.
            Expedited shipping illustrates 1–2 business days after dispatch.
          </p>
        ),
      },
      {
        question: 'Do you ship internationally?',
        answer: (
          <p>
            Some hardware listings are illustrated as available only in
            specific regions. International destinations may incur additional
            duties, taxes, and carrier fees that the buyer would be
            responsible for.
          </p>
        ),
      },
      {
        question: 'How do I track my order?',
        answer: (
          <p>
            A tracking number is illustrated in the shipping confirmation
            email and accessible from your order history page once the order
            ships.
          </p>
        ),
      },
      {
        question: 'My package was marked delivered but I did not receive it.',
        answer: (
          <p>
            Wait 24 hours, then check with neighbors and the carrier. If the
            package is still missing, open a support request and the
            (illustrative) team will investigate with the carrier.
          </p>
        ),
      },
      {
        question: 'Can I ship to a different address than the billing address?',
        answer: (
          <p>
            Yes — the (mock) checkout flow lets you set a separate shipping
            address.
          </p>
        ),
      },
      {
        question: 'Do you ship to PO boxes?',
        answer: (
          <p>
            Bulk hardware bundles are illustrated as freight-shipped and not
            eligible for PO boxes. Smaller items may ship to PO boxes via
            standard ground.
          </p>
        ),
      },
    ],
  },
  {
    label: 'Returns & Refunds',
    items: [
      {
        question: 'What is the return window?',
        answer: (
          <p>
            The illustrative policy is a 30-day return window from the
            simulated delivery date for eligible POS hardware.
          </p>
        ),
      },
      {
        question: 'How do I start a return?',
        answer: (
          <p>
            Visit the Returns page and click &ldquo;Start your return&rdquo;
            to access the (illustrative) returns center portal.
          </p>
        ),
      },
      {
        question: 'Are there any restocking fees?',
        answer: (
          <p>
            A restocking fee may be deducted for hardware returns that are
            accepted but not in fully resellable condition (for example,
            opened packaging, missing inserts, or light cosmetic wear).
          </p>
        ),
      },
      {
        question: 'How long do refunds take?',
        answer: (
          <p>
            Once a returned device is received and inspected, a refund is
            illustratively issued within 5–10 business days to the original
            payment method.
          </p>
        ),
      },
      {
        question: 'Can I exchange an item instead of returning it?',
        answer: (
          <p>
            The fastest illustrative path to an exchange is to return the
            original item and place a separate order for the replacement.
          </p>
        ),
      },
      {
        question: 'What if my order arrives damaged?',
        answer: (
          <p>
            Inspect your order on arrival and report any defects, damage, or
            wrong items immediately. Defective hardware is covered under the
            separate warranty rather than this return policy.
          </p>
        ),
      },
    ],
  },
  {
    label: 'Order Issues',
    items: [
      {
        question: 'I received the wrong item — what should I do?',
        answer: (
          <p>
            Submit an order support request with your order number and a
            photo of the item received. The (illustrative) team will arrange
            a replacement and a return label.
          </p>
        ),
      },
      {
        question: 'My device will not pair or power on.',
        answer: (
          <p>
            Most issues are resolved by following the setup guide that ships
            with the device. If the issue persists, the device may be covered
            under warranty — see the Warranty page for details.
          </p>
        ),
      },
      {
        question: 'I cannot find my order confirmation email.',
        answer: (
          <p>
            Check your spam or promotions folder. If you still cannot locate
            it, sign in to your account and view the order under Order
            history, or contact support with the email used at checkout.
          </p>
        ),
      },
    ],
  },
];

function FAQPage() {
  return (
    <>
      <header className="info-page-hero">
        <h1 className="info-page-title">Frequently Asked Questions</h1>
        <p className="info-page-intro">
          Find answers to common questions about ordering, shipping, returns,
          and order issues for the illustrative POS hardware on this mock
          storefront.
        </p>
      </header>

      <section className="info-support-banner">
        <h2 className="info-support-heading">Still need help with an order?</h2>
        <p className="info-support-copy">
          Send our (illustrative) support team a request and we&apos;ll get
          back to you within one business day.
        </p>
        <Link
          to="/pages/order-support-request"
          className="info-button info-button-primary"
        >
          Open a support request
        </Link>
      </section>

      <section className="info-page-section">
        <FAQAccordion groups={FAQ_GROUPS} />
      </section>

      <section className="info-resource-cards">
        <ResourceCard
          eyebrow="Learn"
          title="Merchant education"
          description="Setup guides, training videos, and best-practice tutorials for running POS hardware day-to-day."
          href="https://help.shopify.com/manual/sell-in-person"
          external
        />
        <ResourceCard
          eyebrow="Help center"
          title="Browse the help center"
          description="Search a deeper FAQ library covering payments, accounting, and store operations."
          href="https://help.shopify.com"
          external
        />
        <ResourceCard
          eyebrow="Talk to us"
          title="Contact support"
          description="Reach the (illustrative) Mock Hardware support team for everything not covered here."
          href="/pages/contact"
        />
      </section>
    </>
  );
}

function ResourceCard({
  eyebrow,
  title,
  description,
  href,
  external,
}: {
  eyebrow: string;
  title: string;
  description: string;
  href: string;
  external?: boolean;
}) {
  const Wrapper: React.ElementType = external ? 'a' : Link;
  const wrapperProps: Record<string, unknown> = external
    ? {href, target: '_blank', rel: 'noopener noreferrer'}
    : {to: href, prefetch: 'intent'};
  return (
    <Wrapper {...wrapperProps} className="info-resource-card">
      <div className="info-resource-card-image" aria-hidden="true">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect width="48" height="48" rx="4" fill="#f0ede8" />
          <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
          <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
        </svg>
      </div>
      <div className="info-resource-card-body">
        <span className="info-resource-card-eyebrow">{eyebrow}</span>
        <h2 className="info-resource-card-title">{title}</h2>
        <p className="info-resource-card-description">{description}</p>
      </div>
    </Wrapper>
  );
}

/* ---------- Returns ---------- */

function ReturnPolicyPage() {
  return (
    <>
      <header className="info-page-header">
        <span className="info-page-eyebrow">Returns center · US</span>
        <h1 className="info-page-title">Returns</h1>
        <p className="info-page-intro">
          Start a return for hardware ordered in the United States. Follow
          the steps below to package the device, generate a prepaid label,
          and track the refund.
        </p>
        <a
          className="info-button info-button-primary"
          href="https://returns.shopify.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          Start your return
        </a>
      </header>

      <section className="info-page-section info-page-section-narrow">
        <ProductAccordion
          sections={[
            {
              id: 'requirements',
              label: 'Requirements',
              content: (
                <div className="info-prose">
                  <p>
                    To be eligible for an illustrative return, the item must
                    be in new, unused condition, with all original packaging,
                    accessories, cables, and documentation included.
                  </p>
                  <ul>
                    <li>Within 30 days of the simulated delivery date.</li>
                    <li>
                      Item must not show signs of use, missing components, or
                      damage outside the original packaging.
                    </li>
                    <li>
                      Original payment method must be valid to issue a refund.
                    </li>
                  </ul>
                </div>
              ),
            },
            {
              id: 'instructions',
              label: 'Instructions',
              content: (
                <div className="info-prose">
                  <ol>
                    <li>
                      Open the (illustrative) returns portal using the button
                      above.
                    </li>
                    <li>
                      Look up your order with the order number and email
                      address used at checkout.
                    </li>
                    <li>Select the items you want to return and a reason.</li>
                    <li>
                      Print the prepaid shipping label and pack the device in
                      its original box with all accessories included.
                    </li>
                    <li>Drop the package at any carrier location.</li>
                  </ol>
                </div>
              ),
            },
            {
              id: 'pos-equipment',
              label: 'POS Equipment Agreement',
              content: (
                <div className="info-prose">
                  <p>
                    Hardware shown on this site is illustrated as sold subject
                    to a hypothetical POS equipment agreement covering
                    availability, order cancellation, and acceptable use. None
                    of these terms are real or enforceable on this research
                    site.
                  </p>
                  <p>
                    The agreement is illustrated as covering: lawful use of
                    payment hardware, prohibition of resale outside the
                    intended region, and a one-time replacement allowance for
                    devices damaged in transit.
                  </p>
                </div>
              ),
            },
          ]}
        />
      </section>
    </>
  );
}

/* ---------- Warranty ---------- */

function WarrantyPage() {
  return (
    <>
      <header className="info-page-header">
        <h1 className="info-page-title">Hardware Warranty</h1>
      </header>

      <section className="info-page-section info-page-section-narrow info-prose">
        <h3>First-party warranties</h3>
        <ul>
          <li>
            <strong>Standard POS terminals:</strong> 1-year limited warranty
            from the (simulated) delivery date.
          </li>
          <li>
            <strong>POS Pro terminals:</strong> 2-year limited warranty,
            including parts and labor for manufacturing defects.
          </li>
          <li>
            <strong>Card readers and docks:</strong> 1-year limited warranty.
          </li>
          <li>
            <strong>Counter accessories</strong> (cash drawers, tablet
            stands): 1-year limited warranty.
          </li>
        </ul>
        <p>
          <em>
            Note: Devices that have been physically opened, modified, or
            tampered with are illustrated as falling outside the warranty
            terms.
          </em>
        </p>

        <h3>Third-party warranties</h3>
        <h5>Note</h5>
        <p>
          Third-party hardware listed on this mock storefront is covered by
          the original manufacturer&apos;s warranty rather than the
          illustrative first-party warranty above. Coverage windows and terms
          vary by manufacturer and region.
        </p>
        <p>
          For region-specific exception logic — for example, EU consumer
          protection statutes or extended Australian Consumer Law remedies —
          the longer of the manufacturer&apos;s warranty or the applicable
          statutory minimum applies.
        </p>
        <p>
          For the fastest resolution on third-party hardware, contact the
          original manufacturer with your serial number, proof of purchase,
          and a description of the issue. The (illustrative) Mock Hardware
          team can help facilitate the conversation if needed.
        </p>
        <p>
          The first-party warranty above covers receipt printers, barcode
          scanners, cash drawers, tablet stands, and card readers branded as
          Mock Hardware.
        </p>
      </section>

      <section className="info-page-section info-page-section-narrow">
        <ProductAccordion
          sections={[
            {
              id: 'shopify-products',
              label: 'Shopify Products',
              content: (
                <div className="info-prose">
                  <p>
                    First-party device models covered by the Mock Hardware
                    illustrative warranty:
                  </p>
                  <ul>
                    <li>
                      <Link to="/products/shopliseum-compact-card-reader">
                        Shopliseum compact card reader
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/shoplodrome-compact-card-reader">
                        Shoplodrome compact card reader
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/carthaeum-counter-terminal">
                        Carthaeum counter terminal
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/aisleum-reader-dock">
                        Aisleum reader dock
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/carthaeum-terminal-reader">
                        Carthaeum terminal reader
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/aislearena-portable-card-reader">
                        Aislearena portable card reader
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/shopliseum-chip-card-reader">
                        Shopliseum chip card reader
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/carthaeum-terminal-reader-pro">
                        Carthaeum terminal reader Pro
                      </Link>
                    </li>
                    <li>
                      <Link to="/products/agoracage-go-handheld-terminal">
                        Agoracage Go handheld terminal
                      </Link>
                    </li>
                  </ul>
                </div>
              ),
            },
            {
              id: 'return-policy',
              label: 'Return Policy',
              content: (
                <div className="info-prose">
                  <p>
                    Defective hardware can be returned for a replacement or
                    refund within the warranty window. Visit{' '}
                    <Link to="/pages/return-policy">Returns</Link> to start
                    the process.
                  </p>
                </div>
              ),
            },
            {
              id: 'reader-issues',
              label: 'Having issues with your reader?',
              content: (
                <div className="info-prose">
                  <p>
                    Most reader issues are resolved by following the setup
                    guide. If pairing, charging, or chip insertion fails after
                    a power cycle, the device may be eligible for warranty
                    replacement.
                  </p>
                </div>
              ),
            },
            {
              id: 'support',
              label: 'Need support?',
              content: (
                <div className="info-prose">
                  <p>
                    Open a request from{' '}
                    <Link to="/pages/order-support-request">
                      Order support
                    </Link>{' '}
                    and include your order number, device serial number, and
                    a description of the issue.
                  </p>
                </div>
              ),
            },
          ]}
        />
      </section>
    </>
  );
}

/* ---------- Rental Program ---------- */

function RentalProgramPage() {
  return (
    <>
      <header className="info-page-hero info-page-hero-large">
        <span className="info-page-eyebrow">Rental Program</span>
        <h1 className="info-page-title">Rent the hardware you need, when you need it</h1>
        <p className="info-page-intro">
          Spin up POS hardware for a pop-up shop, market booth, or one-day
          event without buying equipment outright. Pre-configured kits ship
          ready to use and return with a prepaid label.
        </p>
        <a
          className="info-button info-button-primary"
          href="https://rentals.example.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          Browse rental kits
        </a>
      </header>

      <section className="info-feature-grid">
        <FeatureColumn
          title="Convenient delivery"
          description="Kits ship pre-configured to the venue address — no integration work onsite."
        />
        <FeatureColumn
          title="Setup help"
          description="A short setup video walks staff through power-on, pairing, and first sale."
        />
        <FeatureColumn
          title="Full POS app access"
          description="Rental devices come paired to the (illustrative) Mock Hardware POS app with your store inventory."
        />
        <FeatureColumn
          title="Simple returns"
          description="Drop the kit in the return box with the prepaid label included in the package."
        />
      </section>

      <section className="info-page-section info-rental-cta">
        <span className="info-page-eyebrow">For pop-ups, markets, and events</span>
        <h3 className="info-section-heading">
          Cover your booth, kiosk, or holiday market in one order
        </h3>
        <p className="info-page-intro">
          Choose from kits sized for one register, two registers, or a multi-station setup.
        </p>
        <a
          className="info-button info-button-secondary"
          href="https://rentals.example.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          Rent hardware
        </a>
      </section>

      <section className="info-page-section info-page-section-narrow info-prose">
        <h3>Why rent from Mock Hardware</h3>
        <h4>Pre-configured and ready</h4>
        <p>
          Each kit ships paired to your (illustrative) store inventory and
          payment account so the first sale can happen within minutes of
          unboxing. There is no separate IT integration step.
        </p>
        <h4>Support when you need it</h4>
        <p>
          The (illustrative) support team is available during your event to
          troubleshoot connectivity, payment auth, or printer issues. Loaner
          devices are illustrated as available for shipment if a unit fails
          during the rental.
        </p>
      </section>
    </>
  );
}

function FeatureColumn({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="info-feature-column">
      <div className="info-feature-image" aria-hidden="true">
        <svg width="56" height="56" viewBox="0 0 48 48" fill="none">
          <rect width="48" height="48" rx="6" fill="#f0ede8" />
          <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
          <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
        </svg>
      </div>
      <h2 className="info-feature-title">{title}</h2>
      <p className="info-feature-description">{description}</p>
    </div>
  );
}

/* ---------- Gift Cards ---------- */

function GiftCardsPage() {
  return (
    <>
      <header className="info-page-hero info-page-hero-large">
        <span className="info-page-eyebrow">Gift Cards</span>
        <h1 className="info-page-title">Gift cards customers actually use</h1>
        <p className="info-page-intro">
          Sell branded physical gift cards from your retail counter and turn
          one-time shoppers into repeat customers.
        </p>
        <a
          className="info-button info-button-primary"
          href="https://giftcards.example.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          Order gift cards
        </a>
      </header>

      <section className="info-page-section">
        <h2 className="info-section-heading">Why gift cards work</h2>
        <div className="info-stat-grid">
          <StatCard
            label="Revenue retention"
            value="~10%"
            copy="of gift-card balances are illustrated as never redeemed, becoming pure revenue."
          />
          <StatCard
            label="Customer acquisition"
            value="~40%"
            copy="of gift-card recipients are illustrated as first-time customers to the issuing store."
          />
          <StatCard
            label="Average order uplift"
            value="38%"
            copy="of recipients are illustrated as spending beyond the gift-card value at redemption."
          />
          <StatCard
            label="Brand visibility"
            value="365 days"
            copy="of countertop and wallet exposure between purchase and redemption."
          />
          <StatCard
            label="Purchase frequency"
            value="2.4×"
            copy="more visits per year for customers who redeem a gift card vs. baseline."
          />
        </div>
      </section>

      <section className="info-page-section info-step-section">
        <h2 className="info-section-heading">How it works</h2>
        <ol className="info-step-grid">
          <ProcessStep
            number={1}
            title="Design"
            description="Pick a template or upload your own artwork. Add your logo and a short message."
          />
          <ProcessStep
            number={2}
            title="Order"
            description="Place an order with our (illustrative) print partner — minimums start at 50 cards."
          />
          <ProcessStep
            number={3}
            title="Sell"
            description="Activate cards at the register and scan to redeem on any future order."
          />
        </ol>
      </section>

      <section className="info-page-section info-page-section-narrow">
        <h2 className="info-section-heading">Questions you might have</h2>
        <ProductAccordion
          sections={[
            {
              id: 'ordering',
              label: 'Ordering gift cards',
              content: (
                <div className="info-prose">
                  <p>
                    Cards are produced by an (illustrative) third-party print
                    partner and shipped directly to the address on file.
                    Standard turnaround is 7–10 business days from artwork
                    approval. Rush options are illustrated for events.
                  </p>
                </div>
              ),
            },
            {
              id: 'pos-setup',
              label: 'Set up your gift cards in Shopify POS',
              content: (
                <div className="info-prose">
                  <p>
                    Once cards arrive, link the card numbers to your store
                    using the POS app. See the{' '}
                    <a
                      href="https://help.shopify.com/manual/products/gift-cards"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      help center documentation
                    </a>{' '}
                    for the full setup walkthrough.
                  </p>
                </div>
              ),
            },
          ]}
        />
      </section>
    </>
  );
}

function StatCard({
  label,
  value,
  copy,
}: {
  label: string;
  value: string;
  copy: string;
}) {
  return (
    <div className="info-stat-card">
      <h4 className="info-stat-label">{label}</h4>
      <span className="info-stat-value">{value}</span>
      <p className="info-stat-copy">{copy}</p>
    </div>
  );
}

function ProcessStep({
  number,
  title,
  description,
}: {
  number: number;
  title: string;
  description: string;
}) {
  return (
    <li className="info-step-item">
      <div className="info-step-image" aria-hidden="true">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect width="48" height="48" rx="6" fill="#f0ede8" />
          <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
          <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
        </svg>
      </div>
      <span className="info-step-number">Step {number}</span>
      <h3 className="info-step-title">{title}</h3>
      <p className="info-step-description">{description}</p>
    </li>
  );
}

/* ---------- Hardware Compatibility ---------- */

type CompatProduct = {
  handle: string;
  title: string;
  type?: string;
};

type CompatCategory = {
  id: string;
  label: string;
  products: CompatProduct[];
};

const COMPAT_CATEGORIES: CompatCategory[] = [
  {
    id: 'card-readers',
    label: 'Card readers',
    products: [
      {handle: 'carthaeum-terminal-reader', title: 'Carthaeum terminal reader'},
      {handle: 'aisleum-reader-dock', title: 'Aisleum reader dock + reader bundle'},
    ],
  },
  {
    id: 'receipt-printers',
    label: 'Receipt printers',
    products: [
      {
        handle: 'shopodrome-bluetooth-thermal-slip-printer',
        title: 'Shopodrome Bluetooth thermal slip printer',
      },
      {
        handle: 'shoplodrome-4g-wireless-thermal-slip-printer',
        title: 'Shoplodrome 4G wireless thermal slip printer',
      },
      {
        handle: 'aisleodrome-mini-portable-thermal-slip-printer',
        title: 'Aisleodrome mini portable thermal slip printer',
      },
    ],
  },
  {
    id: 'barcode-scanners',
    label: 'Barcode scanners',
    products: [
      {
        handle: 'shopliseum-2d-wired-code-reader-with-cradle',
        title: 'Shopliseum 2D wired code reader with cradle',
      },
      {
        handle: 'agoracage-pro-wireless-code-scanner-with-dock',
        title: 'Agoracage Pro wireless code scanner with dock',
      },
      {
        handle: 'cartrome-countertop-code-reader',
        title: 'Cartrome countertop code reader',
      },
    ],
  },
  {
    id: 'cash-drawers',
    label: 'Cash drawers',
    products: [
      {
        handle: 'carthaeum-16-inch-heavy-duty-till-tray',
        title: 'Carthaeum 16" heavy-duty till tray',
      },
      {
        handle: 'carthaeum-14-inch-standard-till-tray',
        title: 'Carthaeum 14" standard till tray',
      },
    ],
  },
  {
    id: 'tablet-stands',
    label: 'Tablet stands',
    products: [
      {
        handle: 'aislearena-slim-tablet-display-mount',
        title: 'Aislearena slim tablet display mount',
      },
    ],
  },
];

function CompatibilityPage({
  products,
}: {
  products: Record<string, CompatProductImage> | null;
}) {
  return (
    <>
      <header className="info-page-header">
        <h1 className="info-page-title">Compatible devices</h1>
        <p className="info-page-intro">
          Hardware that works with the (illustrative) Mock Hardware POS
          platform, organized by category.
        </p>
      </header>

      <div className="info-page-section info-compat-sections">
        {COMPAT_CATEGORIES.map((category) => (
          <section key={category.id} className="info-compat-section">
            <h2 className="info-compat-section-label">{category.label}</h2>
            <ul className="info-compat-grid">
              {category.products.map((product) => {
                const image = products?.[product.handle]?.featuredImage;
                return (
                  <li key={product.handle} className="info-compat-card">
                    <Link
                      to={`/products/${product.handle}`}
                      prefetch="intent"
                      className="info-compat-card-link"
                    >
                      <div className="info-compat-card-image">
                        {image ? (
                          <Image
                            data={image}
                            alt={image.altText ?? product.title}
                            sizes="(min-width: 60em) 320px, 50vw"
                            loading="lazy"
                            className="info-compat-card-image-img"
                          />
                        ) : (
                          <CompatImagePlaceholder />
                        )}
                      </div>
                      <span className="info-compat-card-title">
                        {product.title}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <p className="info-compat-secondary">
        Looking for a complete counter? Browse the{' '}
        <Link to="/collections/retail-hub-companions">POS Hub</Link> landing
        page.
      </p>
    </>
  );
}

function CompatImagePlaceholder() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <rect width="48" height="48" rx="4" fill="#f0ede8" />
      <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
      <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
    </svg>
  );
}

/* ---------- Contact / Support ---------- */

function ContactPage({page}: {page: {title: string; body: string}}) {
  return (
    <>
      <header className="info-page-header">
        <h1 className="info-page-title">{page.title}</h1>
        <div
          className="info-page-intro info-page-rich"
          dangerouslySetInnerHTML={{__html: page.body}}
        />
      </header>

      <section className="info-page-section info-page-section-narrow">
        <h2 className="info-section-heading">Send us a message</h2>
        <ContactForm />
      </section>
    </>
  );
}

function OrderSupportRequestPage({
  page,
}: {
  page: {title: string; body: string};
}) {
  return (
    <>
      <header className="info-page-header">
        <h1 className="info-page-title">{page.title}</h1>
        <div
          className="info-page-intro info-page-rich"
          dangerouslySetInnerHTML={{__html: page.body}}
        />
      </header>

      <section className="info-page-section info-page-section-narrow">
        <ContactForm />
      </section>
    </>
  );
}

/* ---------- Generic ---------- */

function GenericPage({page}: {page: {title: string; body: string}}) {
  return (
    <>
      <header className="info-page-header">
        <h1 className="info-page-title">{page.title}</h1>
      </header>
      <section className="info-page-section info-page-section-narrow">
        <div
          className="info-page-rich"
          dangerouslySetInnerHTML={{__html: page.body}}
        />
      </section>
    </>
  );
}

const PAGE_QUERY = `#graphql
  query Page(
    $language: LanguageCode,
    $country: CountryCode,
    $handle: String!
  )
  @inContext(language: $language, country: $country) {
    page(handle: $handle) {
      handle
      id
      title
      body
      seo {
        description
        title
      }
    }
  }
` as const;
