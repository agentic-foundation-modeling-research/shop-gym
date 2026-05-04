import {Link, useLoaderData} from 'react-router';
import {useState, type FormEvent} from 'react';
import type {Route} from './+types/pages.$handle';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {FAQAccordion, type FAQItem} from '~/components/FAQAccordion';

export const meta: Route.MetaFunction = ({data}) => {
  return [{title: `Mock Cookware | ${data?.page.title ?? ''}`}];
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

  return {page};
}

function loadDeferredData(_args: Route.LoaderArgs) {
  return {};
}

export default function Page() {
  const {page} = useLoaderData<typeof loader>();

  if (page.handle === 'about') return <AboutPage />;
  if (page.handle === 'contact') return <ContactPage />;
  if (page.handle === 'faq') return <FAQPage />;
  if (page.handle === 'size-guide') return <SizeGuidePage title={page.title} />;

  return <GenericInfoPage title={page.title} body={page.body} />;
}

function GenericInfoPage({title, body}: {title: string; body: string}) {
  return (
    <article className="info-page">
      <div className="info-page-container">
        <header className="info-page-header">
          <h1 className="info-page-title">{title}</h1>
        </header>
        <div
          className="info-page-body"
          dangerouslySetInnerHTML={{__html: body}}
        />
      </div>
    </article>
  );
}

function AboutPage() {
  return (
    <article className="about-page">
      <section className="about-hero">
        <div className="about-hero-container">
          <h1 className="about-hero-title">A kitchen built for the people who cook in it.</h1>
          <figure className="about-hero-quote">
            <blockquote>
              “These pans react fast, brown evenly, and never warp. They’re
              the cookware I reach for when I’m cooking for my own family.”
            </blockquote>
            <figcaption>— A working chef</figcaption>
          </figure>
          <p className="about-hero-mission">
            We build heirloom-grade cookware, knives, and bakeware that perform
            in professional kitchens and last for decades in your own.
          </p>
        </div>
      </section>

      <section className="about-story">
        <div className="about-story-container">
          <div className="about-story-copy">
            <p className="about-story-eyebrow">Our story</p>
            <h2 className="about-story-title">Started in a working kitchen</h2>
            <p>
              Mock Cookware began when the team, frustrated by warping pans and
              dull knives, partnered with a small metalworks to forge cookware
              that could survive a Saturday-night service. Word spread chef to
              chef, and within a year we were equipping a growing list of
              restaurants.
            </p>
            <p>
              Today our team of metallurgists, chefs, and product engineers
              tests every new piece through 2,000 dishwasher cycles, induction
              shock cycles, and 18 months of home-cook trials before it ever
              ships. We believe great cookware should be quiet to use, easy to
              clean, and built to outlast the kitchen it lives in.
            </p>
          </div>
          <div className="about-story-photo" aria-hidden="true">
            <CookwareIllustration />
          </div>
        </div>
      </section>

      <section className="about-features">
        <div className="about-features-container">
          <p className="about-features-eyebrow">Built into every piece</p>
          <h2 className="about-features-title">Five things we never compromise on</h2>
          <ol className="about-features-list">
            {ABOUT_FEATURES.map((feature, index) => (
              <li key={feature.title} className="about-feature-row">
                <span className="about-feature-number">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div className="about-feature-text">
                  <h3 className="about-feature-title">{feature.title}</h3>
                  <p className="about-feature-body">{feature.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="about-shop">
        <div className="about-shop-container">
          <p className="about-shop-eyebrow">Shop the kitchen</p>
          <h2 className="about-shop-title">Find your next workhorse</h2>
          <div className="about-shop-grid">
            <Link to="/collections/cookware" className="about-shop-card">
              <span className="about-shop-card-label">Cookware</span>
              <span className="about-shop-card-cta">Shop pans →</span>
            </Link>
            <Link to="/collections/knives" className="about-shop-card">
              <span className="about-shop-card-label">Knives</span>
              <span className="about-shop-card-cta">Shop knives →</span>
            </Link>
            <Link
              to="/collections/kitchen-tools-utensils"
              className="about-shop-card"
            >
              <span className="about-shop-card-label">Accessories</span>
              <span className="about-shop-card-cta">Shop tools →</span>
            </Link>
          </div>
        </div>
      </section>

      <AboutSubscribe />
    </article>
  );
}

const ABOUT_FEATURES: Array<{title: string; body: string}> = [
  {
    title: 'PFOA-free nonstick coating',
    body: 'Five-layer ceramic-reinforced nonstick that releases eggs without oil and survives metal utensils for years.',
  },
  {
    title: 'Even-temperature core',
    body: 'A tri-ply aluminum-magnesium core distributes heat edge to edge so you sear without hot spots.',
  },
  {
    title: 'Dishwasher safe',
    body: 'Tested through 2,000 dishwasher cycles. No hand-washing required, even for the nonstick line.',
  },
  {
    title: 'Oven safe to 600°F',
    body: 'Stainless rivets and forged handles let you sear, finish in the oven, or run under a broiler.',
  },
  {
    title: '25-year warranty',
    body: 'If a piece fails under regular kitchen use, we replace it free for the first 25 years you own it.',
  },
];

function AboutSubscribe() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const honeypot = (
      event.currentTarget.elements.namedItem('website') as HTMLInputElement | null
    )?.value;
    if (honeypot) return;
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setError('Please enter a valid email.');
      return;
    }
    setError(null);
    setSubmitted(true);
  }

  return (
    <section className="about-subscribe" aria-label="Newsletter subscribe">
      <div className="about-subscribe-container">
        <div className="about-subscribe-copy">
          <h2 className="about-subscribe-title">Stay in the kitchen with us</h2>
          <p className="about-subscribe-body">
            Recipes, care guides, and early-access drops. One short email a
            week — unsubscribe anytime.
          </p>
        </div>
        {submitted ? (
          <p className="about-subscribe-success" role="status">
            Thanks — check your inbox to confirm.
          </p>
        ) : (
          <form className="about-subscribe-form" onSubmit={handleSubmit} noValidate>
            <label htmlFor="about-subscribe-email" className="sr-only">
              Email address
            </label>
            <input
              id="about-subscribe-email"
              type="email"
              name="email"
              className="about-subscribe-input"
              placeholder="contact@mock-shop.example"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
            <input
              type="text"
              name="website"
              tabIndex={-1}
              autoComplete="off"
              className="about-subscribe-honeypot"
              aria-hidden="true"
            />
            <button type="submit" className="about-subscribe-submit">
              Subscribe
            </button>
            {error && (
              <p className="about-subscribe-error" role="alert">
                {error}
              </p>
            )}
          </form>
        )}
      </div>
    </section>
  );
}

function ContactPage() {
  return (
    <article className="contact-page">
      <section className="contact-hero">
        <div className="contact-hero-image" aria-hidden="true">
          <CookwareIllustration variant="contact" />
        </div>
        <div className="contact-hero-copy">
          <p className="contact-hero-eyebrow">Customer Care</p>
          <h1 className="contact-hero-title">
            Have a question? We have an answer.
          </h1>
          <p className="contact-hero-body">
            Our care team is staffed by real cooks who use the cookware they
            support. We answer most messages within one business day, and our
            help center has step-by-step guides for every product we make.
          </p>
          <a
            href="#"
            className="contact-hero-cta"
            rel="noreferrer"
          >
            Visit the help center →
          </a>
          <p className="contact-hero-meta">
            Open Monday–Friday, 9am–6pm ET. Closed on US federal holidays.
          </p>
        </div>
      </section>

      <section className="contact-cards">
        <div className="contact-cards-container">
          <Link to="/pages/returns" className="contact-card">
            <span className="contact-card-icon" aria-hidden="true">
              <ContactCardIcon kind="warranty" />
            </span>
            <h3 className="contact-card-title">Lifetime warranty</h3>
            <p className="contact-card-body">
              Every cookware piece carries a 25-year warranty. Start a claim or
              request a replacement in under three minutes.
            </p>
            <span className="contact-card-cta">File a claim →</span>
          </Link>
          <a
            href="#"
            className="contact-card"
            rel="noreferrer"
          >
            <span className="contact-card-icon" aria-hidden="true">
              <ContactCardIcon kind="register" />
            </span>
            <h3 className="contact-card-title">Register your product</h3>
            <p className="contact-card-body">
              Activate your warranty and unlock free care reminders, recipe
              drops, and recipe-tested replacement parts.
            </p>
            <span className="contact-card-cta">Register now →</span>
          </a>
          <a
            href="#"
            className="contact-card"
            rel="noreferrer"
          >
            <span className="contact-card-icon" aria-hidden="true">
              <ContactCardIcon kind="support" />
            </span>
            <h3 className="contact-card-title">24/7 support</h3>
            <p className="contact-card-body">
              Email, chat, and SMS — our care team is available around the
              clock for shipping, billing, and product questions.
            </p>
            <span className="contact-card-cta">Get in touch →</span>
          </a>
        </div>
      </section>
    </article>
  );
}

function ContactCardIcon({kind}: {kind: 'warranty' | 'register' | 'support'}) {
  const common = {
    width: 28,
    height: 28,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  if (kind === 'warranty') {
    return (
      <svg {...common}>
        <path d="M12 3l8 3v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6l8-3z" />
        <path d="M9 12l2.5 2.5L16 10" />
      </svg>
    );
  }
  if (kind === 'register') {
    return (
      <svg {...common}>
        <rect x="4" y="5" width="16" height="14" rx="2" />
        <path d="M8 9h8M8 13h6M8 17h4" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M5 9a7 7 0 0114 0v6a3 3 0 01-3 3h-1v-7h4" />
      <path d="M5 9v6a3 3 0 003 3h1v-7H5" />
    </svg>
  );
}

const FAQ_SECTIONS: Array<{
  id: string;
  title: string;
  items: FAQItem[];
}> = [
  {
    id: 'products',
    title: 'Products and Usage',
    items: [
      {
        question: 'Which pans work on induction cooktops?',
        answer:
          'Every Mock Cookware piece is induction compatible thanks to a magnetic stainless base layer.',
      },
      {
        question: 'Can I use metal utensils on the nonstick coating?',
        answer:
          'Yes. Our five-layer ceramic-reinforced nonstick is rated for metal utensils, although wood and silicone will extend the life of the surface.',
      },
      {
        question: 'What is the maximum oven temperature?',
        answer:
          'All cookware is safe to 600°F (315°C). Knives and wooden tools should not be placed in the oven.',
      },
      {
        question: 'How do I season the carbon-steel pan?',
        answer:
          'Wipe a thin layer of neutral oil onto the cooking surface, place the pan upside down in a 450°F oven for 60 minutes, and let it cool. Repeat 2–3 times for a deep, glossy patina.',
      },
      {
        question: 'Are the coatings PFOA-free?',
        answer:
          'Yes. All Mock Cookware coatings are PFOA, PFOS, lead, and cadmium free, and are tested by independent labs each production run.',
      },
      {
        question: 'Can I put my pan in the dishwasher?',
        answer:
          'Yes — every Mock Cookware piece is tested through 2,000 dishwasher cycles. We still recommend hand-washing for very high-end stainless, but it is not required.',
      },
    ],
  },
  {
    id: 'orders',
    title: 'Orders / Shipping & Returns',
    items: [
      {
        question: 'When will my order ship?',
        answer:
          'Orders placed before 2pm ET ship the same business day. Standard delivery is 3–5 business days within the contiguous US.',
      },
      {
        question: 'Do you ship internationally?',
        answer:
          'Yes — we ship to 38 countries. Duties and taxes are calculated at checkout so there are no surprises on delivery.',
      },
      {
        question: 'What is your return policy?',
        answer:
          'You have 30 days from delivery to return any unused item for a full refund. Cookware that has been used and washed can be returned within 14 days.',
      },
      {
        question: 'How do I start a return?',
        answer:
          'Visit your order page in your account, choose “Start a return,” and we’ll email you a prepaid label.',
      },
      {
        question: 'When will I see my refund?',
        answer:
          'Refunds typically post to the original payment method within 5–7 business days of us receiving the return.',
      },
    ],
  },
  {
    id: 'contact',
    title: 'Contact',
    items: [
      {
        question: 'What are your support hours?',
        answer:
          'Email, chat, and SMS support are available 24/7. Phone support is open Monday–Friday, 9am–6pm ET.',
      },
      {
        question: 'How fast do you respond to emails?',
        answer:
          'We answer 95% of emails within one business day. Warranty claims typically receive a response within four hours.',
      },
      {
        question: 'Do you offer wholesale or restaurant pricing?',
        answer:
          'Yes — restaurants, culinary schools, and resellers can apply for trade pricing through our help center.',
      },
    ],
  },
  {
    id: 'warranty',
    title: 'Warranty',
    items: [
      {
        question: 'What does the 25-year warranty cover?',
        answer:
          'It covers manufacturing defects and material failure under normal kitchen use, including warping, rivet failure, and coating delamination.',
      },
      {
        question: 'How do I file a warranty claim?',
        answer:
          'Register your product, then submit a short claim form with photos. Most claims are approved within 24 hours and replacements ship same-day.',
      },
      {
        question: 'Do I need to keep my receipt?',
        answer:
          'No — once your product is registered, the warranty is tied to your account.',
      },
      {
        question: 'Are knives covered by the warranty?',
        answer:
          'Knife steel and handles are covered for life against defects. Sharpening and edge wear are not covered, but our sharpening service is free for warranty-registered customers.',
      },
    ],
  },
];

function FAQPage() {
  return (
    <article className="faq-page">
      <header className="faq-page-header">
        <div className="faq-page-container">
          <p className="faq-page-eyebrow">Help Center</p>
          <h1 className="faq-page-title">Frequently asked questions</h1>
          <p className="faq-page-lede">
            Cookware care, shipping, returns, and warranty answers from our
            customer-care team.
          </p>
        </div>
      </header>
      <nav className="faq-page-nav" aria-label="FAQ sections">
        <div className="faq-page-container">
          <ul className="faq-page-nav-list">
            {FAQ_SECTIONS.map((section) => (
              <li key={section.id}>
                <a href={`#faq-${section.id}`} className="faq-page-nav-link">
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </nav>
      <div className="faq-page-sections faq-page-container">
        {FAQ_SECTIONS.map((section) => (
          <section
            key={section.id}
            id={`faq-${section.id}`}
            className="faq-page-section"
          >
            <h2 className="faq-page-section-title">{section.title}</h2>
            <FAQAccordion items={section.items} />
          </section>
        ))}
      </div>
    </article>
  );
}

function SizeGuidePage({title}: {title: string}) {
  return (
    <article className="info-page">
      <div className="info-page-container">
        <header className="info-page-header">
          <h1 className="info-page-title">{title}</h1>
          <p className="info-page-lede">
            Pan diameters are measured across the top rim. Capacities are flush
            fill. For nesting compatibility, choose pieces from the same series.
          </p>
        </header>
        <div className="info-page-body">
          <table className="size-guide-table">
            <thead>
              <tr>
                <th>Piece</th>
                <th>Diameter</th>
                <th>Depth</th>
                <th>Capacity</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Small frypan</th>
                <td>8 in / 20 cm</td>
                <td>1.6 in</td>
                <td>1.0 qt</td>
              </tr>
              <tr>
                <th scope="row">Medium frypan</th>
                <td>10 in / 25 cm</td>
                <td>1.8 in</td>
                <td>1.6 qt</td>
              </tr>
              <tr>
                <th scope="row">Large frypan</th>
                <td>12 in / 30 cm</td>
                <td>2.0 in</td>
                <td>2.4 qt</td>
              </tr>
              <tr>
                <th scope="row">Saucepan</th>
                <td>7 in / 18 cm</td>
                <td>3.5 in</td>
                <td>2.0 qt</td>
              </tr>
              <tr>
                <th scope="row">Sauté pan</th>
                <td>11 in / 28 cm</td>
                <td>2.5 in</td>
                <td>3.5 qt</td>
              </tr>
              <tr>
                <th scope="row">Stockpot</th>
                <td>9 in / 23 cm</td>
                <td>5.5 in</td>
                <td>8.0 qt</td>
              </tr>
              <tr>
                <th scope="row">Dutch oven</th>
                <td>10 in / 25 cm</td>
                <td>4.0 in</td>
                <td>5.5 qt</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </article>
  );
}

function CookwareIllustration({
  variant = 'default',
}: {
  variant?: 'default' | 'contact';
}) {
  const accent = variant === 'contact' ? 'var(--color-accent)' : '#a3713e';
  return (
    <svg
      width="100%"
      height="100%"
      viewBox="0 0 480 320"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label="Stylized cookware illustration"
    >
      <rect width="480" height="320" fill="var(--color-border)" />
      <rect width="480" height="180" y="140" fill="#d8cdb6" />
      <ellipse cx="180" cy="200" rx="120" ry="22" fill="#1f1f1f" opacity="0.18" />
      <g transform="translate(60 60)">
        <circle cx="120" cy="130" r="86" fill="#1f1f1f" />
        <circle cx="120" cy="130" r="68" fill="#3a3a3a" />
        <rect x="206" y="120" width="120" height="18" rx="6" fill="#3a3a3a" />
        <rect x="216" y="124" width="100" height="10" rx="4" fill="#1f1f1f" />
      </g>
      <g transform="translate(280 70)">
        <path
          d="M20 110 q40 -90 80 -10 q40 90 80 10"
          fill="none"
          stroke={accent}
          strokeWidth="6"
          strokeLinecap="round"
        />
        <circle cx="20" cy="110" r="6" fill={accent} />
        <circle cx="180" cy="110" r="6" fill={accent} />
      </g>
    </svg>
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
