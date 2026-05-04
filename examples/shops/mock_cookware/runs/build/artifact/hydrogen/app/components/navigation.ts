export type NavLinkItem = {label: string; url: string};

export type FeaturedCard = {
  title: string;
  handle: string;
  price: string;
  compareAt?: string;
  savings?: string;
  rating: number;
  imageUrl?: string;
};

export type FlyoutEntry = {
  kind: 'flyout';
  label: string;
  shopAllUrl: string;
  shopAllLabel: string;
  links: NavLinkItem[];
  featured: FeaturedCard[];
};

export type MegaCategoryColumn = {
  heading: string;
  headingUrl: string;
  links: NavLinkItem[];
};

export type MegaEntry = {
  kind: 'mega';
  label: string;
  quickLinks: NavLinkItem[];
  categories: MegaCategoryColumn[];
  productLine: {
    heading: string;
    headingUrl: string;
    links: NavLinkItem[];
  };
  colors: {label: string; swatch: string; url: string}[];
};

export type DirectEntry = {
  kind: 'link';
  label: string;
  url: string;
};

export type NavEntry = MegaEntry | FlyoutEntry | DirectEntry;

export const PRIMARY_NAV: NavEntry[] = [
  {
    kind: 'mega',
    label: 'Cookware',
    quickLinks: [
      {label: 'New Arrivals', url: '/collections/new-arrivals'},
      {label: 'Best Sellers', url: '/collections/best-sellers'},
      {label: 'Sale', url: '/collections/sale'},
    ],
    categories: [
      {
        heading: 'Frypans & Skillets',
        headingUrl: '/collections/frypans-skillets',
        links: [],
      },
      {
        heading: 'Saucepans',
        headingUrl: '/collections/saucepans',
        links: [],
      },
      {
        heading: 'Stockpots & Dutch Ovens',
        headingUrl: '/collections/stockpots-dutch-ovens',
        links: [],
      },
      {
        heading: 'Sauté Pans & Woks',
        headingUrl: '/collections/saute-pans-woks',
        links: [
          {label: 'Griddles', url: '/collections/griddles'},
        ],
      },
    ],
    productLine: {
      heading: 'Cookware Sets',
      headingUrl: '/collections/cookware-sets',
      links: [],
    },
    colors: [],
  },
  {
    kind: 'flyout',
    label: 'Knives',
    shopAllUrl: '/collections/knives',
    shopAllLabel: 'Shop All Knives',
    links: [
      {label: 'Knives', url: '/collections/knives'},
      {label: 'Knife Sets', url: '/collections/knife-sets'},
    ],
    featured: [
      {
        title: "Forged Chef's Knife, 10-inch",
        handle: 'forged-chefs-knife-10-inch',
        imageUrl: '/images/forged-chefs-knife-10-inch-13161.png',
        price: '$129',
        compareAt: '$159',
        savings: 'Save $30',
        rating: 5,
      },
      {
        title: '8-Piece Steak Knife Set',
        handle: '8-piece-steak-knife-set',
        imageUrl: '/images/8-piece-steak-knife-set-10781.png',
        price: '$189',
        rating: 4,
      },
    ],
  },
  {
    kind: 'flyout',
    label: 'Bakeware',
    shopAllUrl: '/collections/bakeware',
    shopAllLabel: 'Shop All Bakeware',
    links: [
      {label: 'Sheet Pans & Roasting Pans', url: '/collections/sheet-pans-roasting-pans'},
      {label: 'Cake & Loaf Pans', url: '/collections/cake-loaf-pans'},
    ],
    featured: [
      {
        title: 'Half-Sheet Baking Pan',
        handle: 'half-sheet-baking-pan',
        imageUrl: '/images/half-sheet-baking-pan-10941.png',
        price: '$32',
        rating: 5,
      },
      {
        title: 'Round Cake Pan, 9-inch',
        handle: 'round-cake-pan-9-inch',
        imageUrl: '/images/round-cake-pan-9-inch-10961.png',
        price: '$24',
        rating: 4,
      },
      {
        title: 'Standard Loaf Pan, 9×5-inch',
        handle: 'standard-loaf-pan-9x5-inch',
        imageUrl: '/images/standard-loaf-pan-9x5-inch-10951.png',
        price: '$22',
        rating: 4,
      },
    ],
  },
  {
    kind: 'flyout',
    label: 'Kitchen',
    shopAllUrl: '/collections/kitchen-tools-utensils',
    shopAllLabel: 'Shop All Kitchen',
    links: [
      {label: 'Tools & Utensils', url: '/collections/kitchen-tools-utensils'},
      {label: 'Cutting Boards & Prep', url: '/collections/cutting-boards-prep'},
      {label: 'Storage & Organization', url: '/collections/storage-organization'},
      {label: 'Aprons & Oven Mitts', url: '/collections/aprons-oven-mitts'},
    ],
    featured: [
      {
        title: 'Silicone Utensil Set, 6-Piece',
        handle: 'silicone-utensil-set-6-piece',
        imageUrl: '/images/silicone-utensil-set-6-piece-13251.png',
        price: '$48',
        compareAt: '$60',
        savings: 'Save $12',
        rating: 5,
      },
      {
        title: 'Bamboo Cutting Board, Large',
        handle: 'bamboo-cutting-board-large',
        imageUrl: '/images/bamboo-cutting-board-large-11401.png',
        price: '$36',
        rating: 4,
      },
    ],
  },
  {
    kind: 'link',
    label: 'Sale',
    url: '/collections/sale',
  },
];

export const UTILITY_LINKS: NavLinkItem[] = [
  {label: 'Recipes', url: '/blogs/journal'},
  {label: 'Brand Story', url: '/pages/about'},
  {label: 'Care Guide', url: '/pages/faq'},
];
