import {useState} from 'react';

const SUBJECT_OPTIONS = [
  'General enquiry',
  'Order status',
  'Returns or exchange',
  'Damaged or faulty item',
  'Personalisation',
  'Wholesale or trade',
  'Press or partnership',
];

export function ContactForm() {
  const [submitted, setSubmitted] = useState(false);
  const [fields, setFields] = useState({
    name: '',
    email: '',
    orderNumber: '',
    subject: SUBJECT_OPTIONS[0],
    message: '',
  });

  function update<K extends keyof typeof fields>(
    key: K,
    value: (typeof fields)[K],
  ) {
    setFields((prev) => ({...prev, [key]: value}));
  }

  return (
    <form
      className="contact-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (fields.name.trim() && fields.email.trim() && fields.message.trim()) {
          setSubmitted(true);
        }
      }}
    >
      <h2 className="contact-form-heading">Send us a message</h2>
      <p className="contact-form-sub">
        Prefer to write? Fill out the form below and a member of the care
        team will reply within one business day.
      </p>

      {submitted ? (
        <div className="contact-form-success" role="status">
          <h3>Thank you</h3>
          <p>
            Your message has been received. You&apos;ll hear from us within
            one business day at the email address you provided.
          </p>
        </div>
      ) : (
        <div className="contact-form-grid">
          <div className="contact-form-row">
            <label className="contact-form-label" htmlFor="contact-name">
              Full Name <span aria-hidden="true">*</span>
            </label>
            <input
              id="contact-name"
              className="contact-form-input"
              type="text"
              required
              autoComplete="name"
              value={fields.name}
              onChange={(e) => update('name', e.target.value)}
            />
          </div>

          <div className="contact-form-row">
            <label className="contact-form-label" htmlFor="contact-email">
              Email Address <span aria-hidden="true">*</span>
            </label>
            <input
              id="contact-email"
              className="contact-form-input"
              type="email"
              required
              autoComplete="email"
              value={fields.email}
              onChange={(e) => update('email', e.target.value)}
            />
          </div>

          <div className="contact-form-row">
            <label className="contact-form-label" htmlFor="contact-order">
              Order Number <span className="contact-form-optional">(optional)</span>
            </label>
            <input
              id="contact-order"
              className="contact-form-input"
              type="text"
              placeholder="e.g. VR-104382"
              value={fields.orderNumber}
              onChange={(e) => update('orderNumber', e.target.value)}
            />
          </div>

          <div className="contact-form-row">
            <label className="contact-form-label" htmlFor="contact-subject">
              Subject
            </label>
            <select
              id="contact-subject"
              className="contact-form-select"
              value={fields.subject}
              onChange={(e) => update('subject', e.target.value)}
            >
              {SUBJECT_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>

          <div className="contact-form-row contact-form-row-full">
            <label className="contact-form-label" htmlFor="contact-message">
              Message <span aria-hidden="true">*</span>
            </label>
            <textarea
              id="contact-message"
              className="contact-form-textarea"
              required
              rows={6}
              value={fields.message}
              onChange={(e) => update('message', e.target.value)}
            />
          </div>

          <div className="contact-form-row contact-form-row-full">
            <button type="submit" className="contact-form-submit">
              Send Message
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
