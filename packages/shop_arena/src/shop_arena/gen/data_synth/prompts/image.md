# `image.md` — `gen_images` OpenAI prompt template (spec §5.1.1)

Rendered once per `(handle, index)` pair by
`shop_arena.gen.data_synth.images._openai_backend.OpenAIImageBackend`. Format
placeholders: `{title}`, `{category}`. The template ends with the fixed
brand-safety hard-constraint suffix (lines 1-5) — that suffix is the
v0.2 spec's only defense against pixel-level brand leakage and is part
of `prompt_version` in the cache key, so editing any of those rules
must come with a `prompt_version` bump.

---
A photorealistic product photograph of "{title}", a {category} item.

Center the product in the frame against a clean, unbranded background.
Soft, even studio lighting. Sharp focus on the product. Natural color
balance. No props beyond what the product needs to be understood.

Brand-safety hard constraints (apply to every image):

1. Render NO text, glyphs, letters, numbers, or wordmarks of any kind
   on, near, or behind the product. Plain unbranded surfaces only.
2. Avoid every recognizable third-party logo, badge, monogram, or
   trademark. When in doubt, omit.
3. Treat any apparent brand name surfaced from the product title as a
   generic placeholder and replace it with an unbranded equivalent
   (a generic athletic shoe).
4. Avoid identifiable real-world products (e.g. iPhone, Coca-Cola
   bottle, IKEA Billy bookshelf) and use a generic equivalent of the
   same product category instead.
5. Do not generate human faces, celebrities, or recognizable real
   people. People may appear only as backs / silhouettes / partial
   body without identifiable faces.
