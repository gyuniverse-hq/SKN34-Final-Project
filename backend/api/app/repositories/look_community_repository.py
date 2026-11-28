import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.look_community import LookPost, LookPostContent, LookPostViewer, ReportedLookPost

_POST = """
SELECT p.id, p.title, p.display_name, p.description, p.products, p.created_at, p.hidden,
       p.owner_id IS NULL AS example,
       p.example_votes + (SELECT count(*) FROM look_post_votes v WHERE v.post_id = p.id) AS votes
FROM look_posts p
"""


class LookCommunityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def feed(self, offset: int, popular: bool, owner: str | None) -> list[LookPost]:
        where = "p.owner_id = :owner" if owner else "NOT p.hidden"
        order = "votes DESC, " if popular and owner is None else ""
        rows = await self.session.execute(
            text(
                f"{_POST} WHERE {where} ORDER BY {order}p.created_at DESC, p.id "
                "LIMIT 20 OFFSET :offset"
            ),
            {"owner": owner, "offset": offset},
        )
        return [LookPost.model_validate(row) for row in rows.mappings()]

    async def detail(self, post_id: UUID, owner: str | None = None) -> LookPost | None:
        rows = await self.session.execute(
            text(f"{_POST} WHERE p.id = :id AND (NOT p.hidden OR p.owner_id = :owner)"),
            {"id": post_id, "owner": owner},
        )
        row = rows.mappings().one_or_none()
        return LookPost.model_validate(row) if row else None

    async def image(self, post_id: UUID, include_hidden: bool = False) -> bytes | None:
        return await self.session.scalar(
            text("SELECT photo FROM look_posts WHERE id = :id AND (NOT hidden OR :include_hidden)"),
            {"id": post_id, "include_hidden": include_hidden},
        )

    async def is_member(self, owner: str) -> bool:
        return bool(
            await self.session.scalar(
                text("SELECT 1 FROM members WHERE id = :owner FOR KEY SHARE"), {"owner": owner}
            )
        )

    async def owned(self, post_id: UUID, owner: str) -> bool:
        return bool(
            await self.session.scalar(
                text("SELECT 1 FROM look_posts WHERE id = :id AND owner_id = :owner"),
                {"id": post_id, "owner": owner},
            )
        )

    async def viewer(self, post_id: UUID, member: str) -> LookPostViewer | None:
        rows = await self.session.execute(
            text("""
                SELECT COALESCE(p.owner_id = :member, false) AS owned,
                       EXISTS (SELECT 1 FROM look_post_votes WHERE post_id = p.id
                               AND member_id = :member) AS recommended,
                       EXISTS (SELECT 1 FROM look_post_reports WHERE post_id = p.id
                               AND member_id = :member) AS reported
                FROM look_posts p WHERE p.id = :id AND NOT p.hidden
            """),
            {"id": post_id, "member": member},
        )
        row = rows.mappings().one_or_none()
        return LookPostViewer.model_validate(row) if row else None

    async def save(
        self,
        post_id: UUID,
        owner: str | None,
        content: LookPostContent,
        photo: bytes | None,
        *,
        create: bool,
    ) -> bool:
        values = {
            "id": post_id,
            "owner": owner,
            "title": content.title,
            "display_name": content.display_name,
            "set_display_name": "display_name" in content.model_fields_set,
            "description": content.description,
            "products": json.dumps(content.model_dump(by_alias=True)["products"]),
            "photo": photo,
        }
        if create:
            query = """INSERT INTO look_posts
                           (id, owner_id, title, display_name, description, products, photo)
                       VALUES (:id, :owner, :title, :display_name, :description,
                               CAST(:products AS jsonb), :photo)
                       ON CONFLICT (id) DO NOTHING RETURNING id"""
        else:
            photo_update = ", photo = :photo" if photo is not None else ""
            query = f"""UPDATE look_posts SET title = :title, description = :description,
                        display_name = CASE WHEN :set_display_name THEN :display_name
                                            ELSE display_name END,
                        products = CAST(:products AS jsonb){photo_update}
                        WHERE id = :id AND owner_id = :owner AND NOT hidden RETURNING id"""
        return bool(await self.session.scalar(text(query), values))

    async def delete(self, post_id: UUID, owner: str) -> bool:
        return bool(
            await self.session.scalar(
                text("DELETE FROM look_posts WHERE id = :id AND owner_id = :owner RETURNING id"),
                {"id": post_id, "owner": owner},
            )
        )

    async def interact(self, post_id: UUID, owner: str, reason: str | None) -> bool:
        result = await self.session.execute(
            text("SELECT owner_id FROM look_posts WHERE id = :id AND NOT hidden FOR UPDATE"),
            {"id": post_id},
        )
        target = result.one_or_none()
        if target is None or target[0] == owner:
            return False
        query = (
            "INSERT INTO look_post_votes (post_id, member_id) "
            "VALUES (:id, :owner) ON CONFLICT DO NOTHING"
            if reason is None
            else "INSERT INTO look_post_reports (post_id, member_id, reason) "
            "VALUES (:id, :owner, :reason) ON CONFLICT DO NOTHING"
        )
        await self.session.execute(text(query), {"id": post_id, "owner": owner, "reason": reason})
        return True

    async def reported(self, offset: int) -> list[ReportedLookPost]:
        rows = await self.session.execute(
            text(f"""
            SELECT posts.*, reports.reasons FROM ({_POST}) posts
            JOIN LATERAL (
                SELECT array_agg(reason ORDER BY member_id) AS reasons
                FROM (SELECT reason, member_id FROM look_post_reports WHERE post_id = posts.id
                      ORDER BY member_id LIMIT 50) bounded
            ) reports ON reports.reasons IS NOT NULL
            ORDER BY posts.hidden, posts.created_at DESC, posts.id LIMIT 20 OFFSET :offset
        """),
            {"offset": offset},
        )
        return [ReportedLookPost.model_validate(row) for row in rows.mappings()]

    async def set_hidden(self, post_id: UUID, hidden: bool) -> bool:
        return bool(
            await self.session.scalar(
                text("UPDATE look_posts SET hidden = :hidden WHERE id = :id RETURNING id"),
                {"id": post_id, "hidden": hidden},
            )
        )
