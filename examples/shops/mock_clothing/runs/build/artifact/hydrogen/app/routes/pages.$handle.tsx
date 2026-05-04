import {Link, useLoaderData} from 'react-router';
import {useState} from 'react';
import type {Route} from './+types/pages.$handle';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {ContactForm} from '~/components/ContactForm';
import {FAQAccordion, type FAQItem} from '~/components/FAQAccordion';
import {SizeGuide} from '~/components/SizeGuide';

export const meta: Route.MetaFunction = ({data}) => {
  return [{title: `Mock Apparel | ${data?.page?.title ?? 'Information'}`}];
};

export async function loader(args: Route.LoaderArgs) {
  const criticalData = await loadCriticalData(args);
  return criticalData;
}

async function loadCriticalData({context, request, params}: Route.LoaderArgs) {
  if (!params.handle) {
    throw new Response('Missing page handle', {status: 404});
  }

  const result = await context.storefront
    .query(PAGE_QUERY, {
      variables: {handle: params.handle},
    })
    .catch(() => ({page: null}));

  const page = result?.page ?? null;

  if (page) {
    redirectIfHandleIsLocalized(request, {handle: params.handle, data: page});
  } else if (!KNOWN_HANDLES.has(params.handle)) {
    throw new Response('Page not found', {status: 404});
  }

  return {
    page,
    handle: params.handle,
  };
}

export default function Page() {
  const {page, handle} = useLoaderData<typeof loader>();

  const title = page?.title ?? defaultTitleForHandle(handle);

  return (
    <div className="info-page">
      <InfoPageHero title={title} />
      <div className="info-page-body">{renderHandle(handle, page?.body)}</div>
    </div>
  );
}

function InfoPageHero({title}: {title: string}) {
  return (
    <header className="info-page-hero">
      <div className="info-page-hero-inner">
        <h1 className="info-page-title">{title}</h1>
      </div>
    </header>
  );
}

function renderHandle(handle: string, body?: string | null) {
  switch (handle) {
    case 'about':
      return <AboutPage />;
    case 'contact':
    case 'email-us':
      return <ContactPage />;
    case 'faq':
    case 'help':
      return <FAQPage />;
    case 'shipping':
      return <ShippingPage />;
    case 'returns':
      return <ReturnsPage />;
    case 'size-guide':
      return <SizeGuidePage />;
    case 'warranty':
      return <WarrantyPage />;
    case 'sustainability':
      return <SustainabilityPage />;
    case 'gift-cards':
      return <GiftCardsPage />;
    case 'track-my-order':
      return <TrackOrderPage />;
    case 'gift-card-balance':
      return <GiftCardBalancePage />;
    case 'rewards':
    case 'loyalty-programme':
      return <LoyaltyPage />;
    case 'careers':
    case 'wellness-club':
    case 'stores':
    case 'guarantee':
    case 'cookie-policy':
      return <GenericInfoPage handle={handle} body={body} />;
    default:
      return <GenericInfoPage handle={handle} body={body} />;
  }
}

const KNOWN_HANDLES = new Set([
  'about',
  'contact',
  'email-us',
  'faq',
  'help',
  'shipping',
  'returns',
  'size-guide',
  'warranty',
  'sustainability',
  'gift-cards',
  'track-my-order',
  'gift-card-balance',
  'rewards',
  'loyalty-programme',
  'careers',
  'wellness-club',
  'stores',
  'guarantee',
  'cookie-policy',
]);

function defaultTitleForHandle(handle: string) {
  const titles: Record<string, string> = {
    about: 'Our Story',
    contact: 'Contact Us',
    'email-us': 'Email Us',
    faq: 'Help Centre',
    help: 'Help Centre',
    shipping: 'Shipping & Delivery',
    returns: 'Returns & Exchanges',
    'size-guide': 'Size Guide',
    warranty: 'Quality Warranty',
    sustainability: 'Sustainability',
    'gift-cards': 'Gift Cards',
    'track-my-order': 'Track My Order',
    'gift-card-balance': 'Check Gift Card Balance',
    rewards: 'Rewards Programme',
    'loyalty-programme': 'Loyalty Programme',
    careers: 'Careers',
    'wellness-club': 'Wellness Club',
    stores: 'Stores & Studios',
    guarantee: 'Happiness Guarantee',
    'cookie-policy': 'Cookie Policy',
  };
  if (titles[handle]) return titles[handle];
  return handle
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

/* ---------- About / Our Story ---------- */
function AboutPage() {
  const values = [
    {
      title: 'Quality Promise',
      body: 'Every piece is finished by hand and tested against our wear-and-tear standards before it leaves our atelier — so each Mock Apparel item is built to be loved daily, not seasonally.',
    },
    {
      title: 'Thoughtful Materials',
      body: 'We work with OEKO-TEX certified mills and recycled metals where possible, choosing materials that age gracefully and feel as good as they look.',
    },
    {
      title: 'Community First',
      body: 'A portion of every collection helps fund our Wellness Club programme, supporting local studios and well-being workshops in the cities we call home.',
    },
    {
      title: 'Wear It Daily',
      body: 'Beauty without occasion. Our designs are quiet, durable, and made for everyday wear — meaningful enough to gift, considered enough to keep.',
    },
  ];

  return (
    <article className="about-page info-page-content">
      <section className="about-narrative">
        <p className="about-lede">
          Crafted with intention. Worn with meaning. Mock Apparel began as a small
          studio with a clear belief — that the most personal objects we own
          deserve to be made with the most care.
        </p>
        <p>
          What began as a side project has grown into a global community of
          makers, customers, and friends. We started with a simple problem to
          solve: most lifestyle accessories were either disposable or
          intimidating. We wanted to make pieces that sat between — heirloom
          quality, but quietly modern; thoughtfully personal, but never fussy.
        </p>
        <blockquote className="about-pullquote">
          “Every piece in this collection has been worn, tested, washed,
          re-shaped, and worn again before it shipped. That&apos;s the bar.
          That&apos;s the promise.”
          <footer>— A note from our founding team</footer>
        </blockquote>
        <p>
          Today, the Mock Apparel studio designs everything in-house. Our craft
          principles have stayed the same since the first prototype: choose
          materials we&apos;d wear ourselves, work with manufacturing partners
          we&apos;d gladly visit, and write the kind of warranty we&apos;d
          want behind any object we love.
        </p>
        <blockquote className="about-pullquote">
          “We don&apos;t chase trends. We design for the way a piece will look
          on the third year you own it, not the third week.”
          <footer>— Head of Craft, Mock Apparel Studio</footer>
        </blockquote>
      </section>

      <section className="about-values">
        <h2 className="about-section-heading">What we believe</h2>
        <div className="about-values-grid">
          {values.map((value) => (
            <div key={value.title} className="about-value-card">
              <h3 className="about-value-title">{value.title}</h3>
              <p className="about-value-body">{value.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="about-mission">
        <div className="about-mission-col">
          <h2 className="about-section-heading">Our product philosophy</h2>
          <p>
            We start with a need, not a category. A bracelet that sits flat
            under a watch. A daily watch that doesn&apos;t need babying. A
            sweatshirt with a drape thoughtful enough to wear out. Form, fit,
            and finish are equally non-negotiable.
          </p>
        </div>
        <div className="about-mission-col">
          <h2 className="about-section-heading">Our wider commitments</h2>
          <p>
            Beyond product, we invest in the communities our work touches —
            from independent studios that host our Wellness Club to the
            artisans who hand-finish our personalised pieces. The work we do
            sits inside a bigger picture, and we try to act like it.
          </p>
        </div>
      </section>

      <section className="about-responsibility">
        <div className="about-responsibility-banner" aria-hidden="true">
          <div className="about-responsibility-banner-inner">
            Made responsibly. Worn forever.
          </div>
        </div>
        <h2 className="about-section-heading">Responsibility</h2>
        <div className="about-responsibility-block">
          <h3>Ethical sourcing</h3>
          <p>
            We trace our raw materials back to source. Our metals are recycled
            where possible; our cottons are organic and OEKO-TEX certified;
            our packaging is FSC-certified and recyclable.
          </p>
          <ul className="about-responsibility-list">
            <li>Recycled silver and gold-vermeil core ranges</li>
            <li>OEKO-TEX 100 certified textile mills</li>
            <li>FSC-certified, plastic-free shipping packaging</li>
          </ul>
        </div>
        <div className="about-responsibility-block">
          <h3>Manufacturing standards</h3>
          <p>
            Our partners audit annually against the SMETA framework. We visit
            every manufacturing partner at least twice a year. Anything we
            wouldn&apos;t want for ourselves doesn&apos;t leave the studio.
          </p>
        </div>
        <div className="about-responsibility-block">
          <h3>Workplace commitments</h3>
          <p>
            Living wage, paid family leave, and structured learning budgets
            for every Mock Apparel employee. Read our Workplace Standards
            commitment for the full breakdown.
          </p>
          <a
            href="/pages/sustainability"
            className="about-responsibility-doc"
          >
            Workplace Standards (PDF)
          </a>
        </div>
      </section>

      <section className="about-cta">
        <Link to="/collections/explore-everything" className="info-page-button">
          Meet the Collection
        </Link>
        <Link to="/pages/contact" className="info-page-textlink">
          Or get in touch →
        </Link>
      </section>
    </article>
  );
}

/* ---------- Contact ---------- */
function ContactPage() {
  const channels = [
    {
      title: 'Live Chat',
      detail: 'Available 24 / 7',
      action: 'Open chat',
      href: '#chat',
    },
    {
      title: 'Email',
      detail: 'contact@mock-shop.example — replies within 24 hours',
      action: 'Email the team',
      href: 'mailto:contact@mock-shop.example',
    },
    {
      title: 'Phone',
      detail: 'Mon–Fri 9am–7pm · Sat–Sun 10am–4pm (GMT)',
      action: '+1-555-0100',
      href: 'tel:+15550100',
    },
    {
      title: 'Collaboration & Trade',
      detail: 'Partnership, press and wholesale enquiries',
      action: 'contact@mock-shop.example',
      href: 'mailto:contact@mock-shop.example',
    },
  ];

  return (
    <article className="contact-page info-page-content">
      <div className="contact-holiday-banner" role="note">
        <strong>Holiday update:</strong> Response times are slightly extended
        through the gifting season. Live chat remains the fastest channel.
      </div>

      <p className="info-page-lede">
        Hello, we&apos;re here to help. Pick the fastest channel for your
        question — or send us a message below and we&apos;ll respond within
        one business day.
      </p>

      <div className="contact-channels-grid">
        {channels.map((channel) => (
          <div key={channel.title} className="contact-channel-card">
            <h2 className="contact-channel-title">{channel.title}</h2>
            <p className="contact-channel-detail">{channel.detail}</p>
            <a href={channel.href} className="contact-channel-action">
              {channel.action} →
            </a>
          </div>
        ))}
      </div>

      <div className="contact-returns-callout" role="note">
        <strong>Already started a return?</strong> Email{' '}
        <a href="mailto:contact@mock-shop.example">
          contact@mock-shop.example
        </a>{' '}
        with your order number for the fastest update.
      </div>

      <ContactForm />
    </article>
  );
}

/* ---------- FAQ Hub ---------- */
function FAQPage() {
  const topicCards = [
    {label: 'Returns & Exchanges', href: '/pages/returns', icon: '↺'},
    {label: 'Orders & Shipping', href: '/pages/shipping', icon: '✈'},
    {label: 'Discounts & Promotions', href: '/policies/terms-of-service', icon: '%'},
    {label: 'Payments & Gift Cards', href: '/pages/gift-cards', icon: '◊'},
    {label: 'Loyalty Programme', href: '/pages/rewards', icon: '★'},
    {label: 'Size Guide', href: '/pages/size-guide', icon: '⊟'},
    {label: 'Sustainability', href: '/pages/sustainability', icon: '✿'},
    {label: 'Store Locations', href: '/pages/stores', icon: '⌖'},
  ];

  const faqs: FAQItem[] = [
    {
      id: 'track',
      question: 'How do I track my order?',
      answer: (
        <p>
          Once your order ships you&apos;ll receive a tracking link by email.
          You can also visit{' '}
          <Link to="/pages/track-my-order">Track My Order</Link> at any time
          and enter your order number plus email.
        </p>
      ),
    },
    {
      id: 'edit',
      question: 'Can I edit or cancel an order?',
      answer: (
        <p>
          Orders can be edited or cancelled within 30 minutes of placement.
          After that the order enters fulfilment and we&apos;re unable to make
          changes — but unwanted items can be returned for free under our
          standard returns policy.
        </p>
      ),
    },
    {
      id: 'window',
      question: 'What is your return window?',
      answer: (
        <p>
          12 months for non-personalised items, 30 days for personalised
          items. Gifts can be returned for store credit within 12 months of
          purchase. See <Link to="/pages/returns">Returns & Exchanges</Link>{' '}
          for the full policy.
        </p>
      ),
    },
    {
      id: 'free-returns',
      question: 'Do you offer free returns?',
      answer: (
        <p>
          Yes — domestic returns are free of charge. International returns
          carry a small handling fee that is deducted from the refund.
        </p>
      ),
    },
    {
      id: 'discount',
      question: 'How do discount codes work?',
      answer: (
        <p>
          Apply your code at checkout in the &ldquo;Discount Code&rdquo;
          field. Only one promotional code can be applied per order, and
          codes can&apos;t be combined with student or first-order offers.
        </p>
      ),
    },
    {
      id: 'payments',
      question: 'What payment methods do you accept?',
      answer: (
        <p>
          Visa, Mastercard, American Express, Apple Pay, Google Pay, PayPal,
          and Mock Apparel Gift Cards. Klarna is available on orders over $50 in
          select markets.
        </p>
      ),
    },
    {
      id: 'loyalty',
      question: 'How does the loyalty programme work?',
      answer: (
        <p>
          Earn 1 point for every dollar spent, plus bonus points on birthdays
          and friend referrals. Redeem points for credit, early access, and
          tier-exclusive gifts. See{' '}
          <Link to="/pages/rewards">Rewards Programme</Link> for full tier
          details.
        </p>
      ),
    },
    {
      id: 'gift-return',
      question: 'Can I return a gift?',
      answer: (
        <p>
          Absolutely. Gift returns are issued as store credit, valid for 12
          months from the date of return. Bring your order number or gift
          receipt to start the process.
        </p>
      ),
    },
  ];

  return (
    <article className="faq-page info-page-content">
      <p className="info-page-lede">
        Find answers to your questions. Most issues can be resolved in a few
        clicks below — and our care team is always one message away.
      </p>

      <div className="faq-quick-actions">
        <Link to="/pages/returns" className="faq-quick-button">
          Start a Return
        </Link>
        <Link to="/pages/track-my-order" className="faq-quick-button">
          Track My Order
        </Link>
        <Link to="/pages/contact" className="faq-quick-button">
          Contact Us
        </Link>
      </div>

      <h2 className="info-page-section-heading">Browse by topic</h2>
      <div className="faq-topic-grid">
        {topicCards.map((topic) => (
          <Link
            key={topic.label}
            to={topic.href}
            className="faq-topic-card"
          >
            <span className="faq-topic-icon" aria-hidden="true">
              {topic.icon}
            </span>
            <span className="faq-topic-label">{topic.label}</span>
            <span className="faq-topic-arrow" aria-hidden="true">
              →
            </span>
          </Link>
        ))}
      </div>

      <h2 className="info-page-section-heading">Frequently asked</h2>
      <FAQAccordion items={faqs} idPrefix="faq" />

      <ContactBlock />
    </article>
  );
}

/* ---------- Shipping ---------- */
function ShippingPage() {
  const [tab, setTab] = useState<'domestic' | 'international'>('domestic');

  const domesticRows = [
    {
      method: 'Standard',
      eta: '3–5 business days',
      cost: 'Free over $75 / $6 flat',
      notes: 'Tracked',
    },
    {
      method: 'Express',
      eta: '1–2 business days',
      cost: '$12 flat',
      notes: 'Tracked',
    },
    {
      method: 'Next Working Day',
      eta: '1 business day',
      cost: '$18 flat',
      notes: 'Order by 2pm GMT',
    },
  ];

  const internationalRegions = [
    {
      heading: 'Europe',
      rows: [
        {method: 'Standard Tracked', eta: '5–8 business days', cost: '$12 flat', notes: 'Tracked'},
        {method: 'Express', eta: '2–3 business days', cost: '$28 flat', notes: 'Tracked'},
      ],
    },
    {
      heading: 'North America',
      rows: [
        {method: 'Standard Tracked', eta: '7–10 business days', cost: '$18 flat', notes: 'Tracked'},
        {method: 'Express', eta: '3–5 business days', cost: '$36 flat', notes: 'Tracked'},
      ],
    },
    {
      heading: 'Australia & New Zealand',
      rows: [
        {method: 'Standard Tracked', eta: '8–12 business days', cost: '$22 flat', notes: 'Tracked'},
        {method: 'Express', eta: '4–6 business days', cost: '$42 flat', notes: 'Tracked'},
      ],
    },
    {
      heading: 'Rest of World',
      rows: [
        {method: 'Standard Tracked', eta: '10–14 business days', cost: '$26 flat', notes: 'Tracked'},
      ],
    },
  ];

  const shippingFAQs: FAQItem[] = [
    {
      id: 's1',
      question: 'When will I receive my tracking email?',
      answer: (
        <p>
          Tracking emails are sent the moment your order is dispatched —
          typically within 24 hours of placement on business days.
        </p>
      ),
    },
    {
      id: 's2',
      question: 'Can I change my address after placing an order?',
      answer: (
        <p>
          Address changes can be made within 30 minutes of placement via the
          confirmation email. After dispatch, the carrier may be able to
          redirect — contact us with your tracking number for help.
        </p>
      ),
    },
    {
      id: 's3',
      question: 'What if my parcel is refused or returned to sender?',
      answer: (
        <p>
          Refused or unclaimed parcels are returned to our warehouse and
          refunded (less return shipping cost) once received.
        </p>
      ),
    },
    {
      id: 's4',
      question: 'Do you offer pick-up in store?',
      answer: (
        <p>
          Yes, in select cities. Choose &ldquo;Collect In-Store&rdquo; at
          checkout to see your nearest available studio.
        </p>
      ),
    },
    {
      id: 's5',
      question: 'Will I have to sign for delivery?',
      answer: (
        <p>
          Express and Next-Day deliveries require a signature. Standard
          deliveries are left in a safe place where instructed.
        </p>
      ),
    },
    {
      id: 's6',
      question: 'What about customs and duties on international orders?',
      answer: (
        <p>
          For deliveries outside our domestic market, the carrier may collect
          customs duties or local sales tax on arrival. These charges are the
          recipient&apos;s responsibility.
        </p>
      ),
    },
    {
      id: 's7',
      question: 'When is the order cut-off for next-day delivery?',
      answer: (
        <p>
          2pm GMT, Monday to Friday. Orders placed after that ship the next
          business day.
        </p>
      ),
    },
  ];

  return (
    <article className="shipping-page info-page-content">
      <div className="info-page-banner-callout">
        Free standard shipping on all orders over $75.
      </div>

      <div className="info-page-tabs" role="tablist">
        {([
          {key: 'domestic', label: 'Domestic'},
          {key: 'international', label: 'International'},
        ] as const).map((option) => (
          <button
            key={option.key}
            type="button"
            role="tab"
            aria-selected={tab === option.key}
            className={`info-page-tab${tab === option.key ? ' is-active' : ''}`}
            onClick={() => setTab(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {tab === 'domestic' ? (
        <ShippingTable
          heading="Domestic — United States"
          rows={domesticRows}
        />
      ) : (
        internationalRegions.map((region) => (
          <ShippingTable
            key={region.heading}
            heading={region.heading}
            rows={region.rows}
          />
        ))
      )}

      <blockquote className="info-page-note-block">
        <p>
          You&apos;ll receive a tracking email the moment your order ships.
          Express and Next-Day parcels require a signature on delivery.
          International orders may attract customs duties or local sales tax,
          which are the recipient&apos;s responsibility. The order cut-off
          for same-day dispatch is 2pm GMT, Monday to Friday.
        </p>
      </blockquote>

      <h2 className="info-page-section-heading">Shipping FAQs</h2>
      <FAQAccordion items={shippingFAQs} idPrefix="shipping" />

      <div className="info-page-inline-callout">
        Need to send something back? See our{' '}
        <Link to="/pages/returns">Returns & Exchanges</Link> page for the
        full process.
      </div>

      <RelatedTopicCards
        topics={[
          {label: 'Returns', href: '/pages/returns'},
          {label: 'Payments', href: '/pages/gift-cards'},
          {label: 'Discounts', href: '/policies/terms-of-service'},
          {label: 'Size Guide', href: '/pages/size-guide'},
          {label: 'Contact', href: '/pages/contact'},
        ]}
      />
    </article>
  );
}

function ShippingTable({
  heading,
  rows,
}: {
  heading: string;
  rows: {method: string; eta: string; cost: string; notes: string}[];
}) {
  return (
    <section className="shipping-table-block">
      <h3 className="shipping-table-heading">{heading}</h3>
      <div className="info-page-table-scroll">
        <table className="info-page-table">
          <thead>
            <tr>
              <th scope="col">Shipping Method</th>
              <th scope="col">Estimated Delivery</th>
              <th scope="col">Cost</th>
              <th scope="col">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.method}>
                <th scope="row">{row.method}</th>
                <td>{row.eta}</td>
                <td>{row.cost}</td>
                <td>{row.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ---------- Returns ---------- */
function ReturnsPage() {
  const [tab, setTab] = useState<'domestic' | 'international'>('domestic');

  const steps = [
    'Repackage the item(s) securely in original or equivalent packaging.',
    'Submit your return request via our portal or by emailing contact@mock-shop.example.',
    'Print and attach the prepaid label, or use the QR code at the post office.',
    'Drop off at any participating post office or collection point.',
  ];

  const items: FAQItem[] = [
    {
      id: 'r1',
      question: 'Return Policy',
      answer: (
        <>
          <p>
            Non-personalised items can be returned within 12 months of
            purchase. Personalised pieces have a 30-day exchange window.
            Items must be unworn, in their original packaging, and free of
            damage.
          </p>
          <p>
            <strong>Exclusions:</strong> Earrings (for hygiene), opened
            advent-style gift sets, and personalised items beyond the 30-day
            exchange window cannot be returned for refund.
          </p>
        </>
      ),
    },
    {
      id: 'r2',
      question: 'Free Returns?',
      answer: (
        <p>
          Domestic returns are free with our prepaid label. International
          returns carry a $12 handling fee, which is deducted from the
          refund.
        </p>
      ),
    },
    {
      id: 'r3',
      question: 'How to mail back an online return',
      answer: (
        <ol className="info-page-numbered-list">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ),
    },
    {
      id: 'r4',
      question: 'Exchange Process',
      answer: (
        <p>
          Choose between an exchange (same item, different size or colour)
          or a refund to your original payment method when you start the
          return. Exchanges ship as soon as your original package is on the
          way back to us.
        </p>
      ),
    },
    {
      id: 'r5',
      question: 'Faulty or Damaged Items',
      answer: (
        <p>
          We&apos;re sorry — please contact{' '}
          <a href="mailto:contact@mock-shop.example">
            contact@mock-shop.example
          </a>{' '}
          with your order number and a clear photo of the issue. We&apos;ll
          arrange a free replacement or refund within 48 hours.
        </p>
      ),
    },
    {
      id: 'r6',
      question: 'Buy Online, Return In-Store',
      answer: (
        <p>
          You can return online orders to any Mock Apparel studio in the United
          States, United Kingdom, or European Union. Bring your packing slip
          and the original payment method.
        </p>
      ),
    },
    {
      id: 'r7',
      question: 'Returning a Gift',
      answer: (
        <p>
          Gift returns are issued as store credit, valid for 12 months from
          the date of return — no need to involve the original purchaser.
          Bring your gift receipt or order number to start the process.
        </p>
      ),
    },
    {
      id: 'r8',
      question: 'What counts as a "personalised" item?',
      answer: (
        <p>
          Anything engraved, hand-stamped, custom-monogrammed, or made to a
          specific colour or size combination outside our standard range.
          The personalisation will be flagged on the product page before you
          add to bag.
        </p>
      ),
    },
  ];

  return (
    <article className="returns-page info-page-content">
      <p className="info-page-lede">
        We want you to love every Mock Apparel piece. If something isn&apos;t
        right, we&apos;ll make it right — refund, exchange, or repair, with
        no fuss.
      </p>

      <div className="returns-cta-row">
        <a href="#start-return" className="info-page-button">
          Start a Return or Exchange
        </a>
        <span className="returns-processing-note">
          Refunds processed within 5 working days of receipt.
        </span>
      </div>

      <div className="info-page-tabs" role="tablist">
        {([
          {key: 'domestic', label: 'Domestic'},
          {key: 'international', label: 'International'},
        ] as const).map((option) => (
          <button
            key={option.key}
            type="button"
            role="tab"
            aria-selected={tab === option.key}
            className={`info-page-tab${tab === option.key ? ' is-active' : ''}`}
            onClick={() => setTab(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <h2 className="info-page-section-heading">Return process</h2>
      <ol className="returns-steps">
        {steps.map((step, idx) => (
          <li key={step} className="returns-step">
            <span className="returns-step-number">{idx + 1}</span>
            <span className="returns-step-body">{step}</span>
          </li>
        ))}
      </ol>

      {tab === 'international' ? (
        <div className="info-page-inline-callout">
          International returns carry a $12 handling fee deducted from your
          refund. Customs paperwork is included with your prepaid label.
        </div>
      ) : null}

      <h2 className="info-page-section-heading">Returns details</h2>
      <FAQAccordion items={items} idPrefix="returns" />

      <RelatedTopicCards
        topics={[
          {label: 'Shipping', href: '/pages/shipping'},
          {label: 'Warranty', href: '/pages/warranty'},
          {label: 'Size Guide', href: '/pages/size-guide'},
          {label: 'Contact', href: '/pages/contact'},
          {label: 'Loyalty', href: '/pages/rewards'},
        ]}
      />
      <ContactBlock />
    </article>
  );
}

/* ---------- Size Guide ---------- */
function SizeGuidePage() {
  return (
    <article className="size-guide-page info-page-content">
      <p className="info-page-lede">
        Find your fit. All measurements are taken with the body relaxed —
        for the closest fit, measure over light clothing and refer to the
        ranges below.
      </p>
      <SizeGuide />
    </article>
  );
}

/* ---------- Warranty ---------- */
function WarrantyPage() {
  const items: FAQItem[] = [
    {
      id: 'w1',
      question: 'What the warranty covers',
      answer: (
        <p>
          Manufacturing defects in materials and workmanship — broken
          clasps, loose stones, premature plating wear, faulty stitching,
          and component failures under normal use.
        </p>
      ),
    },
    {
      id: 'w2',
      question: 'What is not covered',
      answer: (
        <p>
          Cosmetic wear from daily use, accidental damage, scratches,
          dents, lost items, and damage caused by exposure to chemicals,
          chlorine, perfumes, or extreme heat.
        </p>
      ),
    },
    {
      id: 'w3',
      question: 'How to make a warranty claim',
      answer: (
        <p>
          Contact{' '}
          <a href="mailto:contact@mock-shop.example">
            contact@mock-shop.example
          </a>{' '}
          with your order number and clear photographs of the issue. Our
          care team will respond within 48 hours with next steps — repair,
          replace, or store credit.
        </p>
      ),
    },
    {
      id: 'w4',
      question: 'Warranty for personalised items',
      answer: (
        <p>
          Personalised pieces are covered by the same 5-year guarantee on
          materials and workmanship. Engraving, hand-stamping, and
          monogramming are individually inspected before dispatch and
          covered against fading or detachment.
        </p>
      ),
    },
    {
      id: 'w5',
      question: 'Warranty for gifts',
      answer: (
        <p>
          The recipient is the warranty holder once a gift is received.
          Forward the order number from your gift receipt to the recipient,
          or contact us — we&apos;ll happily transfer the warranty record.
        </p>
      ),
    },
  ];

  return (
    <article className="warranty-page info-page-content">
      <div className="warranty-promise">
        <h2 className="warranty-promise-headline">
          Every Mock Apparel piece is covered by our 5-year quality warranty.
        </h2>
        <p className="warranty-promise-sub">
          We stand behind the craft, materials, and finish of every piece
          we make — for half a decade, with no fine print.
        </p>
      </div>
      <FAQAccordion items={items} idPrefix="warranty" />
    </article>
  );
}

/* ---------- Sustainability (generic but rich) ---------- */
function SustainabilityPage() {
  return (
    <article className="info-page-content">
      <p className="info-page-lede">
        We&apos;re building Mock Apparel to last. That means choosing materials
        that age gracefully, partnering with manufacturing teams we visit
        regularly, and writing the kind of warranty we&apos;d want behind
        any object we love.
      </p>
      <h2 className="info-page-section-heading">Materials</h2>
      <p>
        Recycled silver and gold-vermeil core ranges, OEKO-TEX 100 certified
        textile mills, and FSC-certified, plastic-free shipping packaging.
        We trace our raw materials back to source.
      </p>
      <h2 className="info-page-section-heading">Manufacturing</h2>
      <p>
        Our partners audit annually against the SMETA framework. We visit
        every manufacturing partner at least twice a year. Anything we
        wouldn&apos;t want for ourselves doesn&apos;t leave the studio.
      </p>
      <h2 className="info-page-section-heading">Workplace</h2>
      <p>
        Living wage, paid family leave, and structured learning budgets for
        every Mock Apparel employee. Read our Workplace Standards commitment for
        the full breakdown.
      </p>
      <ContactBlock />
    </article>
  );
}

/* ---------- Gift Cards ---------- */
function GiftCardsPage() {
  return (
    <article className="info-page-content gift-cards-page">
      <p className="info-page-lede">
        The thoughtful gift, every time. Mock Apparel gift cards never expire and
        can be used on any product across our store.
      </p>
      <div className="gift-cards-grid">
        <div className="gift-card-tile">
          <div className="gift-card-tile-art">
            <span className="gift-card-tile-mark">MOCK APPAREL</span>
            <span className="gift-card-tile-line">e-Gift Card</span>
          </div>
          <h2 className="gift-card-tile-title">E-Gift Card</h2>
          <p className="gift-card-tile-price">$25 — $500</p>
          <p className="gift-card-tile-detail">
            Delivered by email, instantly or scheduled for a future date.
            Personalise with a hand-written message.
          </p>
          <a href="/products/aislearena-physical-gift-card" className="info-page-button">
            Buy Now
          </a>
        </div>
        <div className="gift-card-tile">
          <div className="gift-card-tile-art gift-card-tile-art-physical">
            <span className="gift-card-tile-mark">MOCK APPAREL</span>
            <span className="gift-card-tile-line">Physical Card</span>
          </div>
          <h2 className="gift-card-tile-title">Physical Gift Card</h2>
          <p className="gift-card-tile-price">$50 — $500</p>
          <p className="gift-card-tile-detail">
            Posted in a signature gift envelope with a hand-finished card.
            Free standard shipping included.
          </p>
          <a href="/products/aislearena-physical-gift-card" className="info-page-button">
            Add to Bag
          </a>
        </div>
      </div>
      <div className="info-page-inline-callout">
        Already have a card?{' '}
        <Link to="/pages/gift-card-balance">Check your balance</Link>.
      </div>
    </article>
  );
}

/* ---------- Track Order ---------- */
function TrackOrderPage() {
  const [orderNumber, setOrderNumber] = useState('');
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  return (
    <article className="info-page-content">
      <p className="info-page-lede">
        Enter your order number and email to view your order status. You can
        also find a tracking link in your shipping confirmation email.
      </p>
      <form
        className="contact-form simple-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (orderNumber.trim() && email.trim()) {
            setSubmitted(true);
          }
        }}
      >
        <div className="contact-form-grid">
          <div className="contact-form-row">
            <label className="contact-form-label" htmlFor="track-order-num">
              Order Number
            </label>
            <input
              id="track-order-num"
              className="contact-form-input"
              type="text"
              placeholder="e.g. MA-104382"
              value={orderNumber}
              onChange={(e) => setOrderNumber(e.target.value)}
              required
            />
          </div>
          <div className="contact-form-row">
            <label className="contact-form-label" htmlFor="track-order-email">
              Email Address
            </label>
            <input
              id="track-order-email"
              className="contact-form-input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="contact-form-row contact-form-row-full">
            <button type="submit" className="contact-form-submit">
              Look up Order
            </button>
          </div>
        </div>
      </form>
      {submitted ? (
        <div className="contact-form-success">
          <p>
            We&apos;ve sent the latest tracking details to <strong>{email}</strong>.
          </p>
        </div>
      ) : null}
    </article>
  );
}

/* ---------- Gift Card Balance ---------- */
function GiftCardBalancePage() {
  const [code, setCode] = useState('');
  const [balance, setBalance] = useState<string | null>(null);

  return (
    <article className="info-page-content">
      <p className="info-page-lede">
        Enter your gift card code below to view its remaining balance.
      </p>
      <form
        className="contact-form simple-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (code.trim()) {
            setBalance('$78.50 remaining');
          }
        }}
      >
        <div className="contact-form-grid">
          <div className="contact-form-row contact-form-row-full">
            <label className="contact-form-label" htmlFor="gc-code">
              Gift Card Code
            </label>
            <input
              id="gc-code"
              className="contact-form-input"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              required
            />
          </div>
          <div className="contact-form-row contact-form-row-full">
            <button type="submit" className="contact-form-submit">
              Check Balance
            </button>
          </div>
        </div>
      </form>
      {balance ? (
        <div className="contact-form-success">
          <p>{balance}</p>
        </div>
      ) : null}
    </article>
  );
}

/* ---------- Loyalty ---------- */
function LoyaltyPage() {
  const tiers = [
    {
      name: 'Friend',
      threshold: '0 — 499 points',
      perks: [
        'Birthday gift each year',
        'Welcome offer on first order',
        'Member-only events',
      ],
    },
    {
      name: 'Insider',
      threshold: '500 — 1,499 points',
      perks: [
        'Free express shipping',
        'Early access to new collections',
        'Surprise seasonal gift',
      ],
    },
    {
      name: 'Atelier',
      threshold: '1,500+ points',
      perks: [
        'Complimentary engraving on every order',
        'Personal styling appointments',
        'First-look access to limited editions',
      ],
    },
  ];
  return (
    <article className="info-page-content">
      <p className="info-page-lede">
        Earn 1 point for every dollar spent and unlock perks across three
        tiers. Points never expire while your account is active.
      </p>
      <div className="loyalty-grid">
        {tiers.map((tier) => (
          <div key={tier.name} className="loyalty-card">
            <h3 className="loyalty-card-name">{tier.name}</h3>
            <p className="loyalty-card-threshold">{tier.threshold}</p>
            <ul className="loyalty-card-perks">
              {tier.perks.map((perk) => (
                <li key={perk}>{perk}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <ContactBlock />
    </article>
  );
}

/* ---------- Generic fallback ---------- */
function GenericInfoPage({
  handle,
  body,
}: {
  handle: string;
  body?: string | null;
}) {
  if (body && body.trim().length > 0) {
    return (
      <article className="info-page-content">
        <div
          className="info-page-prose"
          dangerouslySetInnerHTML={{__html: body}}
        />
        <ContactBlock />
      </article>
    );
  }
  return (
    <article className="info-page-content">
      <p className="info-page-lede">
        We&apos;re polishing this page. In the meantime, our care team can
        answer any question — pop us a message any time.
      </p>
      <p className="info-page-prose">
        For information related to <strong>{defaultTitleForHandle(handle)}</strong>,
        please <Link to="/pages/contact">contact us</Link> directly. We
        appreciate your patience.
      </p>
      <ContactBlock />
    </article>
  );
}

/* ---------- Shared subcomponents ---------- */
function ContactBlock() {
  const channels = [
    {label: 'Live Chat', detail: '24 / 7', href: '#chat'},
    {label: 'Email', detail: 'contact@mock-shop.example', href: 'mailto:contact@mock-shop.example'},
    {label: 'Phone', detail: 'Mon–Sun', href: 'tel:+15550100'},
    {label: 'Trade', detail: 'contact@mock-shop.example', href: 'mailto:contact@mock-shop.example'},
  ];
  return (
    <section className="info-page-contact-block">
      <h2 className="info-page-section-heading">Still need help?</h2>
      <div className="info-page-contact-grid">
        {channels.map((c) => (
          <a key={c.label} href={c.href} className="info-page-contact-pill">
            <span className="info-page-contact-pill-label">{c.label}</span>
            <span className="info-page-contact-pill-detail">{c.detail}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

function RelatedTopicCards({
  topics,
}: {
  topics: {label: string; href: string}[];
}) {
  return (
    <section className="info-page-related">
      <h2 className="info-page-section-heading">Related topics</h2>
      <div className="info-page-related-grid">
        {topics.map((topic) => (
          <Link key={topic.label} to={topic.href} className="info-page-related-card">
            <span>{topic.label}</span>
            <span aria-hidden="true">→</span>
          </Link>
        ))}
      </div>
    </section>
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
