"""FastAPI fixture: dependencies, security schemes, routers, a mount and a WebSocket.

The docs routes are turned off so the golden lockfile does not depend on how a FastAPI
release names its own endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Security, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from starlette.staticfiles import StaticFiles

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
bearer = HTTPBearer()

NO_DOCS = {"docs_url": None, "redoc_url": None, "openapi_url": None}


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict[str, str]:
    """Resolve the user the bearer token belongs to.

    The second paragraph is not recorded.
    """
    return {"token": token}


def get_db() -> None:
    return None


def require_admin(user: dict[str, str] = Depends(get_current_user)) -> None:
    """Allow only administrators."""


class CommonParams:
    """Paging parameters shared by list endpoints."""

    def __init__(self, skip: int = 0, limit: int = 100) -> None:
        self.skip, self.limit = skip, limit


class Exploding:
    """Raises when called, so a test can prove extraction never calls a dependency."""

    def __call__(self) -> None:
        raise RuntimeError("authzlock called a dependency")


explode = Exploding()

app = FastAPI(**NO_DOCS)


@app.get("/items")
def list_items(params: CommonParams = Depends()) -> list[str]:
    return []


@app.post("/items")
def create_item(user=Depends(get_current_user), db=Depends(get_db)) -> None:
    return None


@app.delete("/items/{item_id}")
def delete_item(item_id: int, user=Security(get_current_user, scopes=["items:write"])) -> None:
    return None


@app.api_route("/search", methods=["POST", "GET"])
def search(trigger=Depends(explode)) -> None:
    return None


@app.get("/token-info")
def token_info(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> None:
    return None


@app.websocket("/ws")
async def feed(websocket: WebSocket) -> None:
    await websocket.close()


admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@admin.get("/users")
def list_users() -> list[str]:
    return []


reports = APIRouter(prefix="/reports")


@reports.get("/{report_id}", name="admin-report")
def get_report(report_id: int, db=Depends(get_db)) -> None:
    return None


admin.include_router(reports)
app.include_router(admin)

legacy = FastAPI(**NO_DOCS)


@legacy.get("/status")
def legacy_status() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/legacy", legacy, name="legacy")
app.mount("/static", StaticFiles(directory=".", check_dir=False), name="static")
