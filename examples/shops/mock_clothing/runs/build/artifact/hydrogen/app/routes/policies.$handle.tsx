import {Link, useLoaderData} from 'react-router';
import {useMemo} from 'react';
import type {Route} from './+types/policies.$handle';
import {type Shop} from '@shopify/hydrogen/storefront-api-types';

type SelectedPolicies = keyof Pick<
  Shop,
  'privacyPolicy' | 'shippingPolicy' | 'termsOfService' | 'refundPolicy'
>;

export const meta: Route.MetaFunction = ({data}) => {
  return [{title: `Mock Apparel | ${data?.policy?.title ?? 'Policies'}`}];
};

export async function loader({params, context}: Route.LoaderArgs) {
  if (!params.handle) {
    throw new Response('No handle was passed in', {status: 404});
  }

  const policyName = params.handle.replace(
    /-([a-z])/g,
    (_: unknown, m1: string) => m1.toUpperCase(),
  ) as SelectedPolicies;

  const data = await context.storefront
    .query(POLICY_CONTENT_QUERY, {
      variables: {
        privacyPolicy: false,
        shippingPolicy: false,
        termsOfService: false,
        refundPolicy: false,
        [policyName]: true,
        language: context.storefront.i18n?.language,
      },
    })
    .catch(() => ({shop: null}));

  const policy = data?.shop?.[policyName] ?? null;

  return {policy, handle: params.handle};
}

export default function Policy() {
  const {policy, handle} = useLoaderData<typeof loader>();

  const title = policy?.title ?? defaultTitleForHandle(handle);
  const lastUpdated = useMemo(() => 'Last updated: April 1, 2026', []);

  const isTerms = handle === 'terms-of-service';

  return (
    <div className="info-page policy-page">
      <header className="info-page-hero">
        <div className="info-page-hero-inner">
          <p className="info-page-eyebrow">Legal</p>
          <h1 className="info-page-title">{title}</h1>
          <p className="policy-page-updated">{lastUpdated}</p>
        </div>
      </header>

      <div className="info-page-body">
        <article className="policy-page-content info-page-content">
          <div className="policy-page-back">
            <Link to="/policies" className="policy-page-back-link">
              ← All policies
            </Link>
          </div>

          {isTerms ? <TermsOfServiceTOC /> : null}

          {policy?.body ? (
            <div
              className="policy-page-prose"
              dangerouslySetInnerHTML={{__html: policy.body}}
            />
          ) : (
            <DefaultPolicyBody handle={handle} />
          )}
        </article>
      </div>
    </div>
  );
}

function defaultTitleForHandle(handle: string) {
  const map: Record<string, string> = {
    'privacy-policy': 'Privacy Policy',
    'refund-policy': 'Refund Policy',
    'terms-of-service': 'Terms of Service',
    'shipping-policy': 'Shipping Policy',
    'cookie-policy': 'Cookie Policy',
  };
  if (map[handle]) return map[handle];
  return handle
    .split('-')
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ');
}

function TermsOfServiceTOC() {
  const sections = [
    {id: 'general', label: 'A. General Terms'},
    {id: 'loyalty', label: 'B. Loyalty Programme Terms'},
    {id: 'promotions', label: 'C. Promotional & Competition Terms'},
    {id: 'personalisation', label: 'D. Personalisation & Custom Order Terms'},
  ];
  return (
    <nav className="policy-page-toc" aria-label="Sections">
      <h2 className="policy-page-toc-heading">Sections</h2>
      <ol className="policy-page-toc-list">
        {sections.map((section) => (
          <li key={section.id}>
            <a href={`#${section.id}`}>{section.label}</a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function DefaultPolicyBody({handle}: {handle: string}) {
  switch (handle) {
    case 'privacy-policy':
      return <PrivacyPolicyBody />;
    case 'refund-policy':
      return <RefundPolicyBody />;
    case 'terms-of-service':
      return <TermsOfServiceBody />;
    case 'shipping-policy':
      return <ShippingPolicyBody />;
    default:
      return (
        <div className="policy-page-prose">
          <p>
            This policy is being updated. Please check back soon, or contact
            our care team for any urgent questions.
          </p>
        </div>
      );
  }
}

function PrivacyPolicyBody() {
  return (
    <div className="policy-page-prose">
      <h2>1. Scope &amp; Acceptance</h2>
      <p>
        This Privacy Policy explains how Mock Apparel (&ldquo;we&rdquo;,
        &ldquo;us&rdquo;) collects, uses, and protects information about
        visitors and customers of our website. By using the site, you
        accept the practices described below.
      </p>

      <h2>2. Who We Are</h2>
      <p>
        Mock Apparel is a fictional lifestyle brand created for research
        purposes. The data controller for personal information collected
        through this site is Mock Apparel Studio Ltd.
      </p>

      <h2>3. Data We Collect</h2>
      <p>
        We collect information that you provide directly (such as your
        name, email, shipping address, and payment details), data we gather
        automatically (cookies, device, and usage data), and data from
        third-party services (such as social login providers).
      </p>

      <h2>4. Why We Collect It</h2>
      <p>
        To process your orders, deliver products, personalise your shopping
        experience, prevent fraud, and improve our services.
      </p>

      <h2>5. How We Use It</h2>
      <p>
        We use personal data to fulfil your orders, communicate with you
        about your account, send marketing material (where you have opted
        in), and meet legal obligations.
      </p>

      <h2>6. Third-Party Services</h2>
      <p>
        We share data with carefully selected partners — payment
        processors, shipping carriers, analytics providers, and marketing
        platforms — under contractual data-protection commitments.
      </p>

      <h2>7. Marketing</h2>
      <p>
        You may opt out of marketing communications at any time by clicking
        &ldquo;unsubscribe&rdquo; in any email or by contacting our care
        team.
      </p>

      <h2>8. Lawful Basis for Processing</h2>
      <p>
        We rely on contract performance, legitimate interest, legal
        obligation, and your explicit consent (for marketing) as our
        lawful bases for processing personal data.
      </p>

      <h2>9. Cookie Policy</h2>
      <p>
        Our site uses essential, functional, performance, and marketing
        cookies. You can manage your preferences via the &ldquo;Cookie
        Preferences&rdquo; link in our footer at any time.
      </p>
      <h3>9.1 Essential Cookies</h3>
      <p>Required for the site to function — we cannot disable these.</p>
      <h3>9.2 Functional Cookies</h3>
      <p>Remember preferences such as country, language, and currency.</p>
      <h3>9.3 Performance Cookies</h3>
      <p>Help us understand how the site is used so we can improve it.</p>
      <h3>9.4 Marketing Cookies</h3>
      <p>
        Track ad performance and let us show you relevant content on other
        platforms.
      </p>

      <h2>10. Your Rights</h2>
      <p>
        Depending on your jurisdiction, you may have the right to access,
        rectify, erase, restrict processing, object, port, and withdraw
        consent. Email{' '}
        <a href="mailto:contact@mock-shop.example">
          contact@mock-shop.example
        </a>{' '}
        to exercise any right.
      </p>

      <h2>11. SMS / Text Marketing Terms</h2>
      <p>
        Where you opt in, we may send order updates and marketing texts.
        Reply STOP to opt out at any time. Standard message rates may
        apply.
      </p>

      <h2>12. Accessing Your Data</h2>
      <p>
        You can request a copy of the personal data we hold about you. We
        will respond within 30 days.
      </p>

      <h2>13. Security</h2>
      <p>
        We use encryption in transit and at rest, role-based access
        control, and regular security reviews. No internet transmission is
        completely secure, however, and we cannot guarantee absolute
        security.
      </p>

      <h2>14. Data Retention</h2>
      <p>
        We retain personal data only for as long as necessary to fulfil
        the purposes for which it was collected, including legal,
        accounting, or reporting obligations.
      </p>

      <h2>15. Right to Complain</h2>
      <p>
        You may complain to your local data-protection authority. In the
        UK that is the Information Commissioner&apos;s Office. Or contact{' '}
        <a href="mailto:contact@mock-shop.example">
          contact@mock-shop.example
        </a>
        .
      </p>

      <h2>16. Disclosures</h2>
      <p>
        We may disclose data when required by law, to protect rights and
        safety, or as part of a business transfer.
      </p>

      <h2>17. Accuracy</h2>
      <p>
        We aim to keep personal data accurate and up to date. Please tell
        us if any of your details change.
      </p>

      <h2>18. State-specific Supplements</h2>
      <p>
        Residents of California, Colorado, and Virginia have additional
        rights under local law. Contact us for state-specific disclosures.
      </p>

      <h2>19. International Transfers</h2>
      <p>
        Where personal data is transferred outside your home jurisdiction,
        we use approved transfer mechanisms — Standard Contractual Clauses
        and the UK International Data Transfer Addendum where applicable.
      </p>

      <h2>20. Updates to this Policy</h2>
      <p>
        We may update this policy from time to time. The &ldquo;last
        updated&rdquo; date at the top reflects the most recent revision.
      </p>
    </div>
  );
}

function RefundPolicyBody() {
  return (
    <div className="policy-page-prose">
      <h2>Returns &amp; Refunds</h2>
      <p>
        Non-personalised items can be returned within 12 months of
        purchase for a full refund or exchange. Personalised pieces have a
        30-day exchange window. Items must be unworn and in their original
        packaging.
      </p>

      <h2>Refund Processing</h2>
      <p>
        Refunds are processed within 5 working days of us receiving your
        return. The refund will appear on your original payment method
        within an additional 5–10 business days, depending on your bank.
      </p>

      <h2>Exclusions</h2>
      <p>
        Earrings (for hygiene), opened advent-style gift sets, and
        personalised items beyond the 30-day exchange window cannot be
        returned. Sale items are eligible for store credit only.
      </p>

      <h2>Faulty or Damaged Items</h2>
      <p>
        If your item is damaged or faulty on arrival, contact{' '}
        <a href="mailto:contact@mock-shop.example">
          contact@mock-shop.example
        </a>{' '}
        within 14 days of receipt with photos. We&apos;ll arrange a free
        replacement or refund within 48 hours.
      </p>

      <h2>Gifts</h2>
      <p>
        Gift returns are issued as store credit, valid for 12 months from
        the date of return. The original purchaser will not be notified.
      </p>

      <h2>How to Start a Return</h2>
      <p>
        Visit our <Link to="/pages/returns">Returns &amp; Exchanges</Link>{' '}
        page for the full step-by-step process and prepaid label options.
      </p>
    </div>
  );
}

function ShippingPolicyBody() {
  return (
    <div className="policy-page-prose">
      <h2>Shipping Methods &amp; Costs</h2>
      <p>
        We offer Standard, Express, and Next-Working-Day shipping
        domestically, and Standard and Express shipping internationally.
        Standard shipping is free on all domestic orders over $75.
      </p>

      <h2>Estimated Delivery</h2>
      <p>
        Domestic Standard: 3–5 business days. Domestic Express: 1–2
        business days. Next-Working-Day: 1 business day on orders placed
        before 2pm GMT, Monday–Friday.
      </p>

      <h2>International</h2>
      <p>
        International delivery times vary by region — typically 5–14
        business days. Customs duties or local sales tax may be collected
        on arrival and are the recipient&apos;s responsibility.
      </p>

      <h2>Tracking</h2>
      <p>
        You&apos;ll receive a tracking email the moment your order is
        dispatched. Express and Next-Day deliveries require a signature on
        delivery.
      </p>

      <h2>Order Cut-Off</h2>
      <p>
        Orders placed after 2pm GMT on business days will ship the next
        business day. Orders placed on weekends or public holidays will
        ship the next available business day.
      </p>

      <h2>Address Changes</h2>
      <p>
        Address changes must be requested within 30 minutes of order
        placement. After dispatch, contact us with your tracking number and
        we&apos;ll attempt to redirect through the carrier.
      </p>

      <h2>Full Shipping FAQs</h2>
      <p>
        Visit our <Link to="/pages/shipping">Shipping &amp; Delivery</Link>{' '}
        page for the full set of FAQs and regional rate tables.
      </p>
    </div>
  );
}

function TermsOfServiceBody() {
  return (
    <div className="policy-page-prose">
      <section>
        <h2 id="general">A. General Terms</h2>
        <h3>A.1 Contract Basis</h3>
        <p>
          By using this website you agree to these Terms of Service. We
          may revise these terms at any time; the &ldquo;last
          updated&rdquo; date reflects the most recent revision.
        </p>
        <h3>A.2 Website Use</h3>
        <p>
          Use of this site for unlawful purposes, to harm others, or to
          interfere with the site&apos;s operation is strictly
          prohibited.
        </p>
        <h3>A.3 Prohibited Conduct</h3>
        <p>
          You must not attempt unauthorised access, scrape content, run
          automated agents that overload the site, or interfere with
          security measures.
        </p>
        <h3>A.4 Orders &amp; Purchases</h3>
        <p>
          All orders are subject to acceptance. We reserve the right to
          decline or cancel any order at our discretion, with a full
          refund.
        </p>
        <h3>A.5 Payment</h3>
        <p>
          We accept the payment methods listed at checkout. Payment is
          processed by our payment service providers under their own
          terms.
        </p>
        <h3>A.6 Intellectual Property</h3>
        <p>
          All content on the site — including imagery, copy, design, and
          source code — is owned by Mock Apparel or its licensors and may not
          be reproduced without permission.
        </p>
        <h3>A.7 User Content</h3>
        <p>
          By submitting reviews, photos, or comments, you grant us a
          worldwide, royalty-free licence to use that content in
          connection with our marketing.
        </p>
        <h3>A.8 Disclaimers</h3>
        <p>
          The site is provided &ldquo;as is&rdquo; without warranty of any
          kind. Product colours and dimensions may vary slightly from the
          images shown.
        </p>
        <h3>A.9 Governing Law &amp; Disputes</h3>
        <p>
          These terms are governed by the laws of England and Wales.
          Disputes shall be resolved exclusively in the courts of England
          and Wales unless local consumer protection law provides
          otherwise.
        </p>
      </section>

      <section>
        <h2 id="loyalty">B. Loyalty Programme Terms</h2>
        <h3>B.1 Account &amp; Eligibility</h3>
        <p>
          The loyalty programme is open to anyone aged 16 or older with a
          valid Mock Apparel account.
        </p>
        <h3>B.2 Tiers &amp; Benefits</h3>
        <p>
          Three tiers — Friend (0–499 points), Insider (500–1,499 points),
          and Atelier (1,500+ points) — unlock progressively better perks
          including welcome gifts, birthday rewards, expedited shipping,
          and early access.
        </p>
        <h3>B.3 Point Accrual &amp; Expiry</h3>
        <p>
          Earn 1 point per dollar spent. Returned items reverse their
          earned points. Points never expire while your account is active
          (a 12-month inactivity period applies).
        </p>
      </section>

      <section>
        <h2 id="promotions">C. Promotional &amp; Competition Terms</h2>
        <h3>C.1 Seasonal Promotions</h3>
        <p>
          Seasonal codes apply to full-price items only and cannot be
          combined with other offers.
        </p>
        <h3>C.2 Gift With Purchase</h3>
        <ol>
          <li>Available while stocks last.</li>
          <li>Limited to one gift per order.</li>
          <li>If the qualifying item is returned, the gift must be returned with it.</li>
        </ol>
        <h3>C.3 Competitions</h3>
        <p>
          Competition entries are governed by the specific terms of each
          competition. Entrants must be 18+ unless otherwise stated.
        </p>
      </section>

      <section>
        <h2 id="personalisation">D. Personalisation &amp; Custom Order Terms</h2>
        <h3>D.1 Cancellation Rights</h3>
        <p>
          Personalised orders cannot be cancelled or returned for refund
          once production has started, except in the case of a
          manufacturing defect.
        </p>
        <h3>D.2 Exchange Window</h3>
        <p>
          Personalised items have a 30-day exchange window from the date
          of receipt.
        </p>
        <h3>D.3 Approvals</h3>
        <p>
          Where the personalisation requires approval (e.g., custom
          engraving), we will email you a digital proof. Production begins
          on receipt of your approval.
        </p>
      </section>
    </div>
  );
}

const POLICY_CONTENT_QUERY = `#graphql
  fragment Policy on ShopPolicy {
    body
    handle
    id
    title
    url
  }
  query Policy(
    $country: CountryCode
    $language: LanguageCode
    $privacyPolicy: Boolean!
    $refundPolicy: Boolean!
    $shippingPolicy: Boolean!
    $termsOfService: Boolean!
  ) @inContext(language: $language, country: $country) {
    shop {
      privacyPolicy @include(if: $privacyPolicy) {
        ...Policy
      }
      shippingPolicy @include(if: $shippingPolicy) {
        ...Policy
      }
      termsOfService @include(if: $termsOfService) {
        ...Policy
      }
      refundPolicy @include(if: $refundPolicy) {
        ...Policy
      }
    }
  }
` as const;
