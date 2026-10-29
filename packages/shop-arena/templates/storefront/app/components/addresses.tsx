import { type FormEvent, useId, useState } from 'react';
import { Form } from 'react-router';
import { AddressBlock, FormErrors } from '~/components/account';
import type { AddressField } from '~/lib/addresses';
import type { Country, CustomerUserError, MailingAddress } from '~/lib/types';

/** The text of the browser's confirm dialog before an address is deleted. */
export const DELETE_ADDRESS_CONFIRM = 'Are you sure you wish to delete this address?';

/** The heading of the errors of a form that failed. */
const FORM_ERRORS_HEADING = 'Please adjust the following:';

/** `openForm` of the "Add a new address" form; an edit form is the id of its address. */
const NEW_ADDRESS_FORM = 'new';

/** An address book action that the backend turned down. */
export interface FailedAddressAction {
  readonly intent: 'create' | 'update' | 'delete';
  /** The address of an update or a delete; ignored for a create. */
  readonly addressId: string;
  readonly errors: readonly CustomerUserError[];
  /** The submitted form fields, to fill the form again. */
  readonly values: Readonly<Record<string, string>>;
}

/**
 * Dawn's address book: the "Add a new address" button and form, then one
 * block for each address with its "Edit" and "Delete" buttons. The add and
 * edit forms are closed until their button opens them, except the form of
 * a `failed` action, which opens with the submitted values and the errors.
 * Render it with a new `key` after each action so the forms close again.
 */
export function AddressBook({
  addresses,
  defaultAddressId,
  countries,
  failed,
}: {
  readonly addresses: readonly MailingAddress[];
  readonly defaultAddressId: string | null;
  readonly countries: readonly Country[];
  readonly failed: FailedAddressAction | undefined;
}) {
  const failedFormId =
    failed === undefined || failed.intent === 'delete'
      ? null
      : failed.intent === 'create'
        ? NEW_ADDRESS_FORM
        : failed.addressId;
  const [openForm, setOpenForm] = useState<string | null>(failedFormId);
  const toggle = (form: string) => setOpenForm(openForm === form ? null : form);
  const close = () => setOpenForm(null);
  const failedForm = (form: string) => (form === failedFormId ? failed : undefined);

  return (
    <>
      {failed?.intent === 'delete' ? (
        <FormErrors heading={FORM_ERRORS_HEADING} errors={failed.errors} />
      ) : null}
      <div className="stack">
        <div className="address-book-actions">
          <button
            type="button"
            aria-expanded={openForm === NEW_ADDRESS_FORM}
            aria-controls="AddAddress"
            onClick={() => toggle(NEW_ADDRESS_FORM)}
          >
            Add a new address
          </button>
        </div>
        <div id="AddAddress" className="stack" hidden={openForm !== NEW_ADDRESS_FORM}>
          <h2>Add a new address</h2>
          <AddressForm
            address={null}
            isDefault={false}
            countries={countries}
            failed={failedForm(NEW_ADDRESS_FORM)}
            submitLabel="Add address"
            onCancel={close}
          />
        </div>
      </div>
      <ul className="address-list">
        {addresses.map((address, index) => {
          const position = index + 1;
          const isDefault = address.id === defaultAddressId;
          const editFormId = `EditAddress_${position}`;
          return (
            <li key={address.id} className="stack">
              {isDefault ? <h2 className="address-default">Default</h2> : null}
              <AddressBlock address={address} />
              <div className="address-book-actions">
                <button
                  type="button"
                  className="secondary-button"
                  aria-label={`Edit address ${position}`}
                  aria-expanded={openForm === address.id}
                  aria-controls={editFormId}
                  onClick={() => toggle(address.id)}
                >
                  Edit
                </button>
                <Form method="post" onSubmit={confirmDelete}>
                  <input type="hidden" name="intent" value="delete" />
                  <input type="hidden" name="addressId" value={address.id} />
                  <button
                    type="submit"
                    className="secondary-button"
                    aria-label={`Delete ${position}`}
                  >
                    Delete
                  </button>
                </Form>
              </div>
              <div id={editFormId} className="stack" hidden={openForm !== address.id}>
                <h2>Edit address</h2>
                <AddressForm
                  address={address}
                  isDefault={isDefault}
                  countries={countries}
                  failed={failedForm(address.id)}
                  submitLabel="Update address"
                  onCancel={close}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** Asks the browser's own confirm dialog; a "Cancel" keeps the address. */
function confirmDelete(event: FormEvent<HTMLFormElement>) {
  if (!window.confirm(DELETE_ADDRESS_CONFIRM)) event.preventDefault();
}

/**
 * The add form when `address` is null, else the edit form of `address`.
 * Its fields start from the `failed` submission, else from `address`.
 * "Cancel" resets the fields and calls `onCancel`.
 */
function AddressForm({
  address,
  isDefault,
  countries,
  failed,
  submitLabel,
  onCancel,
}: {
  readonly address: MailingAddress | null;
  readonly isDefault: boolean;
  readonly countries: readonly Country[];
  readonly failed: FailedAddressAction | undefined;
  readonly submitLabel: string;
  readonly onCancel: () => void;
}) {
  const idPrefix = useId();
  const value = (field: AddressField) => failed?.values[field] ?? address?.[field] ?? '';
  const field = (name: AddressField, label: string, autoComplete: string, type = 'text') => (
    <TextField
      id={`${idPrefix}-${name}`}
      name={name}
      label={label}
      type={type}
      autoComplete={autoComplete}
      defaultValue={value(name)}
    />
  );
  return (
    <Form method="post" className="stack address-form">
      <FormErrors heading={FORM_ERRORS_HEADING} errors={failed?.errors} />
      <input type="hidden" name="intent" value={address ? 'update' : 'create'} />
      {address ? <input type="hidden" name="addressId" value={address.id} /> : null}
      <div className="address-name-row">
        {field('firstName', 'First name', 'given-name')}
        {field('lastName', 'Last name', 'family-name')}
      </div>
      {field('company', 'Company', 'organization')}
      {field('address1', 'Address 1', 'address-line1')}
      {field('address2', 'Address 2', 'address-line2')}
      {field('city', 'City', 'address-level2')}
      <label>
        Country/region
        <select name="country" autoComplete="country-name" defaultValue={value('country')}>
          {countries.map((country) => (
            <option key={country.isoCode} value={country.name}>
              {country.name}
            </option>
          ))}
        </select>
      </label>
      {field('province', 'Province', 'address-level1')}
      {field('zip', 'Postal/ZIP code', 'postal-code')}
      {field('phone', 'Phone', 'tel', 'tel')}
      <label className="address-default-choice">
        <input
          type="checkbox"
          name="default"
          value="true"
          defaultChecked={failed ? failed.values.default === 'true' : isDefault}
        />
        Set as default address
      </label>
      <div className="address-book-actions">
        <button type="submit">{submitLabel}</button>
        <button type="reset" className="secondary-button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Form>
  );
}

/** A text field with a floating label: the label shows in the field until it has a value. */
function TextField({
  id,
  label,
  ...inputProps
}: {
  readonly id: string;
  readonly name: AddressField;
  readonly label: string;
  readonly type: string;
  readonly autoComplete: string;
  readonly defaultValue: string;
}) {
  return (
    <div className="floating-field">
      <input id={id} placeholder={label} {...inputProps} />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}
