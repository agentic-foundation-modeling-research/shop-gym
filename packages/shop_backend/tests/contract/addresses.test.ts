/**
 * Contract: the address book. `customerAddressCreate`, `customerAddressUpdate`,
 * `customerAddressDelete` and `customerDefaultAddressUpdate` take the
 * Storefront API arguments and return its payloads and user errors. Each
 * change moves the Episode clock and shows in the StateSnapshot customers.
 * Each test uses its own episode so address changes do not leak between
 * tests.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { type ContractServer, startContractServer } from './helpers.js';

// Seeded Persona with two addresses; the first is the default.
const MARC = {
  email: 'marc.tremblay@example.com',
  password: 'password123',
  id: 'gid://shopify/Customer/2',
  home: 'gid://shopify/MailingAddress/3',
  office: 'gid://shopify/MailingAddress/4',
};
// The highest seeded address id, on a seeded order, is 13.
const FIRST_NEW_ADDRESS = 'gid://shopify/MailingAddress/14';

const NEW_ADDRESS = /* GraphQL */ `{
  firstName: "Marc"
  lastName: "Tremblay"
  address1: "77 Rue Sherbrooke Est"
  address2: ""
  city: "Montreal"
  province: "Quebec"
  country: "Canada"
  zip: "H2X 1C5"
}`;

const UNIDENTIFIED_CUSTOMER = {
  code: 'UNIDENTIFIED_CUSTOMER',
  field: ['customerAccessToken'],
  message: 'Unidentified customer',
};

let ctx: ContractServer;

beforeAll(async () => {
  ctx = await startContractServer();
});

afterAll(async () => {
  await ctx.server.close();
});

interface UserError {
  readonly code: string | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}

interface AddressShape {
  readonly id: string;
  readonly address1: string;
  readonly address2: string | null;
  readonly city: string;
  readonly formatted: readonly string[];
}

async function login(episode: string): Promise<string> {
  const result = await ctx.query<{
    customerAccessTokenCreate: { customerAccessToken: { accessToken: string } | null };
  }>(
    /* GraphQL */ `mutation {
      customerAccessTokenCreate(input: { email: "${MARC.email}", password: "${MARC.password}" }) {
        customerAccessToken { accessToken }
      }
    }`,
    episode,
  );
  const token = result.data?.customerAccessTokenCreate.customerAccessToken?.accessToken;
  if (token === undefined) throw new Error(`login failed: ${JSON.stringify(result)}`);
  return token;
}

async function mutate<T>(episode: string, source: string): Promise<T> {
  const result = await ctx.query<T>(source, episode);
  if (result.data === undefined || result.errors !== undefined) {
    throw new Error(JSON.stringify(result.errors));
  }
  return result.data;
}

/** Marc in the episode's StateSnapshot. */
async function marcInSnapshot(episode: string) {
  const state = await ctx.snapshot(episode);
  const marc = state.customers.find((customer) => customer.id === MARC.id);
  if (marc === undefined) throw new Error('no Marc in the StateSnapshot');
  return { marc, now: state.now };
}

describe('customerAddressCreate', () => {
  it('adds the address to the customer and moves the Episode clock', async () => {
    const episode = 'address-create';
    const token = await login(episode);
    const before = (await ctx.snapshot(episode)).now;

    const data = await mutate<{
      customerAddressCreate: {
        customerAddress: AddressShape | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressCreate(customerAccessToken: "${token}", address: ${NEW_ADDRESS}) {
          customerAddress { id address1 address2 city formatted }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressCreate).toEqual({
      customerAddress: {
        id: FIRST_NEW_ADDRESS,
        address1: '77 Rue Sherbrooke Est',
        address2: null,
        city: 'Montreal',
        formatted: ['Marc Tremblay', '77 Rue Sherbrooke Est', 'Montreal Quebec H2X 1C5', 'Canada'],
      },
      customerUserErrors: [],
    });
    const { marc, now } = await marcInSnapshot(episode);
    expect(marc.addresses.map((address) => address.id)).toEqual([
      MARC.home,
      MARC.office,
      FIRST_NEW_ADDRESS,
    ]);
    expect(marc.addresses[2]).toMatchObject({
      address1: '77 Rue Sherbrooke Est',
      address2: null,
      company: null,
      country: 'Canada',
      countryCode: 'CA',
      provinceCode: null,
    });
    // Adding an address does not change the default.
    expect(marc.defaultAddressId).toBe(MARC.home);
    expect(Date.parse(now)).toBeGreaterThan(Date.parse(before));
  });

  it('makes the first address of a customer with none the default', async () => {
    const episode = 'address-create-first';
    const created = await mutate<{
      customerCreate: { customer: { id: string } | null };
      customerAccessTokenCreate: { customerAccessToken: { accessToken: string } | null };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerCreate(input: { email: "new.buyer@example.com", password: "secret123" }) {
          customer { id }
        }
        customerAccessTokenCreate(input: { email: "new.buyer@example.com", password: "secret123" }) {
          customerAccessToken { accessToken }
        }
      }`,
    );
    const token = created.customerAccessTokenCreate.customerAccessToken?.accessToken;

    const data = await mutate<{
      customerAddressCreate: { customerAddress: { id: string } | null };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressCreate(customerAccessToken: "${token}", address: ${NEW_ADDRESS}) {
          customerAddress { id }
        }
      }`,
    );

    const state = await ctx.snapshot(episode);
    const buyer = state.customers.find(
      (customer) => customer.id === created.customerCreate.customer?.id,
    );
    expect(buyer?.defaultAddressId).toBe(data.customerAddressCreate.customerAddress?.id);
  });

  it('reports each blank required line and adds nothing', async () => {
    const episode = 'address-create-blank';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerAddressCreate: {
        customerAddress: AddressShape | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressCreate(
          customerAccessToken: "${token}"
          address: { address1: "  ", city: "Montreal", country: "Canada" }
        ) {
          customerAddress { id }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressCreate).toEqual({
      customerAddress: null,
      customerUserErrors: [
        { code: 'BLANK', field: ['address', 'address1'], message: "Address1 can't be blank" },
        { code: 'BLANK', field: ['address', 'zip'], message: "Zip can't be blank" },
      ],
    });
    expect(await marcInSnapshot(episode)).toEqual(before);
  });

  it('turns down an unknown access token', async () => {
    const data = await mutate<{
      customerAddressCreate: {
        customerAddress: AddressShape | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      'address-create-token',
      /* GraphQL */ `mutation {
        customerAddressCreate(customerAccessToken: "not-a-token", address: ${NEW_ADDRESS}) {
          customerAddress { id }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressCreate).toEqual({
      customerAddress: null,
      customerUserErrors: [UNIDENTIFIED_CUSTOMER],
    });
  });
});

describe('customerAddressUpdate', () => {
  it('changes only the given lines and moves the Episode clock', async () => {
    const episode = 'address-update';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerAddressUpdate: {
        customerAddress: AddressShape | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressUpdate(
          customerAccessToken: "${token}"
          id: "${MARC.office}"
          address: { address2: "Suite 2500", company: "", province: "Québec" }
        ) {
          customerAddress { id address1 address2 city formatted }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressUpdate).toEqual({
      customerAddress: {
        id: MARC.office,
        address1: '1000 Rue De La Gauchetiere Ouest',
        address2: 'Suite 2500',
        city: 'Montreal',
        formatted: [
          'Marc Tremblay',
          '1000 Rue De La Gauchetiere Ouest',
          'Suite 2500',
          'Montreal Québec H3B 4W5',
          'Canada',
        ],
      },
      customerUserErrors: [],
    });
    const { marc, now } = await marcInSnapshot(episode);
    const office = before.marc.addresses[1];
    expect(marc.addresses).toEqual([
      before.marc.addresses[0],
      // A new province clears the province code; a blank company is no company.
      { ...office, address2: 'Suite 2500', company: null, province: 'Québec', provinceCode: null },
    ]);
    expect(marc.defaultAddressId).toBe(MARC.home);
    expect(Date.parse(now)).toBeGreaterThan(Date.parse(before.now));
  });

  it('reports a blank required line and changes nothing', async () => {
    const episode = 'address-update-blank';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerAddressUpdate: { customerUserErrors: readonly UserError[] };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressUpdate(
          customerAccessToken: "${token}"
          id: "${MARC.office}"
          address: { city: "", address2: "Suite 2500" }
        ) {
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressUpdate.customerUserErrors).toEqual([
      { code: 'BLANK', field: ['address', 'city'], message: "City can't be blank" },
    ]);
    expect(await marcInSnapshot(episode)).toEqual(before);
  });

  it("reports an address that is not the customer's as not found", async () => {
    const episode = 'address-update-not-found';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    // Address 1 is Jane's.
    const data = await mutate<{
      customerAddressUpdate: {
        customerAddress: AddressShape | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressUpdate(
          customerAccessToken: "${token}"
          id: "gid://shopify/MailingAddress/1"
          address: { address2: "Apt 5" }
        ) {
          customerAddress { id }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressUpdate).toEqual({
      customerAddress: null,
      customerUserErrors: [{ code: 'NOT_FOUND', field: ['id'], message: 'Address does not exist' }],
    });
    expect(await marcInSnapshot(episode)).toEqual(before);
  });

  it('turns down an unknown access token', async () => {
    const data = await mutate<{
      customerAddressUpdate: { customerUserErrors: readonly UserError[] };
    }>(
      'address-update-token',
      /* GraphQL */ `mutation {
        customerAddressUpdate(
          customerAccessToken: "not-a-token"
          id: "${MARC.office}"
          address: { address2: "Suite 2500" }
        ) {
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressUpdate.customerUserErrors).toEqual([UNIDENTIFIED_CUSTOMER]);
  });
});

describe('customerAddressDelete', () => {
  it('removes the address and moves the Episode clock', async () => {
    const episode = 'address-delete';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerAddressDelete: {
        deletedCustomerAddressId: string | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressDelete(customerAccessToken: "${token}", id: "${MARC.office}") {
          deletedCustomerAddressId
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressDelete).toEqual({
      deletedCustomerAddressId: MARC.office,
      customerUserErrors: [],
    });
    const { marc, now } = await marcInSnapshot(episode);
    expect(marc.addresses.map((address) => address.id)).toEqual([MARC.home]);
    expect(marc.defaultAddressId).toBe(MARC.home);
    expect(Date.parse(now)).toBeGreaterThan(Date.parse(before.now));
  });

  it('makes the first remaining address the default when the default goes', async () => {
    const episode = 'address-delete-default';
    const token = await login(episode);

    await mutate(
      episode,
      /* GraphQL */ `mutation {
        customerAddressDelete(customerAccessToken: "${token}", id: "${MARC.home}") {
          deletedCustomerAddressId
        }
      }`,
    );
    expect((await marcInSnapshot(episode)).marc.defaultAddressId).toBe(MARC.office);

    await mutate(
      episode,
      /* GraphQL */ `mutation {
        customerAddressDelete(customerAccessToken: "${token}", id: "${MARC.office}") {
          deletedCustomerAddressId
        }
      }`,
    );
    const { marc } = await marcInSnapshot(episode);
    expect(marc.addresses).toEqual([]);
    expect(marc.defaultAddressId).toBeNull();
  });

  it("reports an address that is not the customer's as not found", async () => {
    const episode = 'address-delete-not-found';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerAddressDelete: {
        deletedCustomerAddressId: string | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerAddressDelete(customerAccessToken: "${token}", id: "gid://shopify/MailingAddress/1") {
          deletedCustomerAddressId
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressDelete).toEqual({
      deletedCustomerAddressId: null,
      customerUserErrors: [{ code: 'NOT_FOUND', field: ['id'], message: 'Address does not exist' }],
    });
    expect(await marcInSnapshot(episode)).toEqual(before);
  });

  it('turns down an unknown access token', async () => {
    const data = await mutate<{
      customerAddressDelete: { customerUserErrors: readonly UserError[] };
    }>(
      'address-delete-token',
      /* GraphQL */ `mutation {
        customerAddressDelete(customerAccessToken: "not-a-token", id: "${MARC.office}") {
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerAddressDelete.customerUserErrors).toEqual([UNIDENTIFIED_CUSTOMER]);
  });
});

describe('customerDefaultAddressUpdate', () => {
  it('makes the address the default and moves the Episode clock', async () => {
    const episode = 'address-default';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerDefaultAddressUpdate: {
        customer: { defaultAddress: { id: string } | null } | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerDefaultAddressUpdate(customerAccessToken: "${token}", addressId: "${MARC.office}") {
          customer { defaultAddress { id } }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerDefaultAddressUpdate).toEqual({
      customer: { defaultAddress: { id: MARC.office } },
      customerUserErrors: [],
    });
    const { marc, now } = await marcInSnapshot(episode);
    expect(marc.defaultAddressId).toBe(MARC.office);
    expect(marc.addresses).toEqual(before.marc.addresses);
    expect(Date.parse(now)).toBeGreaterThan(Date.parse(before.now));
  });

  it("reports an address that is not the customer's as not found", async () => {
    const episode = 'address-default-not-found';
    const token = await login(episode);
    const before = await marcInSnapshot(episode);

    const data = await mutate<{
      customerDefaultAddressUpdate: {
        customer: { id: string } | null;
        customerUserErrors: readonly UserError[];
      };
    }>(
      episode,
      /* GraphQL */ `mutation {
        customerDefaultAddressUpdate(
          customerAccessToken: "${token}"
          addressId: "gid://shopify/MailingAddress/1"
        ) {
          customer { id }
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerDefaultAddressUpdate).toEqual({
      customer: null,
      customerUserErrors: [
        { code: 'NOT_FOUND', field: ['addressId'], message: 'Address does not exist' },
      ],
    });
    expect(await marcInSnapshot(episode)).toEqual(before);
  });

  it('turns down an unknown access token', async () => {
    const data = await mutate<{
      customerDefaultAddressUpdate: { customerUserErrors: readonly UserError[] };
    }>(
      'address-default-token',
      /* GraphQL */ `mutation {
        customerDefaultAddressUpdate(customerAccessToken: "not-a-token", addressId: "${MARC.office}") {
          customerUserErrors { code field message }
        }
      }`,
    );

    expect(data.customerDefaultAddressUpdate.customerUserErrors).toEqual([UNIDENTIFIED_CUSTOMER]);
  });
});
