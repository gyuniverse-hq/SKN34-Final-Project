"""Validate and display the first server-owned structured memory keys."""

import re
import unicodedata

from app.schemas.catalog import CatalogProduct
from app.schemas.memory import MemoryKey, StructuredMemoryValue

REGISTRY_VERSION = 1

_LABELS = {
    "dry": ("건성", "Dry", "乾燥肌", "干性"),
    "oily": ("지성", "Oily", "脂性肌", "油性"),
    "combination": ("복합성", "Combination", "混合肌", "混合性"),
    "balanced": ("중성", "Balanced", "普通肌", "中性"),
    "red": ("레드", "Red", "レッド", "红色"),
    "coral": ("코랄", "Coral", "コーラル", "珊瑚色"),
    "pink": ("핑크", "Pink", "ピンク", "粉色"),
    "berry": ("베리", "Berry", "ベリー", "莓果色"),
    "nude": ("누드", "Nude", "ヌード", "裸色"),
    "brown": ("브라운", "Brown", "ブラウン", "棕色"),
    "matte": ("매트", "Matte", "マット", "哑光"),
    "satin": ("새틴", "Satin", "サテン", "缎光"),
    "glossy": ("글로시", "Glossy", "グロッシー", "亮泽"),
    "dewy": ("물광", "Dewy", "ツヤ", "水光"),
    "lip": ("립", "Lip", "リップ", "唇"),
    "cheek": ("치크", "Cheek", "チーク", "腮红"),
    "base": ("베이스", "Base", "ベース", "底妆"),
}
_EXTRA = {
    "lip": ("입술", "lipstick", "lip tint", "口红"),
    "cheek": ("블러셔", "볼터치", "blush"),
    "base": ("파운데이션", "foundation", "ファンデーション", "粉底"),
}
_SKIN = ("dry", "oily", "combination", "balanced")
_COLORS = ("red", "coral", "pink", "berry", "nude", "brown")
_FINISHES = {"lip": ("matte", "satin", "glossy"), "base": ("matte", "dewy")}
_KINDS = {
    "skin.type": "profile",
    "makeup.color": "preference",
    "makeup.finish": "preference",
    "inventory.product": "owned_product",
}
_VALUE_FIELDS = {
    "skin.type": "type",
    "makeup.color": "family",
    "makeup.finish": "finish",
    "inventory.product": "productName",
}
_LOCALES = ("ko", "en", "ja", "zh")
_WORK_LABEL = ("출근할 때", "For work", "出勤時", "上班时")
_UNVERIFIED = ("상품 미확인", "Catalog match unverified", "商品未確認", "商品未核实")
_UNCERTAIN = re.compile(
    r"친구|엄마|어머니|아빠|동생|언니|가정|아닌|(?<![가-힣])아니|"
    r"\b(?:friend|mother|sister|brother|hypothetical|pretend|not|maybe|might|if)\b|"
    r"友達|友人|母が|仮定|ではない|朋友|妈妈|假设|不是"
)
_TRANSIENT = re.compile(
    r"오늘|이번(?:에는|만|\s*주말|\s*여행)|당분간|까지|내일|"
    r"\b(?:today|tomorrow|until|temporarily)\b|"
    r"今日|明日|まで|今天|明天|暂时|为止"
)
_WORK = re.compile(r"출근|직장|\b(?:for work|at work|office)\b|出勤|職場|上班|通勤")
_PREFERENCE = re.compile(
    r"좋아|선호|\b(?:i like|i prefer|i love|my favorite)\b|好き|好み|喜欢|偏好"
)
_NEGATIVE = re.compile(r"안\s*좋아|좋아하지\s*않|싫어|기피|don't like|do not like|嫌い|不喜欢")
_SELF_SKIN = re.compile(
    r"나는|저는|내\s*피부|제\s*피부|피부\s*타입|\b(?:i have|i am|i'm|my skin|skin type)\b|"
    r"私|肌質|肌は|我|肤质"
)
_OWNED = (
    re.compile(r"(?P<name>.+?)(?:을|를)\s*(?:(?:이미|지금)\s*)?(?:갖고|가지고|보유하고)\s*있"),
    re.compile(r"\bi\s+(?:own|already have)\s+(?P<name>.+)", re.I),
    re.compile(r"(?:私は)?(?P<name>.+?)を(?:持っています|持っている|持ってる)"),
    re.compile(r"(?:我(?:已经)?有)(?P<name>.+)"),
)
_REMEMBER = re.compile(
    r"(?:기억해\s*(?:줘|주세요|둬|두세요)|\b(?:please\s+remember|remember\s+(?:that|this|my))\b"
    r"|覚えて(?:おいて|ください)|(?:请)?记住)",
    re.I,
)
_PRIOR = re.compile(
    r"방금\s*(?:말한|얘기한)|직전에\s*말한|\b(?:what i just said|my last message)\b|"
    r"さっき言った|刚才说的"
)
_SENSITIVE_PRODUCT_NAME = re.compile(
    r"주민등록|여권|비밀번호|카드번호|계좌번호|인증번호|"
    r"password|passport|social security|credit card|otp|"
    r"パスワード|クレジットカード|身份证|密码|银行卡|"
    r"\S+@\S+\.\S+|(?:\d[ -]?){8,}",
    re.I,
)


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def is_explicit_request(text: str) -> bool:
    normalized = normalize(text)
    return bool(_REMEMBER.search(normalized)) and not bool(
        re.search(r"기억하지\s*마|(?:don't|do not|never)\s+remember|不要记住|覚えない", normalized)
    )


def refers_to_prior(text: str) -> bool:
    return bool(_PRIOR.search(normalize(text)))


def _matches(text: str, value: str) -> bool:
    for spelling in (*_LABELS[value], *_EXTRA.get(value, ())):
        token = normalize(spelling)
        if token.isascii():
            if re.search(rf"\b{re.escape(token)}\b", text):
                return True
        elif token in text:
            return True
    return False


def _label(value: str, locale: str) -> str:
    return _LABELS[value][_LOCALES.index(locale)]


def color_families_in(text: str) -> set[str]:
    normalized = normalize(text)
    return {family for family in _COLORS if _matches(normalized, family)}


def editable(draft: StructuredMemoryValue, locale: str) -> tuple[str, list[tuple[str, str]]]:
    key = draft.key
    value = draft.value
    codes = {
        "skin.type": _SKIN,
        "makeup.color": _COLORS,
        "makeup.finish": _FINISHES.get(value.get("area", ""), ()),
        "inventory.product": (),
    }[key]
    return value[_VALUE_FIELDS[key]], [(code, _label(code, locale)) for code in codes]


def build_value(
    key: MemoryKey,
    value: dict[str, str],
    locale: str,
    context: str | None = None,
) -> StructuredMemoryValue:
    expected = {
        "skin.type": {"type"},
        "makeup.color": {"area", "family"},
        "makeup.finish": {"area", "finish"},
        "inventory.product": {"productName"},
    }[key]
    field = _VALUE_FIELDS[key]
    item = value.get(field, "")
    area = value.get("area", "")
    if key == "inventory.product":
        if (
            not expected <= value.keys()
            or not value.keys() <= expected | {"productId", "shadeId", "optionId"}
            or (("shadeId" in value or "optionId" in value) and "productId" not in value)
            or (
                "optionId" in value
                and (not value["optionId"].strip() or len(value["optionId"]) > 128)
            )
            or not item.strip()
            or len(item) > 500
            or _SENSITIVE_PRODUCT_NAME.search(item)
            or any(not part.isprintable() for part in item)
        ):
            raise ValueError("Invalid owned product")
        item = item.strip()
        value = {**value, field: item}
        label = item if "productId" in value else f"{item} ({_UNVERIFIED[_LOCALES.index(locale)]})"
    else:
        allowed = {
            "skin.type": _SKIN,
            "makeup.color": _COLORS if area in {"lip", "cheek"} else (),
            "makeup.finish": _FINISHES.get(area, ()),
        }[key]
        if set(value) != expected or item not in allowed:
            raise ValueError("Invalid structured memory value")
        label = f"{_label(area, locale)} · {_label(item, locale)}" if area else _label(item, locale)
    if context == "work":
        label = f"{_WORK_LABEL[_LOCALES.index(locale)]} · {label}"
    return StructuredMemoryValue(
        key=key, kind=_KINDS[key], value=value, display_value=label, context=context
    )


def edited_value(
    draft: StructuredMemoryValue, new_value: str, locale: str
) -> StructuredMemoryValue:
    new_value = new_value.strip()
    key = draft.key
    if new_value == draft.value[_VALUE_FIELDS[key]]:
        return draft
    value = (
        {"productName": new_value}
        if key == "inventory.product"
        else {**draft.value, _VALUE_FIELDS[key]: new_value}
    )
    return build_value(key, value, locale, draft.context)


def inventory_label_matches(
    label: str,
    product: CatalogProduct,
    *,
    require_brand: bool = False,
) -> list[str | None]:
    def exact(value: str) -> str:
        return " ".join(normalize(value).split())

    name = exact(label)
    brand = product.brand.strip()
    names = {
        exact(f"{brand} {label}")
        for label in (product.name, product.name_ko)
        if brand and label.strip()
    }
    if not require_brand:
        names.update(exact(label) for label in (product.name, product.name_ko))
    names.discard("")
    matches: list[str | None] = [None] if name in names else []
    matches.extend(
        shade.id
        for shade in product.shades
        if shade.name.strip() and any(name == f"{label} {exact(shade.name)}" for label in names)
    )
    return matches


def with_verified_product(
    draft: StructuredMemoryValue, product: CatalogProduct, locale: str
) -> StructuredMemoryValue:
    matches = inventory_label_matches(draft.value["productName"], product)
    if len(matches) != 1:
        return draft
    value = {**draft.value, "productId": product.id}
    if matches[0] is not None:
        value["shadeId"] = matches[0]
    return build_value(draft.key, value, locale, draft.context)


def with_verified_option(draft, product, option, locale):
    if option is None or option.product_id != product.id:
        return draft
    label = normalize(draft.value["productName"])
    deictic = label in {
        normalize(v) for v in ("이 옵션", "이 상품 옵션", "선택한 옵션", "this option")
    }
    exact = label == normalize(f"{product.name} {option.name}")
    if not (deictic or exact):
        return draft
    value = {
        "productName": f"{product.name} {option.name}",
        "productId": product.id,
        "optionId": option.option_id,
    }
    if option.ar_shade_id and any(s.id == option.ar_shade_id for s in product.shades):
        value["shadeId"] = option.ar_shade_id
    return build_value(draft.key, value, locale, draft.context)


def extract_values(text: str, locale: str) -> list[StructuredMemoryValue]:
    drafts = []
    for clause in re.split(r"[,;.!?。！？；，\n]+|(?:\s+(?:and|그리고)\s+)", text, flags=re.I):
        clause = _REMEMBER.sub("", clause).strip(" \t\"'“”‘’")
        normalized = normalize(clause)
        if not normalized or _UNCERTAIN.search(normalized) or _TRANSIENT.search(normalized):
            continue
        context = "work" if _WORK.search(normalized) else None
        if _SELF_SKIN.search(normalized):
            skin = [value for value in _SKIN if _matches(normalized, value)]
            if len(skin) == 1:
                drafts.append(build_value("skin.type", {"type": skin[0]}, locale, context))
        if _PREFERENCE.search(normalized) and not _NEGATIVE.search(normalized):
            areas = [area for area in ("lip", "cheek", "base") if _matches(normalized, area)]
            if len(areas) == 1:
                area = areas[0]
                if area in {"lip", "cheek"}:
                    for value in _COLORS:
                        if _matches(normalized, value):
                            drafts.append(
                                build_value(
                                    "makeup.color", {"area": area, "family": value}, locale, context
                                )
                            )
                for value in _FINISHES.get(area, ()):
                    if _matches(normalized, value):
                        drafts.append(
                            build_value(
                                "makeup.finish", {"area": area, "finish": value}, locale, context
                            )
                        )
        for pattern in _OWNED:
            if match := pattern.search(clause):
                name = match["name"].strip(" \t\"'“”‘’")
                if (
                    name
                    and len(name) <= 500
                    and name.isprintable()
                    and not _SENSITIVE_PRODUCT_NAME.search(name)
                ):
                    drafts.append(build_value("inventory.product", {"productName": name}, locale))
                break
    return drafts
