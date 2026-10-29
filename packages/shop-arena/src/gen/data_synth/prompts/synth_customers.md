You are inventing {{count}} fictional customer personas for a fake
storefront's seeded accounts. Agents will log in as these customers,
so every persona needs complete, plausible postal addresses in the
storefront's country.

The brand identity is fixed:

```json
{{identity}}
```

The storefront's country code is `{{country}}`.

Output one JSON array of exactly {{count}} persona objects. Each object
has exactly these fields and nothing else:

- `first_name`, `last_name`: common given and family names for the
  country. Vary them; no two personas share a full name.
- `phone`: a phone number in a clearly fictional range for the
  country (e.g. a 555 exchange for North America), or `null`.
- `accepts_marketing`: boolean.
- `addresses`: array of 1 to 3 saved address objects. The first is
  the persona's home and default address; others are places such as
  an office, a relative's home, or a holiday cottage, often in another
  city. At least two personas have two or more addresses. Each object
  has `address1` (street address), `address2` (unit, or `null`),
  `city`, `province` (state/region name, or `null` where the country
  has none), `province_code` (short code such as `"CA"` or `"ON"`, or
  `null`), and `zip` (a postal code in the country's format).

Rules:

- Use real-looking but fictional street names. Never use a real
  business address, a celebrity, or a trademark.
- Do NOT include an email or password; the orchestrator assigns them.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
