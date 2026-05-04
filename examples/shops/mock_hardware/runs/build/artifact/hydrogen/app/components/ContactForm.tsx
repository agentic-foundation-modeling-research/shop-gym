import {useState} from 'react';

type Status = 'idle' | 'submitting' | 'success';

export function ContactForm() {
  const [status, setStatus] = useState<Status>('idle');

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('submitting');
    setTimeout(() => setStatus('success'), 400);
  }

  if (status === 'success') {
    return (
      <div className="contact-form-success" role="status">
        <h3>Thanks — request received</h3>
        <p>
          This is a research-only mock storefront, so no real ticket has been
          created. Your request has been discarded.
        </p>
      </div>
    );
  }

  return (
    <form className="contact-form" onSubmit={handleSubmit} noValidate>
      <div className="contact-form-row">
        <label className="contact-form-field">
          <span className="contact-form-label">Full name</span>
          <input
            className="contact-form-input"
            type="text"
            name="name"
            autoComplete="name"
            required
          />
        </label>
        <label className="contact-form-field">
          <span className="contact-form-label">Email</span>
          <input
            className="contact-form-input"
            type="email"
            name="email"
            autoComplete="email"
            required
          />
        </label>
      </div>
      <label className="contact-form-field">
        <span className="contact-form-label">Order number (optional)</span>
        <input
          className="contact-form-input"
          type="text"
          name="orderNumber"
          placeholder="e.g. #1024"
        />
      </label>
      <label className="contact-form-field">
        <span className="contact-form-label">Topic</span>
        <select className="contact-form-input" name="topic" defaultValue="order">
          <option value="order">Order or shipping question</option>
          <option value="returns">Return or refund</option>
          <option value="warranty">Warranty claim</option>
          <option value="other">Something else</option>
        </select>
      </label>
      <label className="contact-form-field">
        <span className="contact-form-label">Message</span>
        <textarea
          className="contact-form-input contact-form-textarea"
          name="message"
          rows={6}
          required
        />
      </label>
      <button
        type="submit"
        className="contact-form-submit"
        disabled={status === 'submitting'}
      >
        {status === 'submitting' ? 'Sending…' : 'Submit request'}
      </button>
      <p className="contact-form-note">
        The form is non-functional. Submitted data will be discarded by the
        mock storefront.
      </p>
    </form>
  );
}
