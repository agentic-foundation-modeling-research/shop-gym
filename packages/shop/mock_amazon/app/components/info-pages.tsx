import { useState } from 'react';
import { Form, Link } from 'react-router';
import type { Policy } from '~/lib/types';

export const helpLinks = [
  { label: 'Help Center', url: '/pages/help-center' },
  { label: 'Shipping & delivery', url: '/pages/shipping-policy' },
  { label: 'Privacy Policy', url: '/policies/privacy-policy' },
  { label: 'Terms of Service', url: '/policies/terms-of-service' },
  { label: 'Refund Policy', url: '/policies/refund-policy' },
];

export function HelpHeader() {
  return <div className="help-subheader"><div className="help-subheader-inner"><Link className="help-home" to="/pages/help-center">✳ &nbsp; Customer Service</Link><nav aria-label="Help navigation"><Link to="/pages/shipping-policy">Shipping & delivery</Link><Link to="/account/orders">Your orders</Link><Link to="/account/login">Sign in</Link></nav></div></div>;
}

export function HelpSearch() {
  return <Form className="help-search" action="/search" method="get" role="search"><label htmlFor="help-query">Search the help library</label><div><input id="help-query" type="search" name="q" placeholder="Search help and products" list="help-search-topics" autoComplete="off" required /><datalist id="help-search-topics"><option value="shipping"/><option value="returns"/><option value="order"/><option value="account"/></datalist><button type="submit">Search</button></div></Form>;
}

const services = [
  { icon: '▤', title: 'Your orders', caption: 'Track & manage orders', url: '/account/orders' },
  { icon: '↩', title: 'Returns & refunds', caption: 'Start a return', url: '/account/login' },
  { icon: '✦', title: 'Membership', caption: 'Manage benefits', url: '/account/login' },
  { icon: '▣', title: 'Payment settings', caption: 'Update payment details', url: '/account/login' },
  { icon: '▥', title: 'Delivery information', caption: 'Carrier & shipping help', url: '/pages/shipping-policy' },
  { icon: '♙', title: 'Account settings', caption: 'Manage your account', url: '/account/addresses' },
];

export function SelfService() {
  return <section className="help-services" aria-label="Self-service"><h2>Manage your account and orders</h2><div className="help-service-grid">{services.map(service => <Link to={service.url} key={service.title} className="help-service"><span aria-hidden="true" className="help-service-icon">{service.icon}</span><span><strong>{service.title}</strong><small>{service.caption}</small></span><span aria-hidden="true">›</span></Link>)}</div></section>;
}

export function Feedback() {
  const [answer, setAnswer] = useState<'yes'|'no'|null>(null);
  const [reason, setReason] = useState('');
  const [submitted, setSubmitted] = useState(false);
  return <section className="help-feedback" aria-label="Page feedback"><strong>Was this information helpful?</strong>{submitted || answer === 'yes' ? <p role="status">Thank you for your feedback.</p> : <><div className="help-feedback-actions"><button className="secondary-button" type="button" onClick={() => setAnswer('yes')}>Yes</button><button className="secondary-button" type="button" onClick={() => setAnswer('no')}>No</button></div>{answer === 'no' && <div className="help-feedback-reasons"><p>What could we improve?</p>{['I could not find what I needed', 'The information was unclear', 'The information was not accurate'].map(label => <label key={label}><input type="radio" name="help-reason" value={label} checked={reason === label} onChange={() => setReason(label)} /> {label}</label>)}<button disabled={!reason} type="button" onClick={() => setSubmitted(true)}>Submit feedback</button></div>}</>}</section>;
}

export function HelpSidebar({ active, policies = [] }: { active: string; policies?: readonly Policy[] | undefined }) {
  const topics = helpLinks.filter(link => link.url !== '/policies/refund-policy' || policies.length === 0 || policies.some(policy => policy.handle === 'refund-policy'));
  return <aside className="help-sidebar"><section><h2>Help topics & policies</h2><ul>{topics.map(link => <li key={link.url}>{link.url.endsWith(`/${active}`) ? <strong aria-current="page">{link.label}</strong> : <Link to={link.url}>{link.label}</Link>}</li>)}</ul></section><SelfService /></aside>;
}

export function HelpLayout({ title, handle, children, policies, intro }: { title: string; handle: string; children: React.ReactNode; policies?: readonly Policy[]; intro?: string }) {
  return <><HelpHeader /><div className="help-container page-width"><div className="help-topline"><Link to="/pages/help-center">Help home</Link><span aria-hidden="true">›</span><span>{title}</span></div><div className="help-layout"><main className="help-article"><p className="help-eyebrow">HELP & CUSTOMER SERVICE</p><h1>{title}</h1>{intro && <p className="help-intro">{intro}</p>}{children}<Feedback /></main><HelpSidebar active={handle} policies={policies} /></div></div></>;
}

export function HelpCenter({ body }: { body: string }) {
  const topics = [
    { title: 'Deliveries & orders', url: '/pages/shipping-policy', icon: '▥' },
    { title: 'Returns & refunds', url: '/account/login', icon: '↩' },
    { title: 'Sign-in & account help', url: '/account/login', icon: '♙' },
    { title: 'Payment issues', url: '/account/login', icon: '▣' },
    { title: 'Membership', url: '/account/login', icon: '✦' },
    { title: 'Products & digital content', url: '/collections', icon: '▧' },
    { title: 'Privacy & security', url: '/policies/privacy-policy', icon: '◇' },
    { title: 'Terms & policies', url: '/policies/terms-of-service', icon: '§' },
  ];
  return <><HelpHeader /><div className="help-center"><div className="help-hero"><div className="page-width"><p className="help-eyebrow">WE'RE HERE TO HELP</p><h1>Welcome to the Help Center</h1><p>What can we help you with today?</p><p><Link to="/account/login">Sign in</Link> for help with your orders, returns and account.</p><div className="help-topic-grid">{topics.map(topic => <Link className="help-topic" key={topic.title} to={topic.url}><span aria-hidden="true">{topic.icon}</span><strong>{topic.title}</strong><span aria-hidden="true">›</span></Link>)}</div></div></div><div className="page-width help-center-content"><SelfService /><section className="help-library"><h2>Find answers in our help library</h2><HelpSearch /></section><div className="help-layout"><div className="help-article"><h2>Popular help topics</h2><div className="help-center-topics">{topics.map(topic => <Link key={topic.title} to={topic.url}>{topic.title} <span aria-hidden="true">→</span></Link>)}</div><div className="page-body" dangerouslySetInnerHTML={{__html: body}} /><Feedback /></div><HelpSidebar active="help-center" /></div></div></div></>;
}
