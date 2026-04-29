"""
Sample ForgeOS Plugin
Demonstrates the plugin system with a simple API.
"""

from fastapi import FastAPI, APIRouter
from fastapi.responses import JSONResponse


# Create plugin router
router = APIRouter()


@router.get("/info")
async def get_info():
    """Get plugin information."""
    return {
        "id": "sample-plugin",
        "name": "Sample Plugin",
        "version": "1.0.0",
        "status": "running",
        "message": "Hello from Sample Plugin!"
    }


@router.get("/items")
async def list_items():
    """List sample items."""
    return {
        "items": [
            {"id": 1, "name": "Item 1", "type": "sample"},
            {"id": 2, "name": "Item 2", "type": "sample"},
            {"id": 3, "name": "Item 3", "type": "sample"},
        ],
        "count": 3
    }


@router.post("/items")
async def create_item(body: dict):
    """Create a new item."""
    return {
        "ok": True,
        "item": body,
        "message": "Item created (sample)"
    }


# Health check endpoint
@router.get("/health")
async def health():
    """Health check for plugin monitoring."""
    return {"status": "healthy"}


# Main entrypoint (when run directly)
app = FastAPI(title="Sample Plugin", version="1.0.0")

# Include router
app.include_router(router, prefix="/api/plugins/sample-plugin")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5090)
