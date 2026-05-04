import {useState, type FormEvent} from 'react';

export function NewsletterSignup() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const honeypot = (form.elements.namedItem('website') as HTMLInputElement | null)?.value;
    if (honeypot) {
      return;
    }
    if (!email || !/^\S+@\S+\.\S+$/.test(email)) {
      setError('Please enter a valid email address.');
      return;
    }
    setError(null);
    setSubmitted(true);
  }

  return (
    <section className="newsletter" aria-label="Newsletter signup">
      <div className="section-container newsletter-inner">
        <div className="newsletter-copy">
          <p className="section-eyebrow accent">Stay in the kitchen</p>
          <h2 className="newsletter-title">
            Recipes, care guides, and early access drops
          </h2>
          <p className="newsletter-body">
            Sign up for our weekly journal — a five-minute read with chef
            tutorials, new collection previews, and subscriber-only offers.
          </p>
        </div>
        {submitted ? (
          <p className="newsletter-success" role="status">
            Thanks! Check your inbox for a confirmation.
          </p>
        ) : (
          <form className="newsletter-form" onSubmit={handleSubmit} noValidate>
            <label htmlFor="newsletter-email" className="sr-only">
              Email address
            </label>
            <input
              id="newsletter-email"
              type="email"
              name="email"
              className="newsletter-input"
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
              className="newsletter-honeypot"
              aria-hidden="true"
            />
            <button type="submit" className="newsletter-button">
              Subscribe
            </button>
            {error && (
              <p className="newsletter-error" role="alert">
                {error}
              </p>
            )}
          </form>
        )}
      </div>
    </section>
  );
}
