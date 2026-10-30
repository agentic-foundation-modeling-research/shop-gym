import {
  type ActionFunctionArgs,
  Form,
  Link,
  type LoaderFunctionArgs,
  redirect,
  useActionData,
  useLoaderData,
} from 'react-router';
import { FORM_ERRORS_HEADING, FloatingField, FormErrors } from '~/components/account';
import { getAppContext } from '~/lib/context';
import { loadCustomer, loginCustomer, safeAccountRedirect } from '~/lib/customer';
import { CUSTOMER_RECOVER_MUTATION } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CustomerUserError } from '~/lib/types';

/** The `intent` of the "Forgot your password?" form; the login form sends none. */
const RECOVER_INTENT = 'recover';

/** Shown above the login form after every password reset request, for any email. */
const RECOVER_SUCCESS = "We've sent you an email with a link to update your password.";

interface LoginLoaderData {
  readonly redirectTo: string;
}

type LoginActionData =
  | { readonly errors: readonly CustomerUserError[]; readonly email: string }
  | { readonly recovered: true };

interface CustomerRecoverData {
  readonly customerRecover: { readonly customerUserErrors: readonly CustomerUserError[] };
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
  if (formData.get('intent') === RECOVER_INTENT) {
    // The backend answers every email the same, so there is no error to show.
    await storefrontQuery<CustomerRecoverData>(appContext, CUSTOMER_RECOVER_MUTATION, { email });
    return { recovered: true } satisfies LoginActionData;
  }
  const password = stringField(formData, 'password');
  const redirectTo = safeAccountRedirect(optionalStringField(formData, 'redirectTo'));
  const result = await loginCustomer(appContext, email, password);
  if ('errors' in result) {
    return { errors: result.errors, email } satisfies LoginActionData;
  }
  return redirect(redirectTo, { headers: result.headers });
}

/**
 * Dawn's login page: the login form, and the "Forgot your password?" form
 * in its place. Both are in the page; the link "Forgot your password?"
 * targets `#recover`, which shows the recover form, and "Cancel" targets
 * `#login` again (see `.customer-login` in `app.css`). The recover form
 * reloads the document, so the page that answers it has no `#recover` and
 * shows the login form with the message.
 */
export default function LoginRoute() {
  const { redirectTo } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const failed = actionData !== undefined && 'errors' in actionData ? actionData : undefined;
  const recovered = actionData !== undefined && 'recovered' in actionData;
  return (
    <div className="page-width account-form customer-login">
      <div id="login" className="stack login-panel">
        <h1>Login</h1>
        {recovered ? <p>{RECOVER_SUCCESS}</p> : null}
        <FormErrors heading={FORM_ERRORS_HEADING} errors={failed?.errors} />
        <Form method="post" className="stack">
          <input type="hidden" name="redirectTo" value={redirectTo} />
          <FloatingField
            id="CustomerEmail"
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
            defaultValue={failed?.email ?? ''}
          />
          <FloatingField
            id="CustomerPassword"
            label="Password"
            type="password"
            name="password"
            autoComplete="current-password"
            required
          />
          <a href="#recover">Forgot your password?</a>
          <div className="account-form-actions">
            <button type="submit">Sign in</button>
            <Link to={`/account/register?redirectTo=${encodeURIComponent(redirectTo)}`}>
              Create account
            </Link>
          </div>
        </Form>
      </div>
      <div id="recover" className="stack recover-panel">
        <h1>Reset your password</h1>
        <p>We will send you an email to reset your password</p>
        <Form method="post" reloadDocument className="stack">
          <input type="hidden" name="intent" value={RECOVER_INTENT} />
          <FloatingField
            id="RecoverEmail"
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
          />
          <div className="account-form-actions">
            <button type="submit">Submit</button>
            <a href="#login">Cancel</a>
          </div>
        </Form>
      </div>
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
