import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {createRequestHandler} from '@react-router/express';
import {createCookieSessionStorage} from 'react-router';
import compression from 'compression';
import express from 'express';
import morgan from 'morgan';
import {createHydrogenContext, InMemoryCache} from '@shopify/hydrogen';

// Default env vars for mock API connection (can be overridden by process.env)
const defaults = {
  SESSION_SECRET: 'mock-secret',
  PUBLIC_STORE_DOMAIN: 'http://localhost:4000',
  PUBLIC_STOREFRONT_API_TOKEN: 'mock-token',
  PUBLIC_CHECKOUT_DOMAIN: 'checkout.localhost',
  PUBLIC_STOREFRONT_ID: 'mock',
};
for (const [key, value] of Object.entries(defaults)) {
  if (!(key in process.env)) {
    process.env[key] = value;
  }
}

const isProduction = process.env.NODE_ENV === 'production';

// In dev mode, start Vite dev server for HMR
let vite;
if (!isProduction) {
  const {createServer} = await import('vite');
  vite = await createServer({
    server: {middlewareMode: true},
  });
}

const app = express();

app.use(compression());
app.disable('x-powered-by');

if (isProduction) {
  app.use(morgan('tiny'));
  app.use(
    '/assets',
    express.static('dist/client/assets', {immutable: true, maxAge: '1y'}),
  );
  app.use(express.static('dist/client', {maxAge: '1h'}));
} else {
  app.use(vite.middlewares);
}

// Serve generated product images from the shop's data dir.
// Canonical layout has hydrogen/ as a sibling of data/. Build-loop layout
// nests the runtime tree at runs/build/artifact/hydrogen/, so probe both.
const imagesDir = ['../data/images', '../../../../data/images']
  .map((p) => resolve(p))
  .find(existsSync);
if (imagesDir) {
  app.use('/images', express.static(imagesDir, {maxAge: '1y', immutable: true}));
}

// Health check endpoint for Cloud Run and smoke tests
app.get('/health', (_req, res) => {
  res.status(200).send('ok');
});

// Handle all other requests with React Router
app.all('*', async (req, res, next) => {
  const context = await getContext(req);

  const build = isProduction
    ? await import('./dist/server/index.js')
    : () => vite.ssrLoadModule('virtual:react-router/server-build');

  const handler = createRequestHandler({
    build,
    mode: isProduction ? 'production' : 'development',
    getLoadContext: () => context,
  });

  return handler(req, res, next);
});

const port = process.env.PORT || 3000;

app.listen(port, '0.0.0.0', () => {
  console.log(`Express server listening on http://0.0.0.0:${port}`);
});

// -- Hydrogen context creation --

const CART_QUERY_FRAGMENT = `#graphql
  fragment Money on MoneyV2 {
    currencyCode
    amount
  }
  fragment CartLine on CartLine {
    id
    quantity
    attributes {
      key
      value
    }
    cost {
      totalAmount {
        ...Money
      }
      amountPerQuantity {
        ...Money
      }
      compareAtAmountPerQuantity {
        ...Money
      }
    }
    merchandise {
      ... on ProductVariant {
        id
        availableForSale
        compareAtPrice {
          ...Money
        }
        price {
          ...Money
        }
        requiresShipping
        title
        image {
          id
          url
          altText
          width
          height
        }
        product {
          handle
          title
          id
          vendor
        }
        selectedOptions {
          name
          value
        }
      }
    }
  }
  fragment CartApiQuery on Cart {
    updatedAt
    id
    checkoutUrl
    totalQuantity
    buyerIdentity {
      countryCode
      customer {
        id
        email
        firstName
        lastName
        displayName
      }
      email
      phone
    }
    lines(first: $numCartLines) {
      nodes {
        ...CartLine
      }
    }
    cost {
      subtotalAmount {
        ...Money
      }
      totalAmount {
        ...Money
      }
      totalDutyAmount {
        ...Money
      }
      totalTaxAmount {
        ...Money
      }
    }
    note
    attributes {
      key
      value
    }
    discountCodes {
      code
      applicable
    }
  }
`;

class AppSession {
  constructor(sessionStorage, session) {
    this.isPending = false;
    this.sessionStorage = sessionStorage;
    this.session = session;
  }

  static async init(request, secrets) {
    const storage = createCookieSessionStorage({
      cookie: {
        name: 'session',
        httpOnly: true,
        path: '/',
        sameSite: 'lax',
        secrets,
      },
    });

    const session = await storage
      .getSession(request.get('Cookie'))
      .catch(() => storage.getSession());

    return new AppSession(storage, session);
  }

  get(key) {
    return this.session.get(key);
  }

  has(key) {
    return this.session.has(key);
  }

  flash(key, value) {
    this.session.flash(key, value);
  }

  unset(key) {
    this.isPending = true;
    this.session.unset(key);
  }

  set(key, value) {
    this.isPending = true;
    this.session.set(key, value);
  }

  destroy() {
    return this.sessionStorage.destroySession(this.session);
  }

  commit() {
    this.isPending = false;
    return this.sessionStorage.commitSession(this.session);
  }
}

async function getContext(req) {
  const env = process.env;
  const session = await AppSession.init(req, [env.SESSION_SECRET]);

  const request = new Request(`http://localhost${req.url}`, {
    method: req.method,
    headers: req.headers,
  });

  const hydrogenContext = createHydrogenContext(
    {
      env,
      request,
      cache: new InMemoryCache(),
      waitUntil: () => Promise.resolve(),
      session,
      i18n: {language: 'EN', country: 'US'},
      cart: {
        queryFragment: CART_QUERY_FRAGMENT,
      },
    },
    {},
  );

  return hydrogenContext;
}
