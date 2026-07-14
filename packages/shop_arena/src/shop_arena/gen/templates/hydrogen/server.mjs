import {createRequestHandler} from '@react-router/express';
import {createCookieSessionStorage} from 'react-router';
import compression from 'compression';
import express from 'express';
import morgan from 'morgan';
import {createHydrogenContext, InMemoryCache} from '@shopify/hydrogen';
import {CART_QUERY_FRAGMENT} from './app/lib/cart-fragment.js';

// Load .env into process.env *before* the defaults block below seeds
// any missing keys. shop_arena.gen's write_env_file step (spec §5.5.1) emits
// PUBLIC_STORE_DOMAIN with the resolved sidecar port; without this
// load it stays undefined and the defaults block falls back to
// localhost:4000, where nothing is listening, so every route loader's
// Storefront API fetch fails. process.loadEnvFile is a Node built-in
// (>=21.7.0); a missing .env is ignored so production builds and tests
// without a .env still work via the defaults below.
try {
  process.loadEnvFile();
} catch (err) {
  if (err?.code !== 'ENOENT') throw err;
}

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

app.get('/images/*', proxyBackendImage);
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

async function proxyBackendImage(req, res, next) {
  try {
    const target = new URL(req.originalUrl, resolveBackendUrl()).toString();
    const upstream = await fetch(target);
    res.status(upstream.status);
    copyResponseHeaders(upstream.headers, res);
    if (upstream.body === null) {
      res.end();
      return;
    }
    const body = Buffer.from(await upstream.arrayBuffer());
    res.send(body);
  } catch (error) {
    next(error);
  }
}

function resolveBackendUrl() {
  const raw = process.env.SHOP_BACKEND_URL || process.env.PUBLIC_STORE_DOMAIN;
  if (!raw) {
    throw new Error('Set SHOP_BACKEND_URL or PUBLIC_STORE_DOMAIN for image proxy.');
  }
  return raw.replace(/\/+$/, '');
}

function copyResponseHeaders(headers, res) {
  for (const [name, value] of headers) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      res.setHeader(name, value);
    }
  }
}

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);
