from app.repositories.style_look_repository import StyleLookRepository
from app.schemas.style_look import StyleLook


class StyleLookService:
    def __init__(self, repository: StyleLookRepository) -> None:
        self._repository = repository

    async def list_looks(self) -> list[StyleLook]:
        return await self._repository.list_looks()


def get_style_look_service() -> StyleLookService:
    return StyleLookService(StyleLookRepository())
