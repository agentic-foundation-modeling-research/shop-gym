# visual_fix

Cross-task cleanup pass:

- Shared `Header` component is now imported by every route shell.
- Design tokens defined in `app/styles/theme.css` are referenced from
  the home route (no token drift).
- Internal links resolved against `data/navigation.json`.
- Deferred verifier feedback: none outstanding.
