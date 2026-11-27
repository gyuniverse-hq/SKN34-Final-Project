import asyncio
import json
import os
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.auth import AuthUser, require_user
from app.core.db import get_session
from app.core.errors import ApiError, install_error_handlers
from app.routers.look_community import ADMIN, PUBLIC, router
from app.services.admin_auth_service import admin_user
from app.services.look_community_service import prepare_public_photo

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_public_photo_applies_orientation_and_strips_metadata():
    with Image.open(BytesIO(prepare_public_photo(sample_photo()))) as photo:
        assert photo.format == "JPEG"
        assert photo.size == (24, 16)
        assert len(photo.getexif()) == 0


def sample_photo():
    photo = Image.new("RGB", (16, 24), "pink")
    data = BytesIO()
    exif = photo.getexif()
    exif[274] = 6
    exif[315] = "Private name"
    photo.save(data, "JPEG", exif=exif)
    return data.getvalue()


@pytest.mark.integration
@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set")
def test_community_post_lifecycle():
    owner, reader = str(uuid4()), str(uuid4())
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    async_session = async_sessionmaker(engine)

    async def session():
        async with async_session() as db:
            yield db

    def member(x_member: str | None = Header(None)):
        if not x_member:
            raise ApiError(401, "Sign in")
        return AuthUser(id=x_member, email=None)

    def staff(x_staff: str | None = Header(None)):
        if x_staff != "yes":
            raise ApiError(403, "Staff only")

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides = {get_session: session, require_user: member, admin_user: staff}
    insert = text(
        "INSERT INTO members (id, terms_version, terms_agreed_at) VALUES (:id, 'test', now())"
    )
    delete = text("DELETE FROM members WHERE id IN (:owner, :reader)")

    async def seed_members():
        async with engine.begin() as db:
            await db.execute(insert, [{"id": owner}, {"id": reader}])

    async def clean_up():
        async with engine.begin() as db:
            await db.execute(delete, {"owner": owner, "reader": reader})
        await engine.dispose()

    asyncio.run(seed_members())
    try:
        with TestClient(app) as client:
            examples = [post for post in client.get(PUBLIC).json() if post["example"]]
            assert len(examples) == 6
            assert len({post["createdAt"] for post in examples}) == 6
            assert len({post["votes"] for post in examples}) == 6
            popular = client.get(PUBLIC, params={"popular": "true"}).json()
            assert [post["votes"] for post in popular] == sorted(
                [post["votes"] for post in popular], reverse=True
            )
            for example in examples:
                assert example["products"]
                image = client.get(f"{PUBLIC}/{example['id']}/photo")
                assert image.headers["content-type"] == "image/jpeg"
                with Image.open(BytesIO(image.content)) as photo:
                    photo.verify()
            example_url = f"{PUBLIC}/{examples[0]['id']}"
            reader_headers = {"x-member": reader}
            assert (
                client.get(example_url + "/viewer", headers=reader_headers).json()["owned"] is False
            )
            reaction = client.post(example_url + "/recommend", headers=reader_headers)
            assert reaction.status_code == 200
            assert reaction.json()["votes"] == examples[0]["votes"] + 1
            exercise_post(client, owner, reader)
    finally:
        asyncio.run(clean_up())


def exercise_post(client: TestClient, owner: str, reader: str):
    post_id = str(uuid4())
    post_url = f"{PUBLIC}/{post_id}"
    admin_url = f"{ADMIN}/{post_id}"
    writer, viewer, moderator = {"x-member": owner}, {"x-member": reader}, {"x-staff": "yes"}
    content = json.dumps(
        {
            "title": "Rose makeup",
            "displayName": " Rose Studio ",
            "products": [{"productId": "lip-1", "shadeId": "rose"}, {"productId": "cheek-1"}],
        }
    )
    files = {"image": ("look.jpg", sample_photo(), "image/jpeg")}
    assert (
        client.post(post_url, headers=writer, data={"content": content}, files=files).status_code
        == 400
    )
    fields = {"content": content, "consent": "true"}
    for _ in range(2):
        published = client.post(post_url, headers=writer, data=fields, files=files)
        assert published.status_code == 201
        assert published.json()["id"] == post_id
        assert published.json()["displayName"] == "Rose Studio"
    mine = client.get(PUBLIC + "/mine", headers=writer).json()
    assert [p["id"] for p in mine] == [post_id]
    expected_products = [
        {"productId": "lip-1", "shadeId": "rose"},
        {"productId": "cheek-1", "shadeId": None},
    ]
    assert mine[0]["products"] == expected_products
    assert client.get(post_url).json()["products"] == expected_products
    assert next(p for p in client.get(PUBLIC).json() if p["id"] == post_id)["products"] == (
        expected_products
    )
    assert client.get(post_url + "/photo").headers["cache-control"] == "no-store"
    assert client.patch(post_url, headers=viewer, data=fields).status_code == 404
    changed = client.patch(post_url, headers=writer, data={"content": '{"title":"New title"}'})
    assert changed.json()["title"] == "New title"
    assert changed.json()["displayName"] == "Rose Studio"
    public_post = next(post for post in client.get(PUBLIC).json() if post["id"] == post_id)
    assert public_post["displayName"] == "Rose Studio"
    assert "ownerId" not in public_post and "email" not in public_post
    cleared = client.patch(
        post_url, headers=writer, data={"content": '{"title":"New title","displayName":null}'}
    )
    assert cleared.status_code == 200
    assert client.get(post_url).json()["displayName"] is None
    rec_url = f"{post_url}/recommend"
    assert client.post(rec_url, headers=writer).status_code == 409
    for _ in range(2):
        assert client.post(rec_url, headers=viewer).json()["votes"] == 1
    report_url = f"{post_url}/report"
    assert (
        client.post(report_url, headers=viewer, json={"reason": "Review photo"}).status_code == 200
    )
    assert client.get(post_url + "/viewer", headers=viewer).json() == {
        "owned": False,
        "recommended": True,
        "reported": True,
    }
    assert client.get(ADMIN).status_code == 403
    reported = client.get(ADMIN, headers=moderator).json()
    assert any(p["id"] == post_id and p["reasons"] == ["Review photo"] for p in reported)
    assert client.patch(admin_url, headers=moderator, json={"hidden": True}).json() == {
        "hidden": True
    }
    assert client.get(post_url).status_code == 404
    assert client.get(post_url + "/photo").status_code == 404
    assert post_id not in {p["id"] for p in client.get(PUBLIC).json()}
    assert client.get(admin_url + "/photo", headers=moderator).status_code == 200
    assert client.patch(admin_url, headers=moderator, json={"hidden": False}).status_code == 200
    assert client.get(post_url).json()["votes"] == 1
    assert client.delete(post_url, headers=viewer).status_code == 404
    assert client.delete(post_url, headers=writer).status_code == 204
    assert client.get(admin_url + "/photo", headers=moderator).status_code == 404
