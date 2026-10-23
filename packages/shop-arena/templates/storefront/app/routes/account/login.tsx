import {
  type ActionFunctionArgs,
  Form,
  Link,
  type LoaderFunctionArgs,
  redirect,
  useActionData,
  useLoaderData,
} from 'react-router';
import { FormErrors } from '~/components/account';
import { getAppContext } from '~/lib/context';
import { loadCustomer, loginCustomer, safeAccountRedirect } from '~/lib/customer';
import type { CustomerUserError } from '~/lib/types';

interface LoginLoaderData {
  readonly redirectTo: string;
}

interface LoginActionData {
  readonly errors: readonly CustomerUserError[];
  readonly email: string;
}

export function meta() {
  return [{ title: 'Login' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  const redirectTo = safeAccountRedirect(new URL(request.url).searchParams.get('redirectTo'));
  if ((await loadCustomer(appContext)) !== null) {
    throw redirect(redirectTo);
  }
  return { redirectTo } satisfies LoginLoaderData;
}

export async function action({ context, request }: ActionFunctionArgs) {
  const appContext = getAppContext(context);
  const formData = await request.formData();
  const email = stringField(formData, 'email');
  const password = stringField(formData, 'password');
  const redirectTo = safeAccountRedirect(optionalStringField(formData, 'redirectTo'));
  const result = await loginCustomer(appContext, email, password);
  if ('errors' in result) {
    return { errors: result.errors, email } satisfies LoginActionData;
  }
  return redirect(redirectTo, { headers: result.headers });
}

export default function LoginRoute() {
  const { redirectTo } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  return (
    <div className="page-width stack account-form">
      <h1>Log in</h1>
      <FormErrors errors={actionData?.errors} />
      <Form method="post" className="form-grid">
        <input type="hidden" name="redirectTo" value={redirectTo} />
        <label>
          Email
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            defaultValue={actionData?.email ?? ''}
          />
        </label>
        <label>
          Password
          <input type="password" name="password" autoComplete="current-password" required />
        </label>
        <button type="submit">Log in</button>
      </Form>
      <p>
        New here?{' '}
        <Link to={`/account/register?redirectTo=${encodeURIComponent(redirectTo)}`}>
          Create an account
        </Link>
      </p>
    </div>
  );
}

function stringField(formData: FormData, name: string): string {
  const value = formData.get(name);
  if (typeof value !== 'string' || value.length === 0) {
    throw new Response(`Missing form field: ${name}`, { status: 400 });
  }
  return value;
}

function optionalStringField(formData: FormData, name: string): string | null {
  const value = formData.get(name);
  return typeof value === 'string' && value.length > 0 ? value : null;
}
