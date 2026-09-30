"""Les dépendances des routes : les deux collections et le bucket."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pymongo.collection import Collection

from app.db import channels_collection, tasks_collection
from app.storage import Storage


def optional_storage(request: Request) -> Storage | None:
    return request.app.state.storage


def required_storage(request: Request) -> Storage:
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(
            503, "Stockage non configuré : renseigner SCW_ACCESS_KEY et SCW_SECRET_KEY."
        )
    return storage


Tasks = Annotated[Collection, Depends(tasks_collection)]
Channels = Annotated[Collection, Depends(channels_collection)]
MaybeStorage = Annotated[Storage | None, Depends(optional_storage)]
BucketStorage = Annotated[Storage, Depends(required_storage)]
