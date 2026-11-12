"""Deterministic Style Tool: catalog facts and explicit general guides, no video/LLM analysis."""

import json
import re
from hashlib import sha256
from math import isfinite

from app.core.errors import UpstreamError
from app.schemas.chat import ChatResponse, ProductRef
from app.schemas.style_recipe import RecipeProduct, RecipeStep, StyleContext, StyleRecipe
from app.schemas.supervisor import EvidenceRef, ToolResult

ORDER = (
    "foundation",
    "brow",
    "eyeshadow",
    "eyeliner",
    "mascara",
    "blush",
    "contour",
    "highlighter",
    "lip",
)
PAINT = {"foundation", "brow", "eyeshadow", "eyeliner", "blush", "lip"}
NAMES = {
    "ko": (
        "베이스",
        "눈썹",
        "아이섀도",
        "아이라인",
        "마스카라",
        "블러셔",
        "윤곽",
        "하이라이터",
        "립",
    ),
    "en": (
        "Base",
        "Brows",
        "Eyeshadow",
        "Eyeliner",
        "Mascara",
        "Blush",
        "Contour",
        "Highlighter",
        "Lips",
    ),
    "ja": (
        "ベース",
        "眉",
        "アイシャドウ",
        "アイライン",
        "マスカラ",
        "チーク",
        "シェーディング",
        "ハイライト",
        "リップ",
    ),
    "zh": ("底妆", "眉毛", "眼影", "眼线", "睫毛膏", "腮红", "修容", "高光", "唇妆"),
}
TEXT = {
    "ko": {
        "zone_missing": (
            "이 룩에는 확인 가능한 눈 화장 단계가 없습니다. "
            "다른 룩이나 등록된 단계를 선택해 주세요."
        ),
        "choose": "먼저 스타일 화면에서 안내받을 룩을 선택해 주세요.",
        "missing": "선택한 종류에서 해당 룩을 찾을 수 없습니다. 룩을 다시 선택해 주세요.",
        "error": "룩 자료를 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        "video": (
            "제목·태그·제품 부위 메타데이터를 참고한 일반 가이드입니다. 영상 프"
            "레임을 분석하지 않았으며, 실제 영상의 기법·순서·사용 제품은 확인되"
            "지 않았습니다."
        ),
        "catalog": (
            "등록된 Catalog 메이크업 설정에 근거한 규칙 "
            "기반 가이드입니다. 사람이 검수한 영상 레시피는 아"
            "닙니다."
        ),
        "reviewed": "등록된 검수 레시피의 단계와 출처를 안내합니다.",
        "changed": "룩 또는 레시피 버전이 변경되어 첫 단계로 돌아갔습니다.",
        "none": "단계 자료가 부족합니다. 영상의 화장 순서를 추측하지 않습니다.",
        "step": "현재 단계",
        "synthetic": "테스트용 합성 콘텐츠입니다.",
        "unsupported": (
            "현재 단계 안내와 등록 상품 확인을 지원합니다. 상"
            "품 추천·AR 실행을 함께 완료한 것으로 처리하지 "
            "않습니다."
        ),
    },
    "en": {
        "zone_missing": (
            "This look has no available eye step. Select another look or a listed step."
        ),
        "choose": "Choose a look on the style screen first.",
        "missing": "This look was not found in the selected source. Please select it again.",
        "error": "Look data could not be retrieved. Please try again later.",
        "video": (
            "This is general guidance based on titl"
            "e, tags and product-area metadata. Vid"
            "eo frames were not analyzed; the video"
            "'s actual techniques, order and produc"
            "ts are unconfirmed."
        ),
        "catalog": (
            "This rule-based guide uses registered "
            "Catalog makeup settings. It is not a h"
            "uman-reviewed video recipe."
        ),
        "reviewed": "These steps come from the registered reviewed recipe and its source.",
        "changed": "The look or recipe version changed. Progress returned to the first step.",
        "none": ("Step information is insufficient. The video's makeup order will not be guessed."),
        "step": "Current step",
        "synthetic": "Synthetic test content.",
        "unsupported": (
            "Step guidance and registered product r"
            "eferences are supported. Product recom"
            "mendation and AR execution have not be"
            "en completed together."
        ),
    },
    "ja": {
        "zone_missing": (
            "このルックには確認できるアイメイク手順がありません。別の"
            "ルックか登録手順を選んでください。"
        ),
        "choose": "まずスタイル画面でルックを選択してください。",
        "missing": "選択した種類にこのルックがありません。選び直してください。",
        "error": "ルック資料を取得できませんでした。後でもう一度お試しください。",
        "video": (
            "タイトル・タグ・製品部位のメタデータに基づく一般的なガイ"
            "ドです。動画フレームは解析していません。実際の技法・順序"
            "・使用製品は未確認です。"
        ),
        "catalog": (
            "登録されたCatalogメイク設定に基づくルール型ガイド"
            "です。人が検証した動画レシピではありません。"
        ),
        "reviewed": "登録された検証済みレシピの手順と出典を案内します。",
        "changed": "ルックまたはレシピの版が変わったため、最初の手順に戻りました。",
        "none": "手順の情報が不足しています。動画の順序を推測しません。",
        "step": "現在の手順",
        "synthetic": "テスト用の合成コンテンツです。",
        "unsupported": (
            "手順案内と登録製品の確認に対応しています。製品推薦とAR"
            "実行を一括で完了したとは扱いません。"
        ),
    },
    "zh": {
        "zone_missing": "此妆容没有可确认的眼妆步骤，请选择其他妆容或已列出的步骤。",
        "choose": "请先在风格页面选择妆容。",
        "missing": "所选来源中没有此妆容，请重新选择。",
        "error": "无法查询妆容资料，请稍后重试。",
        "video": (
            "这是基于标题、标签和产品部位元数据的一般指南。未分析视频"
            "帧，视频中的实际技法、顺序和使用产品尚未确认。"
        ),
        "catalog": "这是依据已登记Catalog化妆设置生成的规则指南，并非人工审核的视频教程。",
        "reviewed": "以下步骤来自已登记的审核教程及其来源。",
        "changed": "妆容或教程版本已改变，已返回第一步。",
        "none": "步骤资料不足，不会猜测视频的化妆顺序。",
        "step": "当前步骤",
        "synthetic": "合成测试内容。",
        "unsupported": "目前支持步骤指导和已登记产品查询，不会将产品推荐和AR执行视为已一并完成。",
    },
}


GRADIENT_LIP_GUIDE = {
    "ko": (
        "입술 전체에 연한 색을 얇게 바르고, 진한 색은 입술 안쪽에만 찍어 주세요. "
        "손가락이나 면봉으로 색이 만나는 경계를 가볍게 두드려 풀어 주세요."
    ),
    "en": (
        "Apply a thin layer of a light shade over the lips. Dab a deeper shade on the inner lips, "
        "then tap the boundary lightly with a fingertip or cotton swab to blend it."
    ),
    "ja": (
        "唇全体に淡い色を薄く塗り、内側だけに濃い色をのせます。"
        "色の境目を指先や綿棒で軽くたたいてぼかします。"
    ),
    "zh": "先在整个唇部薄涂浅色，再把深色点涂在唇内侧，用指尖或棉签轻拍晕开两色的交界。",
}


def source_zone(value):
    value = value.casefold()
    aliases = {
        "foundation": ("foundation", "베이스", "파운데이션", "base"),
        "brow": ("brow", "눈썹", "아이브로"),
        "eyeshadow": ("shadow", "섀도", "쉐도"),
        "eyeliner": ("eyeliner", "아이라인", "아이라이너"),
        "mascara": ("mascara", "마스카라"),
        "blush": ("blush", "블러셔", "치크", "cheek"),
        "contour": ("contour", "쉐딩", "셰딩", "윤곽"),
        "highlighter": ("highlighter", "하이라이터"),
        "lip": ("lip", "립", "입술"),
    }
    return next((zone for zone, terms in aliases.items() if any(t in value for t in terms)), None)


# General techniques, independent of what the source video actually shows.
TIPS = {
    "ko": {
        "eyeliner": (
            "얇은 펜슬로 속눈썹 뿌리 사이를 짧은 점으로 채워 보세요. 눈을 뜬 "
            "상태에서 꼬리 길이를 확인하고, 면봉으로 끝을 살짝 풀면 경계가 부드러워져요."
        ),
        "eyeshadow": (
            "작은 블렌딩 브러시에 색을 조금만 묻혀 눈두덩 바깥쪽부터 얇게 "
            "올리세요. 깨끗한 브러시로 경계를 작게 원을 그리며 펴 주세요."
        ),
        "lip": (
            "입술 안쪽에 색을 조금씩 올리고 손가락이나 립 브러시로 바깥쪽을 "
            "향해 두드리세요. 더 진하게 하고 싶으면 안쪽만 한 번 덧발라요."
        ),
        "cheek": (
            "브러시의 여분을 털고 뺨에 색을 조금씩 올리세요. 깨끗한 "
            "스펀지로 가장자리를 톡톡 두드리면 경계가 자연스러워져요."
        ),
        "mascara": (
            "브러시 끝의 여분을 닦고 속눈썹 뿌리부터 얇게 쓸어 올리세요."
            " 마르기 전에 깨끗한 스크루 브러시로 뭉친 부분을 풀어 주세요."
        ),
        "base": (
            "스펀지로 얼굴 중앙부터 얇게 펴고 필요한 부분에만 "
            "조금씩 덧발라요. 턱과 헤어라인의 경계도 두드려 정리하세요."
        ),
    },
    "en": {
        "eyeliner": (
            "Use a fine pencil to dot between the upper lashes. Check the "
            "tail with your eye open, then soften its edge with a cotton swab."
        ),
        "eyeshadow": (
            "Use a small blending brush and build a thin layer from the "
            "outer lid. Soften the edge with a clean brush in small circles."
        ),
        "lip": (
            "Tap a little color onto the inner lips and blend outward with a fingertip "
            "or lip brush. Add another layer only to the center for more depth."
        ),
        "cheek": (
            "Tap excess blush off the brush and build color slowly."
            " Press a clean sponge over the edges to soften them."
        ),
        "mascara": (
            "Wipe excess off the wand, brush from the roots, and "
            "separate clumps with a clean spoolie before they dry."
        ),
        "base": (
            "Use a sponge to spread a thin layer from the center of the face,"
            " build only where needed, and tap along the jaw and hairline."
        ),
    },
    "ja": {
        "eyeliner": (
            "細いペンシルでまつ毛の間を点で埋めます。"
            "目を開けて目尻の長さを確認し、綿棒で端をぼかします。"
        ),
        "eyeshadow": (
            "小さなブラシで目尻側から薄く重ね、"
            "きれいなブラシで境目を小さく円を描くようにぼかします。"
        ),
        "lip": (
            "唇の内側に少量をのせ、指やリップブラシで外側へぼかします。"
            "濃くしたいときは中央だけ重ねます。"
        ),
        "cheek": "ブラシの粉を落としてから少しずつ色をのせ、きれいなスポンジで境目をぼかします。",
        "mascara": (
            "ブラシの余分を拭き取り、根元から薄く塗ります。"
            "乾く前に清潔なスクリューブラシで毛束をほぐします。"
        ),
        "base": (
            "スポンジで顔の中央から薄く広げ、必要な所だけ重ねます。"
            "あごと生え際の境目も軽くたたきます。"
        ),
    },
    "zh": {
        "eyeliner": "用细眼线笔在上睫毛根部点涂填空。睁眼确认眼尾长度，再用棉签轻轻晕开边缘。",
        "eyeshadow": "用小号晕染刷从眼尾薄薄上色，再用干净的刷子画小圈晕开边缘。",
        "lip": "少量唇色点在内侧，用指腹或唇刷向外拍开。想加深时只在中央叠涂。",
        "cheek": "抖掉刷上多余的腮红，少量叠涂，再用干净的海绵轻拍边缘。",
        "mascara": "擦掉刷头多余膏体，从睫毛根部薄刷，趁未干用干净的螺旋刷梳开结块。",
        "base": "用海绵从面部中央薄薄推开，只在需要的位置叠涂，再轻拍下颌与发际线的边缘。",
    },
}

_ADVICE = re.compile(
    r"어떻게|하려면|하면|도구|팁|자연스럽|쉽게|브러시|방법|요령|대처법|\bhow\b"
    r"|tips?|which brush|what (?:tool|brush)"
    r"|自然に|コツ|道具|どう|怎么|怎样|如何|工具|自然",
    re.I,
)
_ADVICE_ZONES = {
    "eyeliner": r"아이라인|eyeliner|アイライン|眼线",
    "eyeshadow": r"섀도|눈 화장|eyeshadow|eye makeup|アイシャドウ|アイメイク|眼影|眼妆",
    "lip": r"입술|립|lip|リップ|唇",
    "cheek": r"볼터치|블러셔|blush|チーク|腮红",
    "mascara": r"마스카라|mascara|マスカラ|睫毛膏",
    "base": r"베이스|파운데이션|foundation|ベース|底妆",
}


_SMUDGING = re.compile(r"번지|번져|번짐|번질|smudg|transfer|にじ|滲|晕染|晕开|脱妆", re.I)
_EYELINER_SMUDGE_TIP = {
    "ko": "아이라인 번짐을 줄이려면 눈가 유분을 먼저 가볍게 닦고, 얇게 그린 뒤 완전히 말려 주세요.",
    "en": "To reduce smudging, gently blot oil around the eye, draw a thin line, and let it dry.",
    "ja": "にじみを防ぐには、目元の皮脂を軽く押さえ、細く描いてしっかり乾かします。",
    "zh": "想减少眼线晕染，可以先轻轻吸去眼周油脂，画细一点并等它完全干透。",
}
_GENERAL_TIP_NOTICE = {
    "ko": "일반 팁입니다. 영상에서 이 방법을 썼는지는 확인되지 않았습니다.",
    "en": "This is a general tip. Its use in the video has not been verified.",
    "ja": "一般的なコツです。動画で使われた方法かどうかは未確認です。",
    "zh": "这是一般技巧，尚未确认视频中是否采用了这种方法。",
}


def style_advice(message, steps, index, locale, followup):
    if not (_ADVICE.search(message) or _SMUDGING.search(message)) or re.search(
        r"영상에서|in the video|動画では|视频里", message, re.I
    ):
        return None
    zone = next(
        (zone for zone, pattern in _ADVICE_ZONES.items() if re.search(pattern, message, re.I)),
        steps[index].zone if steps and followup else None,
    )
    zone = "cheek" if zone == "blush" else zone
    if zone == "eyeliner" and _SMUDGING.search(message):
        return _EYELINER_SMUDGE_TIP[locale]
    return TIPS[locale].get(zone)


async def execute_style(req, catalog):
    text, context = TEXT[req.locale], req.style_context

    def empty(status, reason, key):
        return ChatResponse(answer=text[key], products=[], style_status=status), ToolResult(
            tool="style", status="error" if status == "error" else "clarification", reason=reason
        )

    if context is None:
        if re.search(
            r"그라데이션\s*립|gradient\s+lips?|ombre\s+lips?|グラデーションリップ|渐变唇|咬唇",
            req.message.casefold(),
        ):
            return ChatResponse(
                answer=GRADIENT_LIP_GUIDE[req.locale], products=[], style_status="ready"
            ), ToolResult(tool="style", status="success", reason="general_guide")
        return empty("clarification", "look_required", "choose")
    if catalog is None:
        return empty("error", "catalog_unavailable", "error")
    try:
        look = await catalog.get_style_look(context.kind, context.look_id)
        if look is None:
            return empty("not_found", "look_not_found", "missing")
        if look.id != context.look_id:
            raise UpstreamError("Look identity mismatch")
        digest = sha256(
            json.dumps(look.model_dump(mode="json"), sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()[:24]
        recipe_id = f"{context.kind}:{look.id}"
        recipe = look.recipe
        if recipe and (recipe.look_id != look.id or recipe.kind != context.kind):
            raise UpstreamError("Recipe belongs to a different look")
        reviewed = recipe is not None and recipe.review_status == "verified"
        names = dict(zip(ORDER, NAMES[req.locale], strict=True))
        makeup = None
        if context.kind == "video":
            basis, notice, source = "video_metadata", "video", look.video_url
            zones = {source_zone(p.zone + " " + p.category) for p in look.products}
            features = [v for v in (look.title, look.group, look.tag) if v]
            order = list(ORDER)
        else:
            basis, notice, source = "catalog_settings", "catalog", f"catalog:/api/looks/{look.id}"
            makeup = {z: look.makeup[z] for z in ORDER if look.makeup.get(z) is not None}
            for setting in makeup.values():
                if not isinstance(setting, dict) or not re.fullmatch(
                    r"#[0-9A-Fa-f]{6}", str(setting.get("hex", ""))
                ):
                    raise UpstreamError("Invalid makeup setting")
                if setting.get("geometry") is not None and not isinstance(
                    setting["geometry"], dict
                ):
                    raise UpstreamError("Invalid makeup geometry")
                geometry = setting.get("geometry") or {}
                numeric = [
                    setting.get("intensity"),
                    *[
                        geometry.get(k)
                        for k in (
                            "angle",
                            "length",
                            "thickness",
                            "intensity",
                            "blushSize",
                            "overlip",
                        )
                    ],
                ]
                if any(
                    v is not None
                    and (isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v))
                    for v in numeric
                ):
                    raise UpstreamError("Invalid guide numbers")
                areas = geometry.get("areas")
                if areas is not None and (
                    not isinstance(areas, list)
                    or any(a not in ("forehead", "nose_bridge", "under_eye", "chin") for a in areas)
                ):
                    raise UpstreamError("Invalid highlighter areas")
                if geometry.get("blushPlacement") not in (None, "apple", "under_eye", "side"):
                    raise UpstreamError("Invalid blush placement")
            zones = set(makeup)
            order = list(dict.fromkeys([z for z in look.step_order if z in ORDER] + list(ORDER)))
            features = [
                look.title,
                *[f"{names[z]}: {makeup[z]['hex']}" for z in order if z in makeup],
            ]
        steps = [
            RecipeStep(order=i + 1, zone=z, title=names[z], guide_key=z)
            for i, z in enumerate(z for z in order if z in zones)
        ]
        if reviewed:
            basis, notice, source = "reviewed_recipe", "reviewed", recipe.source
            steps, features = recipe.steps, recipe.features
        version = (recipe.version + ":" if reviewed else "guide-v1:") + digest
        changed = (context.recipe_id is not None and context.recipe_id != recipe_id) or (
            context.recipe_version is not None and context.recipe_version != version
        )
        index = 0 if changed else min(context.current_step, max(0, len(steps) - 1))
        message = req.message.casefold()
        eye_request = re.search(r"눈 화장|eye makeup|アイメイク|眼妆", message)
        if eye_request and not any(s.zone in {"eyeshadow", "eyeliner", "mascara"} for s in steps):
            return empty("clarification", "eye_step_unavailable", "zone_missing")
        tip = style_advice(message, steps, index, req.locale, context.recipe_id is not None)
        if not changed and not tip and not _ADVICE.search(message):
            if re.search(
                r"첫 단계|처음 단계|처음부터|first step|from the beginning|最初|第一步|从头",
                message,
            ):
                index = 0
            elif re.search(r"마지막 단계|last step|最後|最后一步", message):
                index = max(0, len(steps) - 1)
            elif re.search(r"다음\s*단계|\bnext(?: step)?[.!?]?$|次の手順|次へ|下一步", message):
                index = min(index + 1, max(0, len(steps) - 1))
            elif re.search(
                r"이전\s*단계|\bprevious(?: step)?[.!?]?$|前の手順|前へ|上一步", message
            ):
                index = max(0, index - 1)
            elif eye_request and not _ADVICE.search(message):
                index = next(
                    (
                        i
                        for i, s in enumerate(steps)
                        if s.zone in {"eyeshadow", "eyeliner", "mascara"}
                    ),
                    index,
                )
        links, refs, cache = [], {}, {}
        entries = look.products if context.kind == "video" else look.items
        lip_question = re.search(r"립 제품|lip product|リップ製品|唇部产品", message)
        for entry in entries:
            video = context.kind == "video"
            pid = entry.catalog_product_id if video else entry.product_id
            sid = entry.catalog_shade_id if video else entry.shade_id
            verified = entry.mapping_verified if video else True
            zone = source_zone(entry.zone + " " + entry.category) if video else None
            if video and lip_question and zone != "lip":
                continue
            link = RecipeProduct(
                label=f"{entry.brand} {entry.name}" if video else pid, zone=zone or "unknown"
            )
            if pid and verified:
                if pid not in cache:
                    cache[pid] = await catalog.get_product(pid)
                product = cache[pid]
                if product is not None and product.id == pid:
                    link.product_id = product.id
                    link.label = f"{product.brand} {product.name}"
                    link.zone = product.makeup_zone or zone or "unknown"
                    refs[pid] = ProductRef(
                        id=pid, brand=product.brand, name=product.name, category=product.category
                    )
                    shade = next((s for s in product.shades if s.id == sid), None)
                    if shade is not None:
                        link.shade_id, link.catalog_valid, link.mapping_status = (
                            sid,
                            True,
                            "verified",
                        )
                        link.ar_eligible = bool(
                            product.makeup_zone in PAINT
                            and product.texture
                            in {"matte", "velvet", "glossy", "satin", "sheer", "cream", "shimmer"}
                            and re.fullmatch(r"#[0-9A-Fa-f]{6}", shade.hex)
                            and (not video or zone is None or zone == product.makeup_zone)
                            and shade.measure_method != "placeholder"
                            and shade.color_source != "placeholder"
                        )
                    elif sid:
                        link.mapping_status = "invalid"
                else:
                    link.mapping_status = "invalid"
            links.append(link)
        result = StyleRecipe(
            look_id=look.id,
            source_look_id=look.id,
            kind=context.kind,
            recipe_id=recipe_id,
            recipe_version=version,
            title=look.title,
            basis=basis,
            review_status="verified"
            if reviewed
            else "unreviewed"
            if context.kind == "video"
            else "not_applicable",
            synthetic=recipe.synthetic if reviewed else False,
            source=source,
            evidence_id=recipe.evidence_id if reviewed else None,
            features=features,
            steps=steps,
            current_step=index,
            products=links,
            ar_eligible=any(p.ar_eligible for p in links),
            reason="recipe_changed"
            if changed
            else "no_steps"
            if not steps
            else "reviewed_recipe"
            if reviewed
            else "catalog_settings"
            if context.kind == "catalog"
            else "video_not_analyzed",
            makeup=makeup,
        )
        answer = tip or text[notice]
        if tip and context.kind == "video":
            answer += "\n" + _GENERAL_TIP_NOTICE[req.locale]
        if result.synthetic:
            answer += "\n" + text["synthetic"]
        if changed:
            answer += "\n" + text["changed"]
        if not steps:
            answer += "\n" + text["none"]
        next_context = StyleContext(
            kind=context.kind,
            look_id=look.id,
            recipe_id=recipe_id,
            recipe_version=version,
            current_step=index,
        )
        response = ChatResponse(
            answer=answer,
            products=list(refs.values()),
            style_recipe=result,
            style_context=next_context,
            style_status="ready",
        )
        return response, ToolResult(
            tool="style",
            status="success" if reviewed else "partial",
            product_ids=list(refs),
            evidence=[
                EvidenceRef(
                    product_id=p.product_id,
                    shade_id=p.shade_id,
                    source="catalog_api",
                    verification="verified" if p.catalog_valid else "partial",
                    reason="catalog_selection_checked_not_video_analysis",
                )
                for p in links
                if p.product_id
            ],
            reason=result.reason,
        )
    except (UpstreamError, ValueError, TypeError, AttributeError):
        return empty("error", "style_source_unavailable", "error")
