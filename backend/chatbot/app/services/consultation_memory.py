"""Select scoped memory and distinguish prompt input from verified tool use."""

import re
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from app.core.errors import UpstreamError
from app.models.conversation import ChatMemory
from app.schemas.catalog import CatalogProduct
from app.schemas.chat import ChatRequest
from app.schemas.memory import (
    AppliedColorMemory,
    AppliedMemory,
    AppliedOwnedProductMemory,
    ColorShadeMatch,
    ConsultationMemory,
)
from app.schemas.skincare_recommendation import SkincareToolInput
from app.services.g1_catalog_tool import validate_catalog_product
from app.services.memory_registry import (
    REGISTRY_VERSION,
    build_value,
    color_families_in,
    inventory_label_matches,
    normalize,
)

# Keep the current consultation cap until the search and context budget trials.
CONSULTATION_MEMORY_LIMIT = 20

_SKIN_TIGHTNESS = r"(?:피부|얼굴)(?:가|이|은|도)?\s*당[기길겨김긴]"
_TOPICS = {
    "lip": re.compile(r"립|입술|틴트|\b(?:lip|lips|lipstick|tint)\b|リップ|唇"),
    "cheek": re.compile(r"치크|블러셔|볼터치|\b(?:cheek|blush)\b|チーク|腮红"),
    "base": re.compile(r"베이스|파운데이션|쿠션|\b(?:base|foundation|cushion)\b|ベース|底妆|粉底"),
    "eye": re.compile(
        r"아이섀|눈\s*화장|아이라인|\b(?:eye shadow|eyeshadow|eyeliner)\b|アイメイク|眼妆"
    ),
    "skin": re.compile(
        rf"피부|건성|지성|복합성|스킨케어|보습\s*(?:제|크림)|{_SKIN_TIGHTNESS}|"
        r"유분\s*(?:관리|조절)|"
        r"\b(?:skin|skincare|moisturi[sz]er|oil[- ]control)\b|肌|肤|保湿|皮脂|控油"
    ),
    "color": re.compile(r"색|컬러|\b(?:colou?r|shade|coral|pink)\b|色|珊瑚"),
    "finish": re.compile(
        r"제형|마무리|매트|글로시|새틴|물광|\b(?:finish|matte|gloss|glossy|satin|dewy)\b|仕上げ|妆效"
    ),
    "owned": re.compile(
        r"보유|갖고\s*있|가지고\s*있|\b(?:i own|i already have|my products)\b|持って|我有"
    ),
}
_AREAS = frozenset(("lip", "cheek", "base", "eye"))
_WORK = re.compile(r"출근|직장|\b(?:for work|at work|office)\b|出勤|職場|上班|通勤")
_FOLLOW_UP = re.compile(
    r"다시|계속|아까|이어서|그중|추천해\s*줘|\b(?:again|continue|those)\b|さっき|再推荐"
)
_OWN_PREFERENCES = re.compile(
    r"(?:내|제|기존|저장한)\s*(?:취향|선호|기억)|"
    r"\b(?:my (?:saved )?(?:preference|preferences)|what you remember about me)\b|"
    r"私の好み|我的偏好"
)
_NO_MEMORY = re.compile(
    r"(?:취향|기억|선호).{0,15}(?:무시|쓰지\s*마|쓰지\s*말|반영하지|빼고|없이)|"
    r"\b(?:ignore|without|do not use|don't use).{0,15}(?:memory|preferences?)\b|"
    r"(?:好み|記憶).{0,10}(?:使わず|無視)|(?:偏好|记忆).{0,8}(?:不用|忽略)"
)
_EXPLICIT_RANK = re.compile(
    r"우선|정렬|최저가|저렴한\s*순|\b(?:sort|rank|cheapest|lowest price|prioritize)\b|"
    r"順|优先|排序"
)
_EXPLICIT_SKIN_TYPE = re.compile(
    r"건성|지성|복합성|중성|"
    r"\b(?:dry|oily|combination|balanced|normal)\s+skin\b|"
    r"\bskin(?:\s+type)?\s*(?:is\s+|:\s*)(?:dry|oily|combination|balanced|normal)\b|"
    r"乾燥肌|脂性肌|混合肌|普通肌|干[性皮]|油[性皮]|混合[性皮]|中[性皮]"
)
_KO_CURRENT_SKIN_TYPE = re.compile(
    r"(?:피부\s*(?:타입)?\s*[가는은이]|(?:저|나)는)\s*(건성|지성)"
    r"(?:이에요|예요|이야|입니다|이구요|이고|이라서|이라|이거든요|임|(?=[.!?,。！？]|$))"
)
_EXPLICIT_SHADE = re.compile(
    r"#(?:[0-9a-f]{6}|[0-9a-f]{3})\b|\d+\s*(?:호|号|番)|웜톤|쿨톤|\b(?:warm|cool)\b"
)
_OTHER_COLOR_WORDS = re.compile(
    r"오렌지|피치|살구|주황|베이지|라벤더|보라|장밋빛|말린\s*장미|자주|버건디|플럼|"
    r"빨강|빨간|붉은|분홍|갈색|로즈|검정|검은|하양|"
    r"\b(?:peach|orange|beige|lavender|purple|plum|burgundy|mauve|rose|fuchsia|crimson)\b|"
    r"オレンジ|ピーチ|ベージュ|紫|橙|米色"
)
_OTHER_PERSON = re.compile(
    r"친구|엄마|어머니|아빠|아버지|동생|언니|남편|아내|선물|가족|다른\s*사람|"
    r"\b(?:friend|mom|mother|dad|father|sibling|sister|brother|wife|husband|gift|someone else)\b|"
    r"友達|友人|母|父|プレゼント|朋友|妈妈|爸爸|送给"
)
_SKINCARE_GOALS = {
    "dryness": re.compile(
        rf"보습|수분\s*공급|{_SKIN_TIGHTNESS}|"
        r"\b(?:hydrat\w*|moisturi[sz]\w*)\b|保湿"
    ),
    "oiliness": re.compile(r"(?:유분|피지)\s*(?:조절|관리)|번들거림|\boil[- ]control\b|皮脂|控油"),
}
_SKINCARE_GOAL_OPTOUT = re.compile(
    r"(?:보습|유분\s*(?:관리|조절))\s*(?:은|는|을|를)?\s*(?:말고|제외|빼고)|"
    r"\b(?:no|without|skip)\s+(?:hydration|moisturi[sz]\w*|oil[- ]control)\b"
)
_RECOMMENDATION_OPTOUT = re.compile(
    r"추천(?:은|을)?\s*(?:하지\s*마|말고|없이)|"
    r"\b(?:do not|don't|no)\s+recommend(?:ations?)?\b|おすすめは不要|不要推荐"
)
InventoryMode = Literal["include", "exclude"]
_OWNED_ONLY = re.compile(
    r"(?:보유한|보유\s*제품|갖고\s*있는|가지고\s*있는|(?:내가|제가)\s*가진|이미\s*(?:있는|가진)).{0,24}"
    r"(?:\b중\b|중에서|안에서|내에서|제품만|만(?=\s|추천|$)|만으로|제품으로)|"
    r"\b(?:from|among|only)\s+(?:the\s+)?(?:\w+\s+){0,5}"
    r"(?:i already (?:own|have)|i own|my saved products)\b|"
    r"\b(?:recommend|suggest|pick)\s+(?:what|products|items)\s+i (?:already )?(?:own|have)\b|"
    r"持っている.{0,16}(?:から|の中)|从我(?:已|已经)?有的.{0,16}(?:里|中)"
)
_OWNED_EXCLUDE = re.compile(
    r"(?:보유한|보유\s*제품|갖고\s*있는|가지고\s*있는|(?:내가|제가)\s*가진|이미\s*(?:있는|산|가진))"
    r".{0,24}(?:제외|빼고|말고)|"
    r"\b(?:exclude|skip|leave out|except|other than)\s+(?:the\s+)?"
    r"(?:\w+\s+){0,5}(?:i already (?:own|have)|i own|my saved products)\b|"
    r"\bwithout\s+(?:the\s+)?(?:products|items|what)\s+i (?:already )?(?:own|have)\b|"
    r"持っている.{0,16}(?:以外|除いて)|(?:排除|不要)我(?:已|已经)?有的"
)
_INVENTORY_SEARCH = re.compile(r"추천|골라|찾아|\b(?:recommend|suggest|pick|find)\b|おすすめ|推荐")
_prompt_refs: ContextVar[dict[str, int] | None] = ContextVar("memory_prompt_refs", default=None)


@contextmanager
def capture_prompt_dependencies():
    used = {}
    token = _prompt_refs.set(used)
    try:
        yield used
    finally:
        _prompt_refs.reset(token)


def prompt_memories(request: ChatRequest, *, planning: bool = False) -> list:
    entries = request._consultation_memories
    if entries is None:
        return request._consented_memories
    if planning:
        return []
    used = _prompt_refs.get()
    result = []
    for entry in entries:
        if used is not None:
            used[str(entry.id)] = entry.version
        if entry.text is not None:
            result.append(entry.text)
        elif entry.structured is not None:
            memory = entry.structured
            result.append(
                {
                    "key": memory.key,
                    "value": {
                        key: value
                        for key, value in memory.value.items()
                        if key not in {"productId", "shadeId"}
                    },
                    "context": memory.context,
                }
            )
    return result


def _topics(text: str) -> set[str]:
    return {key for key, pattern in _TOPICS.items() if pattern.search(text)}


def ignores_memory(message: str) -> bool:
    return bool(_NO_MEMORY.search(normalize(message)))


def _inventory_intent(text: str) -> InventoryMode | None:
    if (
        not _INVENTORY_SEARCH.search(text)
        or _NO_MEMORY.search(text)
        or _OTHER_PERSON.search(text)
        or _RECOMMENDATION_OPTOUT.search(text)
    ):
        return None
    if _OWNED_EXCLUDE.search(text):
        return "exclude"
    if _OWNED_ONLY.search(text):
        return "include"
    return None


def inventory_mode(request: ChatRequest) -> InventoryMode | None:
    if (
        not request.structured_memory
        or request._g7_execution is None
        or request.style_context
        or request.screen_context
        or request.style_search
    ):
        return None
    return _inventory_intent(normalize(request.message))


def verified_inventory_matches(
    request: ChatRequest,
    products: list[CatalogProduct],
    mode: InventoryMode,
    *,
    match_names: bool,
) -> tuple[list[AppliedOwnedProductMemory], bool]:
    entries = [
        entry
        for entry in request._consultation_memories or ()
        if entry.structured and entry.structured.key == "inventory.product"
    ]
    if not entries:
        return [], False
    counts = Counter(product.id for product in products)
    valid = {}
    for product in products:
        if counts[product.id] != 1:
            continue
        try:
            validate_catalog_product(product)
        except UpstreamError:
            continue
        valid[product.id] = product

    matches = []
    for entry in entries:
        draft = entry.structured
        product_id = draft.value.get("productId")
        shade_id = draft.value.get("shadeId")
        if not product_id and match_names:
            candidates = [
                (product.id, shade)
                for product in products
                for shade in inventory_label_matches(
                    draft.value["productName"], product, require_brand=True
                )
            ]
            if len(candidates) == 1:
                product_id, shade_id = candidates[0]
        product = valid.get(product_id)
        if product is None or (
            shade_id is not None and not any(shade.id == shade_id for shade in product.shades)
        ):
            continue
        matches.append(
            AppliedOwnedProductMemory(
                memory_id=entry.id,
                version=entry.version,
                action=mode,
                product_id=product.id,
                shade_id=shade_id,
            )
        )
    return matches, len(matches) != len(entries)


def skincare_recommendation_request(
    request: ChatRequest,
) -> tuple[ConsultationMemory | None, SkincareToolInput] | None:
    text = normalize(request.message)
    if (
        _EXPLICIT_RANK.search(text)
        or _OTHER_PERSON.search(text)
        or _SKINCARE_GOAL_OPTOUT.search(text)
        or _RECOMMENDATION_OPTOUT.search(text)
    ):
        return None
    goals = [goal for goal, pattern in _SKINCARE_GOALS.items() if pattern.search(text)]
    if not goals:
        return None
    explicit = set(_EXPLICIT_SKIN_TYPE.findall(text))
    if explicit:
        current = _KO_CURRENT_SKIN_TYPE.search(text) if request._server_history else None
        if current and explicit == {current[1]}:
            return None, SkincareToolInput(
                goals=goals, skin_type="dry" if current[1] == "건성" else "oily"
            )
        return None
    if not request._consultation_memories or ignores_memory(text):
        return None
    matches = [
        (entry, entry.structured.value["type"])
        for entry in request._consultation_memories
        if entry.structured and entry.structured.key == "skin.type" and not entry.structured.context
    ]
    if len(matches) != 1:
        return None
    memory, skin_type = matches[0]
    # V4 attributes a profile goal to dry and oily. Other types lack that evidence.
    if skin_type not in {"dry", "oily"}:
        return None
    return memory, SkincareToolInput(goals=goals, skin_type=skin_type)


def select_consultation_memories(
    request: ChatRequest, rows: list[ChatMemory]
) -> tuple[ConsultationMemory, ...]:
    text = normalize(request.message)
    if ignores_memory(text):
        return ()
    current = _topics(text)
    if _inventory_intent(text):
        current.add("owned")
    topics = current
    work = bool(_WORK.search(text))
    if not current and _FOLLOW_UP.search(text):
        for message in reversed(request.recent_messages):
            if message.role == "user" and (recent := _topics(normalize(message.text))):
                topics = recent
                break
    prefs = bool(_OWN_PREFERENCES.search(text))
    ranked = []
    for row in rows:
        if row.consent_scope != "future_consultations" or row.revoked_at is not None:
            continue
        draft = None
        raw = None
        target_topics = set()
        contextual = False
        explicit_product = False
        if row.schema_version == 1:
            value = row.value_json
            if (
                not isinstance(value, dict)
                or set(value) != {"text"}
                or not isinstance(value["text"], str)
                or not 1 <= len(value["text"]) <= 500
            ):
                continue
            raw = value["text"]
            raw_normalized = normalize(raw)
            if _NO_MEMORY.search(raw_normalized):
                continue
            target_topics = _topics(raw_normalized)
            contextual = bool(_WORK.search(raw_normalized))
        elif row.schema_version == 2 and row.registry_version == REGISTRY_VERSION:
            try:
                draft = build_value(
                    row.semantic_key,
                    row.value_json,
                    request.locale,
                    row.applicability_json.get("context"),
                )
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
            if draft.kind != row.kind:
                continue
            contextual = draft.context is not None
            if draft.key == "skin.type":
                target_topics = {"skin", "base"}
            elif draft.key == "inventory.product":
                target_topics = {"owned"}
                if normalize(draft.value["productName"]) in text:
                    explicit_product = True
            else:
                target_topics = {
                    draft.value["area"],
                    "color" if draft.key == "makeup.color" else "finish",
                }
        else:
            continue
        if contextual and not work:
            continue
        if (topics & _AREAS) and (target_topics & _AREAS) and not topics & target_topics & _AREAS:
            continue
        if raw is not None and row.kind == "owned_product" and "owned" not in topics and not prefs:
            continue
        if not prefs and not explicit_product and not target_topics & topics:
            continue
        ranked.append(
            (
                (bool(target_topics & current), contextual, row.updated_at, str(row.id)),
                ConsultationMemory(id=row.id, version=row.version, text=raw, structured=draft),
            )
        )
    ranked.sort(key=lambda value: value[0], reverse=True)
    return tuple(entry for _, entry in ranked[:CONSULTATION_MEMORY_LIMIT])


def _catalog_preference(request, category, key):
    work = bool(_WORK.search(normalize(request.message)))
    matches = [
        entry
        for entry in request._consultation_memories or ()
        if entry.structured
        and entry.structured.key == key
        and entry.structured.value["area"] == category
        and (not entry.structured.context or work)
    ]
    contextual = [entry for entry in matches if entry.structured.context]
    matches = contextual or matches
    return matches[0] if len(matches) == 1 else None


def _color_preference(request, category, text):
    if (
        category not in {"lip", "cheek"}
        or _OTHER_PERSON.search(text)
        or _EXPLICIT_SHADE.search(text)
        or _OTHER_COLOR_WORDS.search(text)
        or color_families_in(text)
    ):
        return None
    return _catalog_preference(request, category, "makeup.color")


def has_catalog_color_preference(request: ChatRequest) -> bool:
    if not request._consultation_memories:
        return False
    text = normalize(request.message)
    if ignores_memory(text) or _EXPLICIT_RANK.search(text) or _RECOMMENDATION_OPTOUT.search(text):
        return False
    return any(
        _TOPICS[area].search(text) and _color_preference(request, area, text)
        for area in ("lip", "cheek")
    )


def _matching_color_shade(product, family):
    if (product.category, product.makeup_zone) not in {("lip", "lip"), ("cheek", "blush")}:
        return None
    if len({shade.id for shade in product.shades}) != len(product.shades):
        return None
    named = None
    for shade in product.shades:
        if (
            not shade.id.strip()
            or len(shade.id) > 128
            or shade.product_id not in {None, product.id}
            or "placeholder" in (shade.measure_method, shade.color_source)
        ):
            continue
        if shade.color_family is not None:
            if shade.color_family != family:
                continue
            basis = shade.measure_method
            if basis not in {"measured", "user_verified", "estimated"}:
                continue
            if basis == "estimated" and shade.color_source not in {
                "option_chip",
                "color_compare",
                "official_hex",
            }:
                continue
            return ColorShadeMatch(product_id=product.id, shade_id=shade.id, basis=basis)
        if (
            named is None
            and color_families_in(shade.name) == {family}
            and not _OTHER_COLOR_WORDS.search(normalize(shade.name))
        ):
            named = ColorShadeMatch(product_id=product.id, shade_id=shade.id, basis="catalog_name")
    return named


def rank_catalog_by_memory(
    request: ChatRequest,
    products: list[CatalogProduct],
    category: str | None,
    visible_limit: int,
    *,
    allow_matte: bool = True,
    allow_color: bool = True,
) -> tuple[list[CatalogProduct], list[AppliedMemory | AppliedColorMemory]]:
    text = normalize(request.message)
    if (
        not request._consultation_memories
        or ignores_memory(text)
        or _EXPLICIT_RANK.search(text)
        or _RECOMMENDATION_OPTOUT.search(text)
    ):
        return products[:visible_limit], []
    matte = (
        _catalog_preference(request, category, "makeup.finish")
        if allow_matte and category in {"lip", "base"} and not _TOPICS["finish"].search(text)
        else None
    )
    if matte is not None and matte.structured.value["finish"] != "matte":
        matte = None

    def matte_rank(product):
        return matte is not None and (product.category != category or product.texture != "matte")

    preferred = sorted(products, key=matte_rank) if matte else products
    applied = []
    if matte and preferred[:visible_limit] != products[:visible_limit]:
        applied.append(AppliedMemory(memory_id=matte.id, version=matte.version))
    color = _color_preference(request, category, text) if allow_color else None
    if color is None:
        return preferred[:visible_limit], applied
    matches = {
        product.id: shade
        for product in preferred
        if product.category == category
        and (shade := _matching_color_shade(product, color.structured.value["family"]))
    }
    visible = sorted(preferred, key=lambda p: (matte_rank(p), p.id not in matches))[:visible_limit]
    before = {product.id: index for index, product in enumerate(preferred)}
    moved = [
        matches[product.id]
        for index, product in enumerate(visible)
        if product.id in matches and index < before[product.id]
    ]
    if moved:
        applied.append(AppliedColorMemory(memory_id=color.id, version=color.version, matches=moved))
    return visible, applied


def visible_memory_evidence(payload: dict, active_versions: dict[str, int]) -> dict:
    evidence = payload.get("appliedMemories")
    if evidence is None:
        return payload
    result = {key: value for key, value in payload.items() if key != "appliedMemories"}
    if isinstance(evidence, list):
        checked = [
            item
            for item in evidence
            if isinstance(item, dict)
            and isinstance(item.get("memoryId"), str)
            and type(item.get("version")) is int
            and active_versions.get(item["memoryId"]) == item["version"]
        ]
        if checked:
            result["appliedMemories"] = checked
    return result
