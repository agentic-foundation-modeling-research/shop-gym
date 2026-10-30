import type { ComponentProps } from 'react';
import {
  type ActionFunctionArgs,
  Form,
  type LoaderFunctionArgs,
  redirect,
  useActionData,
  useLoaderData,
} from 'react-router';
import { FORM_ERRORS_HEADING, FloatingField, FormErrors } from '~/components/account';
import { getAppContext } from '~/lib/context';
import { loadCustomer, loginCustomer, safeAccountRedirect } from '~/lib/customer';
import { CUSTOMER_CREATE_MUTATION } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CustomerUserError } from '~/lib/types';

interface CustomerCreateData {
  readonly customerCreate: {
    readonly customer: { readonly id: string } | null;
    readonly customerUserErrors: readonly CustomerUserError[];
  };
}

interface RegisterActionData {
  readonly errors: readonly CustomerUserError[];
  readonly values: {
    readonly firstName: string;
    readonly lastName: string;
    readonly email: string;
  };
}

export function meta() {
  return [{ title: 'Create account' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  const redirectTo = safeAccountRedirect(new URL(request.url).searchParams.get('redirectTo'));
  if ((await loadCustomer(appContext)) !== null) {
    throw redirect(redirectTo);
  }
  return { redirectTo };
}

export async function action({ context, request }: ActionFunctionArgs) {
  const appContext = getAppContext(context);
  const formData = await request.formData();
  const values = {
    firstName: stringField(formData, 'firstName'),
    lastName: stringField(formData, 'lastName'),
    email: stringField(formData, 'email'),
  };
  const password = stringField(formData, 'password');
  const redirectTo = safeAccountRedirect(optionalStringField(formData, 'redirectTo'));
  const data = await storefrontQuery<CustomerCreateData>(appContext, CUSTOMER_CREATE_MUTATION, {
    input: { ...values, password },
  });
  const created = data.customerCreate;
  if (!created.customer) {
    return { errors: created.customerUserErrors, values } satisfies RegisterActionData;
  }
  const result = await loginCustomer(appContext, values.email, password);
  if ('errors' in result) {
    return { errors: result.errors, values } satisfies RegisterActionData;
  }
  return redirect(redirectTo, { headers: result.headers });
}

/**
 * Dawn's register page. A backend error on a field shows under that field
 * and in the list above the form.
 */
export default function RegisterRoute() {
  const { redirectTo } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const values = actionData?.values;
  const errorOf = (field: string) =>
    actionData?.errors.find((error) => error.field?.at(-1) === field)?.message;
  return (
    <div className="page-width stack account-form">
      <h1>Create account</h1>
      <FormErrors heading={FORM_ERRORS_HEADING} errors={actionData?.errors} />
      <Form method="post" className="stack">
        <input type="hidden" name="redirectTo" value={redirectTo} />
        <FloatingField
          id="RegisterForm-FirstName"
          label="First name"
          name="firstName"
          autoComplete="given-name"
          required
          defaultValue={values?.firstName ?? ''}
        />
        <FloatingField
          id="RegisterForm-LastName"
          label="Last name"
          name="lastName"
          autoComplete="family-name"
          required
          defaultValue={values?.lastName ?? ''}
        />
        <FieldWithError
          id="RegisterForm-email"
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          required
          defaultValue={values?.email ?? ''}
          error={errorOf('email')}
        />
        <FieldWithError
          id="RegisterForm-password"
          label="Password"
          type="password"
          name="password"
          autoComplete="new-password"
          required
          error={errorOf('password')}
        />
        <div className="account-form-actions">
          <button type="submit">Create</button>
        </div>
      </Form>
    </div>
  );
}

/** A floating field with the backend's `error` for it, when there is one, under it. */
function FieldWithError({
  error,
  ...fieldProps
}: ComponentProps<typeof FloatingField> & { readonly error: string | undefined }) {
  const errorId = `${fieldProps.id}-error`;
  if (error === undefined) return <FloatingField {...fieldProps} />;
  return (
    <div>
      <FloatingField {...fieldProps} aria-invalid aria-describedby={errorId} />
      <p id={errorId} className="field-error">
        {error}
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
