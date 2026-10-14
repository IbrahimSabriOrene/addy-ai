"""Versioned catalogue; preview rights and live quality validation remain pending."""
from copy import deepcopy

from admaker.presets import PRESETS

CATEGORIES = {
    "beauty": "Beauty & Skincare", "food": "Food & Drinks",
    "fashion": "Fashion & Accessories", "home": "Home & Decor", "tech": "Tech & Gadgets",
    "jewelry": "Jewelry", "gifts": "Gifts & Handmade", "pets": "Pet Accessories",
}

# Reuse existing creative instructions and stable preset IDs.
TEMPLATES = {
    key: {"id": key, "version": 1, "name": preset.name,
          "categories": list(CATEGORIES), "outputKinds": ["video", "photo"],
          "prompt": preset.prompt_template, "validated": False, "preview": None}
    for key, preset in PRESETS.items()
}

for key, categories in {
    "pedestal_spin": ["beauty", "fashion", "home", "tech"],
    "unboxing_pan": ["fashion", "tech"],
    "lifestyle_zoom": ["food", "fashion", "home"],
    "feature_pop": ["beauty", "tech"],
}.items():
    TEMPLATES[key]["categories"] = categories

# Original prompts remain unchanged for saved version-1 selections.
# New creative definitions are implementation candidates, not validated provider samples.
for key, name, categories, modes, prompt in (
    ("clean_studio", "Clean Studio", ["beauty", "fashion", "home", "tech"], ["photo"],
     "A single {product} on a clean studio background, soft contact shadow and neutral lighting. Preserve the product pixels, shape, color and readable label; edit only the surroundings where practical."),
    ("floating_petals", "Floating Petals", ["beauty"], ["photo", "video"],
     "A single {product} surrounded by sparse floating petals against a soft pastel background. Keep petals away from the product and label; gentle motion and quiet natural ambience."),
    ("fresh_pour", "Fresh Pour", ["food"], ["video"],
     "A single {product} remains upright and unchanged beside a separate glass receiving a fresh pour. Slow camera movement, realistic liquid sound, no invented ingredients or health claims."),
    ("ingredient_still", "Ingredient Still Life", ["food"], ["photo"],
     "A single {product} on a clean tabletop with soft daylight and restrained food photography styling. Do not invent ingredients or add food that implies an unverified ingredient; preserve the packaging and label."),
    ("luxury_spotlight", "Luxury Spotlight", ["fashion", "beauty"], ["photo", "video"],
     "A single {product} against a dark studio background with a controlled soft spotlight and subtle reflections. Preserve exact product shape and color; gentle camera movement with understated instrumental ambience."),
    ("soft_daylight", "Soft Daylight", ["home", "beauty"], ["photo", "video"],
     "A single {product} in a minimal room with soft window daylight and natural shadows. Keep the product unobstructed and unchanged, subtle camera push-in and calm room ambience."),
    ("neon_reveal", "Neon Reveal", ["tech"], ["video"],
     "A single {product} revealed by restrained neon light in a dark studio. Slow camera arc, preserve product geometry and original markings, soft electronic ambience without speech."),
    ("detail_closeup", "Detail Close-up", ["fashion", "tech"], ["photo", "video"],
     "A close view of the visible surface details of a single {product}. Do not invent unseen parts or alter materials, branding or proportions; shallow depth of field, slow camera motion and quiet ambience."),
):
    TEMPLATES[key] = {"id": key, "version": 1, "name": name, "categories": categories,
                      "outputKinds": modes, "prompt": prompt, "validated": False, "preview": None}


# Branding previews: original server-owned directions, never sent in the public catalogue.
for key, name, category, direction in (('skincare_glow', 'Studio glow', 'beauty', 'A restrained studio orbit with soft window lighting and gentle reflections. Quiet original instrumental ambience.'), ('jewelry_detail', 'Fine details', 'jewelry', 'A slow lateral macro slide showing visible craftsmanship and material detail. Soft neutral background and quiet original instrumental ambience.'), ('bakery_morning', 'Freshly baked', 'food', 'A gentle push-in under warm morning light showing the visible food texture. Quiet original instrumental ambience, no invented ingredients.'), ('coffee_ritual', 'Coffee ritual', 'food', 'A slow cinematic push-in on a warm walnut counter with amber backlight. Quiet cafe room tone and original instrumental ambience.'), ('leather_editorial', 'Leather editorial', 'fashion', 'A short lateral camera slide around a stationary product on a cream stone block, soft directional side lighting reveals surface texture. Original understated instrumental ambience.'), ('candle_dusk', 'After dusk', 'home', 'A very slow camera arc in a cozy dusk setting, warm practical light against cool shadows. Only animate an existing visible flame if the reference includes one. Quiet original ambient music.'), ('gift_unwrap', 'Gift reveal', 'gifts', 'A smooth overhead-to-three-quarter camera drift around the existing product arrangement on a warm cream surface, diffuse light reveals the visible textures. Do not invent box contents or packaging. Original delicate piano ambience.'), ('tech_light', 'Light reveal', 'tech', 'A slow quarter-orbit in a dark studio with a restrained cyan light sweep and realistic reflections. Original minimal electronic sound design.'), ('pet_boutique', 'Everyday essentials', 'pets', 'A gentle close-to-medium camera pullback on a sand-colored tabletop with soft leaf shadows. Original acoustic instrumental ambience.')):
    TEMPLATES[key] = {"id": key, "version": 1, "name": name, "categories": [category],
                      "outputKinds": ["photo", "video"], "validated": False, "preview": None,
                      "prompt": "Professional branding composition featuring the supplied {product}. " + direction + " Preserve the reference product count, silhouette, materials, color and markings. No people, hands, animals, speech, invented claims, added logos or generated typography. For a still image, express the lighting and composition without motion. For video, use one continuous restrained shot ending on a clear hero frame. Leave room for campaign text to be added separately."}


# Editor scenes are reference-image edits, not grading filters. Version these
# independently so reopening a saved command never changes its creative intent.
for key, name, scene in (
    ("editor_lifestyle", "Lifestyle", "Place the product on a warm natural stone surface in a believable small interior. Soft window daylight, a softly defocused neutral room, restrained natural styling and realistic contact shadows."),
    ("editor_studio", "Studio", "Place the product on a seamless light-gray studio sweep. Broad diffused softbox lighting, neutral white balance, crisp material detail and a soft contact shadow. No props."),
    ("editor_minimal", "Minimal", "Place the product on a matte ivory plane against an uninterrupted ivory background. Generous negative space, a single soft directional shadow, quiet geometric composition. No props, pedestal, pattern or decoration."),
    ("editor_editorial", "Editorial", "Place the product on a dark polished stone plinth against a deep charcoal background. Controlled directional side lighting, restrained reflections and rich tonal contrast without changing the product's actual color. Premium still-life composition."),
):
    TEMPLATES[key] = {
        "id": key, "version": 1, "name": name, "categories": list(CATEGORIES),
        "outputKinds": ["photo"], "validated": False, "preview": None,
        "prompt": "Re-stage the supplied {product} in a new photographic scene. " + scene
        + " Use the reference as the product identity source. Preserve the reference product count, silhouette, proportions, materials, colors, label and markings. Keep the entire product visible and unobstructed. Change the surroundings and lighting, not the product design. Do not invent unseen details, accessories, packaging, ingredients or claims. No people, hands, animals, additional logos or generated text. Produce one coherent photograph, not a collage or comparison grid.",
    }


# Independent video IDs preserve the photo-only version-1 contracts above.
for scene in ("lifestyle", "studio", "minimal", "editorial"):
    photo = TEMPLATES["editor_" + scene]
    TEMPLATES["editor_" + scene + "_video"] = {
        **deepcopy(photo), "id": "editor_" + scene + "_video", "name": photo["name"] + " video",
        "outputKinds": ["video"],
        "prompt": photo["prompt"].replace("Produce one coherent photograph, not a collage or comparison grid.",
            "Create one continuous branding shot with a restrained slow camera push-in. Keep the product stationary and fully visible. No cuts, morphing or product transformations. Add quiet original instrumental ambience without speech. End on a clear hero frame."),
    }


def catalogue_items(category: str | None = None, output_kind: str | None = None) -> list[dict]:
    if category is not None and category not in CATEGORIES:
        raise ValueError("unsupported category")
    if output_kind is not None and output_kind not in {"photo", "video"}:
        raise ValueError("unsupported output kind")
    return [deepcopy({key: value for key, value in item.items() if key != "prompt"})
            for item in TEMPLATES.values()
            if (category is None or category in item["categories"])
            and (output_kind is None or output_kind in item["outputKinds"])]


def require_template(template_id: str, version: int, output_kind: str) -> dict:
    template = TEMPLATES.get(template_id)
    if not template or template["version"] != version or output_kind not in template["outputKinds"]:
        raise ValueError("unsupported template, version or output kind")
    return deepcopy(template)
