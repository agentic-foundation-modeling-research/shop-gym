import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequestHandler} from '@react-router/express';
import {createCookieSessionStorage} from 'react-router';
import compression from 'compression';
import express from 'express';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

loadEnvFile(path.join(__dirname, '.env'));

const defaults = {
  SESSION_SECRET: 'react-vite-dev-secret',
  PUBLIC_STORE_DOMAIN: 'http://localhost:4000',
  SHOP_BACKEND_URL: 'http://localhost:4000',
  PUBLIC_FOOTER_MENU_HANDLES: 'footer',
};

for (const [key, value] of Object.entries(defaults)) {
  if (!process.env[key]) {
    process.env[key] = value;
  }
}

const isProduction = process.env.NODE_ENV === 'production';
const app = express();

app.get('/images/*', proxyBackendImage);
app.use(compression());
app.disable('x-powered-by');

let vite;
if (!isProduction) {
  const {createServer} = await import('vite');
  vite = await createServer({
    server: {middlewareMode: true},
    appType: 'custom',
  });
  app.use(vite.middlewares);
} else {
  app.use(
    '/assets',
    express.static(path.join(__dirname, 'dist/client/assets'), {
      immutable: true,
      maxAge: '1y',
    }),
  );
  app.use(express.static(path.join(__dirname, 'dist/client'), {maxAge: '1h'}));
}

const sessionStorage = createCookieSessionStorage({
  cookie: {
    name: '__shop_gym_cart',
    httpOnly: true,
    path: '/',
    sameSite: 'lax',
    secrets: [process.env.SESSION_SECRET],
  },
});

app.get('/health', (_req, res) => {
  res.status(200).send('ok');
});

app.all('*', async (req, res, next) => {
  try {
    const session = await sessionStorage
      .getSession(req.headers.cookie)
      .catch(() => sessionStorage.getSession());
    const loadContext = {
      env: pickPublicEnv(process.env),
      session,
      sessionStorage,
    };
    const build = isProduction
      ? await import('./dist/server/index.js')
      : () => vite.ssrLoadModule('virtual:react-router/server-build');

    const handler = createRequestHandler({
      build,
      mode: isProduction ? 'production' : 'development',
      getLoadContext: () => loadContext,
    });

    return handler(req, res, next);
  } catch (error) {
    if (vite) {
      vite.ssrFixStacktrace(error);
    }
    next(error);
  }
});

const port = Number(process.env.PORT ?? 3000);
app.listen(port, '0.0.0.0', () => {
  console.log(`React Vite storefront listening on http://0.0.0.0:${port}`);
});

function pickPublicEnv(env) {
  return {
    PUBLIC_STORE_DOMAIN: env.PUBLIC_STORE_DOMAIN,
    SHOP_BACKEND_URL: env.SHOP_BACKEND_URL,
    SESSION_SECRET: env.SESSION_SECRET,
    PUBLIC_FOOTER_MENU_HANDLES: env.PUBLIC_FOOTER_MENU_HANDLES,
  };
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

function loadEnvFile(filePath) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') return;
    throw error;
  }
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const equals = line.indexOf('=');
    if (equals < 0) continue;
    const key = line.slice(0, equals).trim();
    let value = line.slice(equals + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}
