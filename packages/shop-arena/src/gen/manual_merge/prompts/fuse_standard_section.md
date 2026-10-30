You are fusing the observed notes of a Live storefront into the
`## {{section}}` section of a shop's Standard sub-manual.

The Standard sub-manual describes, by the Shopify standard, the account,
checkout and order confirmation pages of a sandbox shop. The shop's
storefront already has these pages. A build agent restyles them from this
section, and uses its labels word for word. The observed notes come from
an anonymized Shop Manual of a Live storefront. They describe how that
storefront shows the same area.

Rules:

1. Observed notes win on labels, layout and wording. The notes and the
   standard text can disagree on a heading, a label, the order of the
   fields, the columns, or the text of a message. Then use the observed
   version, and remove the standard version.
2. The shop's backend supports only the behavior in "Supported behavior"
   below. When the notes describe behavior that is not in that list (for
   example passwordless login with a one-time code, social login, or
   express payment buttons), keep the standard text for that part. Do not
   describe a control or a page for that behavior, and do not mention it.
3. Keep each label and message in "Checked labels" below word for word, in
   double quotes, also when the notes use a different text for it. Browser
   steps find the pages' controls by these texts. `<...>` in a checked
   label is part of it: keep it as it is.
4. Keep the parts of the standard text that the notes do not describe:
   the routes, the flows, the form fields, the messages and the redirects.
5. Keep the conventions of the standard text: text in double quotes is an
   exact label or message, and `<...>` is a value from the Dataset or from
   the Episode state. Put every label you take from the notes in double
   quotes.
6. Keep the `###` subheadings of the standard text, and add `###`
   subheadings only for new layout details. Do not write a `#` or `##`
   heading.
7. Do not add the name of a real company, brand, product or trademark
   that the standard text does not already have.

## Standard text of `## {{section}}`

{{standard_section}}

## Observed notes for `## {{section}}`

{{observed_section}}

## Supported behavior

{{supported_behavior}}

## Checked labels

{{checked_labels}}

Output: the fused section body for `## {{section}}`. No commentary, no
`##` heading, no fenced wrappers. End with a single newline.
