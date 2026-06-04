"""ForgeOS — FOG Imaging API surface (stubs only — see registry).

Mounts under the existing FastAPI app via:

    from imaging_api import router as imaging_router
    app.include_router(imaging_router)

Routes:
  • GET  /api/imaging/status   — FOG installation status + image list
  • POST /api/imaging/capture  — STUB (returns 501)
  • POST /api/imaging/deploy   — STUB (returns 501)

NOTE: The capture and deploy endpoints currently raise HTTPException 501.
Full FOG integration is on the registry as a future tier 4 item.

No helpers needed — this module only reads from /opt/fog and /images
via os.path, which it imports directly.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()


@router.get("/api/imaging/status")
async def imaging_status(user=Depends(verify_token)):
    """Get FOG imaging status."""
    fog_installed = os.path.exists("/opt/fog")
    images: list[str] = []
    hosts: list[str] = []

    if fog_installed:
        img_dir = "/images"
        if os.path.exists(img_dir):
            try:
                images = os.listdir(img_dir)
            except Exception as e:
                logger.warning("imaging images list failed: %s", e)

    return {"fog_installed": fog_installed, "images": images, "hosts": hosts}


@router.post("/api/imaging/capture")
async def imaging_capture(hostname: str, image_name: str, user=Depends(verify_token)):
    """Request FOG image capture — STUB: FOG integration not yet implemented."""
    raise HTTPException(status_code=501, detail="FOG imaging capture not yet implemented")


@router.post("/api/imaging/deploy")
async def imaging_deploy(image_name: str, target_host: str, user=Depends(verify_token)):
    """Deploy image to target — STUB: FOG integration not yet implemented."""
    raise HTTPException(status_code=501, detail="FOG imaging deploy not yet implemented")
